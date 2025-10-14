import pygame
import sys
from typing import Optional, Tuple, List, Dict, Any
import random
from collections import deque
import json
from pathlib import Path
import math


from engine import Game, load_cards_from_json, load_heros_from_json, load_decks_from_json, choose_loaded_deck, IllegalAction
from ai import pick_best_action

# --- Debug / dev toggles ---
SHOW_ENEMY_HAND = False
DEBUG_BTN_RECT = None

DEBUG = False

pygame.init()
# Fullscreen @ desktop resolution
screen = pygame.display.set_mode((0, 0))
W, H = screen.get_size()
pygame.display.set_caption("Python Card Battler (Animated-Locked + Targets)")

FONT = pygame.font.SysFont(None, 22)
BIG  = pygame.font.SysFont(None, 26)
RULE_FONT = pygame.font.SysFont(None, 20)  # smaller for rules text




# Colors
BG = (20, 25, 30)
WHITE = (230, 230, 230)
GREY = (150, 150, 150)
GREEN = (60, 200, 90)        # ready glow
RED   = (210, 70, 70)        # rush outline + target highlight
BLUE  = (80, 140, 240)       # buttons
YELLOW = (230, 200, 90)
CARD_BG_HAND = (45, 75, 110)
CARD_BG_MY   = (60, 100, 70)
CARD_BG_EN   = (70, 70, 100)
COST_BADGE   = (0, 50, 102)

ATTK_COLOR   = (230, 170, 60)  # orange-yellow for attack
HP_OK        = WHITE
HP_HURT      = (230, 80, 80)   # red when damaged

# --- Hero plate + battlefield ---
BOARD_BG       = (26, 32, 40)   # battleground panel fill
BOARD_BORDER   = (60, 90, 130)  # battleground border

HEALTH_BADGE   = (210, 70, 70)
ARMOR_BADGE    = (130, 130, 130)
MANA_BADGE     = (60, 120, 230)
PLATE_BG       = (30, 36, 46)   # hero plate background
PLATE_RIM      = (42, 50, 60)   # hero plate outline

# Hero plate sizing + crystal width
FACE_W = 220
FACE_H = 64
CRYSTAL_W = 54
CRYSTAL_PAD = 10

LOG_MAX_LINES = 40
LOG_PANEL_W   = 320
LOG_BG        = (18, 22, 26)
LOG_TEXT      = (215, 215, 215)
LOG_ACCENT    = (140, 170, 255)

ACTION_LOG = deque(maxlen=LOG_MAX_LINES)

RARITY_COLORS = {
    "COMMON":     (235, 235, 235),  # white
    "RARE":       (80, 140, 240),   # blue
    "EPIC":       (165, 95, 210),   # purple
    "LEGENDARY":  (255, 140, 20),   # orange
}

HERO_COLORS = {
    "WARRIOR": (185, 35, 35),
    "WARLOCK": (115, 35, 160),
    "PALADIN": (210, 175, 60),
    "MAGE":    (60, 120, 230),
    "HUNTER":  (35, 155, 75),
}

def hero_name(h) -> str:
    if isinstance(h, str):
        return h.capitalize()
    if hasattr(h, "name"):
        return h.name
    return str(h)

# Layout
CARD_W, CARD_H = 125, 200   # bigger cards so text fits
MARGIN = 15                 # gap between cards
ROW_Y_ENEMY = 110              # a bit higher
ROW_Y_ME    = 325               # a bit higher
ROW_Y_HAND  = H - CARD_H - 30  # lock hand to bottom with padding

# Hand fan/hover
HAND_OVERLAP = 0.42      # 0..1 (how much each card overlaps the previous)
HOVER_SCALE  = 1.35      # how big the zoom is on hover
HOVER_LIFT   = 44        # how much it rises while hovered

# Timing (ms)
ANIM_PLAY_MS    = 550
ANIM_ATTACK_MS  = 420
ANIM_RETURN_MS  = 320
ANIM_FLASH_MS   = 220
AI_THINK_MS     = 750
ANIM_SPELL_MS   = 420   # spell projectile travel
ANIM_HERO_MS    = 460   # hero lift + dash
START_GAME      = 1500


KEYWORD_HELP = {
    "Battlecry": "Triggers when played from hand (on summon).",
    "Deathrattle": "After this dies, do its effect.",
    "Taunt": "Enemies must attack this first.",
    "Rush": "Can attack minions immediately.",
    "Charge": "Can attack heroes and minions immediately.",
    "Silence": "Remove text and keywords from a minion.",
    "Spell Damage": "Your spells deal +N damage.",
    "Enrage": "While damaged: gain the listed bonus.",
    "Divine Shield": "Prevents the first damage this minion would take. The hit is fully absorbed, then the shield is removed.",
    "Freeze": "Frozen characters can't attack during their next turn. It wears off after that turn ends.",
}

# -------- LOGGING -------------

def add_log(msg: str):
    if not msg: return
    for line in msg.splitlines():
        ACTION_LOG.append(line)

def format_event(e, g, skip=False) -> str:
    def _minion_name(g: Game, mid: int) -> str:
        # 1) still alive?
        loc = g.find_minion(mid)
        if loc:
            return loc[2].name
        # 2) look in dead piles
        for pid in (0, 1):
            for dm in g.players[pid].dead_minions:
                if dm.id == mid:
                    return dm.name
        # 3) fallback
        return f"#{mid}"

    k = getattr(e, "kind", "")
    p = getattr(e, "payload", {})

    if DEBUG and not skip:
        return f"{k}: {format_event(e, g, True)}"

    if k == "Frozen":
        t = p.get("target_type")
        if t == "player":
            who = "You" if p.get("player") == 0 else "AI"
            return f"{who} is Frozen."
        if t == "minion":
            return f"{_minion_name(g, p.get('minion'))} is Frozen."
    if k == "Thaw":
        t = p.get("target_type")
        if t == "player":
            who = "You" if p.get("player") == 0 else "AI"
            return f"{who} is no longer Frozen."
        if t == "minion":
            return f"{_minion_name(g, p.get('minion'))} thawed."

    if k == "DivineShieldPopped":
        return f"{p.get('name','A minion')}'s Divine Shield broke."
    if k == "SecretPlayed":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} set a Secret."
    if k == "SecretRevealed":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who}'s Secret revealed: {p.get('name','Secret')}!"
    if k == "WeaponEquipped":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} equiped {p.get('name')}."
    if k == "HeroAttack":
        tgt = p.get("target")
        who = "You" if p.get("player") == 0 else "AI"
        if isinstance(tgt, str) and tgt.startswith("player:"):
            side = "AI" if tgt.endswith("1") else "You"
            return f"{who}'s hero attacked {side}'s face."
        # else minion id
        mid = p.get("target")
        # try to resolve name:
        nm = _minion_name(g, mid) if isinstance(mid, int) else "a minion"
        return f"{who}'s hero attacked {nm}."
    if k == "HeroPowerUsed":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} used {p.get('hero','Hero')} power."
    if k == "ArmorGained":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} gained {p.get('amount',0)} Armor."
    if k == "GameStart":
        who = "You" if p.get("active_player") == 0 else "AI"
        return f"Game started. {who} goes first."
    if k == "TurnStart":
        who = "You" if p.get("player") == 0 else "AI"
        return f"— Turn {p.get('turn', '')} start: {who}"
    if k == "TurnEnd":
        who = "You" if p.get("player") == 0 else "AI"
        return f"Turn ended: {who}"
    if k == "CardDrawn":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} drew a card."
    if k == "CardDiscovered":
        who = "You" if p["player"] == 0 else "AI"
        cid = p.get("card")
        nm  = card_name_from_db(g.cards_db, cid)
        return f"{who} discovered {nm}."

    if k == "CardBurned":
        who = "You" if p["player"] == 0 else "AI"
        cid = p.get("card", "")
        name = card_name_from_db(g.cards_db, cid) if cid else "a card"
        return f"{who} burned {name} (hand full)."
    if k == "CardPlayed":
        who = "You" if p["player"] == 0 else "AI"
        cid = p.get("card", "")
        name = card_name_from_db(g.cards_db, cid) if cid else "a card"
        return f"{who} played {name}."
    if k == "MinionSummoned":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} summoned {p.get('name','a minion')}."
    if k == "Attack":
        tgt = p.get("target")
        if isinstance(tgt, str) and tgt.startswith("player:"):
            side = "You" if tgt.endswith("0") else "AI"
            return f"Minion {_minion_name(g, p['attacker'])} attacked {side}'s face."
        return f"Minion {_minion_name(g, p['attacker'])} attacked {_minion_name(g, tgt)}."
    if k == "MinionDamaged":
        src = p.get("source","")
        return f"{_minion_name(g, p['minion'])} took {p['amount']} dmg{f' ({src})' if src else ''}."
    if k == "PlayerDamaged":
        who = "You" if p["player"] == 0 else "AI"
        src = p.get("source","")
        return f"{who} took {p['amount']} dmg{f' ({src})' if src else ''}."
    if k == "MinionHealed":
        return f"Minion {_minion_name(g, p['minion'])} healed {p['amount']}."
    if k == "PlayerHealed":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} healed {p['amount']}."
    if k == "MinionDied":
        # you already store the name in the payload
        return f"{p.get('name','A minion')} died."
    if k == "Buff":
        return f"Minion {_minion_name(g, p['minion'])} buffed (+{p.get('attack_delta',0)}/+{p.get('health_delta',0)})."
    if k == "BuffKeyword":
        return f"Minion {_minion_name(g, p['minion'])} gained {p.get('keyword','a keyword')}."
    if k == "Silenced":
        return f"Minion {_minion_name(g, p['minion'])} was silenced."
    if k == "GainMana":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} gained {p.get('temp',1)} temporary mana."
    if k == "PlayerDefeated":
        who = "You" if p["player"] == 0 else "AI"
        return f"{who} was defeated."
    if k == "SpellHit":
        src = p.get("source", "Spell")
        ttype = p.get("target_type")
        if ttype == "player":
            who = "You" if p.get("player") == 0 else "AI"
            return f"{src} hits {who}'s face."
        if ttype == "minion":
            # payload may include name, but resolve live just in case
            mid = p.get("minion")
            return f"{src} hits {_minion_name(g, mid)}."
        return ""
    
    print(f"not logging {k}")
    
def log_events(ev_list, g):
    for e in ev_list or []:
        s = format_event(e, g)
        if s: add_log(s)


# --------- starter deck ----------
def select_random_hero(hero_db):
    return random.choice(list(hero_db.values()))

def shuffle_deck(deck, seed=None):
    rng = random.Random(seed)
    rng.shuffle(deck)
    return deck

def make_starter_deck(db, seed=None):
    rng = random.Random(seed)
    
    # What you'd *like* to include:
    desired = [
        # 1-cost
        "LEPER_GNOME", "CHARGING_BOAR", "SHIELD_BEARER", "BLESSING_OF_MIGHT", "GIVE_TAUNT", "SCRAPPY_SCAVENGER",
        "VOODOO_DOCTOR", "TIMBER_WOLF",
        # 2-cost
        "RIVER_CROCOLISK", "KOBOLD_PING", "RUSHER", "NERUBIAN_EGG", "HOLY_LIGHT", "NOVICE_ENGINEER", 
        "KOBOLD_GEOMANCER", "AMANI_BERSERKER", "ACIDIC_SWAMP_OOZE",
        # 3-cost
        "IRONFUR_GRIZZLY", "WOLFRIDER", "EARTHEN_RING", "HARVEST_GOLEM", "ARCANE_MISSILES",
        "CHARGE_RUSH_2_2", "SHATTERED_SUN_CLERIC", "RAID_LEADER", "KOBOLD_BLASTER",
        # 4-cost
        "CHILLWIND_YETI", "FIREBALL", "BLESSING_OF_KINGS",
        "POLYMORPH", "ARCANE_INTELLECT", "ARCANE_INTELLECT",
        "SPELLBREAKER", "SHIELDMASTA", "DEFENDER_OF_ARGUS", "ARATHI_WEAPONSMITH",
        # 5+ cost
        "SILVER_HAND_KNIGHT", "CONSECRATION", "BOULDERFIST_OGRE", "FLAMESTRIKE", "RAISE_WISPS", "FERAL_SPIRIT",
        "MUSTER_FOR_BATTLE", "SILENCE", "GIVE_CHARGE", "GIVE_RUSH", "LEGENDARY_LEEROY_JENKINS",
        "STORMPIKE_COMMANDO", "CORE_HOUND", "WAR_GOLEM", "STORMWIND_CHAMPION",
    ]
    desired = ["LOOT_HOARDER"] * 15

    # DB keys that are real cards (ignore internal keys like "_POST_SUMMON_HOOK")
    valid_ids = {cid for cid in db.keys() if not cid.startswith("_")}

    # Filter desired by what actually exists in the JSON
    pool = [cid for cid in desired if cid in valid_ids]

    # Helpful debug print so you can see what's missing from the JSON
    missing = [cid for cid in desired if cid not in valid_ids]
    if missing:
        print("[DeckBuilder] Missing from JSON (will be skipped):", ", ".join(missing))

    # If pool too small, pad with *any* valid IDs from JSON
    if len(pool) < 15:
        extras = [cid for cid in valid_ids if cid not in pool]
        rng.shuffle(extras)
        pool.extend(extras[: max(0, 25 - len(pool))])

    # Allow up to 2 copies of each, shuffle, and take 30
    dupes = [cid for cid in pool for _ in range(2)]
    rng.shuffle(dupes)

    # Ensure 30 cards
    deck = []
    while len(deck) < 30 and dupes:
        deck.append(dupes.pop())
    while len(deck) < 30 and pool:
        deck.append(rng.choice(pool))

    return deck[:30]

# Build DB + deck
db      = load_cards_from_json("lib/cards.json")
hero_db = load_heros_from_json("lib/heroes.json")

