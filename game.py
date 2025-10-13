import pygame
import sys
from typing import Optional, Tuple, List, Dict, Any
import random
from collections import deque
import json
from pathlib import Path


from engine import Game, load_cards_from_json, load_heros_from_json, load_decks_from_json, choose_loaded_deck, IllegalAction
from ai import pick_best_action

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
COST_BADGE   = (60, 120, 230)
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
START_GAME      = 1500


KEYWORD_HELP = {
    "Battlecry": "Triggers when played from hand (on summon).",
    "Deathrattle": "After this dies, do its effect.",
    "Taunt": "Enemies must attack this first.",
    "Rush": "Can attack minions immediately.",
    "Charge": "Can attack heroes and minions immediately.",
    "Silence": "Remove text and keywords from a minion.",
    "Spell Damage": "Your spells deal +N damage.",
    "Enrage": "While damaged: gain the listed bonus."
    # add more as you add mechanics: Divine Shield, Stealth, Windfury, etc.
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
        return f"{who} burned {name} (hand full)."
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
        "LEPER_GNOME", "CHARGING_BOAR", "SHIELD_BEARER", "BLESSING_OF_MIGHT_LITE", "GIVE_TAUNT", "SCRAPPY_SCAVENGER",
        "VOODOO_DOCTOR", "TIMBER_WOLF",
        # 2-cost
        "RIVER_CROCOLISK", "KOBOLD_PING", "RUSHER", "NERUBIAN_EGG", "HOLY_LIGHT", "NOVICE_ENGINEER", 
        "KOBOLD_GEOMANCER", "AMANI_BERSERKER", "ACIDIC_SWAMP_OOZE",
        # 3-cost
        "IRONFUR_GRIZZLY", "WOLFRIDER", "EARTHEN_RING", "HARVEST_GOLEM", "ARCANE_MISSILES_LITE",
        "CHARGE_RUSH_2_2", "SHATTERED_SUN_CLERIC", "RAID_LEADER", "KOBOLD_BLASTER",
        # 4-cost
        "CHILLWIND_YETI", "FIREBALL_LITE", "BLESSING_OF_KINGS_LITE",
        "POLYMORPH_LITE", "ARCANE_INTELLECT_LITE", "ARCANE_INTELLECT",
        "SPELLBREAKER", "SHIELDMASTA", "DEFENDER_OF_ARGUS", "ARATHI_WEAPONSMITH",
        # 5+ cost
        "SILVER_HAND_KNIGHT", "CONSECRATION_LITE", "BOULDERFIST_OGRE", "FLAMESTRIKE_LITE", "RAISE_WISPS", "FERAL_SPIRIT_LITE",
        "MUSTER_FOR_BATTLE_LITE", "SILENCE_LITE", "GIVE_CHARGE", "GIVE_RUSH", "LEGENDARY_LEEROY_JENKINS",
        "STORMPIKE_COMMANDO", "CORE_HOUND", "WAR_GOLEM", "STORMWIND_CHAMPION",
    ]
    desired = ["EXPLOSIVE_TRAP", "EAGLEHORN_BOW"] * 30

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

