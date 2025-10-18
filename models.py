
# ---------------------- Events ----------------------

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


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
    counts_as_spell: bool = False

@dataclass
class Hero:
    id: str             # canonical id, e.g. "MAGE"
    name: str           # friendly display, e.g. "Mage"
    power: HeroPower

@dataclass
class Weapon:
    name: str
    attack: int
    durability: int
    max_durability: int = 0
    card_id: str = ""
    triggers_map: Dict[str, List[Callable]] = field(default_factory=dict)

    def __post_init__(self):
        if self.max_durability <= 0:
            self.max_durability = self.durability

@dataclass
class Minion:
    id: int
    owner: int
    name: str
    attack: int
    health: int
    max_health: int
    minion_type: str = "None"
    spell_damage: int = 0
    taunt: bool = False
    divine_shield: bool = False
    charge: bool = False
    rush: bool = False
    frozen: bool = False
    can_attack: bool = False
    exhausted: bool = True
    silenced: bool = False
    cant_attack: bool = False   # (e.g., Ragnaros)  
    deathrattle: Optional[Callable[['Game','Minion'], List[Event]]] = None # type: ignore
    aura_spec: Optional[Dict[str, Any]] = None   # e.g. {"scope":"other_friendly_minions","attack":1,"health":1}
    cost_aura_spec: Optional[Dict[str, Any]] = None
    auras: List[Dict[str, Any]] = field(default_factory=list)   # NEW (multi-auras)
    aura_active: bool = False
    enrage_spec: Optional[Dict[str, Any]] = None
    enrage_active: bool = False
    triggers_map: Dict[str, List[Callable[['Game','Minion', Optional[Dict]] , List[Event]]]] = field(default_factory=dict) # type: ignore
    temp_stats: Dict[int, Dict[str, int]] = field(default_factory=dict)  # {pid: {"attack":0,"health":0,"max_health":0}}
    temp_keywords: Dict[int, Dict[str, int]] = field(default_factory=dict)  # {pid: {"charge":N,"taunt":N,"rush":N,"divine_shield":N}}

    has_attacked_this_turn: bool = False

    summoned_this_turn: bool = True
    cost: int = 0  # original mana cost to display on-board
    rarity: str = ""

    card_id: str = ""
    base_attack: int = 0
    base_health: int = 0
    base_text: str = ""
    base_minion_type: str = "None"
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
    spell_damage: int = 0
    keywords: List[str] = field(default_factory=list)
    # Scripting hooks:
    battlecry: Optional[Callable[['Game','Card', Optional[int]], List[Event]]] = None # type: ignore
    on_cast: Optional[Callable[['Game','Card', Optional[int]], List[Event]]] = None # type: ignore
    aura_spec: Optional[Dict[str, Any]] = None
    cost_aura_spec: Optional[Dict[str, Any]] = None
    auras: List[Dict[str, Any]] = field(default_factory=list)   # NEW (multi-auras)
    triggers_map: Dict[str, List[Callable]] = field(default_factory=dict)
    text: str = ""
    rarity: str = ""
    minion_type: str = ""

@dataclass
class PlayerState:
    id: int
    deck: List[str]
    hand: List[str] = field(default_factory=list)
    board: List[Minion] = field(default_factory=list)
    graveyard: List[str] = field(default_factory=list)
    dead_minions: List[Minion] = field(default_factory=list)
    active_secrets: List[dict] = field(default_factory=list)
    health: int = 30
    max_health: int = 30
    armor: int = 0
    max_mana: int = 0
    mana: int = 0
    fatigue: int = 0
    hero: Hero = None
    hero_power_used_this_turn: bool = False
    hero_frozen: bool = False
    weapon: Optional[Weapon] = None
    hero_has_attacked_this_turn: bool = False
    temp_cost_mods: List[Dict[str, Any]] = field(default_factory=list)

    def draw(self, g:'Game', n:int=1) -> List[Event]: # type: ignore
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