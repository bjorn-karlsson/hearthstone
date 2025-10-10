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

# ---------------------- Events ----------------------

@dataclass
class Event:
    kind: str
    payload: Dict[str, Any]

# ---------------------- Entities ----------------------

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
    # Flags that actually drive legality:
    summoned_this_turn: bool = True
    has_attacked_this_turn: bool = False
    # Optional script:
    deathrattle: Optional[Callable[['Game','Minion'], List[Event]]] = None

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

@dataclass
class PlayerState:
    id: int
    deck: List[str]
    hand: List[str] = field(default_factory=list)
    board: List[Minion] = field(default_factory=list)
    graveyard: List[str] = field(default_factory=list)
    health: int = 30
    armor: int = 0
    max_mana: int = 0
    mana: int = 0
    fatigue: int = 0

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
    def __init__(self, cards_db: Dict[str, Card], p0_deck: List[str], p1_deck: List[str], seed: int=1337):
        self.cards_db = cards_db
        self.players = [PlayerState(0, list(p0_deck)), PlayerState(1, list(p1_deck))]
        self.active_player = 0
        self.turn = 0
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
        ev = [Event("PlayerDamaged", {"player": pid, "amount": amount, "source": source})]
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
        ev.append(Event("MinionDied", {"minion": m.id, "owner": pid, "reason": reason, "name": m.name}))
        if m.deathrattle:
            ev += m.deathrattle(self, m)
        return ev

    # ---------- Turn Flow ----------
    def start_game(self) -> List[Event]:
        ev: List[Event] = []
        ev += self.players[0].draw(self, 3)
        ev += self.players[1].draw(self, 4)
        if "THE_COIN" in self.cards_db:
            self.players[1].hand.append("THE_COIN")
        ev.append(Event("GameStart", {"active_player": self.active_player}))
        ev += self.start_turn(self.active_player)
        self.history += ev
        return ev

    def start_turn(self, pid:int) -> List[Event]:
        p = self.players[pid]
        self.turn += 1 if pid == 0 else 0
        p.max_mana = min(10, p.max_mana + 1)
        p.mana = p.max_mana
        for m in p.board:
            m.has_attacked_this_turn = False
            m.summoned_this_turn = False
        ev = [Event("TurnStart", {"player": pid, "turn": self.turn})]
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

        opp = self.other(pid)
        taunts = self.get_taunts(opp)

        if target_minion is not None:
            tloc = self.find_minion(target_minion)
            if not tloc:
                raise IllegalAction("Target minion not found")
            tpid, _, tgt = tloc
            if tpid != opp:
                raise IllegalAction("Must target enemy")
            if taunts and not tgt.taunt:
                raise IllegalAction("Must attack Taunt first")

            can_vs_minion = (not att.summoned_this_turn) or att.charge or att.rush
            if not can_vs_minion:
                raise IllegalAction("This minion can't attack another minion yet")

            att.has_attacked_this_turn = True
            ev = [Event("Attack", {"attacker": att.id, "target": tgt.id})]
            ev += self.deal_damage_to_minion(tgt, att.attack, source=att.name)
            if tgt.is_alive():
                ev += self.deal_damage_to_minion(att, tgt.attack, source=tgt.name)
            self.history += ev
            return ev

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

# ---------------------- Card Scripts ----------------------