# Pick a deck for each side (by name or first valid), else fall back to your random builder
player_deck, player_hero_hint = choose_loaded_deck(loaded_decks, preferred_name="Classic Hunter Deck (Midrange / Face Hybrid)")
ai_deck, ai_hero_hint         = choose_loaded_deck(loaded_decks, preferred_name="Classic Hunter Deck (Midrange / Face Hybrid)")

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

    # draw inner FIRST so it doesn't cover badges later
    inner = face_rect.inflate(-18, -28)
    pygame.draw.rect(screen, (22, 26, 34), inner, border_radius=10)

    # tiny label strip at top (class color)
    strip = pygame.Rect(face_rect.x, face_rect.y, face_rect.w, 18)
    hid = getattr(pstate.hero, "id", pstate.hero)
    col = HERO_COLORS.get(str(hid).upper(), (90, 90, 90))
    pygame.draw.rect(screen, col, strip, border_radius=10)

    # class name centered on strip
    cap = FONT.render(hero_name(pstate.hero), True, WHITE)
    screen.blit(cap, cap.get_rect(center=strip.center))

    # health (bottom-right)
    health_center = (face_rect.right - 20, face_rect.bottom - 18)
    draw_badge_circle(health_center, 14, HEALTH_BADGE, str(max(0, pstate.health)), font=FONT)

    # armor (small, above health)
    if pstate.armor > 0:
        armor_center = (health_center[0], health_center[1] - 26)
        draw_badge_circle(armor_center, 11, ARMOR_BADGE, str(pstate.armor), text_color=WHITE, font=FONT)

    # weapon badge (bottom-left)
    if getattr(pstate, "weapon", None):
        wtxt = f"{pstate.weapon.attack}/{pstate.weapon.durability}"
        draw_badge_circle((face_rect.x + 26, face_rect.bottom - 18), 12, (120,120,120), wtxt, font=FONT)

    # mana crystal on the right side
    crystal = pygame.Rect(face_rect.right + CRYSTAL_PAD, face_rect.y + 6, CRYSTAL_W, face_rect.h - 12)
    draw_mana_crystal_rect(crystal, pstate.mana, pstate.max_mana)


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
    if p.mana < c.cost:
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

    if need in ("friendly_minion", "friendly_minions"):
        return any(m.is_alive() for m in p.board)
    if need in ("enemy_minion", "enemy_minions"):
        opp = 1 - pid
        return any(m.is_alive() for m in g.players[opp].board)
    if need in ("any_minion", "any_minions"):
        opp = 1 - pid
        return any(m.is_alive() for m in p.board) or any(m.is_alive() for m in g.players[opp].board)

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


def draw_card_frame(r: pygame.Rect, color_bg, *, card_obj=None, minion_obj=None, in_hand: bool):
    pygame.draw.rect(screen, color_bg, r, border_radius=12)

    

    if card_obj:
        draw_cost_gem(r, card_obj.cost)
        #draw_name_bar(r, card_obj.name)

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
    if getattr(minion_obj, "silenced", False):
        draw_silence_overlay(r)

def draw_layered_borders(r: pygame.Rect, *, taunt: bool, rush: bool, ready: bool):
    if taunt: pygame.draw.rect(screen, GREY, r, 3, border_radius=10)
    if rush:  pygame.draw.rect(screen, RED,  r.inflate(4, 4), 3, border_radius=12)
    if ready: pygame.draw.rect(screen, GREEN,r.inflate(10,10), 3, border_radius=16)

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
           "face_enemy": None, "face_me": None, "hp_enemy": None, "hp_me": None}

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

    # draw non-hovered first (so hovered can render on top)
    for i, cid, r in hot["hand"]:
        if i == hover_idx:
            continue
        c = g.cards_db[cid]
        # subtle overlap shadow
        shadow = r.copy(); shadow.x += 3; shadow.y += 3
        pygame.draw.rect(screen, (0, 0, 0, 40), shadow, border_radius=12)
        draw_card_frame(r, CARD_BG_HAND, card_obj=c, in_hand=True)

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
            # backdrop glow
            glow = rz.inflate(14, 14)
            pygame.draw.rect(screen, (255, 255, 255), glow, 6, border_radius=18)
            draw_card_frame(rz, CARD_BG_HAND, card_obj=c, in_hand=True)

            lines = keyword_explanations_for_card(c)
            draw_keyword_help_panel(rz, lines, side="right")

            if g.active_player == 0 and card_is_playable_now(g, 0, cid0):
                pygame.draw.rect(screen, GREEN, rz.inflate(12, 12), 4, border_radius=18)

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
        draw_card_frame(rdrag, CARD_BG_HAND, card_obj=cobj, in_hand=True)
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


# ---------- Animation system ----------
def lerp(a: float, b: float, t: float) -> float: return a + (b - a) * t
def ease_out(t: float) -> float: return 1 - (1 - t) * (1 - t)

