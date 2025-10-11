"""
Minimal Hearthstone-like rules engine in pure Python (fixed rush + coin).

Change log (key fixes)
- Add Minion.summoned_this_turn to model summoning sickness correctly.
- Rush: can attack MINIONS on summon, but never face on that turn.
- Charge: can attack anything on summon.
- Implement The Coin to actually grant +1 temporary mana (this turn).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Callable, Any, Tuple
import random
import json
from pathlib import Path

# ---------------------- Events ----------------------

@dataclass
class Event:
    kind: str
    payload: Dict[str, Any]

# ---------------------- Entities ----------------------

@dataclass
class HeroPower:
    name: str
    text: str
    cost: int = 2
    targeting: str = "none"  # "none", "any_character", "enemy_face", "friendly_character",
                             # "enemy_minion", "friendly_minion"
    # We keep raw JSON spec; compile into a callable on demand using the cards.json tokens
    effects_spec: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class Hero:
    id: str             # canonical id, e.g. "MAGE"
    name: str           # friendly display, e.g. "Mage"
    power: HeroPower

@dataclass
class Minion:
    id: int
    owner: int
    name: str
    attack: int
    health: int
    max_health: int
    taunt: bool = False
    charge: bool = False
    rush: bool = False
    can_attack: bool = False
    exhausted: bool = True
    silenced: bool = False
    deathrattle: Optional[Callable[['Game','Minion'], List[Event]]] = None
    # internal flags
    has_attacked_this_turn: bool = False

    # NEW: for UI/logic
    summoned_this_turn: bool = True
    cost: int = 0  # original mana cost to display on-board
    rarity: str = ""


    card_id: str = ""
    base_attack: int = 0
    base_health: int = 0
    base_text: str = ""
    base_keywords: List[str] = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.health > 0

@dataclass
class Card:
    id: str
    name: str
    cost: int
    type: str  # "MINION" or "SPELL"
    attack: int = 0
    health: int = 0
    keywords: List[str] = field(default_factory=list)
    # Scripting hooks:
    battlecry: Optional[Callable[['Game','Card', Optional[int]], List[Event]]] = None
    on_cast: Optional[Callable[['Game','Card', Optional[int]], List[Event]]] = None
    text: str = "" 
    rarity: str = ""

@dataclass
class PlayerState:
    id: int
    deck: List[str]
    hand: List[str] = field(default_factory=list)
    board: List[Minion] = field(default_factory=list)
    graveyard: List[str] = field(default_factory=list)
    dead_minions: List[Minion] = field(default_factory=list)
    health: int = 30
    armor: int = 0
    max_mana: int = 0
    mana: int = 0
    fatigue: int = 0
    hero: Hero = None   
    hero_power_used_this_turn: bool = False

    def draw(self, g:'Game', n:int=1) -> List[Event]:
        ev: List[Event] = []
        for _ in range(n):
            if self.deck:
                card_id = self.deck.pop(0)
                if len(self.hand) < 10:
                    self.hand.append(card_id)
                    ev.append(Event("CardDrawn", {"player": self.id, "card": card_id}))
                else:
                    self.graveyard.append(card_id)
                    ev.append(Event("CardBurned", {"player": self.id, "card": card_id}))
            else:
                self.fatigue += 1
                dmg = self.fatigue
                ev += g.deal_damage_to_player(self.id, dmg, source="Fatigue")
        return ev

# ---------------------- Game ----------------------

class IllegalAction(Exception):
    pass

class Game:
    def __init__(self, cards_db: Dict[str, Card], p0_deck: List[str], p1_deck: List[str],
                 seed: Optional[int] = None,
                 heroes: Tuple[Hero, Hero] = None):
        self.cards_db = cards_db
        self.players = [PlayerState(0, list(p0_deck)), PlayerState(1, list(p1_deck))]
        # Expect Hero objects
        if heroes is None:
            raise ValueError("Game requires (Hero, Hero)")
        self.players[0].hero = heroes[0]
        self.players[1].hero = heroes[1]
        self.active_player = 0
        self.turn = 0
        if seed is None:
            seed = random.randint(1, 2_147_483_647)
        self.rng = random.Random(seed)
        self.next_minion_id = 1
        self.history: List[Event] = []

    def other(self, pid:int) -> int:
        return 1 - pid

    def find_minion(self, minion_id:int) -> Optional[Tuple[int, int, Minion]]:
        for pid in (0,1):
            for i, m in enumerate(self.players[pid].board):
                if m.id == minion_id:
                    return pid, i, m
        return None

    def get_taunts(self, pid:int) -> List[Minion]:
        return [m for m in self.players[pid].board if m.taunt and m.is_alive()]

    def deal_damage_to_player(self, pid:int, amount:int, source:str="") -> List[Event]:
        p = self.players[pid]
        dmg = amount
        if p.armor > 0:
            absorb = min(p.armor, dmg)
            p.armor -= absorb
            dmg -= absorb
        p.health -= dmg
        ev = [Event("PlayerDamaged", {"player": pid, "amount": dmg, "absorbed": amount - dmg, "source": source})]
        if p.health <= 0:
            ev.append(Event("PlayerDefeated", {"player": pid}))
        return ev

    def deal_damage_to_minion(self, target:Minion, amount:int, source:str="") -> List[Event]:
        target.health -= amount
        ev = [Event("MinionDamaged", {"minion": target.id, "amount": amount, "source": source})]
        if target.health <= 0:
            ev += self.destroy_minion(target, reason="LethalDamage")
        return ev

    def destroy_minion(self, target:Minion, reason:str="") -> List[Event]:
        ev: List[Event] = []
        loc = self.find_minion(target.id)
        if not loc:
            return ev
        pid, idx, m = loc
        self.players[pid].board.pop(idx)
        self.players[pid].dead_minions.append(m)
        ev.append(Event("MinionDied", {"minion": m.id, "owner": pid, "reason": reason, "name": m.name}))
        if m.deathrattle:
            ev += m.deathrattle(self, m)
        return ev

    # ---------- Turn Flow ----------
    def start_game(self) -> List[Event]:
        ev: List[Event] = []

        # Randomize starting player (0 = You, 1 = AI)
        self.active_player = self.rng.choice([0, 1])
        first  = self.active_player
        second = self.other(first)

        # Mulligan-size draws
        ev += self.players[first].draw(self, 3)   # first: 3 cards
        ev += self.players[second].draw(self, 4)  # second: 4 cards

        # Give Coin to the player going second (if present in DB)
        if "THE_COIN" in self.cards_db:
            self.players[second].hand.append("THE_COIN")

        ev.append(Event("GameStart", {"active_player": self.active_player}))
        ev += self.start_turn(self.active_player)
        self.history += ev
        return ev

    def start_turn(self, pid:int) -> List[Event]:
        p = self.players[pid]
        if pid == 0:
            self.turn += 1
        turn_number = self.turn if pid == 0 else max(1, self.turn)
        p.max_mana = min(10, p.max_mana + 1)
        p.mana = p.max_mana
        p.hero_power_used_this_turn = False
        for m in p.board:
            m.exhausted = False
            m.has_attacked_this_turn = False
            m.summoned_this_turn = False
            m.can_attack = m.charge or (not m.exhausted)
        ev = [Event("TurnStart", {"player": pid, "turn": turn_number})]
        ev += p.draw(self, 1)
        return ev

    def end_turn(self, pid:int) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")
        self.active_player = self.other(pid)
        ev = [Event("TurnEnd", {"player": pid})]
        ev += self.start_turn(self.active_player)
        self.history += ev
        return ev

    # ---------- Commands ----------
    def use_hero_power(self, pid:int,
                       target_player:Optional[int]=None,
                       target_minion:Optional[int]=None) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")
        p = self.players[pid]
        hero = p.hero
        if hero is None:
            raise IllegalAction("No hero")
        if p.hero_power_used_this_turn:
            raise IllegalAction("Hero power already used")
        if p.mana < hero.power.cost:
            raise IllegalAction("Not enough mana for hero power")

        # Validate targeting by hero.power.targeting
        targ = hero.power.targeting
        needs_target = targ in ("any_character", "enemy_minion", "friendly_minion",
                                "friendly_character", "enemy_character")
        runtime_target: Optional[int] = None  # int => minionId or playerId

        if needs_target:
            # We accept either (target_minion) or (target_player)
            if target_minion is not None:
                loc = self.find_minion(target_minion)
                if not loc:
                    raise IllegalAction("Target minion not found")
                # scope checking
                tpid, _, _ = loc
                if targ == "enemy_minion" and tpid == pid:
                    raise IllegalAction("Must target enemy minion")
                if targ == "friendly_minion" and tpid != pid:
                    raise IllegalAction("Must target friendly minion")
                runtime_target = target_minion
            elif target_player in (0, 1):
                if targ == "enemy_minion" or targ == "friendly_minion":
                    raise IllegalAction("This power requires a minion target")
                if targ == "friendly_character" and target_player != pid:
                    raise IllegalAction("Must target friendly character")
                if targ in ("enemy_character",) and target_player == pid:
                    raise IllegalAction("Must target enemy character")
                runtime_target = target_player
            else:
                raise IllegalAction("Hero power needs a target")
        else:
            # If the power declares "enemy_face", UI passes none; effect spec can infer POV
            if targ == "enemy_face":
                runtime_target = None  # effect spec resolves using owner POV
            else:
                runtime_target = None

        # Pay + mark used + log
        p.mana -= hero.power.cost
        p.hero_power_used_this_turn = True
        ev: List[Event] = [Event("HeroPowerUsed", {"player": pid, "hero": hero.id})]

        # Build a lightweight "source" carrying owner + display name
        class _HPSource: pass
        src = _HPSource()
        src.owner = pid
        src.name = hero.power.name

        # Compile & run effects (on demand)
        impl = _compile_effects_for_heroes(hero.power.effects_spec, self.cards_db)
        ev += impl(self, src, runtime_target)

        self.history += ev
        return ev


    def play_card(self, pid:int, hand_index:int, target_player:Optional[int]=None, target_minion:Optional[int]=None) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")
        p = self.players[pid]
        if hand_index < 0 or hand_index >= len(p.hand):
            raise IllegalAction("Bad hand index")
        cid = p.hand[hand_index]
        card = self.cards_db[cid]
        if p.mana < card.cost:
            raise IllegalAction("Not enough mana")
        p.mana -= card.cost
        p.hand.pop(hand_index)
        ev: List[Event] = [Event("CardPlayed", {"player": pid, "card": cid, "name": card.name})]

        if card.type == "MINION":
            if len(p.board) >= 7:
                raise IllegalAction("Board full")
            m = Minion(
                id=self.next_minion_id, owner=pid, name=card.name,
                attack=card.attack, health=card.health, max_health=card.health,
                taunt=("Taunt" in card.keywords),
                charge=("Charge" in card.keywords),
                rush=("Rush" in card.keywords),
                summoned_this_turn=True,
                cost=card.cost,
                rarity=card.rarity,
                card_id=card.id,
                base_attack=card.attack,
                base_health=card.health,
                base_text=card.text or "",
                base_keywords=list(card.keywords),
                
            )
            self.next_minion_id += 1
            p.board.append(m)
            ev.append(Event("MinionSummoned", {"player": pid, "minion": m.id, "name": m.name}))
            if card.battlecry:
                ev += card.battlecry(self, card, target_minion if target_minion is not None else target_player)
        elif card.type == "SPELL":
            if card.on_cast:
                ev += card.on_cast(self, card, target_minion if target_minion is not None else target_player)
            self.players[pid].graveyard.append(card.id)
        else:
            raise IllegalAction("Unknown card type")
        self.history += ev
        return ev

    def attack(self, pid:int, attacker_id:int, target_player:Optional[int]=None, target_minion:Optional[int]=None) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")
        loc = self.find_minion(attacker_id)
        if not loc:
            raise IllegalAction("Attacker not found")
        apid, _, att = loc
        if apid != pid:
            raise IllegalAction("You don't control that minion")
        if att.has_attacked_this_turn or not att.is_alive():
            raise IllegalAction("Minion cannot attack")
        if att.attack <= 0:
            raise IllegalAction("Minion has 0 attack")

        opp = self.other(pid)
        taunts = self.get_taunts(opp)

        # ----- Attack MINION -----
        if target_minion is not None:
            tloc = self.find_minion(target_minion)
            if not tloc:
                raise IllegalAction("Target minion not found")
            tpid, _, tgt = tloc
            if tpid != opp:
                raise IllegalAction("Must target enemy")
            if taunts and not tgt.taunt:
                raise IllegalAction("Must attack Taunt first")

            # Legality vs MINION
            can_vs_minion = (not att.summoned_this_turn) or att.charge or att.rush
            if not can_vs_minion:
                raise IllegalAction("This minion can't attack another minion yet")

            # SIMULTANEOUS DAMAGE
            att.has_attacked_this_turn = True
            ev: List[Event] = [Event("Attack", {"attacker": att.id, "target": tgt.id})]

            a_dmg = att.attack
            t_dmg = tgt.attack

            # Apply raw damage (no immediate deaths)
            tgt.health -= a_dmg
            ev.append(Event("MinionDamaged", {"minion": tgt.id, "amount": a_dmg, "source": att.name}))
            att.health -= t_dmg
            ev.append(Event("MinionDamaged", {"minion": att.id, "amount": t_dmg, "source": tgt.name}))

            # Resolve deaths after both hits are applied
            if tgt.health <= 0:
                ev += self.destroy_minion(tgt, reason="LethalDamage")
            if att.health <= 0:
                ev += self.destroy_minion(att, reason="LethalDamage")

            self.history += ev
            return ev

        # ----- Attack FACE -----
        if taunts:
            raise IllegalAction("Taunt blocks attacking face")
        can_vs_face = (not att.summoned_this_turn) or att.charge
        if not can_vs_face:
            raise IllegalAction("This minion can't attack the enemy hero yet")

        att.has_attacked_this_turn = True
        ev = [Event("Attack", {"attacker": att.id, "target": f"player:{opp}"})]
        ev += self.deal_damage_to_player(opp, att.attack, source=att.name)
        self.history += ev
        return ev

def _ev_hero_power(pid, hero_name):
    return Event("HeroPowerUsed", {"player": pid, "hero": hero_name})

def _ev_armor(pid, amount):
    return Event("ArmorGained", {"player": pid, "amount": amount})

_SILVER_HAND_RECRUIT_SPEC = {
    "id": "SILVER_HAND_RECRUIT_TOKEN",
    "name": "Silver Hand Recruit",
    "type": "MINION",
    "cost": 1, "attack": 1, "health": 1,
    "rarity": "Common",
    "keywords": []
}

# ---------------------- Card Scripts ----------------------

# ---- Effect factories ----

def _fx_gain_armor(params):
    amt = int(params.get("amount", 0))
    t_spec = params.get("target")  # optional: "self"/"friendly_face"/"enemy_face"

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)

        # Resolve player to receive armor
        if isinstance(target, int):
            pid = target
        else:
            pid = owner
            if t_spec:
                s = str(t_spec).lower()
                if s in ("self", "self_face", "friendly", "friendly_face", "ally_face"):
                    pid = owner
                elif s in ("enemy", "enemy_face", "opponent", "opponent_face"):
                    pid = g.other(owner)

        p = g.players[pid]
        p.armor += amt
        return [Event("ArmorGained", {"player": pid, "amount": amt})]
    return run


def _fx_add_keyword(params):
    kw = params["keyword"].lower()
    def run(g, source_obj, target):
        if not isinstance(target, int): return []
        loc = g.find_minion(target)
        if not loc: return []
        _,_,m = loc
        if kw == "taunt":   m.taunt = True
        elif kw == "charge": m.charge = True
        elif kw == "rush":   m.rush = True
        return [Event("BuffKeyword", {"minion": m.id, "keyword": kw})]
    return run

def _fx_deal_damage(params):
    n = int(params["amount"])
    t_spec = params.get("target")

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)  # <- POV anchor
        ev = []

        # 1) If a concrete runtime target was provided (e.g., targeted spells), honor it.
        if isinstance(target, int):
            loc = g.find_minion(target)
            if loc:
                _, _, m = loc
                ev += g.deal_damage_to_minion(m, n, source=name)
            else:
                pid = target  # assume player id 0/1
                ev += g.deal_damage_to_player(pid, n, source=name)
            return ev

        # 2) If the params declare a semantic target (like "enemy_face"), resolve from OWNER's POV.
        if t_spec:
            s = str(t_spec).lower()
            if s in ("enemy_face", "opponent_face", "enemy_hero", "opponent_hero"):
                pid = g.other(owner)
                ev += g.deal_damage_to_player(pid, n, source=name)
                return ev
            if s in ("friendly_face", "ally_face", "self_face", "friendly_hero", "self_hero"):
                ev += g.deal_damage_to_player(owner, n, source=name)
                return ev
            # You can extend here for other patterns later (enemy_random_minion, etc.)
            # For unknown spec, fall through to default owner-based enemy face.

        # 3) Fallback: treat as "enemy_face" relative to OWNER (keeps spells working too).
        opp = g.other(owner)
        ev += g.deal_damage_to_player(opp, n, source=name)
        return ev

    return run

def _fx_heal(params):
    n = int(params["amount"])
    def run(g, source_obj, target):
        name = getattr(source_obj, "name", "Effect")
        ev = []
        if isinstance(target, int):
            loc = g.find_minion(target)
            if loc:
                _, _, m = loc
                before = m.health
                m.health = min(m.max_health, m.health + n)
                ev.append(Event("MinionHealed", {"minion": m.id, "amount": m.health - before, "source": name}))
            else:
                pid = target
                p = g.players[pid]
                before = p.health
                p.health = min(30, p.health + n)
                ev.append(Event("PlayerHealed", {"player": pid, "amount": p.health - before, "source": name}))
        return ev
    return run

def _fx_draw(params):
    count = int(params.get("count", 1))
    def run(g, source_obj, target):
        pid = g.active_player
        return g.players[pid].draw(g, count)
    return run

def _fx_gain_temp_mana(params):
    amt = int(params.get("amount", 1))
    def run(g, source_obj, target):
        p = g.players[g.active_player]
        p.mana = min(p.mana + amt, p.max_mana + amt)
        return [Event("GainMana", {"player": g.active_player, "temp": amt, "mana_after": p.mana})]
    return run

def _fx_random_pings(params):
    count = int(params["count"])
    def run(g, source_obj, target):
        name = getattr(source_obj, "name", "Effect")
        opp = g.other(g.active_player)
        ev = []
        for _ in range(count):
            pool = [("player", opp)] + [("minion", m.id) for m in g.players[opp].board if m.is_alive()]
            tgt = g.rng.choice(pool)
            if tgt[0] == "player":
                ev.append(Event("SpellHit", {"source": name, "target_type":"player", "player": opp}))
                ev += g.deal_damage_to_player(opp, 1, source=name)
            else:
                loc = g.find_minion(tgt[1])
                if loc:
                    _,_,m = loc
                    ev.append(Event("SpellHit", {"source": name, "target_type":"minion", "minion": m.id, "name": m.name}))
                    ev += g.deal_damage_to_minion(m, 1, source=name)
        return ev
    return run

def _fx_aoe_damage(params):
    n = int(params["amount"])
    def run(g, source_obj, target):
        name = getattr(source_obj, "name", "Effect")
        opp = g.other(g.active_player)
        ev = []
        ev.append(Event("SpellHit", {"source": name, "target_type":"player", "player": opp, "aoe": True}))
        ev += g.deal_damage_to_player(opp, n, source=name)
        for m in list(g.players[opp].board):
            if m.is_alive():
                ev.append(Event("SpellHit", {"source": name, "target_type":"minion", "minion": m.id, "name": m.name, "aoe": True}))
                ev += g.deal_damage_to_minion(m, n, source=name)
        return ev
    return run

def _fx_aoe_damage_minions(params):
    n = int(params["amount"])
    def run(g, source_obj, target):
        name = getattr(source_obj, "name", "Effect")
        opp = g.other(g.active_player)
        ev = []
        for m in list(g.players[opp].board):
            if m.is_alive():
                ev += g.deal_damage_to_minion(m, n, source=name)
        return ev
    return run

def _fx_add_attack(params):
    n = int(params["amount"])
    def run(g, source_obj, target):
        if not isinstance(target, int): return []
        loc = g.find_minion(target)
        if not loc: return []
        _,_,m = loc
        m.attack += n
        return [Event("Buff", {"minion": m.id, "attack_delta": n})]
    return run

def _fx_add_stats(params):
    a = int(params.get("attack", 0))
    h = int(params.get("health", 0))
    def run(g, source_obj, target):
        if not isinstance(target, int): return []
        loc = g.find_minion(target)
        if not loc: return []
        _,_,m = loc
        m.attack += a
        m.max_health += h
        m.health += h
        return [Event("Buff", {"minion": m.id, "attack_delta": a, "health_delta": h})]
    return run

def _fx_silence(params):
    def run(g, source_obj, target):
        if not isinstance(target, int): return []
        loc = g.find_minion(target)
        if not loc: return []
        _,_,m = loc
        m.taunt = m.charge = m.rush = False
        m.deathrattle = None
        m.silenced = True           
        return [Event("Silenced", {"minion": m.id})]
    return run

def _summon_from_card_spec(g, owner, card_spec, count):
    ev = []
    for _ in range(count):
        if len(g.players[owner].board) >= 7:
            break

        kws = card_spec.get("keywords", []) or []

        m = Minion(
            id=g.next_minion_id,
            owner=owner,
            name=card_spec.get("name", "Token"),
            attack=int(card_spec.get("attack", 0)),
            health=int(card_spec.get("health", 1)),
            max_health=int(card_spec.get("health", 1)),
            taunt=("Taunt" in kws),
            charge=("Charge" in kws),
            rush=("Rush" in kws),
            exhausted=not ("Charge" in kws or "Rush" in kws),
            cost=int(card_spec.get("cost", 0)),
            rarity=str(card_spec.get("rarity", "Common")),
            # base/origin info for the inspector
            card_id=card_spec.get("id", ""),              # may be injected below
            base_attack=int(card_spec.get("attack", 0)),
            base_health=int(card_spec.get("health", 1)),
            base_text=str(card_spec.get("text", "")),
            base_keywords=list(kws),
        )
        g.next_minion_id += 1
        g.players[owner].board.append(m)
        ev.append(Event("MinionSummoned", {"player": owner, "minion": m.id, "name": m.name}))
    return ev
def _fx_summon(params, json_db_tokens):
    """
    params:
      card_id: str (token id)
      count: int (default 1)
      owner: "player" | "enemy" | "both" | 0 | 1 | "active" | "inactive" (optional)
             - "player"   => the caster's side
             - "enemy"    => the opponent of the caster
             - "both"     => summon for both sides (mirror)
             - 0 or 1     => absolute player index
             - "active"   => g.active_player
             - "inactive" => the other of g.active_player
    """
    token_id = params["card_id"]
    count = int(params.get("count", 1))
    owner_param = params.get("owner", "player")  # default friendly to the caster

    def _resolve_owners(g, source_owner):
        # accepts ints or strings
        if isinstance(owner_param, int):
            return [0 if owner_param == 0 else 1]

        s = str(owner_param).lower()
        if s in ("player", "friendly", "ally", "self"):
            return [source_owner]
        if s in ("enemy", "opponent", "foe"):
            return [g.other(source_owner)]
        if s in ("both", "each", "mirror"):
            return [source_owner, g.other(source_owner)]
        if s in ("active", "current"):
            return [g.active_player]
        if s in ("inactive", "other_active"):
            return [g.other(g.active_player)]
        # fallback (friendly)
        return [source_owner]

    def run(g, source_obj, target):
        source_owner = getattr(source_obj, "owner", g.active_player)
        owners = _resolve_owners(g, source_owner)

        raw = json_db_tokens[token_id]
        spec = dict(raw)
        spec.setdefault("id", token_id)
        evs = []
        for ow in owners:
            evs += _summon_from_card_spec(g, ow, spec, count)
        return evs

    return run

def _fx_transform(params, json_db_tokens):
    token_id = params["card_id"]
    def run(g, source_obj, target):
        if not isinstance(target, int): return []
        loc = g.find_minion(target)
        if not loc: return []
        pid, idx, m = loc
        # destroy target (without deathrattle)
        m.deathrattle = None
        ev = g.destroy_minion(m, reason="Transform")
        # summon token at same side (ensure id present)
        raw = json_db_tokens[token_id]
        spec = dict(raw)
        spec.setdefault("id", token_id)
        ev += _summon_from_card_spec(g, pid, spec, 1)
        return ev
    return run

# Registry maps effect name -> factory
def _effect_factory(name, params, json_tokens):
    table = {
        "deal_damage":        _fx_deal_damage,
        "heal":               _fx_heal,
        "draw":               _fx_draw,
        "gain_temp_mana":     _fx_gain_temp_mana,
        "random_pings":       _fx_random_pings,
        "aoe_damage":         _fx_aoe_damage,
        "aoe_damage_minions": _fx_aoe_damage_minions,
        "add_attack":         _fx_add_attack,
        "add_stats":          _fx_add_stats,
        "silence":            _fx_silence,
        "add_keyword":        _fx_add_keyword,
        "summon":             lambda p: _fx_summon(p, json_tokens),
        "transform":          lambda p: _fx_transform(p, json_tokens),
        "gain_armor":         _fx_gain_armor,
    }
    if name not in table:
        raise ValueError(f"Unknown effect: {name}")
    fn_or_factory = table[name]
    return fn_or_factory(params)

def _compile_effects_for_heroes(effects_spec, cards_db):
    tokens = cards_db.get("_TOKENS", {})
    return _compile_effects(effects_spec, tokens)


def _compile_effects(effects_spec, json_tokens):
    """effects_spec is a list of {effect: 'name', ...params} dicts.
       Returns a callable(game, card_or_minion, target) -> [Event,...] applying all effects in order."""
    fns = []
    for eff in effects_spec:
        name = eff["effect"]
        fns.append(_effect_factory(name, eff, json_tokens))
    def run_all(g, src_obj, target):
        ev = []
        for fn in fns:
            ev += fn(g, src_obj, target)
        return ev
    return run_all

def load_heros_from_json(path: str) -> Dict[str, Hero]:
    """
    heroes.json format (flexible, but this is recommended):
    {
      "heroes": [
        {
          "id": "MAGE",
          "name": "Mage",
          "power": {
            "name": "Fireblast",
            "text": "Deal 1 damage.",
            "cost": 2,
            "targeting": "any_character",
            "effects": [
              {"effect":"deal_damage","amount":1}
            ]
          }
        },
        ...
      ]
    }
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    db: Dict[str, Hero] = {}
    for h in raw.get("heroes", []):
        pid  = str(h.get("id", "")).upper()
        name = h.get("name") or pid.capitalize()
        pwr  = h.get("power", {}) or {}
        hp = HeroPower(
            name=pwr.get("name", "Hero Power"),
            text=pwr.get("text", ""),
            cost=int(pwr.get("cost", 2)),
            targeting=str(pwr.get("targeting", "none")).lower(),
            effects_spec=list(pwr.get("effects", [])),
        )
        db[pid] = Hero(id=pid, name=name, power=hp)
    return db

