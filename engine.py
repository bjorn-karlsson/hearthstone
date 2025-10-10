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
    can_attack: bool = False
    exhausted: bool = True
    deathrattle: Optional[Callable[['Game','Minion'], List[Event]]] = None
    # internal flags
    has_attacked_this_turn: bool = False

    # NEW: for UI/logic
    summoned_this_turn: bool = True
    cost: int = 0  # original mana cost to display on-board

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
            m.exhausted = False
            m.has_attacked_this_turn = False
            m.summoned_this_turn = False
            m.can_attack = m.charge or (not m.exhausted)
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
                cost=card.cost
                
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

# ---------------------- Card Scripts ----------------------

def make_db() -> Dict[str, Card]:
    db: Dict[str, Card] = {}

    # ---------- Helpers ----------
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

    def heal_player(pid:int, amt:int) -> Callable[[Game, Card, Optional[int]], List[Event]]:
        def on_cast(g:Game, c:Card, target:Optional[int]):
            tpid = pid if target is None else target
            p = g.players[tpid]
            before = p.health
            p.health = min(30, p.health + amt)
            healed = p.health - before
            if healed > 0:
                return [Event("PlayerHealed", {"player": tpid, "amount": healed, "source": c.name})]
            return []
        return on_cast

    def heal_minion_or_face(amt:int) -> Callable[[Game, Card, Optional[int]], List[Event]]:
        # Target: minion id OR player id
        def on_cast(g:Game, c:Card, target:Optional[int]):
            ev: List[Event] = []
            if not isinstance(target, int):
                return ev
            loc = g.find_minion(target)
            if loc:
                _,_,m = loc
                before = m.health
                m.health = min(m.max_health, m.health + amt)
                healed = m.health - before
                if healed > 0:
                    ev.append(Event("MinionHealed", {"minion": m.id, "amount": healed, "source": c.name}))
            else:
                pid = target
                p = g.players[pid]
                before = p.health
                p.health = min(30, p.health + amt)
                healed = p.health - before
                if healed > 0:
                    ev.append(Event("PlayerHealed", {"player": pid, "amount": healed, "source": c.name}))
            return ev
        return on_cast

    def buff_minion(delta_atk:int, delta_hp:int, add_taunt:bool=False, give_charge:bool=False, give_rush:bool=False):
        def on_cast(g:Game, c:Card, target:Optional[int]):
            if not isinstance(target, int):
                return []
            loc = g.find_minion(target)
            if not loc:
                return []
            _,_,m = loc
            m.attack += delta_atk
            m.max_health += delta_hp
            m.health += delta_hp
            if add_taunt: m.taunt = True
            if give_charge: m.charge = True
            if give_rush: m.rush = True
            return [Event("MinionBuffed", {"minion": m.id, "atk": delta_atk, "hp": delta_hp, "source": c.name})]
        return on_cast

    def silence_minion():
        def on_cast(g:Game, c:Card, target:Optional[int]):
            if not isinstance(target, int): return []
            loc = g.find_minion(target)
            if not loc: return []
            _,_,m = loc
            # strip keywords and deathrattle; keep stats
            m.taunt = False
            m.charge = False
            m.rush = False
            m.deathrattle = None
            return [Event("MinionSilenced", {"minion": m.id, "source": c.name})]
        return on_cast

    def polymorph_minion(new_name:str, atk:int, hp:int):
        def on_cast(g:Game, c:Card, target:Optional[int]):
            if not isinstance(target, int): return []
            loc = g.find_minion(target)
            if not loc: return []
            _,_,m = loc
            m.name = new_name
            m.attack = atk
            m.max_health = hp
            m.health = min(m.health, hp)
            m.taunt = False
            m.charge = False
            m.rush = False
            m.deathrattle = None
            return [Event("MinionTransformed", {"minion": m.id, "to": new_name, "source": c.name})]
        return on_cast

    def draw_cards(pid:int, n:int):
        def on_cast(g:Game, c:Card, target:Optional[int]):
            return g.players[pid].draw(g, n)
        return on_cast

    def draw_cards_active(n:int):
        def on_cast(g:Game, c:Card, target:Optional[int]):
            return g.players[g.active_player].draw(g, n)
        return on_cast

    def summon_minion(g:Game, pid:int, name:str, atk:int, hp:int, keywords:List[str]=None, cost:int=0) -> List[Event]:
        if keywords is None: keywords = []
        if len(g.players[pid].board) >= 7:
            return [Event("SummonFailed", {"player": pid, "name": name, "reason": "BoardFull"})]
        m = Minion(
            id=g.next_minion_id, owner=pid, name=name,
            attack=atk, health=hp, max_health=hp,
            taunt=("Taunt" in keywords), charge=("Charge" in keywords), rush=("Rush" in keywords),
            summoned_this_turn=True, cost=cost
        )
        g.next_minion_id += 1
        g.players[pid].board.append(m)
        ev = [Event("MinionSummoned", {"player": pid, "minion": m.id, "name": m.name})]
        # apply post-summon hook (deathrattles) if present
        hook = g.cards_db.get("_POST_SUMMON_HOOK")
        if hook: hook(g, m)
        return ev

    def aoe_damage(enemies_only:bool, to_minions:int=0, to_face:int=0):
        def on_cast(g:Game, c:Card, target:Optional[int]):
            ev: List[Event] = []
            opp = g.other(g.active_player)
            # minions
            for m in list(g.players[opp].board if enemies_only else g.players[0].board + g.players[1].board):
                if m.is_alive() and to_minions>0:
                    ev += g.deal_damage_to_minion(m, to_minions, source=c.name)
            # faces
            if to_face>0:
                if enemies_only:
                    ev += g.deal_damage_to_player(opp, to_face, source=c.name)
                else:
                    ev += g.deal_damage_to_player(0, to_face, source=c.name)
                    ev += g.deal_damage_to_player(1, to_face, source=c.name)
            return ev
        return on_cast

    # ---------- The Coin ----------
    def on_cast_coin(g:Game, c:Card, t:Optional[int]):
        p = g.players[g.active_player]
        p.mana = min(p.mana + 1, p.max_mana + 1)
        return [Event("GainMana", {"player": g.active_player, "temp": 1, "mana_after": p.mana})]
    db["THE_COIN"] = Card(id="THE_COIN", name="The Coin", cost=0, type="SPELL", on_cast=on_cast_coin)

    # ---------- Originals ----------
    db["RIVER_CROCOLISK"]   = Card(id="RIVER_CROCOLISK",   name="River Crocolisk", cost=2, type="MINION", attack=2, health=3)
    db["CHILLWIND_YETI"]    = Card(id="CHILLWIND_YETI",    name="Chillwind Yeti",  cost=4, type="MINION", attack=4, health=5)
    db["BOULDERFIST_OGRE"]  = Card(id="BOULDERFIST_OGRE",  name="Boulderfist Ogre",cost=6, type="MINION", attack=6, health=7)
    db["SHIELD_BEARER"]     = Card(id="SHIELD_BEARER",     name="Shieldbearer",    cost=1, type="MINION", attack=0, health=4, keywords=["Taunt"])
    db["WOLFRIDER"]         = Card(id="WOLFRIDER",         name="Wolfrider",       cost=3, type="MINION", attack=3, health=1, keywords=["Charge"])
    db["RUSHER"]            = Card(id="RUSHER",            name="Arena Rusher",    cost=2, type="MINION", attack=2, health=1, keywords=["Rush"])

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

    def dr_boom(g:Game, m:Minion):
        opp = g.other(m.owner)
        return g.deal_damage_to_player(opp, 2, source=m.name+" (Deathrattle)")
    db["LEPER_GNOME"] = Card(id="LEPER_GNOME", name="Leper Gnome", cost=1, type="MINION", attack=2, health=1)

    db["FIREBALL_LITE"] = Card(id="FIREBALL_LITE", name="Fireball Lite", cost=4, type="SPELL", on_cast=spell_damage(4))

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

    # ---------- New Minions ----------
    db["TAUNT_BEAR"] = Card(id="TAUNT_BEAR", name="Ironfur Grizzly-ish", cost=3, type="MINION", attack=3, health=3, keywords=["Taunt"])
    db["CHARGING_BOAR"] = Card(id="CHARGING_BOAR", name="Charging Boar", cost=1, type="MINION", attack=1, health=1, keywords=["Charge"])
    db["KNIFE_THROWER"] = Card(id="KNIFE_THROWER", name="Knife Thrower", cost=3, type="MINION", attack=3, health=2,
                               battlecry=lambda g,c,t: [g.deal_damage_to_player(g.other(g.active_player),1,source=c.name+" (Battlecry)")][0])

    # Loot Hoarder: DR draw 1
    db["LOOT_HOARDER"] = Card(id="LOOT_HOARDER", name="Loot Hoarder", cost=2, type="MINION", attack=2, health=1)
    # Harvest Golem: DR summon 2/1 Damaged Golem
    db["HARVEST_GOLEM"] = Card(id="HARVEST_GOLEM", name="Harvest Golem", cost=3, type="MINION", attack=2, health=3)

    # Nerubian Egg: 0/2 DR summon 4/4
    db["NERUBIAN_EGG"] = Card(id="NERUBIAN_EGG", name="Nerubian Egg", cost=2, type="MINION", attack=0, health=2)

    # Battlecry heal allies
    def bc_earthen_ring(g:Game, c:Card, target:Optional[int]):
        # heal chosen minion or face for 3
        return heal_minion_or_face(3)(g, c, target)
    db["EARTHEN_RING"] = Card(id="EARTHEN_RING", name="Earthen Ring Healer", cost=3, type="MINION", attack=3, health=3, battlecry=bc_earthen_ring)

    # Wolf Rider+Rush variant
    db["CHARGE_RUSH_2_2"] = Card(id="CHARGE_RUSH_2_2", name="Reckless Sprinter", cost=2, type="MINION", attack=2, health=2, keywords=["Rush"])

    # ---------- New Spells (targeted) ----------
    db["HOLY_LIGHT_LITE"] = Card(id="HOLY_LIGHT_LITE", name="Holy Light Lite", cost=2, type="SPELL", on_cast=heal_minion_or_face(6))
    db["BLESSING_OF_MIGHT_LITE"] = Card(id="BLESSING_OF_MIGHT_LITE", name="Blessing of Might Lite", cost=1, type="SPELL",
                                        on_cast=buff_minion(3,0))
    db["BLESSING_OF_KINGS_LITE"] = Card(id="BLESSING_OF_KINGS_LITE", name="Blessing of Kings Lite", cost=4, type="SPELL",
                                        on_cast=buff_minion(4,4))
    db["HAND_OF_PROTECTION_LITE"] = Card(id="HAND_OF_PROTECTION_LITE", name="Hand of Protection Lite", cost=1, type="SPELL",
                                         on_cast=buff_minion(0,0))  # (no divine shield mechanic, left as placeholder buff)
    db["GIVE_TAUNT"] = Card(id="GIVE_TAUNT", name="Give Taunt", cost=1, type="SPELL", on_cast=buff_minion(0,0,add_taunt=True))
    db["GIVE_CHARGE"] = Card(id="GIVE_CHARGE", name="Give Charge", cost=1, type="SPELL", on_cast=buff_minion(0,0,give_charge=True))
    db["GIVE_RUSH"] = Card(id="GIVE_RUSH", name="Give Rush", cost=1, type="SPELL", on_cast=buff_minion(0,0,give_rush=True))

    db["SILENCE_LITE"] = Card(id="SILENCE_LITE", name="Silence Lite", cost=2, type="SPELL", on_cast=silence_minion())
    db["POLYMORPH_LITE"] = Card(id="POLYMORPH_LITE", name="Polymorph Lite", cost=4, type="SPELL", on_cast=polymorph_minion("Sheep", 1, 1))

    # ---------- New Spells (non-targeted) ----------
    db["ARCANE_INTELLECT_LITE"] = Card(id="ARCANE_INTELLECT_LITE", name="Arcane Intellect Lite", cost=3, type="SPELL", on_cast=draw_cards_active(2))
    db["CONSECRATION_LITE"] = Card(id="CONSECRATION_LITE", name="Consecration Lite", cost=4, type="SPELL", on_cast=aoe_damage(True, to_minions=2, to_face=2))
    db["FAN_OF_KNIVES_LITE"] = Card(id="FAN_OF_KNIVES_LITE", name="Fan of Knives Lite", cost=3, type="SPELL",
                                    on_cast=lambda g,c,t: aoe_damage(True, to_minions=1, to_face=0)(g,c,t) + g.players[g.active_player].draw(g,1))
    db["FLAMESTRIKE_LITE"] = Card(id="FLAMESTRIKE_LITE", name="Flamestrike Lite", cost=7, type="SPELL",
                                  on_cast=aoe_damage(True, to_minions=4, to_face=0))
    db["SWIPE_LITE"] = Card(id="SWIPE_LITE", name="Swipe Lite", cost=4, type="SPELL",
                            on_cast=lambda g,c,t: (g.deal_damage_to_minion(g.find_minion(t)[2],4,source=c.name) if isinstance(t,int) and g.find_minion(t) else []) +
                                                  [e for m in g.players[g.other(g.active_player)].board for e in g.deal_damage_to_minion(m,1,source=c.name) if m.is_alive()])

    # Summon tokens
    def on_cast_wisps(g:Game, c:Card, t:Optional[int]):
        pid = g.active_player
        ev: List[Event] = []
        ev += summon_minion(g, pid, "Wisp", 1, 1, [], cost=0)
        ev += summon_minion(g, pid, "Wisp", 1, 1, [], cost=0)
        return ev
    db["RAISE_WISPS"] = Card(id="RAISE_WISPS", name="Raise Wisps", cost=2, type="SPELL", on_cast=on_cast_wisps)

    def on_cast_wolves(g:Game, c:Card, t:Optional[int]):
        pid = g.active_player
        ev: List[Event] = []
        ev += summon_minion(g, pid, "Spirit Wolf", 2, 3, ["Taunt"], cost=2)
        ev += summon_minion(g, pid, "Spirit Wolf", 2, 3, ["Taunt"], cost=2)
        return ev
    db["FERAL_SPIRIT_LITE"] = Card(id="FERAL_SPIRIT_LITE", name="Feral Spirit Lite", cost=3, type="SPELL", on_cast=on_cast_wolves)

    # Token spawner spells/minions
    db["MUSTER_FOR_BATTLE_LITE"] = Card(
        id="MUSTER_FOR_BATTLE_LITE", name="Muster for Battle Lite", cost=3, type="SPELL",
        on_cast=lambda g,c,t: summon_minion(g, g.active_player, "Recruit", 1, 1, [], cost=1) +
                             summon_minion(g, g.active_player, "Recruit", 1, 1, [], cost=1) +
                             summon_minion(g, g.active_player, "Recruit", 1, 1, [], cost=1)
    )

    # ---------- Deathrattles via post-summon hook ----------
    def attach_deathrattle_on_summon(g:Game, m:Minion):
        # Leper Gnome -> 2 face
        if m.name == "Leper Gnome":
            def dr(g2:Game, m2:Minion):
                opp = g2.other(m2.owner)
                return g2.deal_damage_to_player(opp, 2, source=m2.name+" (Deathrattle)")
            m.deathrattle = dr
        # Loot Hoarder -> draw 1
        elif m.name == "Loot Hoarder":
            def dr(g2:Game, m2:Minion):
                return g2.players[m2.owner].draw(g2, 1)
            m.deathrattle = dr
        # Harvest Golem -> summon Damaged Golem 2/1
        elif m.name == "Harvest Golem":
            def dr(g2:Game, m2:Minion):
                return summon_minion(g2, m2.owner, "Damaged Golem", 2, 1, [], cost=1)
            m.deathrattle = dr
        # Nerubian Egg -> summon 4/4
        elif m.name == "Nerubian Egg":
            def dr(g2:Game, m2:Minion):
                return summon_minion(g2, m2.owner, "Nerubian", 4, 4, [], cost=4)
            m.deathrattle = dr

    db["_POST_SUMMON_HOOK"] = attach_deathrattle_on_summon


    # ---------- Attach Hearthstone-style text ----------
    def set_text(cid: str, text: str):
        if cid in db:
            db[cid].text = text

    # Core
    set_text("THE_COIN", "Gain 1 temporary Mana Crystal this turn only.")
    set_text("RIVER_CROCOLISK", "A sturdy river dweller.")
    set_text("CHILLWIND_YETI", "It's not just a breeze.")
    set_text("BOULDERFIST_OGRE", "Big. Loud. Effective.")
    set_text("SHIELD_BEARER", "Taunt")
    set_text("WOLFRIDER", "Charge")
    set_text("RUSHER", "Rush")

    # Your minions/spells with effects
    set_text("KOBOLD_PING", "Battlecry: Deal 1 damage.")
    set_text("LEPER_GNOME", "Deathrattle: Deal 2 damage to the enemy hero.")
    set_text("FIREBALL_LITE", "Deal 4 damage.")
    set_text("ARCANE_MISSILES_LITE", "Deal 3 damage randomly split among enemies.")
    set_text("TAUNT_BEAR", "Taunt")
    set_text("CHARGING_BOAR", "Charge")
    set_text("KNIFE_THROWER", "Battlecry: Deal 1 damage to the enemy hero.")
    set_text("LOOT_HOARDER", "Deathrattle: Draw a card.")
    set_text("HARVEST_GOLEM", "Deathrattle: Summon a 2/1 Damaged Golem.")
    set_text("NERUBIAN_EGG", "Deathrattle: Summon a 4/4 Nerubian.")
    set_text("EARTHEN_RING", "Battlecry: Restore 3 Health.")
    set_text("CHARGE_RUSH_2_2", "Rush")
    set_text("HOLY_LIGHT_LITE", "Restore 6 Health.")
    set_text("BLESSING_OF_MIGHT_LITE", "Give a minion +3 Attack.")
    set_text("BLESSING_OF_KINGS_LITE", "Give a minion +4/+4.")
    set_text("HAND_OF_PROTECTION_LITE", "Give a friendly minion… (placeholder)")  # you can change later
    set_text("GIVE_TAUNT", "Give a minion Taunt.")
    set_text("GIVE_CHARGE", "Give a minion Charge.")
    set_text("GIVE_RUSH", "Give a minion Rush.")
    set_text("SILENCE_LITE", "Silence a minion.")
    set_text("POLYMORPH_LITE", "Transform a minion into a 1/1 Sheep.")
    set_text("ARCANE_INTELLECT_LITE", "Draw 2 cards.")
    set_text("CONSECRATION_LITE", "Deal 2 damage to all enemies.")
    set_text("FAN_OF_KNIVES_LITE", "Deal 1 damage to all enemy minions. Draw a card.")
    set_text("FLAMESTRIKE_LITE", "Deal 4 damage to all enemy minions.")
    set_text("SWIPE_LITE", "Deal 4 damage to an enemy minion and 1 to the rest.")
    set_text("RAISE_WISPS", "Summon two 1/1 Wisps.")
    set_text("FERAL_SPIRIT_LITE", "Summon two 2/3 Spirit Wolves with Taunt.")
    set_text("MUSTER_FOR_BATTLE_LITE", "Summon three 1/1 Recruits.")



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