def make_db() -> Dict[str, Card]:
    db: Dict[str, Card] = {}

    def spell_damage(n:int):
        def on_cast(g:Game, c:Card, target:Optional[int]):
            ev: List[Event] = []
            if isinstance(target, int):
                loc = g.find_minion(target)
                if loc:
                    _,_,m = loc
                    ev += g.deal_damage_to_minion(m, n, source=c.name)
                else:
                    pid = target
                    ev += g.deal_damage_to_player(pid, n, source=c.name)
            else:
                opp = g.other(g.active_player)
                ev += g.deal_damage_to_player(opp, n, source=c.name)
            return ev
        return on_cast

    # The Coin (+1 temporary mana this turn)
    def on_cast_coin(g:Game, c:Card, t:Optional[int]):
        p = g.players[g.active_player]
        p.mana = min(p.mana + 1, p.max_mana + 1)
        return [Event("GainMana", {"player": g.active_player, "temp": 1, "mana_after": p.mana})]

    db["THE_COIN"] = Card(id="THE_COIN", name="The Coin", cost=0, type="SPELL", on_cast=on_cast_coin)

    db["RIVER_CROCOLISK"]   = Card(id="RIVER_CROCOLISK",   name="River Crocolisk", cost=2, type="MINION", attack=2, health=3)
    db["CHILLWIND_YETI"]    = Card(id="CHILLWIND_YETI",    name="Chillwind Yeti",  cost=4, type="MINION", attack=4, health=5)
    db["BOULDERFIST_OGRE"]  = Card(id="BOULDERFIST_OGRE",  name="Boulderfist Ogre",cost=6, type="MINION", attack=6, health=7)
    db["SHIELD_BEARER"]     = Card(id="SHIELD_BEARER",     name="Shieldbearer",    cost=1, type="MINION", attack=0, health=4, keywords=["Taunt"])
    db["WOLFRIDER"]         = Card(id="WOLFRIDER",         name="Wolfrider",       cost=3, type="MINION", attack=3, health=1, keywords=["Charge"])
    db["RUSHER"]            = Card(id="RUSHER",            name="Arena Rusher",    cost=2, type="MINION", attack=2, health=1, keywords=["Rush"])

    # Battlecry: deal 1 to a target
    def bc_pinger(g:Game, c:Card, target:Optional[int]):
        ev: List[Event] = []
        if isinstance(target, int):
            loc = g.find_minion(target)
            if loc:
                _,_,m = loc
                ev += g.deal_damage_to_minion(m, 1, source=c.name+" (Battlecry)")
            else:
                pid = target
                ev += g.deal_damage_to_player(pid, 1, source=c.name+" (Battlecry)")
        return ev
    db["KOBOLD_PING"] = Card(id="KOBOLD_PING", name="Kobold Pinger", cost=2, type="MINION", attack=2, health=2, battlecry=bc_pinger)

    # Leper Gnome with deathrattle: deal 2 face
    def dr_boom(g:Game, m:Minion):
        opp = g.other(m.owner)
        return g.deal_damage_to_player(opp, 2, source=m.name+" (Deathrattle)")
    db["LEPER_GNOME"] = Card(id="LEPER_GNOME", name="Leper Gnome", cost=1, type="MINION", attack=2, health=1)
    def attach_deathrattle_on_summon(g:Game, m:Minion):
        if m.name == "Leper Gnome":
            def dr(g2:Game, m2:Minion):
                return dr_boom(g2, m2)
            m.deathrattle = dr

    db["FIREBALL_LITE"] = Card(id="FIREBALL_LITE", name="Fireball Lite", cost=4, type="SPELL", on_cast=spell_damage(4))

    # Arcane Missiles-like: 3 random pings among enemies
    def on_cast_missiles(g:Game, c:Card, target:Optional[int]):
        ev: List[Event] = []
        opp = g.other(g.active_player)
        for _ in range(3):
            pool = [("player", opp)] + [("minion", m.id) for m in g.players[opp].board if m.is_alive()]
            choice = g.rng.choice(pool)
            if choice[0] == "player":
                ev += g.deal_damage_to_player(opp, 1, source=c.name)
            else:
                loc = g.find_minion(choice[1])
                if loc:
                    _,_,m = loc
                    ev += g.deal_damage_to_minion(m, 1, source=c.name)
        return ev
    db["ARCANE_MISSILES_LITE"] = Card(id="ARCANE_MISSILES_LITE", name="Arcane Missiles Lite", cost=1, type="SPELL", on_cast=on_cast_missiles)

    db["_POST_SUMMON_HOOK"] = attach_deathrattle_on_summon
    return db

def apply_post_summon_hooks(g:Game, evs:list):
    hook = g.cards_db.get("_POST_SUMMON_HOOK")
    if not hook:
        return
    for e in evs:
        if e.kind == "MinionSummoned":
            minfo = g.find_minion(e.payload["minion"])
            if minfo:
                _,_,m = minfo
                hook(g, m)