def load_cards_from_json(path: str) -> Dict[str, Card]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tokens = data.get("tokens", {})
    db: Dict[str, Card] = {}
    targeting: Dict[str, str] = {}
    deathrattles_map: Dict[str, Any] = {}

    for raw in data["cards"]:
        cid   = raw["id"]
        name  = raw["name"]
        typ   = raw["type"]
        cost  = int(raw["cost"])
        text  = raw.get("text", "")
        atk   = int(raw.get("attack", 0))
        hp    = int(raw.get("health", 0))
        kwords= list(raw.get("keywords", []))
        rarity = (raw.get("rarity") or "Common")

        bc = oc = None
        if "battlecry" in raw:
            bc = _compile_effects(raw["battlecry"], tokens)
        if "on_cast" in raw:
            oc = _compile_effects(raw["on_cast"], tokens)
        if "deathrattle" in raw:
            deathrattles_map[cid] = raw["deathrattle"]  # keep spec for hook attachment

        card = Card(id=cid, name=name, cost=cost, type=typ, attack=atk, health=hp,
                    keywords=kwords, battlecry=bc, on_cast=oc, rarity=rarity)
        # if your Card has a text field:
        try:
            setattr(card, "text", text)
        except Exception:
            pass

        db[cid] = card
        targeting[cid] = raw.get("targeting", "none")

    # Provide post-summon hook that attaches JSON deathrattles
    def _post_summon(g: Game, m: Minion):
        # find the card id by name (cheap, but fine for prototype)
        for cid, c in db.items():
            if c.name == m.name and cid in deathrattles_map:
                dr = _compile_effects(deathrattles_map[cid], tokens)
                def _dr(g2: Game, m2: Minion, _dr_inner=dr, _nm=m.name):
                    return _dr_inner(g2, m2, None)
                m.deathrattle = _dr
                break
    
    db["_TOKENS"] = tokens  # expose raw token specs for other compilers (heroes)
    db["_POST_SUMMON_HOOK"] = _post_summon
    db["_TARGETING"] = targeting  # (optional) UI can use this to highlight targets
    return db