# Try to load preconfigured decks
try:
    loaded_decks = load_decks_from_json("lib/decks.json", db)
except Exception as e:
    print("[DeckLoader] Failed to read decks.json:", e)
    loaded_decks = {}

playable_decks = [
    "Classic Hunter Deck (Midrange / Face Hybrid)", 
    "Classic Paladin Deck (Midrange / Control)",
    "Classic Mage Deck (Spell Control / Burst)"
]


# Pick a deck for each side (by name or first valid), else fall back to your random builder
player_deck, player_hero_hint = choose_loaded_deck(loaded_decks, preferred_name=random.choice(playable_decks))
ai_deck, ai_hero_hint         = choose_loaded_deck(loaded_decks, preferred_name=random.choice(playable_decks))

#player_deck = None
if not player_deck:
    player_deck = make_starter_deck(db, random.randint(1, 5_000_000))
if not ai_deck:
    ai_deck = make_starter_deck(db, random.randint(1, 5_000_000))

player_deck = shuffle_deck(player_deck, random.randint(1, 5_000_000))
ai_deck = shuffle_deck(ai_deck, random.randint(1, 5_000_000))
# Choose heroes (use deck hero hint if present and valid)
def _pick_hero(hint, default):
    if hint:
        h = hero_db.get(str(hint).upper())
        if h: return h
    return default


HERO_PLAYER = _pick_hero(player_hero_hint, random.choice(list(hero_db.values())))
HERO_AI     = _pick_hero(ai_hero_hint,     random.choice(list(hero_db.values())))

STARTER_DECK_PLAYER = player_deck
STARTER_DECK_AI     = ai_deck

# Surface invalid deck errors (optional)
for name, d in loaded_decks.items():
    if "errors" in d:
        print(f"[DeckLoader] Deck '{name}' invalid:")
        for msg in d["errors"]:
            print("  -", msg)

#HERO_PLAYER = select_random_hero(hero_db)
#HERO_AI     = select_random_hero(hero_db)

#STARTER_DECK_PLAYER = make_starter_deck(db, random.randint(1, 5000000))
#STARTER_DECK_AI     = make_starter_deck(db, random.randint(1, 50000))


# ---------- Drawing helpers (reworked cards) ----------

def draw_action_log():
    # Panel
    panel = pygame.Rect(8, 8, LOG_PANEL_W, H - 16)
    pygame.draw.rect(screen, LOG_BG, panel, border_radius=8)
    pygame.draw.rect(screen, (42, 50, 60), panel, 1, border_radius=8)

    # Title
    title = BIG.render("Combat Log", True, LOG_ACCENT)
    screen.blit(title, (panel.x + 10, panel.y + 8))

    # Text area
    y = panel.y + 44
    x = panel.x + 10
    max_w = panel.w - 20

    # Render from newest -> oldest but clip to visible area
    lines = list(ACTION_LOG)[-200:]  # safety
    # We want oldest at top; ACTION_LOG already keeps order, so iterate directly
    for line in lines:
        # wrap long lines
        wrapped = wrap_text(line, RULE_FONT, max_w)
        for wline in wrapped:
            surf = RULE_FONT.render(wline, True, LOG_TEXT)
            if y + surf.get_height() > panel.bottom - 10:
                return
            screen.blit(surf, (x, y))
            y += surf.get_height() + 2

def battle_area_rect():
    top_y    = ROW_Y_ENEMY - 5
    bottom_y = ROW_Y_ME + CARD_H + 15
    return pygame.Rect(370, top_y, W - 450, bottom_y - top_y)

def draw_badge_circle(center: Tuple[int,int], radius: int, color: Tuple[int,int,int], text: str, text_color=WHITE, font=BIG):
    pygame.draw.circle(screen, color, center, radius)
    pygame.draw.circle(screen, (20,20,20), center, radius, 2)
    label = font.render(text, True, text_color)
    screen.blit(label, label.get_rect(center=center))

def draw_mana_crystal_rect(r: pygame.Rect, mana: int, max_mana: int):
    """Right-side vertical crystal showing current/maximum mana."""
    # crystal body
    pygame.draw.rect(screen, MANA_BADGE, r, border_radius=10)
    pygame.draw.rect(screen, (20, 30, 50), r, 2, border_radius=10)
    # numbers stacked
    t1 = BIG.render(str(mana), True, WHITE)
    t2 = FONT.render(f"/{max_mana}", True, WHITE)
    screen.blit(t1, t1.get_rect(center=(r.centerx, r.centery - 8)))
    screen.blit(t2, t2.get_rect(center=(r.centerx, r.centery + 12)))

def draw_hero_plate(face_rect: pygame.Rect, pstate, friendly: bool):
    # plate
    pygame.draw.rect(screen, PLATE_BG, face_rect, border_radius=12)
    pygame.draw.rect(screen, PLATE_RIM, face_rect, 2, border_radius=12)

    # tiny label strip at top (class color)
    strip = pygame.Rect(face_rect.x, face_rect.y, face_rect.w, face_rect.h)
    hid = getattr(pstate.hero, "id", pstate.hero)
    col = HERO_COLORS.get(str(hid).upper(), (90, 90, 90))
    pygame.draw.rect(screen, col, strip, border_radius=10)

    # class name centered on strip
    cap = FONT.render(hero_name(pstate.hero), True, WHITE)
    screen.blit(cap, cap.get_rect(center=strip.center))

    # health (bottom-right)
    max_hp = getattr(pstate, "max_health", 30)  # fallback if engine doesn't expose it
    health_center = (face_rect.right - 20, face_rect.bottom - 18)
    if pstate.health < max_hp:
        draw_badge_circle(health_center, 14, (40, 35, 25), str(max(0, pstate.health)),
                      text_color=HP_HURT, font=FONT)
    else:
        draw_badge_circle(health_center, 14, (40, 35, 25), str(max(0, pstate.health)),
                        text_color=HP_OK, font=FONT)

    # armor (small, above health)
    if pstate.armor > 0:
        armor_center = (health_center[0], health_center[1] - 26)
        draw_badge_circle(armor_center, 11, ARMOR_BADGE, str(pstate.armor), text_color=WHITE, font=FONT)

    # weapon badge (bottom-left)
    if getattr(pstate, "weapon", None):
        cx, cy = face_rect.x + 26, face_rect.bottom - 18
        radius = 14

        # badge circle
        pygame.draw.circle(screen, (40, 35, 25), (cx, cy), radius)
        pygame.draw.circle(screen, (20, 20, 20), (cx, cy), radius, 2)

        atk = int(getattr(pstate.weapon, "attack", 0))
        cur = int(getattr(pstate.weapon, "durability", 0))
        base = _weapon_base_durability_safe(GLOBAL_GAME, pstate.weapon)

        # Only durability turns red if it’s below max
        dur_col = HP_HURT if (base is not None and cur < base) else WHITE

        atk_surf   = FONT.render(str(atk), True, WHITE)
        slash_surf = FONT.render("/", True, WHITE)   # keep slash neutral
        dur_surf   = FONT.render(str(cur), True, dur_col)

        total_w = atk_surf.get_width() + slash_surf.get_width() + dur_surf.get_width()
        max_h   = max(atk_surf.get_height(), slash_surf.get_height(), dur_surf.get_height())
        x = cx - total_w // 2
        y = cy - max_h // 2

        screen.blit(atk_surf,   (x, y)); x += atk_surf.get_width()
        screen.blit(slash_surf, (x, y)); x += slash_surf.get_width()
        screen.blit(dur_surf,   (x, y))


    # mana crystal on the right side
    crystal = pygame.Rect(face_rect.right + CRYSTAL_PAD, face_rect.y + 6, CRYSTAL_W, face_rect.h - 12)
    draw_mana_crystal_rect(crystal, pstate.mana, pstate.max_mana)

    if getattr(pstate, "hero_frozen", False):
        draw_frozen_overlay(face_rect)

def keyword_explanations_for_card(card_obj) -> List[str]:
    tips = []
    kws = set(getattr(card_obj, "keywords", []) or [])
    # Some cards have battlecry but not the literal keyword in JSON:
    if getattr(card_obj, "battlecry", None):
        kws.add("Battlecry")
    if getattr(card_obj, "on_cast", None) and card_obj.type == "MINION":
        kws.add("Battlecry")

    for k in ["Battlecry","Deathrattle","Taunt","Rush","Charge","Silence"]:
        if k in kws:
            tips.append(f"{k}: {KEYWORD_HELP[k]}")
    return tips

def keyword_explanations_for_minion(m) -> List[str]:
    tips = []
    if getattr(m, "silenced", False):
        tips.append(f"Silence: {KEYWORD_HELP['Silence']}")
    else:
        if m.taunt:  tips.append(f"Taunt: {KEYWORD_HELP['Taunt']}")
        if m.rush:   tips.append(f"Rush: {KEYWORD_HELP['Rush']}")
        if m.charge: tips.append(f"Charge: {KEYWORD_HELP['Charge']}")
        if getattr(m, "deathrattle", None):
            tips.append(f"Deathrattle: {KEYWORD_HELP['Deathrattle']}")
    return tips

def draw_keyword_help_panel(anchor_rect: pygame.Rect, lines: List[str], side: str = "right"):
    if not lines: return
    pad = 10
    max_w = 320
    # position panel
    if side == "right":
        px = min(W - max_w - 12, anchor_rect.right + 12)
    else:
        px = max(12, anchor_rect.left - max_w - 12)
    py = max(12, anchor_rect.top)

    # measure height
    wrapped = []
    for ln in lines:
        wrapped += wrap_text(ln, RULE_FONT, max_w - pad*2)
    ph = 8 + sum(RULE_FONT.size(w)[1] + 4 for w in wrapped) + 40

    panel = pygame.Rect(px, py, max_w, ph)
    pygame.draw.rect(screen, (26, 32, 40), panel, border_radius=10)
    pygame.draw.rect(screen, (60, 90, 130), panel, 1, border_radius=10)

    y = panel.y + 8
    title = FONT.render("Keywords", True, LOG_ACCENT)
    screen.blit(title, (panel.x + pad, y))
    y += title.get_height() + 4
    for w in wrapped:
        surf = RULE_FONT.render(w, True, WHITE)
        screen.blit(surf, (panel.x + pad, y))
        y += surf.get_height() + 4

# --- Weapon/Secret helpers ---

def _weapon_base_durability_safe(g, w_obj):
    bd = getattr(w_obj, "base_durability", None)
    if bd is not None:
        return bd
    try:
        base_card = _weapon_card_from_state(g, w_obj)
    except Exception:
        base_card = None
    if base_card is not None:
        # in your JSON the printed durability is stored as `health` (or `durability`)
        return getattr(base_card, "health", getattr(base_card, "durability", None))
    return None


def _weapon_card_from_state(g: Game, w_obj):
    """
    Try to resolve the original weapon Card object from the weapon state on the hero.
    Falls back by name if no id is available.
    """
    if w_obj is None:
        return None
    # common patterns
    for key in ("card_id", "id"):
        cid = getattr(w_obj, key, None)
        if cid and cid in g.cards_db:
            return g.cards_db[cid]
    # name fallback
    nm = getattr(w_obj, "name", None)
    if nm:
        for cid, obj in g.cards_db.items():
            if getattr(obj, "name", None) == nm and getattr(obj, "type", "") == "WEAPON":
                return obj
    return None

def _active_secret_ids(pstate) -> list[str]:
    """
    Return a list of *card_id* strings for the player's active secrets, no matter
    how pstate.active_secrets is structured (list of dicts, dict keyed by id, etc).
    """
    s = getattr(pstate, "active_secrets", None)
    if not s:
        return []

    ids: list[str] = []

    # Case 1: dict keyed by card id
    if isinstance(s, dict):
        for k in s.keys():
            if isinstance(k, str):
                ids.append(k)
            elif isinstance(k, (int,)):
                ids.append(str(k))
        return ids

    # Case 2: iterable (list/tuple/set) of items
    try:
        for item in s:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                cid = item.get("card_id") or item.get("id") or item.get("cid") or item.get("card")
                if cid:
                    ids.append(str(cid))
            elif isinstance(item, (int,)):
                ids.append(str(item))
    except TypeError:
        # not iterable; ignore
        pass

    return ids


def _badge_rect_from_center(cx: int, cy: int, r: int = 14) -> pygame.Rect:
    d = r * 2
    return pygame.Rect(cx - r, cy - r, d, d)

# ui file
def card_name_from_db(db, cid: str) -> str:
    obj = db.get(cid)
    if obj is None:
        return cid or "a card"
    if hasattr(obj, "name"):
        return obj.name
    if isinstance(obj, dict):
        return obj.get("name", cid)
    return str(cid)