class AnimStep:
    def __init__(self, kind: str, duration_ms: int, data: dict, on_finish=None):
        self.kind = kind
        self.duration_ms = duration_ms
        self.data = data
        self.on_finish = on_finish
        self.start_ms = None
    def start(self): self.start_ms = pygame.time.get_ticks()
    def progress(self) -> float:
        if self.start_ms is None: return 0.0
        t = (pygame.time.get_ticks() - self.start_ms) / self.duration_ms
        return 0.0 if t < 0 else (1.0 if t > 1.0 else t)
    def done(self) -> bool: return self.progress() >= 1.0

class AnimQueue:
    def __init__(self): self.queue: List[AnimStep] = []
    def push(self, step: AnimStep): self.queue.append(step)
    def busy(self) -> bool: return len(self.queue) > 0
    def update_and_draw(self, g: Game, hot):
        hidden_ids = set()
        top_overlay = None                         # <-- NEW
        if not self.queue:
            return hidden_ids, top_overlay        # <-- changed
        step = self.queue[0]
        if step.start_ms is None: step.start()
        t = ease_out(step.progress())

        if step.kind == "play_move":
            src: pygame.Rect = step.data["src"]; dst: pygame.Rect = step.data["dst"]
            color = step.data.get("color", CARD_BG_HAND)
            lbl = step.data.get("label", "")
            r = pygame.Rect(int(lerp(src.x, dst.x, t)), int(lerp(src.y, dst.y, t)), CARD_W, CARD_H)
            pygame.draw.rect(screen, color, r, border_radius=8)
            if lbl: screen.blit(FONT.render(lbl, True, WHITE), (r.x+6, r.y+6))
            spawn_mid = step.data.get("spawn_mid")
            if spawn_mid: hidden_ids.add(spawn_mid)

        elif step.kind == "attack_dash":
            src: pygame.Rect = step.data["src"]; dst: pygame.Rect = step.data["dst"]
            color = step.data.get("color", CARD_BG_MY)
            r = pygame.Rect(int(lerp(src.x, dst.x, t)), int(lerp(src.y, dst.y, t)), CARD_W, CARD_H)
            pygame.draw.rect(screen, color, r, border_radius=8)

        elif step.kind == "flash":
            target: pygame.Rect = step.data["rect"]
            alpha = int(255 * (1.0 - t))
            s = pygame.Surface((target.w, target.h), pygame.SRCALPHA)
            s.fill((255, 255, 255, alpha))
            screen.blit(s, (target.x, target.y))

        elif step.kind == "think_pause":
            # build an overlay surface to draw LATER (on top)
            overlay = pygame.Surface((W, H), pygame.SRCALPHA)
            overlay.fill((0,0,0, min(120, int(150 * t))))
            # render the text onto the overlay too
            txt = BIG.render("AI is thinking...", True, WHITE)
            overlay.blit(txt, txt.get_rect(center=(W//2, H//2)))
            top_overlay = overlay 
            centered_text("AI is thinking...", H//2)
        elif step.kind == "start_game":
            overlay = pygame.Surface((W, H), pygame.SRCALPHA)
            overlay.fill((0,0,0, min(120, int(150 * t))))
            screen.blit(overlay, (0,0))
            centered_text("Game starting...", H//2)

        if step.done():
            self.queue.pop(0)
            if step.on_finish:
                try: step.on_finish()
                except Exception: pass
        return hidden_ids, top_overlay 
    def peek_hidden_ids(self):
        hidden = set()
        if not self.queue:
            return hidden
        step = self.queue[0]
        if step.kind == "play_move":
            spawn_mid = step.data.get("spawn_mid")
            if spawn_mid:
                hidden.add(spawn_mid)
        return hidden
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
                    # 1) If hero can attack, do it first: hit Taunt if present, else face
                    if g.hero_can_attack(1):
                        mins, face_ok = g.hero_legal_targets(1)
                        target_min = next(iter(mins), None)
                        def do_attack():
                            try:
                                if target_min is not None:
                                    ev2 = g.hero_attack(1, target_minion=target_min)
                                    log_events(ev2, g)
                                    post = layout_board(g)
                                    for mid, r in post["my_minions"]:
                                        if mid == target_min:
                                            enqueue_flash(r); break
                                elif face_ok:
                                    ev2 = g.hero_attack(1, target_player=0)
                                    log_events(ev2, g)
                                    enqueue_flash(my_face_rect(layout_board(g)))
                            except IllegalAction:
                                pass
                        ANIMS.push(AnimStep("think_pause", 300, {}, on_finish=do_attack))
                        return  # don’t pick another action this frame

                    # 2) Pick best action (play/attack) via AI policy
                    act, score = pick_best_action(g, 1)
                    kind = act[0]

                    if kind == 'play':
                        _, idx, tp, tm = act
                        cid = g.players[1].hand[idx]
                        src = pygame.Rect(W//2 - CARD_W//2, 20, CARD_W, CARD_H)
                        def do_on_finish(i=idx, tpp=tp, tmm=tm):
                            try:
                                ev = g.play_card(1, i, target_player=tpp, target_minion=tmm)
                                log_events(ev, g)
                                apply_post_summon_hooks(g, ev)
                                flash_from_events(g, ev)
                            except IllegalAction:
                                pass
                        dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ENEMY, CARD_W, CARD_H)
                        ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}))
                        ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                            {"src": src, "dst": dst, "label": db[cid].name,
                                            "color": CARD_BG_EN}, on_finish=do_on_finish))
                        return

                    elif kind == 'attack':
                        _, aid, tp, tm = act
                        before = layout_board(g)
                        tr = None
                        if tm is not None:
                            for mid, r in before["my_minions"]:
                                if mid == tm: tr = r; break
                        if tr is None: tr = my_face_rect(before)
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
                                    if mid == tmm: enqueue_flash(r); break
                        enqueue_attack_anim(before, attacker_mid=aid, target_rect=tr, enemy=True, on_hit=on_hit)
                        return

                    # 3) No good play/attack picked this frame → *then* consider hero power conservatively
                    def try_power_then_end():
                        try:
                            from ai import maybe_use_hero_power
                            ev = maybe_use_hero_power(g, 1)  # this now refuses “Coin → Power” shenanigans
                        except Exception:
                            ev = []
                        if ev:
                            log_events(ev, g)
                            flash_from_events(g, ev)
                            return  # spent our frame

                        # 4) Finally end the turn
                        try:
                            ev2 = g.end_turn(1)
                            log_events(ev2, g)
                        except IllegalAction:
                            pass

                    ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=try_power_then_end))

                ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=decide))

            # drain events while AI acts
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

                    # End turn
                    if hot["end_turn"].collidepoint(mx, my):
                        try: 
                            ev = g.end_turn(0)
                            log_events(ev, g)
                        except IllegalAction: pass
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
                                ANIMS.push(AnimStep("attack_dash", ANIM_ATTACK_MS,
                                                    {"src": hot["face_me"], "dst": r, "color": CARD_BG_MY},
                                                    on_finish=do_hit))
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
                            ANIMS.push(AnimStep("attack_dash", ANIM_ATTACK_MS,
                                                {"src": hot["face_me"], "dst": enemy_face_rect(hot), "color": CARD_BG_MY},
                                                on_finish=do_hit))
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

                        # needs a target: DO NOT play yet — enter targeting mode and remember slot
                        enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)
                        waiting_target_for_play = ("__PENDING_MINION__", idx, cid, src_rect, slot_idx)
                        hilite_enemy_min = set(enemy_mins)
                        hilite_my_min = set(my_mins)
                        hilite_enemy_face = enemy_face_ok or (need in ("any_character", "enemy_character"))
                        hilite_my_face = my_face_ok or (need in ("any_character", "friendly_character"))
                        hover_slot_index = slot_idx
                        continue
                        
        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