def draw_silence_overlay(r: pygame.Rect):
    # diagonal ribbon across the card
    s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    pygame.draw.polygon(
        s, (100, 80, 150, 180),  # semi-transparent purple
        [( -10, r.h*0.35), (r.w+10, r.h*0.10), (r.w+10, r.h*0.25), (-10, r.h*0.50)]
    )
    # text
    lbl = BIG.render("SILENCED", True, (240, 235, 255))
    s.blit(lbl, lbl.get_rect(center=(r.w//2, int(r.h*0.23))))
    screen.blit(s, (r.x, r.y))

def card_is_playable_now(g: Game, pid: int, cid: str) -> bool:
    """Green-glow condition for cards in hand."""
    c = g.cards_db[cid]
    p = g.players[pid]

    # Mana + basic board space for minions
    eff_cost = g.get_effective_cost(pid, cid)
    if p.mana < eff_cost:
        return False
    if c.type == "MINION" and len(p.board) >= 7:
        return False
    
    # --- Secret duplicate check for UI ---
    is_secret = ("Secret" in getattr(c, "keywords", [])) or getattr(c, "is_secret", False) or (c.type == "SECRET")
    if is_secret:
        # active_secrets is a list of dicts: {"card_id": ..., "name": ..., ...}
        if any(s.get("card_id") == cid for s in p.active_secrets or []):
            return False

    # Optional: simple target availability checks using JSON "_TARGETING"
    targ_map = g.cards_db.get("_TARGETING", {})
    need = (targ_map.get(cid, "none") or "none").lower()

    # Spells still require a valid target; minions may be played without one (BC fizzles)
    if c.type == "SPELL":
        if need in ("friendly_minion", "friendly_minions"):
            return any(m.is_alive() for m in p.board)
        if need in ("enemy_minion", "enemy_minions"):
            opp = 1 - pid
            return any(m.is_alive() for m in g.players[opp].board)
        if need in ("any_minion", "any_minions"):
            opp = 1 - pid
            return any(m.is_alive() for m in p.board) or any(m.is_alive() for m in g.players[opp].board)
    # for MINION: don't gate on targets at all (we'll fizzle BC if none)

    # "enemy_character" / "any_character" are always targetable (face exists)
    return True

def draw_rarity_droplet(r: pygame.Rect, rarity: Optional[str]):
    """Small gem centered at bottom of the card."""
    if not rarity:
        rarity = "COMMON"
    key = str(rarity).upper()
    color = RARITY_COLORS.get(key, RARITY_COLORS["COMMON"])

    radius = 9
    cx, cy = r.centerx, r.bottom - 16
    pygame.draw.circle(screen, color, (cx, cy), radius)
    # subtle rim
    pygame.draw.circle(screen, (20, 20, 20), (cx, cy), radius, 2)

def centered_text(text: str, y: int, font=BIG, color=WHITE):
    surf = font.render(text, True, color)
    screen.blit(surf, surf.get_rect(center=(W//2, y)))

def wrap_text(text: str, font: pygame.font.Font, max_w: int) -> List[str]:
    if not text: return []
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= max_w:
            cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def draw_cost_gem(r: pygame.Rect, cost: int):
    gem = pygame.Rect(r.x + 8, r.y + 8, 30, 30)
    pygame.draw.ellipse(screen, COST_BADGE, gem)
    t = BIG.render(str(cost), True, WHITE)
    screen.blit(t, t.get_rect(center=gem.center))


def draw_name_footer(r: pygame.Rect, name: str):
    """
    Bottom-centered pill for name, sitting just above rarity droplet.
    Leaves room for stats at the very bottom row.
    """
    name_h   = 22
    stats_h  = 28
    gap      = 4
    footer_w = r.w - 20  # insets for a nicer shape
    footer_x = r.x + (r.w - footer_w)//2
    footer_y = r.bottom - stats_h - gap - name_h

    bar = pygame.Rect(footer_x, footer_y, footer_w, name_h)
    pygame.draw.rect(screen, (30, 35, 45), bar, border_radius=10)

    # truncate gracefully
    nm = name
    while FONT.size(nm)[0] > bar.w - 16 and len(nm) > 0:
        nm = nm[:-1]
    if len(nm) < len(name) and len(nm) > 0:
        nm = nm[:-1] + "…"
    text_surf = FONT.render(nm, True, WHITE)
    screen.blit(text_surf, text_surf.get_rect(center=bar.center))

def draw_text_box(
    r: pygame.Rect,
    body_text: str,
    max_lines: int,
    *,
    title: Optional[str] = None,
    font_body=RULE_FONT,
    font_title=BIG
):
    # Top padding inside the card art area
    top_pad = 45

    # Reserve bottom area: footer (type) + stats + gaps
    name_h  = 22
    stats_h = 28
    gap     = 4
    bottom_reserved = name_h + stats_h + gap + 6

    # Text box rect
    box = pygame.Rect(r.x + 10, r.y + top_pad, r.w - 20, r.h - top_pad - bottom_reserved)
    pygame.draw.rect(screen, (28, 28, 34), box, border_radius=8)

    y = box.y + 6

    # --- Title (centered) ---
    if title:
        # shrink with ellipsis if needed
        t_txt = title
        while font_title.size(t_txt)[0] > box.w - 12 and len(t_txt) > 0:
            t_txt = t_txt[:-1]
        if len(t_txt) < len(title) and len(t_txt) > 0:
            t_txt = t_txt[:-1] + "…"

        ts = font_title.render(t_txt, True, WHITE)
        screen.blit(ts, ts.get_rect(center=(box.centerx, y + ts.get_height()//2)))
        y += ts.get_height() + 4

        # thin divider under title
        pygame.draw.line(screen, (60, 70, 85), (box.x + 6, y), (box.right - 6, y), 1)
        y += 6

    # --- Body (wrapped, left-aligned) ---
    lines = wrap_text(body_text, font_body, box.w - 12)[:max_lines]
    for ln in lines:
        surf = font_body.render(ln, True, WHITE)
        screen.blit(surf, (box.x + 6, y))
        y += surf.get_height() + 2

def draw_minion_stats(r: pygame.Rect, attack: int, health: int,
                      max_health: int, *, base_attack: int, base_health: int):
    # Attack bottom-left
    atk_rect = pygame.Rect(r.x + 10, r.bottom - 28, 28, 22)
    pygame.draw.rect(screen, (40, 35, 25), atk_rect, border_radius=6)
    atk_col = (60, 200, 90) if attack > base_attack else ATTK_COLOR  # green if buffed
    ta = FONT.render(str(attack), True, atk_col)
    screen.blit(ta, ta.get_rect(center=atk_rect.center))

    # Health bottom-right
    hp_rect = pygame.Rect(r.right - 38, r.bottom - 28, 28, 22)
    pygame.draw.rect(screen, (40, 35, 35), hp_rect, border_radius=6)
    if health < max_health:
        hp_col = HP_HURT
    elif max_health > base_health:
        hp_col = (60, 200, 90)  # green only when at full *and* buffed
    else:
        hp_col = HP_OK
    th = FONT.render(str(health), True, hp_col)
    screen.blit(th, th.get_rect(center=hp_rect.center))


def draw_card_frame(r: pygame.Rect, color_bg, *, card_obj=None, minion_obj=None, in_hand: bool, override_cost: int | None = None):
    pygame.draw.rect(screen, color_bg, r, border_radius=12)

    

    if card_obj:
        cost_to_show = card_obj.cost if override_cost is None else int(override_cost)
        draw_cost_gem(r, cost_to_show)

        kw = []
        if "Taunt" in card_obj.keywords: kw.append("Taunt")
        if "Charge" in card_obj.keywords: kw.append("Charge")
        if "Rush" in card_obj.keywords:   kw.append("Rush")
        

        text = (card_obj.text or "").strip()
        if text in kw: text = ""
        for k in kw:
            if text.lower().startswith(k.lower()):
                text = text[len(k):].lstrip(" :.-").strip()

        header = " / ".join(kw) 
        body   = header if header and not text else (header + ("\n" + text if text else ""))
        draw_text_box(r, body, max_lines=6, title=card_obj.name, font_body=RULE_FONT)
        
        draw_rarity_droplet(r, getattr(card_obj, "rarity", "Common"))
        if card_obj.type == "MINION":
            draw_minion_stats(
                r, card_obj.attack, card_obj.health, card_obj.health,
                base_attack=card_obj.attack, base_health=card_obj.health
            )
            if card_obj.minion_type != "None":
                draw_name_footer(r, card_obj.minion_type)
            else:
                draw_name_footer(r, "Neutral")
        elif card_obj.type == "WEAPON":
            draw_minion_stats(
                r, card_obj.attack, card_obj.health, card_obj.health,
                base_attack=card_obj.attack, base_health=card_obj.health
            )
            draw_name_footer(r, "Weapon")
        else: 
            draw_name_footer(r, card_obj.type)

    elif minion_obj:
        draw_cost_gem(r, getattr(minion_obj, "cost", 0))

        # Compose short description: keywords header + first lines of base rules text
        kws = []
        if getattr(minion_obj, "taunt", False):  kws.append("Taunt")
        if getattr(minion_obj, "charge", False): kws.append("Charge")
        if getattr(minion_obj, "rush", False):   kws.append("Rush")

        header = " / ".join(kws)

        text = (getattr(minion_obj, "base_text", "") or "").strip()
        # If body starts with a keyword line, trim it (avoid duplicate)
        for k in ["Taunt", "Charge", "Rush"]:
            if text.lower().startswith(k.lower()):
                text = text[len(k):].lstrip(" :.-").strip()
        # Final short text (2–3 lines on board)
        body   = header if header and not text else (header + ("\n" + text if text else ""))
        

        draw_text_box(r, body, max_lines=4, title=minion_obj.name, font_body=RULE_FONT)

        # Bottom UI
        #draw_name_footer(r, minion_obj.name)
        draw_rarity_droplet(r, getattr(minion_obj, "rarity", "Common"))
        draw_minion_stats(
            r,
            minion_obj.attack,
            minion_obj.health,
            minion_obj.max_health,
            base_attack=getattr(minion_obj, "base_attack", minion_obj.attack),
            base_health=getattr(minion_obj, "base_health", minion_obj.max_health),
        )
        if minion_obj.minion_type != "None":
            draw_name_footer(r, minion_obj.minion_type)
        else:
            draw_name_footer(r, "Neutral") 

    # Tiny Divine Shield indicator on board
    if getattr(minion_obj, "divine_shield", False) and not getattr(minion_obj, "silenced", False):
        
        sx, sy = r.x + (CARD_W / 2) - 11, r.y
        badge = pygame.Rect(sx, sy, 22, 22)
        pygame.draw.ellipse(screen, (235, 200, 80), badge)            # golden fill
        pygame.draw.ellipse(screen, (30, 24, 10), badge, 2)           # rim
        # simple shield glyph
        p1 = (badge.centerx, badge.y + 5)
        p2 = (badge.x + 5, badge.y + 11)
        p3 = (badge.centerx, badge.bottom - 5)
        p4 = (badge.right - 5, badge.y + 11)
        pygame.draw.polygon(screen, (255, 245, 180), [p1, p2, p3, p4])

    if getattr(minion_obj, "silenced", False):
        draw_silence_overlay(r)

    if getattr(minion_obj, "frozen", False):
        draw_frozen_overlay(r)

def draw_layered_borders(r: pygame.Rect, *, taunt: bool, rush: bool, ready: bool):
    if taunt: pygame.draw.rect(screen, GREY, r, 3, border_radius=10)
    if rush:  pygame.draw.rect(screen, RED,  r.inflate(4, 4), 3, border_radius=12)
    if ready: pygame.draw.rect(screen, GREEN,r.inflate(10,10), 3, border_radius=16)

def draw_frozen_overlay(r: pygame.Rect):
    s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    pygame.draw.polygon(
        s, (120, 180, 255, 170),
        [(-12, int(r.h*0.18)), (r.w+12, int(r.h*0.03)), (r.w+12, int(r.h*0.17)), (-12, int(r.h*0.32))]
    )
    lbl = BIG.render("FROZEN", True, (235, 245, 255))
    s.blit(lbl, lbl.get_rect(center=(r.w//2, int(r.h*0.12))))
    screen.blit(s, (r.x, r.y))

def flash_from_events(g: Game, ev_list: List[Any]):
    """Reads damage events and enqueues appropriate flash overlays."""
    post = layout_board(g)
    for e in ev_list or []:
        if getattr(e, "kind", "") == "PlayerDamaged":
            pid = e.payload.get("player")
            face = my_face_rect(post) if pid == 0 else enemy_face_rect(post)
            enqueue_flash(face)
        elif getattr(e, "kind", "") == "MinionDamaged":
            mid = e.payload.get("minion")
            loc = g.find_minion(mid)
            if not loc:
                continue
            pid2, _, _m2 = loc
            post2 = layout_board(g)
            coll = "my_minions" if pid2 == 0 else "enemy_minions"
            for mid2, r2 in post2[coll]:
                if mid2 == mid:
                    enqueue_flash(r2)
                    break

# ---------- Layout ----------
def _centered_row_rects(n: int, y: int, container: Optional[pygame.Rect] = None) -> List[pygame.Rect]:
    if n <= 0: return []
    if container is None:
        container = pygame.Rect(0, 0, W, H)
    total_w = n * CARD_W + (n - 1) * MARGIN
    start_x = max(container.x + (container.w - total_w)//2, container.x + MARGIN)
    return [pygame.Rect(start_x + i * (CARD_W + MARGIN), y, CARD_W, CARD_H) for i in range(n)]

def _stacked_hand_rects(n: int, y: int) -> List[pygame.Rect]:
    """Return overlapped, centered rects for the hand (Hearthstone-ish stack)."""
    if n <= 0: return []
    step = max(1, int(CARD_W * (1.0 - HAND_OVERLAP)))  # horizontal step between cards
    total_w = step * (n - 1) + CARD_W
    start_x = max((W - total_w) // 2, MARGIN)
    return [pygame.Rect(start_x + i * step, y, CARD_W, CARD_H) for i in range(n)]


def insertion_slots_for_my_row(g: Game, arena: pygame.Rect) -> List[pygame.Rect]:
    """
    Returns n+1 drop slots, index = insertion index.
    - If board is empty: one big slot spanning the entire arena width at the row.
    - If not empty: wide left & right edge slots, slim 'between' slots.
    """
    board = g.players[0].board
    if len(board) == 0:
        # full-width easy target
        full = pygame.Rect(arena.x + 10, ROW_Y_ME, arena.w - 20, CARD_H)
        return [full]

    card_rects = _centered_row_rects(len(board), ROW_Y_ME, arena)

    slots: List[pygame.Rect] = []

    # --- Wide LEFT edge slot (index 0) ---
    left_edge_right = (card_rects[0].x + (card_rects[0].x - (arena.x + 10))) // 2
    left_slot = pygame.Rect(arena.x + 10, ROW_Y_ME, max(24, card_rects[0].x - (arena.x + 10)), CARD_H)
    slots.append(left_slot)

    # --- Slim BETWEEN slots (indices 1..n-1) ---
    for i in range(len(card_rects) - 1):
        a, b = card_rects[i], card_rects[i + 1]
        cx = (a.right + b.x) // 2
        slots.append(pygame.Rect(cx - 8, ROW_Y_ME, 16, CARD_H))

    # --- Wide RIGHT edge slot (index n) ---
    right_slot = pygame.Rect(card_rects[-1].right + 1, ROW_Y_ME,
                             max(24, (arena.right - 10) - (card_rects[-1].right + 1)), CARD_H)
    slots.append(right_slot)

    return slots

def slot_index_at_point(slots: List[pygame.Rect], mx: int, my: int) -> Optional[int]:
    for i, s in enumerate(slots):
        if s.collidepoint(mx, my):
            return i
    return None

def layout_board(g: Game) -> Dict[str, Any]:
    hot = {"hand": [], "my_minions": [], "enemy_minions": [], "end_turn": None,
           "face_enemy": None, "face_me": None, "hp_enemy": None, "hp_me": None,
           "weapon_enemy": None, "weapon_me": None,
           "secrets_enemy": [], "secrets_me": []}

    arena = battle_area_rect()

    # Enemy row
    for m, r in zip(g.players[1].board, _centered_row_rects(len(g.players[1].board), ROW_Y_ENEMY, arena)):
        hot["enemy_minions"].append((m.id, r))

    # My row
    for m, r in zip(g.players[0].board, _centered_row_rects(len(g.players[0].board), ROW_Y_ME, arena)):
        hot["my_minions"].append((m.id, r))

    # Hand row (unchanged)
    for (i, cid), r in zip(list(enumerate(g.players[0].hand)), _stacked_hand_rects(len(g.players[0].hand), ROW_Y_HAND)):
        hot["hand"].append((i, cid, r))

    # Faces: center on arena, not on whole window
    hot["face_enemy"] = pygame.Rect(arena.centerx - FACE_W//2, ROW_Y_ENEMY - 75, FACE_W, FACE_H)

    face_me_y = ROW_Y_ME + CARD_H + 24
    max_face_me_y = ROW_Y_HAND - 68
    face_me_y = min(face_me_y, max_face_me_y)
    hot["face_me"] = pygame.Rect(arena.centerx - FACE_W//2, face_me_y, FACE_W, FACE_H)

    # Hero power buttons (keep your current offsets)
    hp_x_enemy = hot["face_enemy"].right + CRYSTAL_PAD + CRYSTAL_W + CRYSTAL_PAD
    hp_x_me    = hot["face_me"].right    + CRYSTAL_PAD + CRYSTAL_W + CRYSTAL_PAD
    hot["hp_enemy"] = pygame.Rect(hp_x_enemy, hot["face_enemy"].y, 150, 52)
    hot["hp_me"]    = pygame.Rect(hp_x_me,    hot["face_me"].y,    150, 52)

    # --- NEW: hotspots for weapon badges (same centers as draw_hero_plate)
    # bottom-left of each hero plate: (x+26, bottom-18)
    if getattr(g.players[1], "weapon", None):
        cx, cy = hot["face_enemy"].x + 26, hot["face_enemy"].bottom - 18
        hot["weapon_enemy"] = _badge_rect_from_center(cx, cy, 14)
    if getattr(g.players[0], "weapon", None):
        cx, cy = hot["face_me"].x + 26, hot["face_me"].bottom - 18
        hot["weapon_me"] = _badge_rect_from_center(cx, cy, 14)

    # --- NEW: secret badge rects (place across the top strip, right-to-left)
    def _secret_slots(face_rect: pygame.Rect, count: int):
        slots = []
        if count <= 0: return slots
        pad = 6
        size = 22
        x = face_rect.right - size - 6  # start near right edge
        y = face_rect.y + 2              # on the colored strip
        for i in range(count):
            slots.append(pygame.Rect(x - i*(size+pad), y, size, size))
        return slots

    en_secrets = _active_secret_ids(g.players[1])
    my_secrets = _active_secret_ids(g.players[0])

    for r in _secret_slots(hot["face_enemy"], len(en_secrets or [])):
        hot["secrets_enemy"].append((None, r))       # don't reveal enemy ids
    for cid, r in zip(my_secrets, _secret_slots(hot["face_me"], len(my_secrets))):
        hot["secrets_me"].append((cid, r))

    hot["end_turn"] = pygame.Rect(W - 170, H - 70, 150, 50)
    return hot

def scale_rect_about_center(r: pygame.Rect, s: float, lift: int = 0) -> pygame.Rect:
    w, h = int(r.w * s * 1.2), int(r.h * s)
    cx, cy = r.centerx, r.centery - lift * 1.5
    return pygame.Rect(cx - w // 2, cy - h // 2, w, h)

def hand_hover_index(hot, mx, my) -> Optional[int]:
    """Return the hand index under the mouse (consider a slightly enlarged hitbox)."""
    for i, cid, r in hot["hand"]:
        hit = scale_rect_about_center(r, 1.10, 0)  # generous hit area
        if hit.collidepoint(mx, my):
            return i
    return None

def minion_ready_to_act(g: Game, m) -> bool:
    if getattr(m, "frozen", False):     # NEW
        return False
    if m.has_attacked_this_turn or m.attack <= 0:
        return False
    if not getattr(m, "summoned_this_turn", True):
        return True
    if getattr(m, "charge", False):
        return True
    if getattr(m, "rush", False) and any(mm.is_alive() for mm in g.players[1 - m.owner].board):
        return True
    return False

# ---------- Targeting logic (for highlights) ----------
def targets_for_card(g: Game, cid: str, pid: int):
    spec = (g.cards_db.get("_TARGETING", {}).get(cid, "none") or "none").lower()
    opp = 1 - pid

    enemy_all = [m for m in g.players[opp].board if m.is_alive()]
    my_all    = [m for m in g.players[pid].board if m.is_alive()]

    def is_tribe(m, t: str):
        if not t: return True
        mt = (getattr(m, "minion_type", "None") or "None").lower()
        return mt == "all" or mt == t

    # Parse generic pattern + legacy
    def parse(spec: str):
        # legacy like "friendly_beast"
        for t in ("beast","mech","demon","dragon","murloc","pirate","totem","elemental","naga","undead","all"):
            if spec == f"friendly_{t}": return ("friendly","minion",t)
            if spec == f"enemy_{t}":    return ("enemy","minion",t)
            if spec == f"any_{t}":      return ("any","minion",t)
        if "_tribe:" in spec:
            side, t = spec.split("_tribe:", 1)
            side = side.replace("target_", "")
            if side not in ("friendly","enemy","any"): side = "any"
            return (side, "minion", t.strip())
        if spec.endswith("_minion"):
            if spec.startswith("friendly_"): return ("friendly","minion",None)
            if spec.startswith("enemy_"):    return ("enemy","minion",None)
            if spec.startswith("any_"):      return ("any","minion",None)
        # character scopes (for faces)
        if spec == "any_character":      return ("any","character",None)
        if spec == "enemy_character":    return ("enemy","character",None)
        if spec == "friendly_character": return ("friendly","character",None)
        if spec == "enemy_face":         return ("enemy","face",None)
        if spec == "friendly_face":      return ("friendly","face",None)
        return ("none","none",None)

    side, kind, tribe = parse(spec)

    enemy_min = set()
    my_min    = set()
    e_face = m_face = False

    if kind == "minion":
        if side in ("enemy","any"):
            enemy_min = {m.id for m in enemy_all if is_tribe(m, tribe)}
        if side in ("friendly","any"):
            my_min = {m.id for m in my_all if is_tribe(m, tribe)}
    elif kind == "character":
        e_face = side in ("enemy","any")
        m_face = side in ("friendly","any")
        enemy_min = {m.id for m in enemy_all}
        my_min    = {m.id for m in my_all}
    elif kind == "face":
        e_face = (side in ("enemy","any"))
        m_face = (side in ("friendly","any"))

    return enemy_min, my_min, e_face, m_face

def can_use_hero_power(g: Game, pid: int) -> bool:
    p = g.players[pid]
    cost = getattr(p.hero.power, "cost", 2)
    if p.mana < cost or p.hero_power_used_this_turn: return False
    # Example: Paladin still needs board space
    if p.hero.id.upper() == "PALADIN" and len(p.board) >= 7: return False
    return True

def targets_for_hero_power(g: Game, pid: int):
    """
    Return (enemy_min_ids, my_min_ids, enemy_face_ok, my_face_ok)
    Based on hero.power.targeting
    """
    h = g.players[pid].hero
    spec = h.power.targeting.lower()
    opp = 1 - pid

    enemy_min = set(m.id for m in g.players[opp].board if m.is_alive())
    my_min    = set(m.id for m in g.players[pid].board if m.is_alive())

    if spec == "none":
        return set(), set(), False, False
    if spec == "enemy_face":
        return set(), set(), True, False    
    if spec == "any_character":
        return enemy_min, my_min, True, True
    if spec == "friendly_character":
        return set(), my_min, False, True
    if spec == "enemy_minion":
        return enemy_min, set(), False, False
    if spec == "friendly_minion":
        return set(), my_min, False, False
    # fallback: no targeting
    return set(), set(), False, False

def legal_attack_targets(g: Game, attacker_id: int):
    minfo = g.find_minion(attacker_id)
    if not minfo:
        return set(), False
    pid, _, att = minfo
    opp = 1 - pid
    if att.attack <= 0 or att.has_attacked_this_turn or not att.is_alive():
        return set(), False
    face_allowed = ((not getattr(att, "summoned_this_turn", True)) or getattr(att, "charge", False))
    can_hit_minions = ((not getattr(att, "summoned_this_turn", True)) or getattr(att, "charge", False) or getattr(att, "rush", False))
    enemy_taunts = [m for m in g.players[opp].board if m.taunt and m.is_alive()]
    enemy_mins = [m for m in g.players[opp].board if m.is_alive()]
    if not can_hit_minions:
        mins = set()
    else:
        if enemy_taunts:
            mins = {m.id for m in enemy_taunts}
            face_allowed = False
        else:
            mins = {m.id for m in enemy_mins}
    if enemy_taunts:
        face_allowed = False
    return mins, face_allowed

def hero_ready_to_act(g: Game, pid:int) -> bool:
    return g.hero_can_attack(pid)

def hero_legal_targets(g: Game, pid:int):
    """Return (enemy_min_ids, face_ok) for hero attacks."""
    return g.hero_legal_targets(pid)

# ---------- Rendering ----------
def draw_board(g: Game, hot, hidden_minion_ids: Optional[set] = None,
               highlight_enemy_minions: Optional[set] = None,
               highlight_my_minions: Optional[set] = None,
               highlight_enemy_face: bool = False,
               highlight_my_face: bool = False,
               *,
               show_slots: bool = False,
               active_slot_index: Optional[int] = None,
               dragging_card: Optional[Tuple[str, pygame.Rect]] = None):
    hidden_minion_ids = hidden_minion_ids or set()
    highlight_enemy_minions = highlight_enemy_minions or set()
    highlight_my_minions = highlight_my_minions or set()

    global DEBUG_BTN_RECT
    global SHOW_ENEMY_HAND
    # --- Battleground panel/background ---
    # A framed area spanning enemy row to your row
    arena = battle_area_rect()
    pygame.draw.rect(screen, BOARD_BG, arena, border_radius=16)
    pygame.draw.rect(screen, BOARD_BORDER, arena, 2, border_radius=16)

    # Hero plates (enemy + you)
    draw_hero_plate(hot["face_enemy"], g.players[1], friendly=False)
    draw_hero_plate(hot["face_me"],    g.players[0], friendly=True)

    # after drawing hero plates:
    if g.hero_can_attack(0):
        pygame.draw.rect(screen, GREEN, hot["face_me"].inflate(12, 12), 3, border_radius=16)
    if g.hero_can_attack(1):
        # purely informative; AI uses this programmatically
        pygame.draw.rect(screen, GREEN, hot["face_enemy"].inflate(12, 12), 3, border_radius=16)

    # --- NEW: secrets rendering (as ? badges, class color)
    def _class_color(pid: int):
        hid = getattr(g.players[pid].hero, "id", g.players[pid].hero)
        return HERO_COLORS.get(str(hid).upper(), (100,100,100))

    # Enemy secrets (no hover info)
    for _cid, rr in hot["secrets_enemy"]:
        pygame.draw.rect(screen, _class_color(1), rr, border_radius=6)
        pygame.draw.rect(screen, (20,20,20), rr, 1, border_radius=6)
        q = FONT.render("?", True, WHITE)
        screen.blit(q, q.get_rect(center=rr.center))

    # My secrets (hoverable)
    for cid, rr in hot["secrets_me"]:
        pygame.draw.rect(screen, _class_color(0), rr, border_radius=6)
        pygame.draw.rect(screen, (20,20,20), rr, 1, border_radius=6)
        q = FONT.render("?", True, WHITE)
        screen.blit(q, q.get_rect(center=rr.center))

    # Hero Power buttons
    me = g.players[0]; ai = g.players[1]
    # Enemy button (display only; AI clicks programmatically)
    hp_en = hot["hp_enemy"]; col_en = HERO_COLORS.get(ai.hero.id.upper(), (100,100,100))
    pygame.draw.rect(screen, col_en, hp_en, border_radius=10)
    cap = FONT.render(f"{hero_name(ai.hero)} Power", True, WHITE)
    screen.blit(cap, cap.get_rect(center=hp_en.center))

    # My button (clickable if can use)
    hp_me = hot["hp_me"]; col_me = HERO_COLORS.get(me.hero.id.upper(), (100,100,100))
    usable = (g.active_player == 0) and can_use_hero_power(g, 0)
    bg = col_me if usable else (60,60,60)
    pygame.draw.rect(screen, bg, hp_me, border_radius=10)
    cap2 = FONT.render(f"{hero_name(me.hero)} Power ({getattr(me.hero.power, 'cost', 2)})", True, WHITE)
    screen.blit(cap2, cap2.get_rect(center=hp_me.center))

    # Enemy minions
    for mid, r in hot["enemy_minions"]:
        minfo = g.find_minion(mid)
        if not minfo:
            continue
        _, _, m = minfo
        if m.id in hidden_minion_ids:
            continue
        draw_card_frame(r, CARD_BG_EN, minion_obj=m, in_hand=False)
        draw_layered_borders(r, taunt=m.taunt, rush=m.rush, ready=minion_ready_to_act(g, m))
        if mid in highlight_enemy_minions:
            pygame.draw.rect(screen, RED, r.inflate(8, 8), 3, border_radius=12)

    # My minions  (FIXED: use card-frame, not old helpers)
    for mid, r in hot["my_minions"]:
        minfo = g.find_minion(mid)
        if not minfo:
            continue
        _, _, m = minfo
        if m.id in hidden_minion_ids:
            continue
        draw_card_frame(r, CARD_BG_MY, minion_obj=m, in_hand=False)
        draw_layered_borders(r, taunt=m.taunt, rush=m.rush, ready=minion_ready_to_act(g, m))
        if mid in highlight_my_minions:
            pygame.draw.rect(screen, RED, r.inflate(8, 8), 3, border_radius=12)

    # My hand (stacked + hover zoom)
    mx, my = pygame.mouse.get_pos()
    hover_idx = hand_hover_index(hot, mx, my)

    # --- Enemy hand overlay (debug) ---
    if SHOW_ENEMY_HAND:
        panel_w = 760
        panel_h = CARD_H + 24
        panel_x = W - panel_w - 20
        panel_y = DEBUG_BTN_RECT.bottom + 10

        panel = pygame.Rect(panel_x, panel_y, panel_w, panel_h)
        pygame.draw.rect(screen, (18, 22, 26), panel, border_radius=12)
        pygame.draw.rect(screen, (60, 90, 130), panel, 2, border_radius=12)

        title = FONT.render("Enemy Hand", True, LOG_ACCENT)
        screen.blit(title, (panel.x + 10, panel.y + 8))

        # lay out stacked rects inside panel
        cards = list(g.players[1].hand)
        if cards:
            inner = panel.inflate(-16, -36)
            # reuse your stacked hand layout but clamp to the inner rect
            step = max(1, int(CARD_W * (1.0 - HAND_OVERLAP)))
            total_w = step * (len(cards) - 1) + CARD_W
            start_x = max(inner.x, inner.centerx - total_w // 2)
            y = inner.y + 4
            rects = [pygame.Rect(start_x + i * step, y, CARD_W, CARD_H) for i in range(len(cards))]

            for cid, r in zip(cards, rects):
                cobj = g.cards_db[cid]
                draw_card_frame(r, CARD_BG_EN, card_obj=cobj, in_hand=True)
    

    # draw non-hovered first (so hovered can render on top)
    for i, cid, r in hot["hand"]:
        if i == hover_idx:
            continue
        c = g.cards_db[cid]
        eff = g.get_effective_cost(0, cid)
        # subtle overlap shadow
        shadow = r.copy(); shadow.x += 3; shadow.y += 3
        pygame.draw.rect(screen, (0, 0, 0, 40), shadow, border_radius=12)
        draw_card_frame(r, CARD_BG_HAND, card_obj=c, in_hand=True, override_cost=eff)

        # NEW: playable glow for your turn
        if g.active_player == 0 and card_is_playable_now(g, 0, cid):
            pygame.draw.rect(screen, GREEN, r.inflate(10, 10), 3, border_radius=16)

    # hovered last (zoomed + lifted)
    if hover_idx is not None:
        # find its original rect
        r0 = None; cid0 = None
        for i, cid, r in hot["hand"]:
            if i == hover_idx:
                r0, cid0 = r, cid
                break
        if r0 is not None:
            rz = scale_rect_about_center(r0, HOVER_SCALE, HOVER_LIFT)
            c = g.cards_db[cid0]
            eff = g.get_effective_cost(0, cid0)
            # backdrop glow
            glow = rz.inflate(14, 14)
            pygame.draw.rect(screen, (255, 255, 255), glow, 6, border_radius=18)
            draw_card_frame(rz, CARD_BG_HAND, card_obj=c, in_hand=True, override_cost=eff)

            lines = keyword_explanations_for_card(c)
            draw_keyword_help_panel(rz, lines, side="right")

            if g.active_player == 0 and card_is_playable_now(g, 0, cid0):
                pygame.draw.rect(screen, GREEN, rz.inflate(12, 12), 4, border_radius=18)

    # --- NEW: hover previews for weapon + my secrets
    preview_card = None
    preview_anchor = None

    # weapon hover (both sides)
    if hot["weapon_me"] and hot["weapon_me"].collidepoint(mx, my):
        preview_card = _weapon_card_from_state(g, g.players[0].weapon)
        preview_anchor = hot["weapon_me"]
    elif hot["weapon_enemy"] and hot["weapon_enemy"].collidepoint(mx, my):
        preview_card = _weapon_card_from_state(g, g.players[1].weapon)
        preview_anchor = hot["weapon_enemy"]

    # my secret hover (reveal my actual secret)
    if preview_card is None:
        for cid, rr in hot["secrets_me"]:
            if rr.collidepoint(mx, my):
                preview_card = g.cards_db.get(cid)
                preview_anchor = rr
                break

    # draw the preview (reuse card frame; 1.7x card size near anchor)
    if preview_card is not None:
        pw, ph = int(CARD_W * 1.7), int(CARD_H * 1.9)
        # try to place to the right of the anchor, clamp on screen
        ax = min(preview_anchor.right + 16, W - pw - 12)
        ay = max(12, min(preview_anchor.y - ph//3, H - ph - 12))
        R = pygame.Rect(ax, ay, pw, ph)

        # backdrop glow
        glow = R.inflate(14, 14)
        pygame.draw.rect(screen, (255,255,255), glow, 6, border_radius=18)

        draw_card_frame(R, CARD_BG_HAND, card_obj=preview_card, in_hand=True)


    # --- Debug button (top-right) ---
    
    btn_w, btn_h = 220, 40
    DEBUG_BTN_RECT = pygame.Rect(W - btn_w - 20, 20, btn_w, btn_h)

    dbg_col = (40, 160, 100) if SHOW_ENEMY_HAND else (120, 120, 120)
    pygame.draw.rect(screen, dbg_col, DEBUG_BTN_RECT, border_radius=10)
    cap = FONT.render(("Hide" if SHOW_ENEMY_HAND else "Show") + " Enemy Hand  (H)", True, WHITE)
    screen.blit(cap, cap.get_rect(center=DEBUG_BTN_RECT.center))

    # End turn
    pygame.draw.rect(screen, BLUE if g.active_player == 0 else (90, 90, 90), hot["end_turn"], border_radius=8)
    t = FONT.render("End Turn", True, WHITE)
    screen.blit(t, t.get_rect(center=hot["end_turn"].center))

    # --- insertion slots (when dragging a minion) ---
    if show_slots:
        arena = battle_area_rect()
        slots = insertion_slots_for_my_row(g, arena)
        for i, s in enumerate(slots):
            col = (255, 255, 255) if i == active_slot_index else (120, 140, 180)
            pygame.draw.rect(screen, col, s, 0, border_radius=6)
            pygame.draw.rect(screen, (30, 40, 55), s, 2, border_radius=6)

    # --- draw dragged hand card on top ---
    if dragging_card is not None:
        cid, rdrag = dragging_card
        cobj = g.cards_db[cid]
        eff = g.get_effective_cost(0, cid)
        draw_card_frame(rdrag, CARD_BG_HAND, card_obj=cobj, in_hand=True, override_cost=eff)
        pygame.draw.rect(screen, (255,255,255), rdrag.inflate(12,12), 4, border_radius=18)



    # Face highlights
    if highlight_enemy_face:
        pygame.draw.rect(screen, RED, hot["face_enemy"].inflate(8, 8), 3, border_radius=12)
    if highlight_my_face:
        pygame.draw.rect(screen, RED, hot["face_me"].inflate(8, 8), 3, border_radius=12)

def draw_card_inspector_for_minion(g: Game, minion_id: int):
    loc = g.find_minion(minion_id)
    if not loc:
        return
    pid, idx, m = loc

    # Build a lightweight card-like object from the minion’s base fields
    class _ViewCard:
        pass
    vc = _ViewCard()
    vc.id = m.card_id or m.name
    vc.name = m.name
    vc.cost = getattr(m, "cost", 0)
    vc.type = "MINION"
    vc.attack = m.base_attack
    vc.health = m.base_health
    vc.keywords = list(getattr(m, "base_keywords", []))
    vc.text = getattr(m, "base_text", "")
    vc.rarity = getattr(m, "rarity", "Common")
    vc.minion_type = getattr(m, "minion_type", "None")

    # Darken background
    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    screen.blit(overlay, (0, 0))

    # Big centered rect
    INSPECT_W, INSPECT_H = int(CARD_W * 2.0), int(CARD_H * 2.2)
    R = pygame.Rect(W//2 - INSPECT_W//2, H//2 - INSPECT_H//2, INSPECT_W, INSPECT_H)
    pygame.draw.rect(screen, (24, 28, 34), R, border_radius=16)
    # Draw the card using your existing frame renderer
    draw_card_frame(R, CARD_BG_HAND, card_obj=vc, in_hand=True)

    lines = keyword_explanations_for_minion(m)
    draw_keyword_help_panel(R, lines, side="right")

    # Small hint
    hint = RULE_FONT.render("Right-click to close", True, WHITE)
    screen.blit(hint, (R.x + 8, R.bottom + 8))


# ---------- Animation system (overhauled) ----------
def clamp(x, a=0.0, b=1.0): 
    return a if x < a else (b if x > b else x)

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def ease_in_out_cubic(t: float) -> float:
    t = clamp(t)
    return 4*t*t*t if t < 0.5 else 1 - pow(-2*t + 2, 3)/2

def ease_out_quart(t: float) -> float:
    t = clamp(t); return 1 - pow(1 - t, 4)

def back_out(t: float, s: float = 1.70158) -> float:
    t = clamp(t); t -= 1
    return (t*t*((s+1)*t + s) + 1)

def smoothstep01(t: float) -> float:
    t = clamp(t); return t*t*(3 - 2*t)

def arc_lerp(src: pygame.Rect, dst: pygame.Rect, t: float, height_px: int) -> Tuple[int,int]:
    """Parabolic arc between rect centers."""
    t = clamp(t)
    sx, sy = src.center; dx, dy = dst.center
    x = lerp(sx, dx, t)
    # y goes up then down
    peak = -height_px
    y = lerp(sy, dy, t) + peak * 4 * (t - t*t)  # 0 at ends, peak at t=0.5
    return int(x), int(y)

class AnimStep:
    """
    Compatible with your old step object, but adds:
    - non_blocking: True → runs in parallel (great for flashes/banners)
    - layer: z-order for non-blocking (0 below banners, 1 for HUD overlays)
    - ease: which easing to use for progress shaping
    - meta helpers (like scale/squash) handled per kind below
    """
    def __init__(self, kind: str, duration_ms: int, data: dict, on_finish=None):
        self.kind = kind
        self.duration_ms = max(1, int(duration_ms))
        self.data = data or {}
        self.on_finish = on_finish
        self.start_ms: Optional[int] = None

        # extras (with sensible defaults)
        self.non_blocking: bool = bool(self.data.get("non_blocking", kind in ("flash", "banner")))
        self.layer: int = int(self.data.get("layer", 1 if kind in ("banner", "start_game") else 0))
        self.ease_name: str = str(self.data.get("ease", "cubic"))  # cubic | quart | back | linear

    def start(self): 
        self.start_ms = pygame.time.get_ticks()

    def raw_progress(self) -> float:
        if self.start_ms is None: 
            return 0.0
        t = (pygame.time.get_ticks() - self.start_ms) / self.duration_ms
        return 0.0 if t < 0 else (1.0 if t > 1.0 else t)

    def eased(self) -> float:
        t = self.raw_progress()
        e = self.ease_name
        if e == "quart": return ease_out_quart(t)
        if e == "back":  return back_out(t)
        if e == "linear":return clamp(t)
        # default
        return ease_in_out_cubic(t)

    def done(self) -> bool: 
        return self.raw_progress() >= 1.0

class AnimQueue:
    """
    New model:
      - One *blocking* track that behaves like your old queue (perfect compatibility).
      - Many *non-blocking* ambient tracks (flash/banner) that run in parallel.
    Composition order per frame:
      board → blocking anim (0 or 1) → ambient layer 0 → ambient layer 1 (HUD/top).
    """
    def __init__(self):
        self.blocking: List[AnimStep] = []
        self.ambient: List[AnimStep]  = []  # any non_blocking steps

    def push(self, step: AnimStep):
        if step.non_blocking:
            self.ambient.append(step)
            if step.start_ms is None:
                step.start()
        else:
            should_start = (len(self.blocking) == 0)
            self.blocking.append(step)
            if should_start and step.start_ms is None:
                step.start()

    def busy(self) -> bool:
        # Gameplay is "busy" if there is a blocking step executing.
        # Ambient effects don't lock input (feels snappier).
        return len(self.blocking) > 0

    def peek_hidden_ids(self) -> set:
        hidden = set()
        if self.blocking:
            step = self.blocking[0]
            if step.kind == "play_move" and step.data.get("spawn_mid"):
                hidden.add(step.data["spawn_mid"])
        return hidden

    def _draw_hero_attack(self, step: AnimStep):
        src: pygame.Rect = step.data["src"]
        dst: pygame.Rect = step.data["dst"]

        # Use precomputed hero sprite if provided; otherwise snapshot from 'src' once.
        if "sprite" not in step.data:
            snap_rect = step.data.get("snapshot_rect", src)
            try:
                step.data["sprite"] = screen.subsurface(snap_rect).copy()
            except Exception:
                step.data["sprite"] = None

        t = step.eased()
        x = lerp(src.centerx, dst.centerx, t)
        y = lerp(src.centery, dst.centery, t) - 24 * 4 * (t - t*t)

        scale = 1.0 + 0.12 * smoothstep01(1.0 - abs(t*2 - 1))
        if t > 0.9:
            scale *= 1.0 - 0.07 * smoothstep01((t - 0.9)/0.1)

        # Optional dim: by default we dim 'src'; allow override/disable via step.data
        dim_allowed = step.data.get("dim", True)
        dim_rect = step.data.get("dim_rect", src) if dim_allowed else None
        if dim_rect is not None:
            alpha = max(0, min(255, int(150 * (1.0 - abs(t*2 - 1)))))
            shade = pygame.Surface((dim_rect.w, dim_rect.h), pygame.SRCALPHA, 32)
            shade.fill((0, 0, 0))
            shade.set_alpha(alpha)
            screen.blit(shade, (dim_rect.x, dim_rect.y))

        # Draw sprite
        if step.data["sprite"] is None:
            w, h = int(src.w * scale), int(src.h * scale)
            rr = pygame.Rect(0, 0, w, h); rr.center = (int(x), int(y))
            pygame.draw.rect(screen, PLATE_BG, rr, border_radius=12)
            pygame.draw.rect(screen, PLATE_RIM, rr, 2, border_radius=12)
            return

        surf = pygame.transform.smoothscale(step.data["sprite"], (int(src.w * scale), int(src.h * scale)))
        r = surf.get_rect(center=(int(x), int(y)))
        screen.blit(surf, r.topleft)


    def _draw_play_move(self, step: AnimStep):
        src: pygame.Rect = step.data["src"]; dst: pygame.Rect = step.data["dst"]
        color = step.data.get("color", CARD_BG_HAND)
        label = step.data.get("label", "")

        # shapely timing: accelerate then float → then settle
        t = step.eased()
        x, y = arc_lerp(src, dst, t, height_px=60)

        # scale up a touch mid-flight, then down a bit on land (squash)
        s = 1.0 + 0.06 * smoothstep01(1.0 - abs(t*2 - 1))  # 1.06 at mid-air
        if t > 0.92:
            s *= 1.0 - 0.08 * smoothstep01((t - 0.92)/0.08)  # tiny settle

        w, h = int(CARD_W * s), int(CARD_H * s)
        r = pygame.Rect(0, 0, w, h); r.center = (x, y)

        # soft shadow under the card
        sh = pygame.Surface((w+26, h+26), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (0,0,0,120), sh.get_rect())
        screen.blit(sh, (r.x-13, r.bottom-14))

        pygame.draw.rect(screen, color, r, border_radius=10)
        if label:
            screen.blit(FONT.render(label, True, WHITE), (r.x+8, r.y+8))

        # subtle motion trail (two faint ghosts)
        ghost_t = max(0.0, t - 0.15)
        gx, gy = arc_lerp(src, dst, ghost_t, height_px=60)
        gr = pygame.Rect(0, 0, int(w*0.98), int(h*0.98)); gr.center = (gx, gy)
        gsurf = pygame.Surface((gr.w, gr.h), pygame.SRCALPHA)
        pygame.draw.rect(gsurf, (*color, 120), gsurf.get_rect(), border_radius=10)
        screen.blit(gsurf, gr.topleft)

        ghost_t2 = max(0.0, t - 0.30)
        gx2, gy2 = arc_lerp(src, dst, ghost_t2, height_px=60)
        gr2 = pygame.Rect(0, 0, int(w*0.96), int(h*0.96)); gr2.center = (gx2, gy2)
        gsurf2 = pygame.Surface((gr2.w, gr2.h), pygame.SRCALPHA)
        pygame.draw.rect(gsurf2, (*color, 70), gsurf2.get_rect(), border_radius=10)
        screen.blit(gsurf2, gr2.topleft)

        # hide spawned unit while animating (handled in peek_hidden_ids)

    def _draw_attack_dash(self, step: AnimStep):
        src: pygame.Rect = step.data["src"]; dst: pygame.Rect = step.data["dst"]
        color = step.data.get("color", CARD_BG_MY)

        # fast start, back-out finish for a nice impact feel
        t = step.eased()
        x = lerp(src.x, dst.x, t)
        y = lerp(src.y, dst.y, t)

        # squash/stretch: more stretch mid-dash, squash on arrival
        stretch = 1.0 + 0.15 * smoothstep01(1.0 - abs(t*2 - 1))  # 1.15 mid way
        squash  = 1.0 - 0.10 * smoothstep01(max(0.0, t - 0.85)/0.15)  # 0.9 at very end
        sx, sy = stretch, squash
        w, h = int(CARD_W * sx), int(CARD_H * sy)
        r = pygame.Rect(0, 0, w, h); r.center = (int(x + 0.5), int(y + 0.5))

        # shadow smear
        sh = pygame.Surface((w+30, 22), pygame.SRCALPHA)
        pygame.draw.ellipse(sh, (0,0,0,110), sh.get_rect())
        screen.blit(sh, (r.x-15, r.bottom-12))

        pygame.draw.rect(screen, color, r, border_radius=10)

    def _draw_flash(self, step: AnimStep):
        target: pygame.Rect = step.data["rect"]
        # fade out radial flash
        t = step.raw_progress()
        alpha = int(200 * (1.0 - t))
        rad = int(max(target.w, target.h) * lerp(0.6, 1.1, t))
        s = pygame.Surface((rad*2, rad*2), pygame.SRCALPHA)
        pygame.draw.circle(s, (255,255,255, alpha), (rad, rad), rad)
        screen.blit(s, (target.centerx - rad, target.centery - rad))

    def _draw_start_game(self, step: AnimStep):
        t = step.eased()
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0,0,0, int(160 * t)))
        screen.blit(overlay, (0,0))
        centered_text("Game starting...", H//2)

    def _draw_banner(self, step: AnimStep):
        # Fade in, hold, fade out
        t = step.raw_progress()
        if t < 0.2:
            a = smoothstep01(t/0.2)
        elif t > 0.8:
            a = smoothstep01((1.0 - t)/0.2)
        else:
            a = 1.0

        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0,0,0, int(120 * a)))
        screen.blit(shade, (0,0))

        msg = step.data.get("text", "")
        box = pygame.Surface((W, 1), pygame.SRCALPHA)  # just for text render baseline
        txt = BIG.render(str(msg), True, WHITE)
        screen.blit(txt, txt.get_rect(center=(W//2, H//2)))

    def update_and_draw(self, g: Game, hot):
        """
        Return (hidden_ids, top_overlay) like before.
        We now composite overlays directly; we return None for top_overlay.
        """
        # start steps if needed
        if self.blocking:
            if self.blocking[0].start_ms is None:
                self.blocking[0].start()
        # start ambient newcomers
        for s in self.ambient:
            if s.start_ms is None: s.start()

        hidden_ids = self.peek_hidden_ids()

        # ----- draw current blocking step (if any) -----
        if self.blocking:
            step = self.blocking[0]
            k = step.kind
            if k == "play_move":       self._draw_play_move(step)
            elif k == "attack_dash":   self._draw_attack_dash(step)
            elif k == "flash":         self._draw_flash(step)     # normally NB, but supported
            elif k == "think_pause":   pass                       # invisible timing gate
            elif k == "start_game":    self._draw_start_game(step)
            elif k == "banner":        self._draw_banner(step)
            elif k == "hero_attack":   self._draw_hero_attack(step)
            # finish?
            if step.done():
                self.blocking.pop(0)
                if step.on_finish:
                    try: step.on_finish()
                    except Exception: pass

        # ----- draw ambient (non-blocking) steps -----
        # sort by layer (0 below, 1 top/HUD)
        if self.ambient:
            self.ambient.sort(key=lambda s: s.layer)
            to_remove = []
            for s in self.ambient:
                k = s.kind
                if k == "flash":       self._draw_flash(s)
                elif k == "banner":    self._draw_banner(s)
                elif k == "start_game":self._draw_start_game(s)
                elif k == "think_pause": pass
                elif k == "attack_dash": self._draw_attack_dash(s)
                elif k == "play_move":   self._draw_play_move(s)
                if s.done():
                    to_remove.append(s)
                    if s.on_finish:
                        try: s.on_finish()
                        except Exception: pass
            if to_remove:
                for s in to_remove:
                    try: self.ambient.remove(s)
                    except ValueError: pass

        # We now composite overlays internally; keep signature compatibility
        return hidden_ids, None

ANIMS = AnimQueue()

def enqueue_attack_anim(hot, attacker_mid: int, target_rect: pygame.Rect, enemy: bool, on_hit):
    coll = "enemy_minions" if enemy else "my_minions"
    src = None
    for mid, r in hot[coll]:
        if mid == attacker_mid:
            src = r; break
    if src is None: return
    def after_forward(attacker_mid=attacker_mid, coll=coll, target_rect=target_rect):
        try: on_hit()
        except Exception as e: print("on_hit error:", repr(e))
        post = layout_board(GLOBAL_GAME)
        if any(mid == attacker_mid for mid, _ in post[coll]):
            back_dst = None
            for mid, rr in post[coll]:
                if mid == attacker_mid: back_dst = rr; break
            if back_dst:
                ANIMS.push(AnimStep("attack_dash", ANIM_RETURN_MS,
                                    {"src": target_rect, "dst": back_dst,
                                     "color": CARD_BG_EN if enemy else CARD_BG_MY}))
    ANIMS.push(AnimStep("attack_dash", ANIM_ATTACK_MS,
                        {"src": src, "dst": target_rect,
                         "color": CARD_BG_EN if enemy else CARD_BG_MY},
                        on_finish=after_forward))

def enqueue_play_anim(pre_hot, post_hot, from_rect: pygame.Rect, spawned_mid: Optional[int], label: str, is_enemy: bool):
    if spawned_mid:
        coll = "enemy_minions" if is_enemy else "my_minions"
        dst = None
        for mid, r in post_hot[coll]:
            if mid == spawned_mid: dst = r; break
        if dst:
            ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                {"src": from_rect, "dst": dst, "label": label,
                                 "spawn_mid": spawned_mid,
                                 "color": CARD_BG_EN if is_enemy else CARD_BG_HAND}))

def enqueue_flash(rect: pygame.Rect):
    ANIMS.push(AnimStep("flash", ANIM_FLASH_MS, {"rect": rect}))

def enqueue_hero_attack_anim(hot, pid: int, target_rect: pygame.Rect, on_hit):
    face_rect = hot["face_me"] if pid == 0 else hot["face_enemy"]

    # Snapshot hero plate once and reuse
    try:
        hero_sprite = screen.subsurface(face_rect).copy()
    except Exception:
        hero_sprite = None

    def after_forward(pid=pid, tgt=target_rect):
        try:
            on_hit()
        except Exception as e:
            print("on_hit error:", repr(e))
        post = layout_board(GLOBAL_GAME)
        back_dst = post["face_me"] if pid == 0 else post["face_enemy"]

        # Return leg: reuse SAME sprite; don't dim the target, optionally dim the landing plate
        ANIMS.push(AnimStep(
            "hero_attack",
            ANIM_RETURN_MS,
            {
                "src": tgt,
                "dst": back_dst,
                "sprite": hero_sprite,
                "dim": False,          # no dim during takeoff from target
                # or: "dim": True, "dim_rect": back_dst  # to dim landing plate instead
                "non_blocking": False,
                "ease": "back",
            }
        ))

    # Outbound leg: use hero sprite, dim the original plate while lifting
    ANIMS.push(AnimStep(
        "hero_attack",
        ANIM_HERO_MS,
        {
            "src": face_rect,
            "dst": target_rect,
            "sprite": hero_sprite,     # <- critical: same sprite
            "dim": True,
            "dim_rect": face_rect,
            "non_blocking": False,
            "ease": "back",
        },
        on_finish=after_forward
    ))
def has_spell_hit(ev_list) -> bool:
    return any(getattr(e, "kind", "") == "SpellHit" for e in (ev_list or []))

def queue_spell_projectiles_from_events(caster_pid: int, ev_list):
    if not ev_list:
        return
    post = layout_board(GLOBAL_GAME)
    src = post["face_me"].center if caster_pid == 0 else post["face_enemy"].center

    for e in ev_list:
        if getattr(e, "kind", "") != "SpellHit": 
            continue
        p = e.payload or {}
        ttype = p.get("target_type")
        if ttype == "player":
            dst = (post["face_me"].center if p.get("player") == 0 else post["face_enemy"].center)
            dest_rect = post["face_me"] if p.get("player") == 0 else post["face_enemy"]
        elif ttype == "minion":
            mid = p.get("minion")
            dest_rect = None
            for coll in ("my_minions", "enemy_minions"):
                for mmid, rr in post[coll]:
                    if mmid == mid:
                        dest_rect = rr; break
                if dest_rect: break
            if not dest_rect:
                continue
            dst = dest_rect.center
        else:
            continue

        def on_arrive(r=dest_rect):
            enqueue_flash(r)

        ANIMS.push(AnimStep("spell_orbs", ANIM_SPELL_MS, {"src": src, "dst": dst, "count": 5, "radius": 7, "non_blocking": True}, on_finish=on_arrive))

def enemy_face_rect(hot): return hot["face_enemy"]
def my_face_rect(hot):    return hot["face_me"]

# Small compatibility shim – runs the JSON post-summon hook on all summon events
def apply_post_summon_hooks(g, events):
    hook = g.cards_db.get("_POST_SUMMON_HOOK")
    if not hook or not events:
        return
    for e in events:
        if getattr(e, "kind", None) == "MinionSummoned":
            loc = g.find_minion(e.payload["minion"])
            if loc:
                _, _, m = loc
                hook(g, m)

def minion_under_point(g: Game, hot, mx, my) -> Optional[int]:
    for mid, r in hot["my_minions"] + hot["enemy_minions"]:
        if r.collidepoint(mx, my):
            return mid
    return None


# ---------- Main loop ----------
GLOBAL_GAME: Game

def start_game() -> Game:
    ANIMS.push(AnimStep("start_game", 1500, {}))
    g = Game(db, STARTER_DECK_PLAYER.copy(), STARTER_DECK_AI.copy(),
             heroes=(HERO_PLAYER, HERO_AI))
    ev = g.start_game()
    apply_post_summon_hooks(g, ev)
    log_events(ev, g)
    return g

def main():
    global GLOBAL_GAME
    global SHOW_ENEMY_HAND
    global DEBUG_BTN_RECT
    clock = pygame.time.Clock()
    g = start_game()
    GLOBAL_GAME = g

    selected_attacker: Optional[int] = None
    selected_hero: bool = False
    waiting_target_for_play: Optional[Tuple[int, str, pygame.Rect]] = None
    waiting_target_for_power: Optional[int] = None  # holds pid (0 only for UI)
    hilite_enemy_min: set = set()
    hilite_my_min: set = set()
    hilite_enemy_face: bool = False
    hilite_my_face: bool = False
    inspected_minion_id: Optional[int] = None
    # --- drag state for minion placement ---
    dragging_from_hand: Optional[Tuple[int, str, pygame.Rect]] = None  # (hand_index, cid, original_rect)
    drag_offset: Tuple[int, int] = (0, 0)  # mouse-to-card offset while dragging
    dragging_pos: Tuple[int, int] = (0, 0)
    hover_slot_index: Optional[int] = None  # 0..len(board)

    
    
    RUNNING = True
    while RUNNING:
        clock.tick(60)
        screen.fill(BG)
        hot = layout_board(g)

        #draw_headers(g)
        draw_action_log()
        # 1) get IDs to hide (no drawing yet)
        hidden = ANIMS.peek_hidden_ids()

        # 2) draw the board first (so the arena is underneath)
        # compute dragging preview rect if any
        drag_preview = None
        if dragging_from_hand is not None:
            _, cid_drag, _r0 = dragging_from_hand
            mx, my = pygame.mouse.get_pos()
            dx, dy = drag_offset
            drag_rect = pygame.Rect(mx - dx, my - dy, CARD_W, CARD_H)
            drag_preview = (cid_drag, drag_rect)

        show_slots = dragging_from_hand is not None and len(g.players[0].board) < 7
        draw_board(
            g, hot,
            hidden_minion_ids=hidden,
            highlight_enemy_minions=hilite_enemy_min,
            highlight_my_minions=hilite_my_min,
            highlight_enemy_face=hilite_enemy_face,
            highlight_my_face=hilite_my_face,
            show_slots=show_slots,
            active_slot_index=hover_slot_index,
            dragging_card=drag_preview
        )
        # 3) now draw the animations ON TOP
        _, top_overlay = ANIMS.update_and_draw(g, hot)
        if top_overlay is not None:
            screen.blit(top_overlay, (0, 0))

        if inspected_minion_id is not None:
            draw_card_inspector_for_minion(g, inspected_minion_id)
            # Input drain: allow close via right-click or ESC only
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if inspected_minion_id is not None:
                        inspected_minion_id = None
                    else:
                        RUNNING = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    inspected_minion_id = None
            pygame.display.flip()
            continue
        # GG
        if g.players[0].health <= 0 or g.players[1].health <= 0:
            winner = "AI" if g.players[0].health <= 0 else "You"
            centered_text(f"Game over! {winner} wins. ESC to quit.", H//2 + 8)
            for event in pygame.event.get():
                if event.type == pygame.QUIT: RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: RUNNING = False
            pygame.display.flip()
            continue
        if top_overlay is not None:
            screen.blit(top_overlay, (0, 0))
        # ----- AI turn -----
        if g.active_player == 1:
            if not ANIMS.busy():
                def decide():
                    def schedule_if_ai_turn():  
                        # Only queue the next think if the AI still has the turn
                        if g.active_player == 1:
                            ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=decide))

                    queued_any = False

                    # 1) Try hero attack
                    if g.hero_can_attack(1):
                        mins, face_ok = g.hero_legal_targets(1)
                        target_min = next(iter(mins), None)

                        before = layout_board(g)
                        tr = None
                        if target_min is not None:
                            for mid, rr in before["my_minions"]:
                                if mid == target_min:
                                    tr = rr; break
                        if tr is None and face_ok:
                            tr = my_face_rect(before)
                        if tr is None:
                            schedule_if_ai_turn()
                            return

                        def on_hit(target_min=target_min):
                            try:
                                if target_min is not None:
                                    ev2 = g.hero_attack(1, target_minion=target_min)
                                else:
                                    ev2 = g.hero_attack(1, target_player=0)
                                log_events(ev2, g)
                            except IllegalAction:
                                pass
                            schedule_if_ai_turn()

                        enqueue_hero_attack_anim(before, pid=1, target_rect=tr, on_hit=on_hit)
                        queued_any = True

                    else:
                        # 2) Otherwise use AI policy (play/attack)
                        result = None
                        try:
                            result = pick_best_action(g, 1)
                        except Exception:
                            result = None

                        if not result:
                            # 3) Try hero power, else end turn
                            def try_power_then_end():
                                try:
                                    from ai import maybe_use_hero_power
                                    ev = maybe_use_hero_power(g, 1)
                                except Exception:
                                    ev = []
                                if ev:
                                    log_events(ev, g)
                                    flash_from_events(g, ev)
                                    schedule_if_ai_turn()
                                    return
                                try:
                                    ev2 = g.end_turn(1)
                                    log_events(ev2, g)
                                    ANIMS.push(AnimStep("banner", 700, {"text": "End Turn"}))
                                except IllegalAction:
                                    pass
                            ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=try_power_then_end))
                            queued_any = True

                        else:
                            act, score = result
                            kind = act[0]

                            if kind == 'play':
                                _, idx, tp, tm = act
                                cid = g.players[1].hand[idx]
                                src = pygame.Rect(W // 2 - CARD_W // 2, 20, CARD_W, CARD_H)

                                def do_on_finish(i=idx, tpp=tp, tmm=tm):
                                    try:
                                        ev = g.play_card(1, i, target_player=tpp, target_minion=tmm)
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        flash_from_events(g, ev)
                                        
                                    except IllegalAction:
                                        pass
                                    schedule_if_ai_turn()

                                dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ENEMY, CARD_W, CARD_H)
                                ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}))
                                ANIMS.push(
                                    AnimStep(
                                        "play_move",
                                        ANIM_PLAY_MS,
                                        {"src": src, "dst": dst, "label": db[cid].name, "color": CARD_BG_EN},
                                        on_finish=do_on_finish,
                                    )
                                )
                                queued_any = True

                            elif kind == 'attack':
                                _, aid, tp, tm = act
                                before = layout_board(g)
                                tr = None
                                if tm is not None:
                                    for mid, r in before["my_minions"]:
                                        if mid == tm:
                                            tr = r; break
                                if tr is None:
                                    tr = my_face_rect(before)

                                def on_hit(aid=aid, tpp=tp, tmm=tm):
                                    try:
                                        ev = g.attack(1, attacker_id=aid, target_player=tpp, target_minion=tmm)
                                        log_events(ev, g)
                                    except IllegalAction:
                                        return
                                    post = layout_board(g)
                                    if tmm is None:
                                        enqueue_flash(my_face_rect(post))
                                    else:
                                        for mid, r in post["my_minions"]:
                                            if mid == tmm:
                                                enqueue_flash(r)
                                                break
                                    schedule_if_ai_turn()

                                enqueue_attack_anim(before, attacker_mid=aid, target_rect=tr, enemy=True, on_hit=on_hit)
                                queued_any = True

                            else:
                                # Fallback to power/end
                                def try_power_then_end_fallback():
                                    try:
                                        from ai import maybe_use_hero_power
                                        ev = maybe_use_hero_power(g, 1)
                                    except Exception:
                                        ev = []
                                    if ev:
                                        log_events(ev, g)
                                        flash_from_events(g, ev)
                                        schedule_if_ai_turn()
                                        return
                                    try:
                                        ev2 = g.end_turn(1)
                                        log_events(ev2, g)
                                        ANIMS.push(AnimStep("banner", 700, {"text": "End Turn"}))
                                    except IllegalAction:
                                        pass
                                ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=try_power_then_end_fallback))
                                queued_any = True

                    # Failsafe if nothing queued at all
                    if not queued_any:
                        def _force_end():
                            try:
                                ev2 = g.end_turn(1)
                                log_events(ev2, g)
                            except IllegalAction:
                                add_log("[AI] Failsafe: could not end turn.")
                        ANIMS.push(AnimStep("think_pause", 200, {}, on_finish=_force_end))

                # IMPORTANT: only schedule the first decide; don't call decide() immediately
                ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=decide))

            # Drain events while AI acts
            for event in pygame.event.get():
                if event.type == pygame.QUIT: RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: RUNNING = False

        # ----- YOUR turn -----
        else:
            events = pygame.event.get()
            if ANIMS.busy():
                for event in events:
                    if event.type == pygame.QUIT: RUNNING = False
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: RUNNING = False
                pygame.display.flip()
                continue

            for event in events:
                if event.type == pygame.QUIT:
                    RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    RUNNING = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos

                    if DEBUG_BTN_RECT and DEBUG_BTN_RECT.collidepoint(event.pos):
                        SHOW_ENEMY_HAND = not SHOW_ENEMY_HAND
                        continue

                    # End turn
                    if hot["end_turn"].collidepoint(mx, my):
                        try:
                            ev = g.end_turn(0)
                            log_events(ev, g)
                            ANIMS.push(AnimStep("banner", 700, {"text": "End Turn"}))
                        except IllegalAction:
                            pass
                        selected_attacker = None
                        waiting_target_for_play = None
                        hilite_enemy_min.clear(); hilite_my_min.clear()
                        hilite_enemy_face = False; hilite_my_face = False
                        continue
                    
                    # Select hero attacker
                    if hot["face_me"].collidepoint(mx, my) and hero_ready_to_act(g, 0):
                        mins, face_ok = hero_legal_targets(g, 0)
                        selected_hero = True
                        selected_attacker = None
                        hilite_enemy_min = mins
                        hilite_enemy_face = face_ok
                        hilite_my_min.clear(); hilite_my_face = False
                        continue
                    # If selecting target for a HERO POWER (Mage)
                    if waiting_target_for_power is not None:
                        pid_power = waiting_target_for_power  # 0
                        e_min, m_min, e_face, m_face = targets_for_hero_power(g, pid_power)

                        # Enemy face?
                        if e_face and enemy_face_rect(hot).collidepoint(mx, my):
                            try:
                                ev = g.use_hero_power(0, target_player=1)
                                log_events(ev, g)
                                enqueue_flash(enemy_face_rect(layout_board(g)))
                            except IllegalAction:
                                pass
                            waiting_target_for_power = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            continue

                        # My face?
                        if m_face and my_face_rect(hot).collidepoint(mx, my):
                            try:
                                ev = g.use_hero_power(0, target_player=0)
                                log_events(ev, g)
                                enqueue_flash(my_face_rect(layout_board(g)))
                            except IllegalAction:
                                pass
                            waiting_target_for_power = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            continue

                        # Enemy minion?
                        for mid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my) and mid in e_min:
                                try:
                                    ev = g.use_hero_power(0, target_minion=mid)
                                    log_events(ev, g)
                                    enqueue_flash(r)
                                except IllegalAction:
                                    pass
                                waiting_target_for_power = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                break
                        else:
                            # My minion?
                            did = False
                            for mid, r in hot["my_minions"]:
                                if r.collidepoint(mx, my) and mid in m_min:
                                    try:
                                        ev = g.use_hero_power(0, target_minion=mid)
                                        log_events(ev, g)
                                        enqueue_flash(r)
                                    except IllegalAction:
                                        pass
                                    waiting_target_for_power = None
                                    hilite_enemy_min.clear(); hilite_my_min.clear()
                                    hilite_enemy_face = False; hilite_my_face = False
                                    did = True
                                    break
                            if did:
                                continue
                    
                    # ---- Resolve a pending MINION that needs a battlecry target (pre-play) ----
                    if waiting_target_for_play is not None and waiting_target_for_play[0] == "__PENDING_MINION__":
                        _, idx, cid, src_rect, slot_idx = waiting_target_for_play
                        enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)

                        def _finish_with(target_player=None, target_minion=None, target_rect=None):
                            if len(g.players[0].board) >= 7:
                                # Board filled up while choosing a target; cancel safely.
                                waiting_target_for_play = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                add_log("Board is full. You can't play more minions.")
                                return


                            # animate from hand to the chosen slot (or to target rect for nice feel)
                            slot_rect = insertion_slots_for_my_row(g, battle_area_rect())[slot_idx]
                            dst = pygame.Rect(slot_rect.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                            def on_finish(i=idx, tp=target_player, tm=target_minion, sl=slot_idx):
                                try:
                                    ev = g.play_card(0, i, insert_at=sl, target_player=tp, target_minion=tm)
                                    log_events(ev, g)
                                    apply_post_summon_hooks(g, ev)
                                    flash_from_events(g, ev)
                                except IllegalAction:
                                    pass

                            ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                                {"src": src_rect, "dst": dst, "label": db[cid].name},
                                                on_finish=on_finish))

                        # enemy face?
                        if enemy_face_ok and enemy_face_rect(hot).collidepoint(mx, my):
                            _finish_with(target_player=1, target_minion=None, target_rect=enemy_face_rect(hot))
                        # my face?
                        elif my_face_ok and my_face_rect(hot).collidepoint(mx, my):
                            _finish_with(target_player=0, target_minion=None, target_rect=my_face_rect(hot))
                        else:
                            # enemy minion?
                            done = False
                            for mid, r in hot["enemy_minions"]:
                                if r.collidepoint(mx, my) and mid in enemy_mins:
                                    _finish_with(target_player=None, target_minion=mid, target_rect=r)
                                    done = True
                                    break
                            if not done:
                                # my minion?
                                for mid, r in hot["my_minions"]:
                                    if r.collidepoint(mx, my) and mid in my_mins:
                                        _finish_with(target_player=None, target_minion=mid, target_rect=r)
                                        break

                        # clear highlights if we completed
                        waiting_target_for_play = None
                        hilite_enemy_min.clear(); hilite_my_min.clear()
                        hilite_enemy_face = False; hilite_my_face = False
                        continue


                    if waiting_target_for_play is not None and waiting_target_for_play[0] == "__PENDING_BC__":
                        # resolve the pending battlecry target
                        handled = False

                        # enemy face?
                        if hilite_enemy_face and enemy_face_rect(hot).collidepoint(mx, my):
                            try:
                                ev = g.resolve_pending_battlecry(0, target_player=1)
                                log_events(ev, g); flash_from_events(g, ev)
                            except IllegalAction: pass
                            handled = True

                        # my face?
                        elif hilite_my_face and my_face_rect(hot).collidepoint(mx, my):
                            try:
                                ev = g.resolve_pending_battlecry(0, target_player=0)
                                log_events(ev, g); flash_from_events(g, ev)
                            except IllegalAction: pass
                            handled = True

                        # enemy minion?
                        if not handled:
                            for mid, r in hot["enemy_minions"]:
                                if r.collidepoint(mx, my) and mid in hilite_enemy_min:
                                    try:
                                        ev = g.resolve_pending_battlecry(0, target_minion=mid)
                                        log_events(ev, g); flash_from_events(g, ev)
                                    except IllegalAction: pass
                                    handled = True
                                    break

                        # my minion?
                        if not handled:
                            for mid, r in hot["my_minions"]:
                                if r.collidepoint(mx, my) and mid in hilite_my_min:
                                    try:
                                        ev = g.resolve_pending_battlecry(0, target_minion=mid)
                                        log_events(ev, g); flash_from_events(g, ev)
                                    except IllegalAction: pass
                                    handled = True
                                    break

                        # clear targeting highlights if resolved
                        if handled:
                            waiting_target_for_play = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                        continue


                    # If selecting target for a spell
                    if waiting_target_for_play is not None:
                        idx, cid, src_rect = waiting_target_for_play
                        enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)

                        # Enemy face?
                        if enemy_face_ok and enemy_face_rect(hot).collidepoint(mx, my):
                            def on_finish(i=idx):
                                try:
                                    ev = g.play_card(0, i, target_player=1)
                                    log_events(ev, g)
                                    apply_post_summon_hooks(g, ev)
                                    enqueue_flash(enemy_face_rect(layout_board(g)))
                                    
                                except IllegalAction: pass
                            dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ME, CARD_W, CARD_H)
                            ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                                {"src": src_rect, "dst": dst, "label": db[cid].name},
                                                on_finish=on_finish))
                            waiting_target_for_play = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            continue

                        # My face?
                        if my_face_ok and my_face_rect(hot).collidepoint(mx, my):
                            def on_finish(i=idx):
                                try:
                                    ev = g.play_card(0, i, target_player=0)
                                    log_events(ev, g)
                                    apply_post_summon_hooks(g, ev)
                                   
                                    enqueue_flash(my_face_rect(layout_board(g)))
                                    
                                except IllegalAction: pass
                            dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ME, CARD_W, CARD_H)
                            ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                                {"src": src_rect, "dst": dst, "label": db[cid].name},
                                                on_finish=on_finish))
                            waiting_target_for_play = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            continue

                        # Enemy minion target?
                        targeted = False
                        for mid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my) and mid in enemy_mins:
                                def on_finish(i=idx, mid_target=mid):
                                    try:
                                        ev = g.play_card(0, i, target_minion=mid_target)
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        enqueue_flash(r)
                                        
                                    except IllegalAction: pass
                                ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                                    {"src": src_rect, "dst": r, "label": db[cid].name},
                                                    on_finish=on_finish))
                                waiting_target_for_play = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                targeted = True
                                break
                        if targeted:
                            continue

                        # My minion target?
                        for mid, r in hot["my_minions"]:
                            if r.collidepoint(mx, my) and mid in my_mins:
                                def on_finish(i=idx, mid_target=mid):
                                    try:
                                        ev = g.play_card(0, i, target_minion=mid_target)
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        enqueue_flash(r)
                                        
                                    except IllegalAction: pass
                                ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                                    {"src": src_rect, "dst": r, "label": db[cid].name},
                                                    on_finish=on_finish))
                                waiting_target_for_play = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                break
                        continue
                    
                    # Click hero power button
                    if hot["hp_me"].collidepoint(mx, my) and g.active_player == 0 and can_use_hero_power(g, 0):
                        spec = g.players[0].hero.power.targeting.lower()
                        if spec in ("none", "enemy_face"):  # immediate or auto-resolved
                            try:
                                # enemy_face doesn't need an explicit target; engine resolves via POV
                                ev = g.use_hero_power(0)
                                log_events(ev, g)
                                post = layout_board(g)
                                if spec == "enemy_face":
                                    enqueue_flash(enemy_face_rect(post))
                            except IllegalAction:
                                pass
                        else:
                            # enter targeting mode
                            waiting_target_for_power = 0
                            e_min, m_min, e_face, m_face = targets_for_hero_power(g, 0)
                            hilite_enemy_min = set(e_min)
                            hilite_my_min = set(m_min)
                            hilite_enemy_face = e_face
                            hilite_my_face = m_face
                        continue

                    # Click/drag from hand
                    started_drag = False
                    for i, cid, r in hot["hand"]:
                        if r.collidepoint(mx, my):
                            cobj = g.cards_db[cid]
                            if g.active_player == 0 and cobj.type == "MINION" and card_is_playable_now(g, 0, cid) and len(g.players[0].board) < 7:
                                # ALWAYS begin drag for minions (targeted or not) ✅
                                dragging_from_hand = (i, cid, r.copy())
                                dx, dy = mx - r.x, my - r.y
                                drag_offset = (dx, dy)
                                dragging_pos = (mx, my)
                                slots = insertion_slots_for_my_row(g, battle_area_rect())
                                hover_slot_index = slot_index_at_point(slots, mx, my)
                                started_drag = True
                            else:
                                # Spells or unplayable minions keep the old click-to-play flow
                                enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)
                                if enemy_mins or my_mins or enemy_face_ok or my_face_ok:
                                    waiting_target_for_play = (i, cid, r.copy())
                                    hilite_enemy_min = set(enemy_mins)
                                    hilite_my_min = set(my_mins)
                                    hilite_enemy_face = enemy_face_ok
                                    hilite_my_face = my_face_ok
                                else:
                                    def on_finish(i=i):
                                        try:
                                            ev = g.play_card(0, i)
                                            log_events(ev, g)
                                            apply_post_summon_hooks(g, ev)
                                        except IllegalAction:
                                            pass
                                    dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ME, CARD_W, CARD_H)
                                    ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                                        {"src": r.copy(), "dst": dst, "label": db[cid].name},
                                                        on_finish=on_finish))
                            break

                    if started_drag:
                        continue


                    # Select attacker (only if has legal targets)
                    for mid, r in hot["my_minions"]:
                        if r.collidepoint(mx, my):
                            mins, face_ok = legal_attack_targets(g, mid)
                            if mins or face_ok:
                                selected_attacker = mid
                                hilite_enemy_min = mins
                                hilite_enemy_face = face_ok
                                hilite_my_min.clear(); hilite_my_face = False
                            else:
                                selected_attacker = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                            break
                    
                    # If HERO is selected, try to attack a highlighted target
                    if selected_hero:
                        did = False
                        for emid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my) and emid in hilite_enemy_min:
                                def do_hit(mid=emid, rect=r):
                                    try:
                                        ev = g.hero_attack(0, target_minion=mid)
                                        log_events(ev, g)
                                        enqueue_flash(rect)
                                    except IllegalAction:
                                        return
                                # small dash from hero to target (optional)
                                enqueue_hero_attack_anim(
                                    hot, pid=0, target_rect=r,
                                    on_hit=lambda rect=r, mid=emid: (
                                        log_events(g.hero_attack(0, target_minion=mid), g),
                                        enqueue_flash(rect)
                                    )
                                )
                                did = True
                                break
                        if did:
                            selected_hero = False
                            hilite_enemy_min.clear(); hilite_enemy_face = False
                            continue

                        if hilite_enemy_face and enemy_face_rect(hot).collidepoint(mx, my):
                            def do_hit(rect=enemy_face_rect(hot)):
                                try:
                                    ev = g.hero_attack(0, target_player=1)
                                    log_events(ev, g)
                                    enqueue_flash(rect)
                                except IllegalAction:
                                    return
                            enqueue_hero_attack_anim(
                                hot, pid=0, target_rect=enemy_face_rect(hot),
                                on_hit=lambda rect=enemy_face_rect(hot): (
                                    log_events(g.hero_attack(0, target_player=1), g),
                                    enqueue_flash(rect)
                                )
                            )
                            selected_hero = False
                            hilite_enemy_min.clear(); hilite_enemy_face = False
                            continue

                    # If an attacker is selected, attempt to attack a highlighted target
                    if selected_attacker is not None:
                        did = False
                        for emid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my) and emid in hilite_enemy_min:
                                def on_hit(attacker=selected_attacker, em=emid):
                                    try: 
                                        ev = g.attack(0, attacker, target_minion=em)
                                        log_events(ev, g)
                                    except IllegalAction: pass
                                enqueue_attack_anim(hot, attacker_mid=selected_attacker, target_rect=r, enemy=False, on_hit=on_hit)
                                selected_attacker = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                did = True
                                break
                        if did: continue
                        if hilite_enemy_face and enemy_face_rect(hot).collidepoint(mx, my):
                            def on_hit(attacker=selected_attacker):
                                try: 
                                    ev = g.attack(0, attacker, target_player=1)
                                    log_events(ev, g)
                                except IllegalAction: return
                                enqueue_flash(enemy_face_rect(layout_board(g)))
                            enqueue_attack_anim(hot, attacker_mid=selected_attacker, target_rect=enemy_face_rect(hot), enemy=False, on_hit=on_hit)
                            selected_attacker = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    mx, my = event.pos

                    # Priority: cancel selection if any

                    if selected_attacker is not None or waiting_target_for_play is not None or waiting_target_for_power is not None:
                        selected_attacker = None
                        selected_hero = False
                        waiting_target_for_play = None
                        waiting_target_for_power = None
                        hilite_enemy_min.clear(); hilite_my_min.clear()
                        hilite_enemy_face = False; hilite_my_face = False
                        continue
                    
                    
                    # Toggle inspector
                    if inspected_minion_id is not None:
                        inspected_minion_id = None
                        continue

                    mid = minion_under_point(g, hot, mx, my)
                    if mid is not None:
                        inspected_minion_id = mid
                        continue
                elif event.type == pygame.MOUSEMOTION:
                    if dragging_from_hand is not None:
                        mx, my = event.pos
                        dragging_pos = (mx, my)
                        slots = insertion_slots_for_my_row(g, battle_area_rect())
                        hover_slot_index = slot_index_at_point(slots, mx, my)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if dragging_from_hand is not None:
                        mx, my = event.pos
                        idx, cid, src_rect = dragging_from_hand
                        dragging_from_hand = None
                        # Did we drop over a valid slot?
                        slots = insertion_slots_for_my_row(g, battle_area_rect())
                        slot_idx = slot_index_at_point(slots, mx, my)
                        if slot_idx is None or len(g.players[0].board) >= 7:
                            # cancel: no action
                            hover_slot_index = None
                            continue
                        
                        need = (g.cards_db.get("_TARGETING", {}).get(cid, "none") or "none").lower()

                        if need == "none":
                            # same as before: animate and play immediately
                            slot_rect = slots[slot_idx]
                            dst = pygame.Rect(slot_rect.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                            def on_finish(i=idx):
                                try:
                                    ev = g.play_card(0, i, insert_at=slot_idx)
                                    log_events(ev, g)
                                    apply_post_summon_hooks(g, ev)
                                    flash_from_events(g, ev)
                                except IllegalAction:
                                    pass

                            ANIMS.push(AnimStep(
                                "play_move", ANIM_PLAY_MS,
                                {"src": src_rect, "dst": dst, "label": db[cid].name},
                                on_finish=on_finish
                            ))
                            hover_slot_index = None
                            continue
                        else: 
                            # Check if any legal targets exist
                            enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)
                            any_targets = bool(enemy_mins or my_mins or enemy_face_ok or my_face_ok)
                            if any_targets:
                                # enter targeting mode (same as before)
                                waiting_target_for_play = ("__PENDING_MINION__", idx, cid, src_rect, slot_idx)
                                hilite_enemy_min = set(enemy_mins)
                                hilite_my_min = set(my_mins)
                                hilite_enemy_face = enemy_face_ok or (need in ("any_character", "enemy_character"))
                                hilite_my_face = my_face_ok or (need in ("any_character", "friendly_character"))
                                hover_slot_index = slot_idx
                                continue
                            else:
                                # No valid targets → just play the minion; battlecry will fizzle
                                slot_rect = slots[slot_idx]
                                dst = pygame.Rect(slot_rect.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                                def on_finish(i=idx, sl=slot_idx):
                                    try:
                                        ev = g.play_card(0, i, insert_at=sl)   # no target args
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        flash_from_events(g, ev)
                                    except IllegalAction:
                                        pass

                                ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                                    {"src": src_rect, "dst": dst, "label": db[cid].name},
                                                    on_finish=on_finish))
                                hover_slot_index = None
                                continue
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_h:
                        SHOW_ENEMY_HAND = not SHOW_ENEMY_HAND
                        continue
        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
