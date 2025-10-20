import pygame
import sys
from typing import Callable, Optional, Tuple, List, Dict, Any
import random
from collections import deque
import json
from pathlib import Path
import math
import json


from engine import Game, hero_name, load_cards_from_json, load_heros_from_json, load_decks_from_json, choose_loaded_deck, _has_tribe, IllegalAction
from ai import pick_best_action
from consts import *
from models import Card



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

    if not skip:
        if DEBUG:
            print(f"{k}: {format_event(e, g, True)} RAW: {p}")
        else:
            print(f"{k}: {format_event(e, g, True)}")

    if k == "CardDiscarded":
        who = "You" if p.get("player") == 0 else "AI"
        return f"{who} discarded: {p.get('name')}"
    if k == "HeroTempAttack":
        who = "You" if p.get("player") == 0 else "AI"
        return f"{who}'s hero gained +{p.get('added', 0)} Attack this turn."

    if k == "HeroBuffExpired":
        who = "You" if p.get("player") == 0 else "AI"
        return f"{who}'s temporary hero Attack expired."
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
        return ""
        who = "You" if p["player"] == 0 else "AI"
        cid = p.get("card", "")
        name = card_name_from_db(g.cards_db, cid) if cid else "a card"
        return f"{who} played {name}."
    if k == "MinionTransformed":
        who = "You" if p["player"] == 0 else "AI"

        return f"{who} transformed {p.get('old_name')} into a {p.get('new_name')}"
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
    
    print(f"not logging {k}, data: {p}")
    
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
    
    desired = ["ZOMBIE_CHOW", "HAUNTED_CREEPER", "MAD_SCIENTIST", "SHADE_OF_NAXXRAMAS", "SLUDGE_BELCHER", "LOATHEB"]

    # DB keys that are real cards (ignore internal keys like "_POST_SUMMON_HOOK")
    valid_ids = {cid for cid in db.keys() if not cid.startswith("_")}

    # Filter desired by what actually exists in the JSON
    pool = [cid for cid in desired if cid in valid_ids]

    # Helpful debug print so you can see what's missing from the JSON
    missing = [cid for cid in desired if cid not in valid_ids]
    if missing:
        print("[DeckBuilder] Missing from JSON (will be skipped):", ", ".join(missing))

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

if DEBUG:
    for k, c in db.items():
        if isinstance(c, Card):
            c.cost = 0
            #print(c.name, c.keywords, c.text)
# Try to load preconfigured decks
try:
    loaded_decks = load_decks_from_json("lib/decks.json", db)
except Exception as e:
    print("[DeckLoader] Failed to read decks.json:", e)
    loaded_decks = {}

playable_decks = [
    "Classic Hunter Deck (Midrange / Face Hybrid)", 
    "Classic Paladin Deck (Midrange / Control)",
    "Classic Mage Deck (Spell Control / Burst)",
    "Big Big Mage",
    "Classic Warlock Deck (Zoo Aggro)",
    "Handlock",
    "Classic Warrior Deck (Control)",
    "Classic Priest Deck (Control / Value)",
    "Classic Shaman Deck (Midrange / Control)",
    "Classic Shaman Deck (Aggro / Burst)"
]

def get_random_deck(playable_decks: list):
    return random.choice(playable_decks)


# Pick a deck for each side (by name or first valid), else fall back to your random builder
player_deck, player_hero_hint = choose_loaded_deck(loaded_decks, preferred_name=get_random_deck(playable_decks))
ai_deck, ai_hero_hint         = choose_loaded_deck(loaded_decks, preferred_name=get_random_deck(playable_decks))

if DEBUG:
    player_deck = None
#ai_deck = None
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
#HERO_PLAYER = hero_db.get("SHAMAN")
HERO_AI     = _pick_hero(ai_hero_hint,     random.choice(list(hero_db.values())))

STARTER_DECK_PLAYER = player_deck
STARTER_DECK_AI     = ai_deck

# Surface invalid deck errors (optional)
for name, d in loaded_decks.items():
    if "errors" in d:
        print(f"[DeckLoader] Deck '{name}' invalid:")
        for msg in d["errors"]:
            print("  -", msg)




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

def draw_mana_crystal_rect(r: pygame.Rect, mana: int, max_mana: int, *, locked: int = 0, overloaded: int = 0):
    """
    Draw a HORIZONTAL row of 10 diamonds (left → right).
      • locked      = LEFTMOST 'amber' slots (locked this turn; e.g., Overload carryover)
      • overloaded  = spent THIS TURN (orange/red) after the locked portion
      • filled      = current usable mana left this turn (blue)
      • empty line  = capacity this turn that's not filled (outline only)
      • dim line    = beyond current max cap
    """
    total_slots = 10

    mana       = max(0, min(mana, total_slots))
    max_mana   = max(0, min(max_mana, total_slots))
    locked     = max(0, min(locked, total_slots))
    overloaded = max(0, min(overloaded, total_slots))

    # Colors
    col_filled  = MANA_BADGE
    col_empty   = (32, 46, 64)
    col_dim     = (24, 30, 40)
    col_outline = (20, 30, 50)
    col_locked  = (220, 160, 60)
    col_over    = (210, 80, 45)

    # Interior box + sizing
    pad_x = 0
    pad_y = 6
    inner = r.inflate(-pad_x*2, -pad_y*2)
    gap = 6

    # Slot width so 10 items + gaps fit; height based on inner height
    w = max(15, int((inner.w - gap * (total_slots - 1)) / total_slots))
    h = max(10, min(inner.h, int(w * 1.1)))  # a bit taller than wide for a diamond look

    # Vertical centering
    top_y = inner.centery - h // 2
    start_x = inner.x

    def diamond(center_x: int, top_y: int, width: int, height: int):
        mid_x = center_x
        left  = center_x - width // 2
        right = center_x + width // 2
        top   = top_y
        mid_y = top_y + height // 2
        bot   = top_y + height
        return [(mid_x, top), (right, mid_y), (mid_x, bot), (left, mid_y)]

    # Partition counts within the first max_mana slots
    locked_cnt = min(locked, max_mana)
    usable_cnt = max(0, max_mana - locked_cnt)
    # Overload spent applies against usable slots (not the locked ones)
    over_cnt   = min(overloaded, usable_cnt)
    filled_cnt = min(max(0, mana), max(0, usable_cnt - over_cnt))
    empty_cnt  = max(0, usable_cnt - over_cnt - filled_cnt)

    # Draw left → right
    for i in range(total_slots):  # i=0 leftmost
        x = start_x + i * (w + gap) + w // 2
        poly = diamond(x, top_y, w, h)
        slot_idx = i + 1  # 1-based index from left

        if slot_idx <= max_mana:
            # Within the active cap: locked → spent → filled → empty
            if slot_idx <= locked_cnt:
                pygame.draw.polygon(screen, col_locked, poly)
                pygame.draw.polygon(screen, col_outline, poly, 2)
            elif slot_idx <= locked_cnt + over_cnt:
                pygame.draw.polygon(screen, col_over, poly)
                pygame.draw.polygon(screen, col_outline, poly, 2)
            elif slot_idx <= locked_cnt + over_cnt + filled_cnt:
                pygame.draw.polygon(screen, col_filled, poly)
                pygame.draw.polygon(screen, col_outline, poly, 2)
            else:
                pygame.draw.polygon(screen, col_empty, poly, 2)
        else:
            # Beyond max cap
            pygame.draw.polygon(screen, col_dim, poly, 2)


    # Locked crystals: paint onto the RIGHTMOST slots so they read as “next turn”
   


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

        base_atk = int(getattr(pstate.weapon, "attack", 0))
        temp_atk = int(getattr(pstate, "temp_hero_attack", 0))
        atk      = base_atk + max(0, temp_atk)  # show weapon + temp hero attack

        cur = int(getattr(pstate.weapon, "durability", 0))
        base = _weapon_base_durability_safe(GLOBAL_GAME, pstate.weapon)

        # Colors: durability red if damaged; attack green if temporarily buffed
        dur_col = HP_HURT if (base is not None and cur < base) else WHITE
        atk_col = (60, 200, 90) if temp_atk > 0 else WHITE

        atk_surf   = FONT.render(str(atk), True, atk_col)
        slash_surf = FONT.render("/", True, WHITE)
        dur_surf   = FONT.render(str(cur), True, dur_col)

        

        total_w = atk_surf.get_width() + slash_surf.get_width() + dur_surf.get_width()
        max_h   = max(atk_surf.get_height(), slash_surf.get_height(), dur_surf.get_height())
        x = cx - total_w // 2
        y = cy - max_h // 2

        screen.blit(atk_surf,   (x, y)); x += atk_surf.get_width()
        screen.blit(slash_surf, (x, y)); x += slash_surf.get_width()
        screen.blit(dur_surf,   (x, y))
        
    elif getattr(pstate, "temp_hero_attack", 0) > 0:
        # NEW: show temp hero Attack when no weapon is equipped
        cx, cy = face_rect.x + 26, face_rect.bottom - 18
        radius = 14
        pygame.draw.circle(screen, (40, 35, 25), (cx, cy), radius)
        pygame.draw.circle(screen, (20, 20, 20), (cx, cy), radius, 2)

        atk_val = int(getattr(pstate, "temp_hero_attack", 0))
        # Slightly green to indicate a buff this turn
        atk_surf = FONT.render(str(atk_val), True, (60, 200, 90))
        screen.blit(atk_surf, atk_surf.get_rect(center=(cx, cy)))

    # After armor/weapon/temp-attack, place mana *after* hero power
    HP_W = 150
    HP_H = 52  # keep in sync with layout_board

    crystal = pygame.Rect(
        face_rect.right + CRYSTAL_PAD + HP_W + CRYSTAL_PAD,  # after the power
        face_rect.y + 6,
        CRYSTAL_W,                                           # make this wider in consts if you want bigger crystals
        HP_H                                                 # short strip to match the power button
    )

    draw_mana_crystal_rect(
        crystal,
        pstate.mana,
        pstate.max_mana,
        locked=getattr(pstate, "locked_mana", 0) or getattr(pstate, "overload_locked", 0),
        overloaded=getattr(pstate, "overloaded", 0) or getattr(pstate, "overload_spent", 0),
    )

    if getattr(pstate, "hero_frozen", False):
        draw_frozen_overlay(face_rect)

def keyword_explanations_for_card(card_obj) -> List[str]:
    """
    STRICT: Only show tooltips for keywords explicitly present on the card JSON.
    No inference from handlers like `battlecry` or `on_cast`.
    """
    raw = getattr(card_obj, "keywords", []) or []
    # Normalize to strings and filter to those we have help text for
    kws = [str(k) for k in raw if str(k) in KEYWORD_HELP]
    return [f"{k}: {KEYWORD_HELP[k]}" for k in kws]

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

def card_is_playable_now(g: Game, pid: int, cid: str) -> bool:
    c = g.cards_db[cid]
    p = g.players[pid]

    eff_cost = g.get_effective_cost(pid, cid)
    if p.mana < eff_cost:
        return False
    if c.type == "MINION" and len(p.board) >= 7:
        return False

    # Secrets: prevent duplicate
    is_secret = ("Secret" in getattr(c, "keywords", [])) or getattr(c, "is_secret", False) or (c.type == "SECRET")
    if is_secret:
        if any(s.get("card_id") == cid for s in p.active_secrets or []):
            return False

    # Optional per-card requirement (e.g., EXECUTE needs a damaged enemy on board)
    req = PLAY_REQUIREMENTS.get(cid)
    if req and not req(g, pid):
        return False

    # Basic targeting availability (kept from your original)
    targ_map = g.cards_db.get("_TARGETING", {})
    need = (targ_map.get(cid, "none") or "none").lower()

    if c.type == "SPELL":
        if need in ("friendly_minion", "friendly_minions"):
            return any(m.is_alive() for m in p.board)
        if need in ("enemy_minion", "enemy_minions"):
            opp = 1 - pid
            return any(m.is_alive() for m in g.players[opp].board)
        if need in ("any_minion", "any_minions"):
            opp = 1 - pid
            return any(m.is_alive() for m in p.board) or any(m.is_alive() for m in g.players[opp].board)

    return True

def card_is_secret(cobj) -> bool:
    return (
        "Secret" in (getattr(cobj, "keywords", []) or [])
        or getattr(cobj, "is_secret", False)
        or getattr(cobj, "type", "").upper() == "SECRET"
    )

def card_is_non_target_cast(g: Game, pid: int, cid: str) -> bool:
    """
    True if the card should be cast by dragging onto the board (no targeting step):
    - non-target spell
    - secret
    - weapon
    """
    c = g.cards_db[cid]
    if getattr(c, "type", "").upper() == "WEAPON":
        return True
    if card_is_secret(c):
        return True

    # Spells with no targets
    if getattr(c, "type", "").upper() == "SPELL":
        enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid)
        return not (enemy_mins or my_mins or enemy_face_ok or my_face_ok)

    return False



# ----------- FILTERS and Exists
def _exists_minion_attack_7plus(g: Game, pid: int) -> bool:
    return any(m.is_alive() and m.attack >= 7 for m in g.players[0].board) \
        or any(m.is_alive() and m.attack >= 7 for m in g.players[1].board)

def _exists_damaged_enemy_minion(g, pid: int) -> bool:
    opp = 1 - pid
    return any(m.is_alive() and m.health < m.max_health for m in g.players[opp].board)

def _exists_friendly_minion(g: Game, pid: int) -> bool:
    return any(m.is_alive() for m in g.players[pid].board)

def _exists_armor_for_shield_slam(g, pid: int) -> bool:
    return getattr(g.players[pid], "armor", 0) > 0

def _exists_any_minion(g: Game, pid: int) -> bool:
    return any(m.is_alive() for m in g.players[0].board) or any(m.is_alive() for m in g.players[1].board)

def _exists_any_demon_minion(g: Game, pid: int) -> bool:
    for side in (pid, g.other(pid)):
        for m in g.players[side].board:
            if m.is_alive() and _has_tribe(m, "demon"):
                return True
    return False

def _exists_enemy_minion_attack_leq3(g, pid: int) -> bool:
    opp = 1 - pid
    return any(m.is_alive() and m.attack <= 3 for m in g.players[opp].board)

def _exists_enemy_minion_attack_geq5(g, pid: int) -> bool:
    opp = 1 - pid
    return any(m.is_alive() and m.attack >= 5 for m in g.players[opp].board)

def _filter_damaged_enemy_minions(g, pid: int, m) -> bool:
    # Only allow enemy + damaged
    return (m.owner != pid) and m.is_alive() and (m.health < m.max_health)

def _filter_any_demon_minions(g: Game, pid: int, m) -> set[int]:
    ids = set()
    for side in (pid, g.other(pid)):
        for m in g.players[side].board:
            if m.is_alive() and _has_tribe(m, "demon"):
                ids.add(m.id)
    return ids

def _filter_friendly_minions(g: Game, pid: int, m) -> set[int]:
    return {m.id for m in g.players[pid].board if m.is_alive()}

def _filter_any_enemy_minion(g, pid: int, m) -> bool:
    return (m.owner != pid) and m.is_alive()

def _filter_any_minions(g: Game, pid: int, m) -> set[int]:
    s = {m.id for m in g.players[0].board if m.is_alive()}
    s |= {m.id for m in g.players[1].board if m.is_alive()}
    return s


def _filter_minions_attack_7plus(g: Game, pid: int, m) -> set[int]:
    ids = {m.id for m in g.players[0].board if m.is_alive() and m.attack >= 7}
    ids |= {m.id for m in g.players[1].board if m.is_alive() and m.attack >= 7}
    return ids

def _filter_enemy_attack_leq3(g, pid: int, m) -> bool:
    return (m.owner != pid) and m.is_alive() and (m.attack <= 3)

def _filter_enemy_attack_geq5(g, pid: int, m) -> bool:
    return (m.owner != pid) and m.is_alive() and (m.attack >= 5)

# Registry: simple, extend as needed
PLAY_REQUIREMENTS: dict[str, callable] = {
    "EXECUTE": _exists_damaged_enemy_minion,
    "SHIELD_SLAM": _exists_armor_for_shield_slam,
    "SACRIFICIAL_PACT" : _exists_any_demon_minion,
    "SHADOWFLAME": _exists_friendly_minion,


    "SHADOW_WORD_PAIN":  _exists_enemy_minion_attack_leq3,
    "SHADOW_WORD_DEATH": _exists_enemy_minion_attack_geq5,
    #"BIG_GAME_HUNTER": _exists_minion_attack_7plus
}

TARGET_FILTERS: dict[str, callable] = {
    "EXECUTE": _filter_damaged_enemy_minions,   
    "SACRIFICIAL_PACT": _filter_any_demon_minions,
    "SHADOWFLAME" : _filter_friendly_minions,
    "SHADOW_WORD_PAIN":  _filter_enemy_attack_leq3,
    "SHADOW_WORD_DEATH": _filter_enemy_attack_geq5,

    "BIG_GAME_HUNTER": _filter_minions_attack_7plus,
    
}

# --- helpers -
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
def draw_cost_gem(r: pygame.Rect, cost: int, *, surface=None):
    if surface is None: surface = screen
    gem = pygame.Rect(r.x + 8, r.y + 8, 30, 30)
    pygame.draw.ellipse(surface, COST_BADGE, gem)
    t = BIG.render(str(cost), True, WHITE)
    surface.blit(t, t.get_rect(center=gem.center))

def draw_name_footer(r: pygame.Rect, name: str, *, surface=None):
    if surface is None: surface = screen
    name_h   = 22
    stats_h  = 28
    gap      = 4
    footer_w = r.w - 20
    footer_x = r.x + (r.w - footer_w)//2
    footer_y = r.bottom - stats_h - gap - name_h
    bar = pygame.Rect(footer_x, footer_y, footer_w, name_h)
    pygame.draw.rect(surface, (30, 35, 45), bar, border_radius=10)
    nm = name
    while FONT.size(nm)[0] > bar.w - 16 and len(nm) > 0: nm = nm[:-1]
    if len(nm) < len(name) and len(nm) > 0: nm = nm[:-1] + "…"
    text_surf = FONT.render(nm, True, WHITE)
    surface.blit(text_surf, text_surf.get_rect(center=bar.center))

def draw_text_box(r: pygame.Rect, body_text: str, max_lines: int, *,
                  title: Optional[str] = None, font_body=RULE_FONT, font_title=BIG, surface=None):
    if surface is None: surface = screen
    top_pad = 45
    name_h  = 22
    stats_h = 28
    gap     = 4
    bottom_reserved = name_h + stats_h + gap + 6
    box = pygame.Rect(r.x + 10, r.y + top_pad, r.w - 20, r.h - top_pad - bottom_reserved)
    pygame.draw.rect(surface, (28, 28, 34), box, border_radius=8)
    y = box.y + 6
    if title:
        t_txt = title
        while font_title.size(t_txt)[0] > box.w - 12 and len(t_txt) > 0: t_txt = t_txt[:-1]
        if len(t_txt) < len(title) and len(t_txt) > 0: t_txt = t_txt[:-1] + "…"
        ts = font_title.render(t_txt, True, WHITE)
        surface.blit(ts, ts.get_rect(center=(box.centerx, y + ts.get_height()//2)))
        y += ts.get_height() + 4
        pygame.draw.line(surface, (60, 70, 85), (box.x + 6, y), (box.right - 6, y), 1)
        y += 6
    lines = wrap_text(body_text, font_body, box.w - 12)[:max_lines]
    for ln in lines:
        surf = font_body.render(ln, True, WHITE)
        surface.blit(surf, (box.x + 6, y))
        y += surf.get_height() + 2

def draw_minion_stats(r: pygame.Rect, attack: int, health: int, max_health: int, *,
                      base_attack: int, base_health: int, surface=None):
    if surface is None: surface = screen
    atk_rect = pygame.Rect(r.x + 10, r.bottom - 28, 28, 22)
    pygame.draw.rect(surface, (40, 35, 25), atk_rect, border_radius=6)
    atk_col = (60, 200, 90) if attack > base_attack else ATTK_COLOR
    ta = FONT.render(str(attack), True, atk_col)
    surface.blit(ta, ta.get_rect(center=atk_rect.center))
    hp_rect = pygame.Rect(r.right - 38, r.bottom - 28, 28, 22)
    pygame.draw.rect(surface, (40, 35, 35), hp_rect, border_radius=6)
    if health < max_health:
        hp_col = HP_HURT
    elif max_health > base_health:
        hp_col = (60, 200, 90)
    else:
        hp_col = HP_OK
    th = FONT.render(str(health), True, hp_col)
    surface.blit(th, th.get_rect(center=hp_rect.center))

def draw_rarity_droplet(r: pygame.Rect, rarity: Optional[str], *, surface=None):
    if surface is None: surface = screen
    if not rarity: rarity = "COMMON"
    key = str(rarity).upper()
    color = RARITY_COLORS.get(key, RARITY_COLORS["COMMON"])
    radius = 9
    cx, cy = r.centerx, r.bottom - 16
    pygame.draw.circle(surface, color, (cx, cy), radius)
    pygame.draw.circle(surface, (20, 20, 20), (cx, cy), radius, 2)

def draw_silence_overlay(r: pygame.Rect, *, surface=None):
    if surface is None: surface = screen
    s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    pygame.draw.polygon(
        s, (100, 80, 150, 180),
        [(-10, int(r.h*0.35)), (r.w+10, int(r.h*0.10)), (r.w+10, int(r.h*0.25)), (-10, int(r.h*0.50))]
    )
    lbl = BIG.render("SILENCED", True, (240, 235, 255))
    s.blit(lbl, lbl.get_rect(center=(r.w//2, int(r.h*0.23))))
    surface.blit(s, (r.x, r.y))

def draw_frozen_overlay(r: pygame.Rect, *, surface=None):
    if surface is None: surface = screen
    s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    pygame.draw.polygon(
        s, (120, 180, 255, 170),
        [(-12, int(r.h*0.18)), (r.w+12, int(r.h*0.03)), (r.w+12, int(r.h*0.17)), (-12, int(r.h*0.32))]
    )
    lbl = BIG.render("FROZEN", True, (235, 245, 255))
    s.blit(lbl, lbl.get_rect(center=(r.w//2, int(r.h*0.12))))
    surface.blit(s, (r.x, r.y))


def _infer_card_class_name(card_obj) -> str | None:
    """Best-effort: grab the class name off the Card object (or dict)."""
    if card_obj is None:
        return None
    # probe common field names
    candidates = [
        "card_class", "hero_class", "class_name", "class", "klass",
        "cardClass", "Class", "clazz", "classId", "cardclass", "class_"
    ]
    val = None
    for key in candidates:
        if hasattr(card_obj, key):
            val = getattr(card_obj, key)
            break
        if isinstance(card_obj, dict) and key in card_obj:
            val = card_obj[key]
            break

    # lists like ["MAGE"] → take first
    if isinstance(val, (list, tuple)) and val:
        val = val[0]

    if not val:
        return None

    # strings/ints
    s = str(val).strip()
    if not s:
        return None
    # normalize Neutral-ish values
    if s.upper() in ("NEUTRAL", "NONE", "0"):
        return None
    return s

def _class_color_from_name(name: str | None) -> tuple[int,int,int]:
    if not name:
        return NEUTRAL_BG
    col = HERO_COLORS.get(str(name).upper())
    return col if col else NEUTRAL_BG

def class_color_for_card(card_obj) -> tuple[int,int,int]:
    return _class_color_from_name(_infer_card_class_name(card_obj))

def class_color_for_minion(minion_obj) -> tuple[int,int,int]:
    """
    Use the minion's original card to determine class color.
    If we can’t resolve, fall back to gray.
    """
    try:
        cid = getattr(minion_obj, "card_id", None)
        if cid and GLOBAL_GAME and cid in GLOBAL_GAME.cards_db:
            return class_color_for_card(GLOBAL_GAME.cards_db[cid])
    except Exception:
        pass
    return NEUTRAL_BG

def draw_card_frame(r: pygame.Rect, color_bg, *, card_obj=None, minion_obj=None, in_hand: bool,
                    override_cost: int | None = None, surface=None):
    if surface is None: surface = screen

    if card_obj is not None:
        color_bg = class_color_for_card(card_obj)
    elif minion_obj is not None:
        color_bg = class_color_for_minion(minion_obj)

    pygame.draw.rect(surface, color_bg, r, border_radius=12)

    if card_obj:
        cost_to_show = card_obj.cost if override_cost is None else int(override_cost)
        draw_cost_gem(r, cost_to_show, surface=surface)

        # Show only the printed text, no auto-added keywords
        body = (card_obj.text or "").strip()
        
        draw_text_box(r, body, max_lines=4, title=card_obj.name, font_body=RULE_FONT, surface=surface)

        draw_rarity_droplet(r, getattr(card_obj, "rarity", "Common"), surface=surface)

        if card_obj.type == "MINION":
            draw_minion_stats(
                r, card_obj.attack, card_obj.health, card_obj.health,
                base_attack=card_obj.attack, base_health=card_obj.health, surface=surface
            )
            draw_name_footer(r, card_obj.minion_type if card_obj.minion_type != "None" else "Neutral", surface=surface)
        elif card_obj.type == "WEAPON":
            draw_minion_stats(
                r, card_obj.attack, card_obj.health, card_obj.health,
                base_attack=card_obj.attack, base_health=card_obj.health, surface=surface
            )
            draw_name_footer(r, card_obj.type.capitalize(), surface=surface)
        elif card_obj.type in ["SPELL", "SECRET"]:
            draw_name_footer(r, card_obj.type.capitalize(), surface=surface)
        else:
            draw_name_footer(r, card_obj.type.capitalize(), surface=surface)

    elif minion_obj:
        draw_cost_gem(r, getattr(minion_obj, "cost", 0), surface=surface)
        kws = []
        # Show only the printed base text, no auto-added keywords
        body = (getattr(minion_obj, "base_text", "") or "").strip()
        
        draw_text_box(r, body, max_lines=4, title=minion_obj.name, font_body=RULE_FONT, surface=surface)
        draw_rarity_droplet(r, getattr(minion_obj, "rarity", "Common"), surface=surface)
        draw_minion_stats(
            r, minion_obj.attack, minion_obj.health, minion_obj.max_health,
            base_attack=getattr(minion_obj, "base_attack", minion_obj.attack),
            base_health=getattr(minion_obj, "base_health", minion_obj.max_health),
            surface=surface
        )
        draw_name_footer(r, minion_obj.minion_type if minion_obj.minion_type != "None" else "Neutral", surface=surface)

    if getattr(minion_obj, "divine_shield", False) and not getattr(minion_obj, "silenced", False):
        sx, sy = r.x + (CARD_W / 2) - 11, r.y
        badge = pygame.Rect(sx, sy, 22, 22)
        pygame.draw.ellipse(surface, (235, 200, 80), badge)
        pygame.draw.ellipse(surface, (30, 24, 10), badge, 2)
        p1 = (badge.centerx, badge.y + 5)
        p2 = (badge.x + 5, badge.y + 11)
        p3 = (badge.centerx, badge.bottom - 5)
        p4 = (badge.right - 5, badge.y + 11)
        pygame.draw.polygon(surface, (255, 245, 180), [p1, p2, p3, p4])

    if getattr(minion_obj, "silenced", False):
        draw_silence_overlay(r, surface=surface)
    if getattr(minion_obj, "frozen", False):
        draw_frozen_overlay(r, surface=surface)

def _deck_source_rect_for_pid(pid: int) -> pygame.Rect:
    """Where cards 'come from' visually."""
    if pid == 0:
        return pygame.Rect(W - CARD_W - 20, ROW_Y_HAND + CARD_H // 4, CARD_W, CARD_H)
    else:
        return pygame.Rect(W - CARD_W - 20, ROW_Y_ENEMY - 30, CARD_W, CARD_H)
def _retro_animate_missing_draws(g: Game, ev_list):
    """
    If the hand grew but we saw fewer CardDrawn events than the growth,
    enqueue 'play_move' animations for the missing draws.
    """
    if ev_list is None:
        ev_list = []

    # how many explicit CardDrawn we saw per player
    explicit = {0: 0, 1: 0}
    for e in ev_list:
        if getattr(e, "kind", "") == "CardDrawn":
            explicit[e.payload.get("player", 0)] += 1

    for pid in (0, 1):
        prev = LAST_HAND_COUNT.get(pid, 0)
        cur  = len(g.players[pid].hand)
        inc  = max(0, cur - prev)       # actual growth
        miss = max(0, inc - explicit.get(pid, 0))  # silent draws we must animate

        if miss <= 0:
            continue

        # Animate the last `miss` slots (rightmost new cards)
        src_rect = _deck_source_rect_for_pid(pid)
        hide_set = HIDDEN_HAND_INDICES_ME if pid == 0 else HIDDEN_HAND_INDICES_EN

        for k in range(miss):
            idx = cur - miss + k  # indices of the new cards at the end
            dst_rect = _hand_slot_rect_for(pid, idx, g)
            if dst_rect is None:
                continue

            # hide until the animation finishes
            hide_set.add(idx)
            def _unhide(i=idx, hs=hide_set):
                try: hs.remove(i)
                except KeyError: pass

            this_cid = g.players[pid].hand[idx] if pid == 0 else None

            ANIMS.push(AnimStep(
                "play_move",
                ANIM_DRAW_MS,
                {
                    "src": src_rect.copy(),
                    "dst": dst_rect.copy(),
                    "pid": pid,
                    "cid": this_cid,  # show true card for you; hidden back for enemy
                    "color": CARD_BG_HAND if pid == 0 else CARD_BG_EN,
                    "ease": "quart",
                },
                on_finish=_unhide
            ))

        # Update our record so we don’t re-animate
        LAST_HAND_COUNT[pid] = cur


def draw_layered_borders(r: pygame.Rect, *, taunt: bool, rush: bool, ready: bool):
    if taunt: pygame.draw.rect(screen, GREY, r, 3, border_radius=10)
    if rush:  pygame.draw.rect(screen, RED,  r.inflate(4, 4), 3, border_radius=12)
    if ready: pygame.draw.rect(screen, GREEN,r.inflate(10,10), 3, border_radius=16)

def _board_right_showcase_rect(who: int) -> pygame.Rect:
    """
    A neutral reveal spot on the board's right edge.
    Y is aligned to the corresponding player's row so it's obvious who burned it.
    """
    arena = battle_area_rect()
    x = arena.right - CARD_W - 16
    y = (ROW_Y_HAND if who == 0 else (ROW_Y_ENEMY - 30))
    return pygame.Rect(x, y, CARD_W, CARD_H)

def _animate_hand_card_play(i: int, cid: str, src_rect: pygame.Rect, dst_rect: pygame.Rect,
                            pid: int, label: str, on_finish: Callable | None):
    """
    Hide the hand slot (so the card doesn't appear twice), fly it out, then unhide and run on_finish.
    """
    hide_set = HIDDEN_HAND_INDICES_ME if pid == 0 else HIDDEN_HAND_INDICES_EN
    hide_set.add(i)

    def _cleanup_and_finish():
        # unhide regardless of success/failure
        try:
            hide_set.remove(i)
        except KeyError:
            pass
        if on_finish:
            on_finish()

    push_play_move_anim(src_rect, dst_rect, cid, pid=pid, label=label)
    # redirect the animation's on_finish to our wrapper
    ANIMS.blocking[-1].on_finish = _cleanup_and_finish


def animate_from_events(g: Game, ev_list: List[Any], hot_snapshot=None):
    """
    Queue small ambient animations based on events. Uses LAST_MINION_RECTS for
    things that disappear (death, discard, burn).
    """
    _retro_animate_missing_draws(g, ev_list)
    if not ev_list:
        return

    post = layout_board(g)  # for rectangles that exist after the event


    # --- NEW: compute per-player draw windows for this batch ---
    total_draws = {0: 0, 1: 0}
    seen_draws  = {0: 0, 1: 0}
    for e in ev_list:
        if getattr(e, "kind", "") == "CardDrawn":
            total_draws[e.payload.get("player", 0)] += 1

    # Useful targets
    arena = battle_area_rect()
    abyss_pt = (arena.centerx, H + 140)  # fall off screen

    # hero plate badges
    def _weapon_badge_rect(pid: int) -> pygame.Rect:
        face = post["face_me"] if pid == 0 else post["face_enemy"]
        cx, cy = face.x + 26, face.bottom - 18
        return _badge_rect_from_center(cx, cy, 14)

    def _my_secret_badge_slot() -> pygame.Rect | None:
        # pulse on the rightmost secret slot
        if not post["secrets_me"]:
            return None
        return post["secrets_me"][0][1]  # newest is placed right-most in draw order

    # index quick-lookup for minion id -> rect (post)
    rect_by_mid = {}
    for mid, r in post["my_minions"] + post["enemy_minions"]:
        rect_by_mid[mid] = r

    for e in ev_list:
        k = getattr(e, "kind", "")
        p = getattr(e, "payload", {}) or {}

        if k == "MinionDied":
            mid = p.get("minion")
            r = LAST_MINION_RECTS.get(mid)
            if r:
                ANIMS.push(AnimStep("fade_rect", 420, {"rect": r, "non_blocking": True, "layer": 1}))
        elif k == "CardDrawn":
            who = p.get("player", 0)

            # --- NEW: compute the exact slot this draw should land in ---
            # final hand size already includes all draws; back up by remaining
            final_size = len(g.players[who].hand)
            base = final_size - total_draws[who]        # index of the first new card
            dst_idx = base + seen_draws[who]           # index for THIS draw
            seen_draws[who] += 1

            # Build/lookup source & destination rects
            src_rect = _deck_source_rect_for_pid(who)

            # Destination: real slot for me; virtual top row for enemy
            dst = _hand_slot_rect_for(who, dst_idx, g)
            if dst is None:
                # Fallback so we don’t crash if layout changed mid-frame
                dst = pygame.Rect((W - CARD_W)//2, ROW_Y_HAND if who == 0 else ROW_Y_ENEMY - 30, CARD_W, CARD_H)

            # Hide that hand slot until animation completes
            hide_set = HIDDEN_HAND_INDICES_ME if who == 0 else HIDDEN_HAND_INDICES_EN
            hide_set.add(dst_idx)
            def _unhide(i=dst_idx, hs=hide_set):
                try: hs.remove(i)
                except KeyError: pass

            # Show the actual card for the player; back-of-card for enemy
            maybe_cid = g.players[who].hand[dst_idx] if (who == 0 and 0 <= dst_idx < len(g.players[who].hand)) else None
            ANIMS.push(AnimStep(
                "play_move",
                ANIM_DRAW_MS,
                {
                    "src": src_rect,
                    "dst": dst,
                    "pid": who,
                    "cid": maybe_cid,
                    "color": CARD_BG_HAND if who == 0 else CARD_BG_EN,
                    "ease": "quart",
                },
                on_finish=_unhide
            ))

        
        elif k == "CardDiscarded":
            who = p.get("player", 0)
            # animate from that side's hand region center to abyss
            # (we may not know exact card rect, so use a generic card slab near hand row)
            y = ROW_Y_HAND if who == 0 else ROW_Y_ENEMY - 30
            x = W//2
            src = pygame.Rect(x - CARD_W//2, y, CARD_W, CARD_H)
            ANIMS.push(AnimStep("to_abyss", 520, {"src": src, "dst": abyss_pt, "non_blocking": True}))

        elif k == "CardBurned":
            who = p.get("player", 0)

            # 1) Source: the deck on that side
            src_rect = _deck_source_rect_for_pid(who)

            # 2) Destination: board-right reveal spot
            dst_rect = _board_right_showcase_rect(who)

            # 3) Burned card id – show the ACTUAL card face (both sides)
            burned_cid = p.get("card") or p.get("card_id") or p.get("cid")
            if burned_cid is not None:
                burned_cid = str(burned_cid)

            # Fly deck → board-right, then ignite there
            def _ignite_at_dst(dst=dst_rect, cid=burned_cid, pid=who):
                ANIMS.push(AnimStep(
                    "burn_card",
                    900,  # total burn time; tweak to taste
                    {
                        "rect": dst.copy(),
                        "cid": cid,   # draw real face
                        "pid": pid,   # for eff. cost coloring if needed
                        "non_blocking": True,
                        "layer": 1
                    }
                ))

            ANIMS.push(AnimStep(
                "play_move",
                ANIM_DRAW_MS,
                {
                    "src": src_rect,
                    "dst": dst_rect,
                    "pid": who,
                    "cid": burned_cid,  # show the real card while flying in
                    "color": CARD_BG_HAND if who == 0 else CARD_BG_EN,
                    "ease": "quart",
                },
                on_finish=_ignite_at_dst
            ))


        elif k == "MinionSummoned":
            mid = p.get("minion")
            r = rect_by_mid.get(mid)
            if r:
                # Fancy materialization (ambient)
                ANIMS.push(AnimStep("summon_materialize", 420, {"rect": r, "non_blocking": True, "layer": 1}))
                # (optional) keep your old poof too for extra punch)
                # ANIMS.push(AnimStep("poof", 320, {"rect": r, "non_blocking": True, "layer": 1}))

        elif k == "SecretPlayed":
            # pulse your secret badge if it's you; otherwise enemy's strip
            pid = p.get("player", 0)
            if pid == 0:
                rr = _my_secret_badge_slot()
            else:
                # pulse on enemy hero strip near right side
                face = post["face_enemy"]
                rr = pygame.Rect(face.right - 26, face.y + 2, 22, 22)
            if rr:
                ANIMS.push(AnimStep("badge_pulse", 420, {"rect": rr, "non_blocking": True, "layer": 1}))

        elif k == "WeaponEquipped":
            pid = p.get("player", 0)
            rr = _weapon_badge_rect(pid)
            if rr:
                ANIMS.push(AnimStep("badge_pulse", 420, {"rect": rr, "non_blocking": True, "layer": 1}))

        elif k == "HeroTempAttack":
            pid = p.get("player", 0)
            rr = _weapon_badge_rect(pid)
            if rr:
                ANIMS.push(AnimStep("badge_pulse", 420, {"rect": rr, "non_blocking": True, "layer": 1}))
        elif k == "SpellHit":
            # you already call queue_spell_projectiles_from_events elsewhere,
            # but if you want to ensure it here:
            pass  # handled by queue_spell_projectiles_from_events

    # keep hand sizes up to date (idempotent)
    LAST_HAND_COUNT[0] = len(g.players[0].hand)
    LAST_HAND_COUNT[1] = len(g.players[1].hand)

def _animate_coin_entry_if_present(g: Game):
    """
    After mulligans, if a player has 'The Coin' (or similar bonus start card)
    already in hand, animate it flying in from the deck position so it doesn't just appear.
    """
    def _looks_like_coin(cid: str) -> bool:
        c = g.cards_db.get(cid)
        if not c: return False
        nm = (getattr(c, "name", "") or "").strip().lower()
        return cid.upper() == "THE_COIN" or nm == "the coin"

    for pid in (0, 1):
        hand = g.players[pid].hand
        for idx, cid in enumerate(hand):
            if _looks_like_coin(cid):
                src_rect = _deck_source_rect_for_pid(pid)
                dst_rect = _hand_slot_rect_for(pid, idx, g)
                if dst_rect is None:
                    continue
                hide_set = HIDDEN_HAND_INDICES_ME if pid == 0 else HIDDEN_HAND_INDICES_EN
                hide_set.add(idx)
                def _unhide(i=idx, hs=hide_set):
                    try: hs.remove(i)
                    except KeyError: pass

                ANIMS.push(AnimStep(
                    "play_move",
                    ANIM_DRAW_MS,
                    {
                        "src": src_rect.copy(),
                        "dst": dst_rect.copy(),
                        "pid": pid,
                        "cid": (cid if pid == 0 else None),
                        "color": CARD_BG_HAND if pid == 0 else CARD_BG_EN,
                        "ease": "quart",
                    },
                    on_finish=_unhide
                ))
                break  # only do one coin per player


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
    hp_x_enemy = hot["face_enemy"].right +  CRYSTAL_PAD
    hp_x_me    = hot["face_me"].right    + CRYSTAL_PAD
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
    for i, cid, r in hot["hand"]:
        # skip hidden slots (e.g., during mulligan fly-in)
        if i in HIDDEN_HAND_INDICES_ME:
            continue
        hit = scale_rect_about_center(r, 1.10, 0)
        if hit.collidepoint(mx, my):
            return i
    return None

def minion_ready_to_act(g: Game, m) -> bool:

    if getattr(m, "cant_attack", False):
        return False

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

    # --- NEW: apply per-card filtering (e.g., EXECUTE → damaged enemy only)
    filt = TARGET_FILTERS.get(cid)
    if filt:
        enemy_min = {m.id for m in enemy_all if m.id in enemy_min and filt(g, pid, m)}
        my_min    = {m.id for m in my_all    if m.id in my_min    and filt(g, pid, m)}

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
               dragging_card: Optional[Tuple[str, pygame.Rect]] = None,
               show_cast_zone: bool = False):
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

    hidden = ANIMS.peek_hidden_ids()
    # before draw_hero_plate(...)
    if "hero:1" not in hidden:
        draw_hero_plate(hot["face_enemy"], g.players[1], friendly=False)
    if "hero:0" not in hidden:
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
        if i in HIDDEN_HAND_INDICES_ME:
            continue
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
    if hover_idx is not None and hover_idx not in HIDDEN_HAND_INDICES_ME:
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

    # --- cast zone (when dragging a non-target spell/secret/weapon) ---
    if show_cast_zone:
        arena = battle_area_rect()
        glow = arena.inflate(12, 12)
        pygame.draw.rect(screen, (255, 255, 255), glow, 4, border_radius=16)
        pygame.draw.rect(screen, (230, 200, 90), arena, 3, border_radius=16)  # yellow rim
        msg = BIG.render("Release on board to CAST", True, WHITE)
        screen.blit(msg, msg.get_rect(center=arena.center))

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

def push_play_move_anim(src_rect: pygame.Rect, dst_rect: pygame.Rect, cid: str, pid: int, *, label: str = "", spawned_mid: int | None = None, color=None):
    if color is None:
        color = CARD_BG_EN if pid == 1 else CARD_BG_HAND
    try:
        eff = GLOBAL_GAME.get_effective_cost(pid, cid)
    except Exception:
        eff = None

    data = {
        "src": src_rect,
        "dst": dst_rect,
        "label": label,
        "color": color,
        "cid": cid,
        "pid": pid,
        "eff_cost": eff,    
    }
    if spawned_mid is not None:
        data["spawn_mid"] = spawned_mid
    ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS, data))


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

    def _draw_burn_card(self, step: AnimStep):
        """
        Show the card face at a fixed rect, then burn it away:
        - brief glow-in
        - subtle jitter/tilt
        - ember/smoke fade out
        - shrink & alpha to 0
        """
        rect: pygame.Rect = step.data["rect"]
        cid = step.data.get("cid")
        pid = int(step.data.get("pid", 0))
        t = step.raw_progress()  # 0..1 linear works well for burn timing

        # Lazy-build a cached face surface once (so the look stays stable)
        if "face_surf" not in step.data or step.data["face_surf"] is None:
            base = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
            try:
                cobj = GLOBAL_GAME.cards_db.get(cid)
                eff = None
                try:
                    eff = GLOBAL_GAME.get_effective_cost(pid, cid) if cid else None
                except Exception:
                    eff = getattr(cobj, "cost", 0) if cobj else 0
                draw_card_frame(
                    pygame.Rect(0, 0, CARD_W, CARD_H),
                    CARD_BG_HAND if pid == 0 else CARD_BG_EN,
                    card_obj=cobj,
                    in_hand=True,
                    override_cost=eff,
                    surface=base,
                )
            except Exception:
                pygame.draw.rect(base, (220, 120, 90), base.get_rect(), border_radius=12)
            step.data["face_surf"] = base

        surf = step.data["face_surf"]

        # Effects over time
        # Fade/scale
        alpha = int(255 * (1.0 - t))
        scale = 1.0 - 0.15 * t

        # Jitter/tilt (tiny, for heat shimmer)
        jitter_x = int(2 * math.sin(10 * t * math.pi))
        jitter_y = int(1 * math.sin(13 * t * math.pi))
        tilt_deg = 4.0 * math.sin(2 * math.pi * t)

        # Glow halo early, smoke late
        # Glow strength peaks ~t=0.2 then fades
        glow_strength = max(0.0, 1.0 - abs((t - 0.2) / 0.2))
        if glow_strength > 0.01:
            rad = int(max(rect.w, rect.h) * (0.6 + 0.1 * glow_strength))
            halo = pygame.Surface((rad*2, rad*2), pygame.SRCALPHA)
            pygame.draw.circle(halo, (255, 180, 60, int(160 * glow_strength)), (rad, rad), rad)
            screen.blit(halo, (rect.centerx - rad, rect.centery - rad))

        # Smoke wisps near the end
        if t > 0.45:
            wisp_alpha = int(140 * (t - 0.45) / 0.55)
            for i in range(3):
                ox = int((i - 1) * 12 + 6 * math.sin((t*3 + i) * 3.1))
                oy = int(-24 - 18 * i - 26 * (t - 0.45) * (1 + i * 0.3))
                r = pygame.Rect(0, 0, 22, 10)
                r.center = (rect.centerx + ox, rect.centery + oy)
                s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                pygame.draw.ellipse(s, (80, 80, 80, max(0, 180 - wisp_alpha)), s.get_rect())
                screen.blit(s, r)

        # Render face with scale/tilt/alpha
        w, h = int(surf.get_width() * scale), int(surf.get_height() * scale)
        face = pygame.transform.rotozoom(surf, tilt_deg, scale)
        face.set_alpha(alpha)
        rr = face.get_rect(center=(rect.centerx + jitter_x, rect.centery + jitter_y))
        screen.blit(face, rr.topleft)


    def _draw_impact_hold(self, step: AnimStep):
        # Draw a provided sprite at a fixed center with a little scale pop
        sprite = step.data.get("sprite")
        center = step.data.get("center")
        base_size = step.data.get("base_size", (CARD_W, CARD_H))
        t = step.raw_progress()  # raw here feels snappier for the pop
        # ease-in pop up to +10% then settle to +4%
        pop = 0.10 * smoothstep01(1.0 - abs(t*2 - 1)) + 0.04
        if sprite is None:
            w, h = int(base_size[0] * (1.0 + pop)), int(base_size[1] * (1.0 + pop))
            rr = pygame.Rect(0, 0, w, h); rr.center = center
            pygame.draw.rect(screen, (255,255,255), rr, border_radius=10)
            return
        surf = pygame.transform.smoothscale(sprite,
                                            (int(sprite.get_width() * (1.0 + pop)),
                                            int(sprite.get_height()* (1.0 + pop))))
        screen.blit(surf, surf.get_rect(center=center).topleft)

    def peek_hidden_ids(self) -> set:
        hidden = set()

        # Keep existing special case: hide the freshly spawned minion during play-in
        if self.blocking:
            step = self.blocking[0]
            if step.kind == "play_move" and step.data.get("spawn_mid"):
                hidden.add(step.data["spawn_mid"])
            # NEW: honor generic hide_id for any blocking step (hero/minion attacks etc.)
            hid = step.data.get("hide_id")
            if hid is not None:
                hidden.add(hid)

        # NEW: honor hide_id on ambient steps too (if any)
        for s in self.ambient:
            hid = s.data.get("hide_id")
            if hid is not None:
                hidden.add(hid)

        return hidden

    def _draw_summon_materialize(self, step: AnimStep):
        # Try rect first; if missing, try to resolve from a minion id
        rect = step.data.get("rect")
        if rect is None:
            mid = step.data.get("minion") or step.data.get("mid")
            if mid is not None:
                post = layout_board(GLOBAL_GAME)
                for coll in ("my_minions", "enemy_minions"):
                    for mmid, rr in post[coll]:
                        if mmid == mid:
                            rect = rr
                            # cache for subsequent frames
                            step.data["rect"] = rect
                            break
                    if rect is not None:
                        break

        if rect is None:
            # Nothing to draw this frame; keep the step alive until it times out
            return

        t = step.raw_progress()  # 0..1

        # radial glow
        alpha_glow = int(180 * (1.0 - t))
        glow_rad = int(max(rect.w, rect.h) * (0.6 + 0.5 * t))
        glow = pygame.Surface((glow_rad*2, glow_rad*2), pygame.SRCALPHA)
        pygame.draw.circle(glow, (255, 255, 255, alpha_glow), (glow_rad, glow_rad), glow_rad)
        screen.blit(glow, (rect.centerx - glow_rad, rect.centery - glow_rad))

        # golden ring
        ring_rad = int(max(rect.w, rect.h) * (0.35 + 0.55 * t))
        ring = pygame.Surface((ring_rad*2, ring_rad*2), pygame.SRCALPHA)
        pygame.draw.circle(ring, (230, 200, 90, int(200 * (1.0 - t))), (ring_rad, ring_rad), ring_rad, width=4)
        screen.blit(ring, (rect.centerx - ring_rad, rect.centery - ring_rad))

        # veil over the card
        veil = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        veil.fill((255, 255, 255, int(120 * (1.0 - t))))
        screen.blit(veil, (rect.x, rect.y))


    def _draw_hero_attack(self, step: AnimStep):
        src: pygame.Rect = step.data["src"]
        dst: pygame.Rect = step.data["dst"]

        # Build/keep a dedicated hero sprite once (never tied to card sizes)
        if "sprite" not in step.data or step.data["sprite"] is None:
            # Prefer a clean offscreen render of the hero plate to avoid capturing overlaps
            base = pygame.Surface((src.w, src.h), pygame.SRCALPHA)
            try:
                # Render the hero plate into `base` so it's stable during the whole anim
                # We just mirror what's on screen: same face_rect size/coloring.
                draw_hero_plate(src.copy(), GLOBAL_GAME.players[0] if src == layout_board(GLOBAL_GAME)["face_me"] else GLOBAL_GAME.players[1], friendly=(src == layout_board(GLOBAL_GAME)["face_me"]))
                # Fallback to snapshot if rendering fails (shouldn't)
                step.data["sprite"] = base.subsurface(pygame.Rect(0,0,src.w,src.h)).copy()
            except Exception:
                try:
                    step.data["sprite"] = screen.subsurface(src).copy()
                except Exception:
                    step.data["sprite"] = None

        t_raw = step.raw_progress()   # for alpha/shadow timing
        t = step.eased()              # for motion/scale

        # Parabolic path (gentle lift)
        x = lerp(src.centerx, dst.centerx, t)
        y = lerp(src.centery, dst.centery, t) - 28 * 4 * (t - t*t)

        # Uniform scale only (no width squash)
        scale = 1.0 + 0.10 * smoothstep01(1.0 - abs(t*2 - 1))
        if t > 0.9:
            scale *= 1.0 - 0.06 * smoothstep01((t - 0.9)/0.1)

        # Tiny tilt that switches sign mid-flight (adds energy, never distorts)
        # Peak ~8 degrees at mid-flight
        tilt = (1.0 - abs(t*2 - 1)) * 8.0
        # Nudge the sign so outbound leans forward, return leans backward
        if dst.centerx < src.centerx:
            tilt = -tilt

        # Subtle ground shadow (ellipse) under hero while airborne
        ground_y = lerp(src.centery, dst.centery, t)
        shadow_w = int(src.w * 0.95)
        shadow_h = max(6, int(src.h * 0.25 * (1.0 - (y - ground_y) / max(1, src.h))))
        sh_alpha = int(120 * (1.0 - abs(t*2 - 1)))
        if shadow_w > 0 and shadow_h > 0 and sh_alpha > 0:
            sh = pygame.Surface((shadow_w, shadow_h), pygame.SRCALPHA)
            pygame.draw.ellipse(sh, (0, 0, 0, sh_alpha), sh.get_rect())
            screen.blit(sh, sh.get_rect(center=(int(x), int(ground_y + src.h*0.35))).topleft)

        # Optional dimming of the origin/landing plate (already supported by your data flags)
        dim_allowed = step.data.get("dim", True)
        dim_rect = step.data.get("dim_rect", src) if dim_allowed else None
        if dim_rect is not None:
            alpha = max(0, min(255, int(140 * (1.0 - abs(t*2 - 1)))))
            shade = pygame.Surface((dim_rect.w, dim_rect.h), pygame.SRCALPHA, 32)
            shade.fill((0, 0, 0))
            shade.set_alpha(alpha)
            screen.blit(shade, (dim_rect.x, dim_rect.y))

        sprite = step.data["sprite"]
        if sprite is None:
            # Draw a neutral hero plate proxy (keeps aspect)
            w, h = int(src.w * scale), int(src.h * scale)
            rr = pygame.Rect(0, 0, w, h); rr.center = (int(x), int(y))
            pygame.draw.rect(screen, PLATE_BG, rr, border_radius=12)
            pygame.draw.rect(screen, PLATE_RIM, rr, 2, border_radius=12)
            return

        # Rotate + uniform scale without ever using CARD_W/H
        surf = pygame.transform.rotozoom(sprite, tilt, scale)
        r = surf.get_rect(center=(int(x), int(y)))
        screen.blit(surf, r.topleft)



    def _draw_play_move(self, step: AnimStep):
        src: pygame.Rect = step.data["src"]
        dst: pygame.Rect = step.data["dst"]

        # progress + path shape (unchanged)
        t = step.eased()
        x, y = arc_lerp(src, dst, t, height_px=60)

        # scale up a touch mid-flight, then tiny settle near the end
        s = 1.0 + 0.06 * smoothstep01(1.0 - abs(t*2 - 1))
        if t > 0.92:
            s *= 1.0 - 0.08 * smoothstep01((t - 0.92)/0.08)

        w, h = int(CARD_W * s), int(CARD_H * s)
        r = pygame.Rect(0, 0, w, h); r.center = (x, y)

        # --- NEW: draw the actual card instead of a subsurface snapshot ---
        cid = step.data.get("cid")
        pid = step.data.get("pid", 0)
        if cid:
            try:
                cobj = GLOBAL_GAME.cards_db[cid]
                eff = step.data.get("eff_cost")
                if eff is None:
                    try:
                        eff = GLOBAL_GAME.get_effective_cost(pid, cid)
                    except Exception:
                        eff = getattr(cobj, "cost", 0)

                # Render onto an offscreen surface AT NATIVE SIZE, then scale
                base = pygame.Surface((CARD_W, CARD_H), pygame.SRCALPHA)
                draw_card_frame(
                    pygame.Rect(0, 0, CARD_W, CARD_H),
                    CARD_BG_HAND,
                    card_obj=cobj,
                    in_hand=True,
                    override_cost=eff,
                    surface=base,          # <— IMPORTANT
                )
                surf = pygame.transform.smoothscale(base, (w, h)) if (w, h) != (CARD_W, CARD_H) else base
                screen.blit(surf, r.topleft)
                return
            except Exception:
                pass

        # --- Fallback (old behavior) ---
        color = step.data.get("color", CARD_BG_HAND)
        pygame.draw.rect(screen, color, r, border_radius=10)
        label = step.data.get("label", "")
        if label:
            screen.blit(FONT.render(label, True, WHITE), (r.x + 8, r.y + 8))

    def _draw_attack_dash(self, step: AnimStep):
        src: pygame.Rect = step.data["src"]
        dst: pygame.Rect = step.data["dst"]
        color = step.data.get("color", CARD_BG_MY)
        sprite = step.data.get("sprite")

        t = step.eased()
        x = lerp(src.centerx, dst.centerx, t)
        y = lerp(src.centery, dst.centery, t)

        # Use provided base size if present; else default to card size
        base_w, base_h = step.data.get("base_size", (CARD_W, CARD_H))

        stretch = 1.0 + 0.15 * smoothstep01(1.0 - abs(t*2 - 1))
        squash  = 1.0 - 0.10 * smoothstep01(max(0.0, t - 0.85)/0.15)
        w, h = int(base_w * stretch), int(base_h * squash)

        if sprite is not None:
            surf = pygame.transform.smoothscale(sprite, (w, h))
            rr = surf.get_rect(center=(int(x + 0.5), int(y + 0.5)))
            screen.blit(surf, rr.topleft)
        else:
            rr = pygame.Rect(0, 0, w, h); rr.center = (int(x + 0.5), int(y + 0.5))
            pygame.draw.rect(screen, color, rr, border_radius=10)


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
            if k == "fade_rect":       self._draw_fade_rect(step)
            elif k == "poof":          self._draw_poof(step)
            elif k == "to_abyss":      self._draw_to_abyss(step)
            elif k == "badge_pulse":   self._draw_badge_pulse(step)
            elif k == "spell_orbs":    self._draw_spell_orbs(step)
            elif k == "play_move":     self._draw_play_move(step)
            elif k == "attack_dash":   self._draw_attack_dash(step)
            elif k == "flash":         self._draw_flash(step)     # normally NB, but supported
            elif k == "think_pause":   pass                       # invisible timing gate
            elif k == "start_game":    self._draw_start_game(step)
            elif k == "banner":        self._draw_banner(step)
            elif k == "hero_attack":   self._draw_hero_attack(step)
            elif k == "summon_materialize": self._draw_summon_materialize(step)
            elif k == "burn_card":    self._draw_burn_card(step)
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
                if k == "fade_rect":       self._draw_fade_rect(s)
                elif k == "poof":          self._draw_poof(s)
                elif k == "to_abyss":      self._draw_to_abyss(s)
                elif k == "badge_pulse":   self._draw_badge_pulse(s)
                elif k == "spell_orbs":    self._draw_spell_orbs(s)
                elif k == "flash":       self._draw_flash(s)
                elif k == "banner":    self._draw_banner(s)
                elif k == "start_game":self._draw_start_game(s)
                elif k == "think_pause": pass
                elif k == "attack_dash": self._draw_attack_dash(s)
                elif k == "play_move":   self._draw_play_move(s)
                elif k == "summon_materialize": self._draw_summon_materialize(s)
                elif k == "burn_card":    self._draw_burn_card(s)
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
    def _draw_fade_rect(self, step: AnimStep):
        r: pygame.Rect = step.data["rect"]
        t = step.raw_progress()
        alpha = max(0, 255 - int(255 * t))
        scale = 1.0 - 0.15 * t
        rw, rh = int(r.w * scale), int(r.h * scale)
        rr = pygame.Rect(0, 0, rw, rh); rr.center = r.center
        s = pygame.Surface((rw, rh), pygame.SRCALPHA)
        pygame.draw.rect(s, (255, 255, 255, alpha), s.get_rect(), border_radius=10)
        screen.blit(s, rr.topleft)

    def _draw_poof(self, step: AnimStep):
        r: pygame.Rect = step.data["rect"]
        t = step.raw_progress()
        # expanding soft circle + inner flash
        rad = int(max(r.w, r.h) * (0.3 + 0.7 * t))
        alpha = int(180 * (1 - t))
        s = pygame.Surface((rad*2, rad*2), pygame.SRCALPHA)
        pygame.draw.circle(s, (255, 255, 255, alpha), (rad, rad), rad)
        pygame.draw.circle(s, (230, 200, 90, int(alpha*0.8)), (rad, rad), int(rad*0.6))
        screen.blit(s, (r.centerx - rad, r.centery - rad))

    def _draw_to_abyss(self, step: AnimStep):
        src: pygame.Rect = step.data["src"]
        dst_pt: tuple[int,int] = step.data["dst"]
        t = step.eased()
        x = lerp(src.centerx, dst_pt[0], t)
        y = lerp(src.centery, dst_pt[1], t) - 50 * (t - t*t)  # small arc
        scale = 1.0 - 0.25 * t
        alpha = int(255 * (1 - t))
        w, h = int(src.w * scale), int(src.h * scale)
        rr = pygame.Rect(0, 0, w, h); rr.center = (int(x), int(y))
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(s, (255, 255, 255, alpha), s.get_rect(), border_radius=10)
        screen.blit(s, rr.topleft)

    def _draw_badge_pulse(self, step: AnimStep):
        r: pygame.Rect = step.data["rect"]
        t = step.raw_progress()
        # scale up then back a bit
        if t < 0.5:
            s = 1.0 + 0.4 * (t / 0.5)
        else:
            s = 1.4 - 0.3 * ((t - 0.5) / 0.5)
        w, h = int(r.w * s), int(r.h * s)
        rr = pygame.Rect(0, 0, w, h); rr.center = r.center
        pygame.draw.rect(screen, (255, 255, 255), rr, 2, border_radius=10)

    def _draw_spell_orbs(self, step: AnimStep):
        src = step.data["src"]; dst = step.data["dst"]
        count = int(step.data.get("count", 5))
        radius = int(step.data.get("radius", 6))
        t = step.raw_progress()
        for i in range(count):
            # staggered progress per orb
            ti = clamp((t * 1.1) - (i * 0.06))
            x = lerp(src[0], dst[0], ti)
            y = lerp(src[1], dst[1], ti) - 25 * (ti - ti*ti)
            pygame.draw.circle(screen, (255,255,255), (int(x), int(y)), radius)


ANIMS = AnimQueue()

def enqueue_attack_anim(hot, attacker_mid: int, target_rect: pygame.Rect, enemy: bool, on_hit):
    coll = "enemy_minions" if enemy else "my_minions"
    src = None
    for mid, r in hot[coll]:
        if mid == attacker_mid:
            src = r
            break
    if src is None:
        return

    # NEW: snapshot the on-screen card (includes buffs, silenced overlay, frozen, etc.)
    try:
        sprite = screen.subsurface(src).copy()
    except Exception:
        sprite = None  # fallback

    def after_forward(attacker_mid=attacker_mid, coll=coll, target_rect=target_rect, sprite=sprite):
        try:
            on_hit()
        except Exception as e:
            print("on_hit error:", repr(e))
        post = layout_board(GLOBAL_GAME)
        if any(mid == attacker_mid for mid, _ in post[coll]):
            back_dst = None
            for mid, rr in post[coll]:
                if mid == attacker_mid:
                    back_dst = rr
                    break
            if back_dst:
                ANIMS.push(AnimStep(
                    "attack_dash",
                    ANIM_RETURN_MS,
                    {
                        "src": target_rect,
                        "dst": back_dst,
                        "color": CARD_BG_EN if enemy else CARD_BG_MY,
                        "sprite": sprite,
                        "base_size": (src.w, src.h),
                        "hide_id": attacker_mid,
                    }
                ))

    ANIMS.push(AnimStep(
        "attack_dash",
        ANIM_ATTACK_MS,
        {
            "src": src,
            "dst": target_rect,
            "color": CARD_BG_EN if enemy else CARD_BG_MY,
            "sprite": sprite,  # <-- forward leg uses snapshot too
            "base_size": (src.w, src.h),
            "hide_id": attacker_mid,
        },
        on_finish=after_forward
    ))


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

    try:
        hero_sprite = screen.subsurface(face_rect).copy()
    except Exception:
        hero_sprite = None

    def after_forward(pid=pid, tgt=target_rect):
        hold_ms = 0

        def after_hold():
            # apply hit
            try:
                on_hit()
            except Exception as e:
                print("on_hit error:", repr(e))
            post = layout_board(GLOBAL_GAME)
            back_dst = post["face_me"] if pid == 0 else post["face_enemy"]
            ANIMS.push(AnimStep(
                "hero_attack",
                ANIM_RETURN_MS,
                {
                    "src": tgt,
                    "dst": back_dst,
                    "sprite": hero_sprite,
                    "dim": False,
                    "ease": "back",
                    "hide_id": f"hero:{pid}",  # see note below
                }
            ))

        ANIMS.push(AnimStep(
            "impact_hold",
            hold_ms,
            {
                "center": target_rect.center,
                "sprite": hero_sprite,
                "base_size": (face_rect.w, face_rect.h),
                "hide_id": f"hero:{pid}",
            },
            on_finish=after_hold
        ))

    ANIMS.push(AnimStep(
        "hero_attack",
        ANIM_HERO_MS,
        {
            "src": face_rect,
            "dst": target_rect,
            "sprite": hero_sprite,
            "dim": True,
            "dim_rect": face_rect,
            "ease": "back",
            "hide_id": f"hero:{pid}",
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

        #ANIMS.push(AnimStep("spell_orbs", ANIM_SPELL_MS, {"src": src, "dst": dst, "count": 5, "radius": 7, "non_blocking": True}, on_finish=on_arrive))

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


def _hand_slot_rect_for(pid: int, index: int, g: Game) -> Optional[pygame.Rect]:
    """
    Destination rect of a given hand index for a player.
    - pid == 0 → use the real on-screen hand layout from layout_board(...)
    - pid == 1 → synthesize a stacked hand row near the enemy area
                 (we don't normally render enemy hand, but this keeps
                  their mulligan draw visuals off your side).
    """
    if pid == 0:
        post = layout_board(g)
        for i, _cid, r in post["hand"]:
            if i == index:
                return r
        return None

    # pid == 1 (enemy): build a virtual stacked hand row at the top
    # Keep it centered and slightly below the enemy name strip.
    n = len(g.players[1].hand)
    if not (0 <= index < n):
        return None
    rects = _stacked_hand_rects(n, ROW_Y_ENEMY - 30)
    return rects[index] if 0 <= index < len(rects) else None


def _mulligan_pick_count(g, pid: int) -> int:
    """
    Show up to 3 cards for the starting player; 4 for the player who goes second,
    but we clamp to their current hand size so we don't overreach the engine.
    """
    # If active_player == pid at game start → that pid goes first
    goes_first = (getattr(g, "active_player", 0) == pid)
    want = 3 if goes_first else 4
    return min(want, len(g.players[pid].hand))

def _mulligan_ai_should_keep(g, cid: str) -> bool:
    """
    Heuristic:
      - Keep MINION with printed cost 1–3.
      - Keep 0-cost flexible cards (optional sweetener).
      - Toss 5+ cost always.
      - Toss expensive spells (>3) by default.
    """
    c = g.cards_db[cid]
    t = getattr(c, "type", "").upper()
    cost = int(getattr(c, "cost", 0))

    if cost >= 5:
        return False
    if t == "MINION":
        return 1 <= cost <= 3
    if t == "SPELL":
        return cost <= 3
    # WEAPON/SECRET/ETC: keep if cheap
    return cost <= 3

def _mulligan_replace(g, pid: int, replace_indices: list[int]):
    """
    Return the selected cards to the deck, shuffle, and draw the same count.
    We keep it simple and deterministic:
      - Move selected (by index in *current* hand order snapshot) to the bottom of deck,
      - Shuffle deck,
      - Draw the same amount.
    """
    p = g.players[pid]

    if not replace_indices:
        return

    # Work on a snapshot of the hand so indices remain stable
    # as we pop and reinsert.
    replace_indices = sorted(set(replace_indices))
    original_hand = list(p.hand)

    to_replace: list[str] = []
    keep: list[str] = []
    for i, cid in enumerate(original_hand):
        if i in replace_indices:
            to_replace.append(cid)
        else:
            keep.append(cid)

    # Put replaced cards to bottom of deck
    for cid in to_replace:
        p.deck.append(cid)

    # Shuffle deck
    random.shuffle(p.deck)

    # New hand = kept + (draw N)
    draws = min(len(p.deck), len(to_replace))
    new_cards = [p.deck.pop(0) for _ in range(draws)]
    p.hand[:] = keep + new_cards

    # ---- Animate newly drawn cards into the hand ----
    # New cards are placed at the end of the hand (indices tail_start..tail_end)
    tail_start = len(keep)
    tail_end   = len(p.hand) - 1
    if draws > 0:
        post = layout_board(GLOBAL_GAME)
        # choose whose hide set
        hide_set = HIDDEN_HAND_INDICES_ME if pid == 0 else HIDDEN_HAND_INDICES_EN
        src_rect = _deck_source_rect_for_pid(pid)

        # mark these slots hidden until their animation finishes
        for idx in range(tail_start, tail_end + 1):
            hide_set.add(idx)

        # queue one animation per new card (right → slot)
        for idx in range(tail_start, tail_end + 1):
            # find the destination rect for this hand index
            dst_rect = None 
            dst_rect = _hand_slot_rect_for(pid, idx, GLOBAL_GAME)
            if dst_rect is None:
                continue  # safety

            this_cid = p.hand[idx] if idx < len(p.hand) else None
            def _unhide(i=idx, hs=hide_set):
                try:
                    hs.remove(i)
                except KeyError:
                    pass

            ANIMS.push(AnimStep(
                "play_move",
                ANIM_DRAW_MS,  # same timing as normal draws
                {
                    "src": src_rect.copy(),
                    "dst": dst_rect.copy(),
                    "pid": pid,
                    "cid": this_cid if pid == 0 else None,  # show real card for you; slab for enemy
                    "color": CARD_BG_HAND if pid == 0 else CARD_BG_EN,
                    "ease": "quart",
                },
                on_finish=_unhide
            ))

    # Optional: log
    add_log(f"{'You' if pid == 0 else 'AI'} mulliganed {len(to_replace)} card(s).")

def run_player_mulligan(g: Game) -> None:
    """
    Full-screen overlay before turn 1: show first N cards of your hand,
    allow toggling each to replace. Confirm with a button.
    """
    clock = pygame.time.Clock()
    N = _mulligan_pick_count(g, 0)
    if N <= 0: 
        return

    # we mulligan the *first N* hand cards to keep logic simple and fair
    hand_view = list(g.players[0].hand[:N])
    selected = set()  # indices 0..N-1 chosen to replace

    # precompute card rects (centered row, larger size)
    CARDW, CARDH = int(CARD_W * 1.25), int(CARD_H * 1.35)
    gap = 18
    total_w = N * CARDW + (N - 1) * gap
    start_x = (W - total_w) // 2
    row_y = H // 2 - CARDH // 2

    rects = [pygame.Rect(start_x + i * (CARDW + gap), row_y, CARDW, CARDH) for i in range(N)]
    confirm_rect = pygame.Rect(W//2 - 140, row_y + CARDH + 30, 130, 42)
    keep_rect     = pygame.Rect(W//2 + 10,  row_y + CARDH + 30, 130, 42)

    while True:
        clock.tick(60)

        # Dim background and draw board as context (optional)
        screen.fill(BG)
        hot_preview = layout_board(g)
        hot_preview["hand"] = []
        draw_board(g, hot_preview)  # background context
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 180))
        screen.blit(shade, (0, 0))

        title = BIG.render("Choose cards to REPLACE", True, WHITE)
        screen.blit(title, title.get_rect(center=(W//2, row_y - 36)))

        # Cards
        for i, (cid, r) in enumerate(zip(hand_view, rects)):
            pygame.draw.rect(screen, (28, 32, 40), r, border_radius=14)
            # draw the actual card onto an offscreen surface then scale
            base = pygame.Surface((CARD_W * 1.25, CARD_H * 1.25), pygame.SRCALPHA)
            draw_card_frame(
                pygame.Rect(0, 0, CARD_W * 1.25, CARD_H * 1.25),
                CARD_BG_HAND,
                card_obj=g.cards_db[cid],
                in_hand=True,
                override_cost=g.get_effective_cost(0, cid),
                surface=base,
            )
            surf = pygame.transform.smoothscale(base, (r.w, r.h))
            screen.blit(surf, r.topleft)

            # toggle overlay
            if i in selected:
                ov = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                ov.fill((210, 70, 70, 90))
                screen.blit(ov, r.topleft)
                x_txt = BIG.render("REPLACE", True, WHITE)
                screen.blit(x_txt, x_txt.get_rect(center=(r.centerx, r.bottom - 18)))

            # rim
            pygame.draw.rect(screen, (60, 90, 130), r, 2, border_radius=14)

        # Buttons
        pygame.draw.rect(screen, (80, 140, 240), confirm_rect, border_radius=10)
        pygame.draw.rect(screen, (120, 120, 120), keep_rect, border_radius=10)
        screen.blit(FONT.render("Confirm", True, WHITE), FONT.render("Confirm", True, WHITE).get_rect(center=confirm_rect.center))
        screen.blit(FONT.render("Keep All", True, WHITE), FONT.render("Keep All", True, WHITE).get_rect(center=keep_rect.center))

        hint = RULE_FONT.render("Click cards to toggle. Confirm to redraw selected.", True, WHITE)
        screen.blit(hint, hint.get_rect(center=(W//2, keep_rect.bottom + 20)))

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                # ESC = keep all
                _mulligan_replace(g, 0, [])
                return
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                # cards
                for i, r in enumerate(rects):
                    if r.collidepoint(mx, my):
                        if i in selected: selected.remove(i)
                        else: selected.add(i)
                        break
                # buttons
                if confirm_rect.collidepoint(mx, my):
                    _mulligan_replace(g, 0, list(selected))
                    return
                if keep_rect.collidepoint(mx, my):
                    _mulligan_replace(g, 0, [])
                    return

def run_ai_mulligan(g: Game) -> None:
    N = _mulligan_pick_count(g, 1)
    if N <= 0:
        return

    # Evaluate first N cards of AI hand
    ai_hand = list(g.players[1].hand[:N])
    replace_indices = []
    for i, cid in enumerate(ai_hand):
        if not _mulligan_ai_should_keep(g, cid):
            replace_indices.append(i)

    _mulligan_replace(g, 1, replace_indices)


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

# refresh last-known rects for minions
def _update_last_minion_rects(hot):
    # Keep only ids we saw last frame to avoid unbounded growth
    seen = {}
    for mid, r in hot["my_minions"] + hot["enemy_minions"]:
        seen[mid] = r.copy()
    LAST_MINION_RECTS.clear()
    LAST_MINION_RECTS.update(seen)

def main():
    global GLOBAL_GAME
    global SHOW_ENEMY_HAND
    global DEBUG_BTN_RECT
    clock = pygame.time.Clock()
    g = start_game()
    GLOBAL_GAME = g

    # --- MULLIGAN PHASE (player first so UI is visible, then AI) ---
    run_player_mulligan(g)
    run_ai_mulligan(g)

    
    # Initialize hand counters now that starting hands are settled
    LAST_HAND_COUNT[0] = len(g.players[0].hand)
    LAST_HAND_COUNT[1] = len(g.players[1].hand)

    # If The Coin (or similar) is already in hand, make it fly in once
    _animate_coin_entry_if_present(g)
    ev = g.start_first_turn()
    animate_from_events(g, ev)
    
    
    # small banner for feedback
    ANIMS.push(AnimStep("banner", 800, {"text": "Mulligan complete"}))

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
        _update_last_minion_rects(hot)

        #draw_headers(g)
        draw_action_log()
        # 1) get IDs to hide (no drawing yet)
        hidden = ANIMS.peek_hidden_ids()

        # 2) draw the board first (so the arena is underneath)
        # compute dragging preview rect if any
        drag_preview = None
        show_cast_zone = False
        if dragging_from_hand is not None:
            _, cid_drag, _r0 = dragging_from_hand
            mx, my = pygame.mouse.get_pos()
            dx, dy = drag_offset
            drag_rect = pygame.Rect(mx - dx, my - dy, CARD_W, CARD_H)
            drag_preview = (cid_drag, drag_rect)

            # if we are dragging a non-minion (non-target spell/secret/weapon), show cast zone
            cobj_drag = g.cards_db[cid_drag]
            if getattr(cobj_drag, "type", "").upper() != "MINION" and card_is_non_target_cast(g, 0, cid_drag):
                show_cast_zone = True

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
            dragging_card=drag_preview,
            show_cast_zone=show_cast_zone,
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

        # ===================== AI TURN =====================
        if g.active_player == 1:
            if not ANIMS.busy():
                def decide():
                    def schedule_if_ai_turn():
                        if g.active_player == 1:
                            ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=decide))

                    queued_any = False

                    # 1) Try hero attack if ready
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
                            #schedule_if_ai_turn()

                        enqueue_hero_attack_anim(before, pid=1, target_rect=tr, on_hit=on_hit)
                        queued_any = True

                    else:
                        # 2) Otherwise use AI policy (play/attack/power)
                        result = None
                        try:
                            result = pick_best_action(g, 1)
                        except Exception:
                            result = None

                        if not result:
                            # 3) Try hero power (conservative helper), else end turn
                            def try_power_then_end():
                                try:
                                    from ai import maybe_use_hero_power
                                    ev = maybe_use_hero_power(g, 1)
                                except Exception:
                                    ev = []
                                if ev:
                                    log_events(ev, g)
                                    queue_spell_projectiles_from_events(g.active_player, ev)
                                    animate_from_events(g, ev)
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
                                if len(act) == 5:
                                    _, idx, tp, tm, bp = act
                                else:
                                    _, idx, tp, tm = act
                                    bp = None
                                cid = g.players[1].hand[idx]
                                src = pygame.Rect(W // 2 - CARD_W // 2, 20, CARD_W, CARD_H)

                                def do_on_finish(i=idx, tpp=tp, tmm=tm):
                                    try:
                                        ev = g.play_card(1, i, target_player=tpp, target_minion=tmm, insert_at=bp)
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        flash_from_events(g, ev)
                                    except IllegalAction:
                                        pass
                                    schedule_if_ai_turn()

                                dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ENEMY, CARD_W, CARD_H)
                                ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}))

                                push_play_move_anim(src, dst, cid, pid=1, label=db[cid].name)
                                ANIMS.blocking[-1].on_finish = do_on_finish

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
                                    #schedule_if_ai_turn()

                                enqueue_attack_anim(before, attacker_mid=aid, target_rect=tr, enemy=True, on_hit=on_hit)
                                queued_any = True

                            elif kind == 'power':
                                # NEW: execute the exact hero power and target picked by the planner
                                _, pwr_pid, tp, tm = act

                                def on_finish(pwr_pid=pwr_pid, tp=tp, tm=tm):
                                    try:
                                        ev = g.use_hero_power(pwr_pid, target_player=tp, target_minion=tm)
                                        log_events(ev, g)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        flash_from_events(g, ev)
                                    except IllegalAction:
                                        pass
                                    if g.active_player == 1:
                                        ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=decide))

                                ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=on_finish))
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
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        flash_from_events(g, ev)
                                        if g.active_player == 1:
                                            ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=decide))
                                        return
                                    try:
                                        ev2 = g.end_turn(1)
                                        log_events(ev2, g)
                                        queue_spell_projectiles_from_events(g.active_player, ev2)
                                        animate_from_events(g, ev2)
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
                                queue_spell_projectiles_from_events(g.active_player, ev2)
                                animate_from_events(g, ev2)
                            except IllegalAction:
                                add_log("[AI] Failsafe: could not end turn.")
                        ANIMS.push(AnimStep("think_pause", 200, {}, on_finish=_force_end))

                # IMPORTANT: only schedule the first think
                ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=decide))

            # Drain events while AI acts
            for event in pygame.event.get():
                if event.type == pygame.QUIT: RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: RUNNING = False

        # ===================== YOUR TURN =====================
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
                            queue_spell_projectiles_from_events(g.active_player, ev)
                            animate_from_events(g, ev)
                            ANIMS.push(AnimStep("banner", 700, {"text": "End Turn"}))
                        except IllegalAction:
                            pass
                        selected_attacker = None
                        waiting_target_for_play = None
                        selected_hero = False
                        hilite_enemy_min.clear(); hilite_my_min.clear()
                        hilite_enemy_face = False; hilite_my_face = False
                        continue

                    # Select hero attacker
                    if (waiting_target_for_play is None
                        and waiting_target_for_power is None
                        and hot["face_me"].collidepoint(mx, my)
                        and hero_ready_to_act(g, 0)):
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
                                queue_spell_projectiles_from_events(g.active_player, ev)
                                animate_from_events(g, ev)
                            except IllegalAction:
                                pass
                            waiting_target_for_power = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            selected_attacker = None       # <-- add
                            selected_hero = False          # <-- add
                            continue

                        # My face?
                        if m_face and my_face_rect(hot).collidepoint(mx, my):
                            try:
                                ev = g.use_hero_power(0, target_player=0)
                                log_events(ev, g)
                                queue_spell_projectiles_from_events(g.active_player, ev)
                                animate_from_events(g, ev)
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
                                    queue_spell_projectiles_from_events(g.active_player, ev)
                                    animate_from_events(g, ev)
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
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
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
                                waiting_target_for_play = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                selected_attacker = None     # <-- add
                                selected_hero = False        # <-- add
                                add_log("Board is full. You can't play more minions.")
                                return

                            slot_rect = insertion_slots_for_my_row(g, battle_area_rect())[slot_idx]
                            dst = pygame.Rect(slot_rect.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                            def on_finish(i=idx, tp=target_player, tm=target_minion, sl=slot_idx):
                                try:
                                    ev = g.play_card(0, i, insert_at=sl, target_player=tp, target_minion=tm)
                                    log_events(ev, g)
                                    apply_post_summon_hooks(g, ev)
                                    queue_spell_projectiles_from_events(g.active_player, ev)
                                    animate_from_events(g, ev)
                                    flash_from_events(g, ev)
                                except IllegalAction:
                                    pass
                            
                            _animate_hand_card_play(idx, cid, src_rect, dst, 0, db[cid].name, on_finish)

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

                        waiting_target_for_play = None
                        hilite_enemy_min.clear(); hilite_my_min.clear()
                        hilite_enemy_face = False; hilite_my_face = False
                        continue

                    if waiting_target_for_play is not None and waiting_target_for_play[0] == "__PENDING_BC__":
                        handled = False

                        if hilite_enemy_face and enemy_face_rect(hot).collidepoint(mx, my):
                            try:
                                ev = g.resolve_pending_battlecry(0, target_player=1)
                                log_events(ev, g)
                                queue_spell_projectiles_from_events(g.active_player, ev)
                                animate_from_events(g, ev)
                                flash_from_events(g, ev)
                            except IllegalAction: pass
                            handled = True

                        elif hilite_my_face and my_face_rect(hot).collidepoint(mx, my):
                            try:
                                ev = g.resolve_pending_battlecry(0, target_player=0)
                                log_events(ev, g)
                                queue_spell_projectiles_from_events(g.active_player, ev)
                                animate_from_events(g, ev)
                                flash_from_events(g, ev)
                            except IllegalAction: pass
                            handled = True

                        if not handled:
                            for mid, r in hot["enemy_minions"]:
                                if r.collidepoint(mx, my) and mid in hilite_enemy_min:
                                    try:
                                        ev = g.resolve_pending_battlecry(0, target_minion=mid)
                                        log_events(ev, g)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        flash_from_events(g, ev)
                                    except IllegalAction: pass
                                    handled = True
                                    break

                        if not handled:
                            for mid, r in hot["my_minions"]:
                                if r.collidepoint(mx, my) and mid in hilite_my_min:
                                    try:
                                        ev = g.resolve_pending_battlecry(0, target_minion=mid)
                                        log_events(ev, g)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        flash_from_events(g, ev)
                                    except IllegalAction: pass
                                    handled = True
                                    break

                        if handled:
                            waiting_target_for_play = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            selected_attacker = None     # <-- add
                            selected_hero = False        # <-- add
                        continue

                    # If selecting target for a spell
                    if waiting_target_for_play is not None:
                        idx, cid, src_rect = waiting_target_for_play
                        enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)

                        if enemy_face_ok and enemy_face_rect(hot).collidepoint(mx, my):
                            def on_finish(i=idx):
                                try:
                                    ev = g.play_card(0, i, target_player=1)
                                    log_events(ev, g)
                                    apply_post_summon_hooks(g, ev)
                                    queue_spell_projectiles_from_events(g.active_player, ev)
                                    animate_from_events(g, ev)
                                    #enqueue_flash(enemy_face_rect(layout_board(g)))
                                except IllegalAction: pass
                            dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ME, CARD_W, CARD_H)
                            _animate_hand_card_play(idx, cid, src_rect, dst, 0, db[cid].name, on_finish)
                            waiting_target_for_play = None
                            selected_attacker = None     # <-- add
                            selected_hero = False        # <-- add
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            continue

                        if my_face_ok and my_face_rect(hot).collidepoint(mx, my):
                            def on_finish(i=idx):
                                try:
                                    ev = g.play_card(0, i, target_player=0)
                                    log_events(ev, g)
                                    
                                    apply_post_summon_hooks(g, ev)
                                    queue_spell_projectiles_from_events(g.active_player, ev)
                                    animate_from_events(g, ev)
                                    
                                    #enqueue_flash(my_face_rect(layout_board(g)))
                                except IllegalAction: pass
                            dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ME, CARD_W, CARD_H)
                            _animate_hand_card_play(idx, cid, src_rect, dst, 0, db[cid].name, on_finish)
                            waiting_target_for_play = None
                            selected_attacker = None     # <-- add
                            selected_hero = False        # <-- add
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            continue

                        targeted = False
                        for mid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my) and mid in enemy_mins:
                                def on_finish(i=idx, mid_target=mid, r=r):
                                    try:
                                        ev = g.play_card(0, i, target_minion=mid_target)
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        #enqueue_flash(r)
                                    except IllegalAction: pass

                                _animate_hand_card_play(idx, cid, src_rect, r, 0, db[cid].name, on_finish)

                                waiting_target_for_play = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                targeted = True
                                break
                        if targeted: continue

                        for mid, r in hot["my_minions"]:
                            if r.collidepoint(mx, my) and mid in my_mins:
                                def on_finish(i=idx, mid_target=mid, r=r):
                                    try:
                                        ev = g.play_card(0, i, target_minion=mid_target)
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        #enqueue_flash(r)
                                    except IllegalAction: pass
                                _animate_hand_card_play(idx, cid, src_rect, r, 0, db[cid].name, on_finish)

                                waiting_target_for_play = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                break
                        continue

                    # Click hero power button
                    if hot["hp_me"].collidepoint(mx, my) and g.active_player == 0 and can_use_hero_power(g, 0):
                        spec = g.players[0].hero.power.targeting.lower()
                        if spec in ("none", "enemy_face"):
                            try:
                                ev = g.use_hero_power(0)
                                log_events(ev, g)
                                post = layout_board(g)
                                queue_spell_projectiles_from_events(g.active_player, ev)
                                animate_from_events(g, ev)
                                #if spec == "enemy_face":
                                    #enqueue_flash(enemy_face_rect(post))
                                
                            except IllegalAction:
                                pass
                            selected_attacker = None  
                            selected_hero = False  
                        else:
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
                            if not card_is_playable_now(g, 0, cid):
                                add_log("You can't play that right now.")
                                break

                            card_type = getattr(cobj, "type", "").upper()

                            # MINION → drag to a slot (existing behavior)
                            if g.active_player == 0 and card_type == "MINION" and len(g.players[0].board) < 7:
                                dragging_from_hand = (i, cid, r.copy())
                                dx, dy = mx - r.x, my - r.y
                                drag_offset = (dx, dy)
                                dragging_pos = (mx, my)
                                slots = insertion_slots_for_my_row(g, battle_area_rect())
                                hover_slot_index = slot_index_at_point(slots, mx, my)
                                started_drag = True

                            else:
                                # Determine if this should be a DRAG-TO-CAST card
                                if card_is_non_target_cast(g, 0, cid):
                                    # Start dragging to the board (cast zone)
                                    dragging_from_hand = (i, cid, r.copy())
                                    dx, dy = mx - r.x, my - r.y
                                    drag_offset = (dx, dy)
                                    dragging_pos = (mx, my)
                                    hover_slot_index = None
                                    started_drag = True

                                else:
                                    # TARGETED spell → show targeting highlights (existing)
                                    enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)
                                    if enemy_mins or my_mins or enemy_face_ok or my_face_ok:
                                        waiting_target_for_play = (i, cid, r.copy())
                                        hilite_enemy_min = set(enemy_mins)
                                        hilite_my_min = set(my_mins)
                                        hilite_enemy_face = enemy_face_ok
                                        hilite_my_face = my_face_ok
                                        selected_attacker = None
                                        selected_hero = False
                                    else:
                                        # (Very rare) truly no-target but not covered above → fall back to drag-to-cast
                                        dragging_from_hand = (i, cid, r.copy())
                                        dx, dy = mx - r.x, my - r.y
                                        drag_offset = (dx, dy)
                                        dragging_pos = (mx, my)
                                        hover_slot_index = None
                                        started_drag = True
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
                                selected_hero = False 
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
                                def on_hit(rect=r, tgt_mid=emid):
                                    try:
                                        ev = g.hero_attack(0, target_minion=tgt_mid)
                                        log_events(ev, g)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        #enqueue_flash(rect)
                                    except IllegalAction:
                                        return
                                enqueue_hero_attack_anim(hot, pid=0, target_rect=r, on_hit=on_hit)
                                did = True
                                break
                        if did:
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
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                    except IllegalAction:
                                        pass
                                enqueue_attack_anim(hot, attacker_mid=selected_attacker, target_rect=r, enemy=False, on_hit=on_hit)
                                selected_attacker = None
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                                did = True
                                break

                        # NEW: minion → face attack
                        if not did and hilite_enemy_face and enemy_face_rect(hot).collidepoint(mx, my):
                            def on_hit(attacker=selected_attacker):
                                try:
                                    ev = g.attack(0, attacker, target_player=1)
                                    log_events(ev, g)
                                    queue_spell_projectiles_from_events(g.active_player, ev)
                                    animate_from_events(g, ev)
                                except IllegalAction:
                                    pass
                            enqueue_attack_anim(hot, attacker_mid=selected_attacker, target_rect=enemy_face_rect(hot), enemy=False, on_hit=on_hit)
                            selected_attacker = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False
                            continue
                    if selected_hero and hilite_enemy_face and enemy_face_rect(hot).collidepoint(mx, my):
                        def on_hit():
                            try:
                                ev = g.hero_attack(0, target_player=1)
                                log_events(ev, g)
                                queue_spell_projectiles_from_events(g.active_player, ev)
                                animate_from_events(g, ev)
                                #enqueue_flash(enemy_face_rect(layout_board(g)))
                            except IllegalAction:
                                return
                        enqueue_hero_attack_anim(hot, pid=0, target_rect=enemy_face_rect(hot), on_hit=on_hit)
                        selected_hero = False
                        hilite_enemy_min.clear(); hilite_enemy_face = False
                        continue

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    mx, my = event.pos

                    # Priority: cancel selection if any
                    if selected_attacker is not None or waiting_target_for_play is not None or waiting_target_for_power is not None or selected_hero :
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

                        cobj = g.cards_db[cid]
                        ctype = getattr(cobj, "type", "").upper()

                        # MINION dropping (existing behavior)
                        if ctype == "MINION":
                            slots = insertion_slots_for_my_row(g, battle_area_rect())
                            slot_idx = slot_index_at_point(slots, mx, my)
                            if slot_idx is None or len(g.players[0].board) >= 7:
                                hover_slot_index = None
                                continue

                            need = (g.cards_db.get("_TARGETING", {}).get(cid, "none") or "none").lower()

                            if need == "none":
                                slot_rect = slots[slot_idx]
                                dst = pygame.Rect(slot_rect.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                                def on_finish(i=idx):
                                    try:
                                        ev = g.play_card(0, i, insert_at=slot_idx)
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        flash_from_events(g, ev)
                                    except IllegalAction:
                                        pass

                                _animate_hand_card_play(idx, cid, src_rect, dst, 0, db[cid].name, on_finish)
                                hover_slot_index = None
                                continue
                            else:
                                enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)
                                any_targets = bool(enemy_mins or my_mins or enemy_face_ok or my_face_ok)
                                if any_targets:
                                    waiting_target_for_play = ("__PENDING_MINION__", idx, cid, src_rect, slot_idx)
                                    hilite_enemy_min = set(enemy_mins)
                                    hilite_my_min = set(my_mins)
                                    hilite_enemy_face = enemy_face_ok or (need in ("any_character", "enemy_character"))
                                    hilite_my_face = my_face_ok or (need in ("any_character", "friendly_character"))
                                    selected_attacker = None
                                    selected_hero = False
                                    hover_slot_index = slot_idx
                                    continue
                                else:
                                    slot_rect = slots[slot_idx]
                                    dst = pygame.Rect(slot_rect.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                                    def on_finish(i=idx, sl=slot_idx):
                                        try:
                                            ev = g.play_card(0, i, insert_at=sl)
                                            log_events(ev, g)
                                            apply_post_summon_hooks(g, ev)
                                            queue_spell_projectiles_from_events(g.active_player, ev)
                                            animate_from_events(g, ev)
                                            flash_from_events(g, ev)
                                        except IllegalAction:
                                            pass

                                    _animate_hand_card_play(idx, cid, src_rect, dst, 0, db[cid].name, on_finish)
                                    hover_slot_index = None
                                    continue

                        # NON-MINION (Spell/Secret/Weapon) dropping → must drop on arena to cast
                        else:
                            arena = battle_area_rect()
                            if not card_is_non_target_cast(g, 0, cid):
                                # safety: if this was a targeted spell we shouldn't be here,
                                # but just in case, do nothing (user must click to target).
                                continue

                            if arena.collidepoint(mx, my):
                                # Animate into a nice board-ish destination (center bottom of arena)
                                dst = pygame.Rect(arena.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                                def on_finish(i=idx):
                                    try:
                                        ev = g.play_card(0, i)   # no targets
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        flash_from_events(g, ev)
                                    except IllegalAction:
                                        pass

                                _animate_hand_card_play(idx, cid, src_rect, dst, 0, db[cid].name, on_finish)
                            else:
                                # dropped outside the board → cancel (do nothing)
                                pass
                            continue

                    if dragging_from_hand is not None:
                        mx, my = event.pos
                        idx, cid, src_rect = dragging_from_hand
                        dragging_from_hand = None
                        slots = insertion_slots_for_my_row(g, battle_area_rect())
                        slot_idx = slot_index_at_point(slots, mx, my)
                        if slot_idx is None or len(g.players[0].board) >= 7:
                            hover_slot_index = None
                            continue

                        need = (g.cards_db.get("_TARGETING", {}).get(cid, "none") or "none").lower()

                        if need == "none":
                            slot_rect = slots[slot_idx]
                            dst = pygame.Rect(slot_rect.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                            def on_finish(i=idx):
                                try:
                                    ev = g.play_card(0, i, insert_at=slot_idx)
                                    log_events(ev, g)
                                    apply_post_summon_hooks(g, ev)
                                    queue_spell_projectiles_from_events(g.active_player, ev)
                                    animate_from_events(g, ev)
                                    flash_from_events(g, ev)
                                except IllegalAction:
                                    pass

                            _animate_hand_card_play(idx, cid, src_rect, dst, 0, db[cid].name, on_finish)
                            selected_attacker = None    # <-- add
                            selected_hero = False       # <-- add
                            hover_slot_index = None
                            continue
                        else:
                            enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_card(g, cid, pid=0)
                            any_targets = bool(enemy_mins or my_mins or enemy_face_ok or my_face_ok)
                            if any_targets:
                                waiting_target_for_play = ("__PENDING_MINION__", idx, cid, src_rect, slot_idx)
                                hilite_enemy_min = set(enemy_mins)
                                hilite_my_min = set(my_mins)
                                hilite_enemy_face = enemy_face_ok or (need in ("any_character", "enemy_character"))
                                hilite_my_face = my_face_ok or (need in ("any_character", "friendly_character"))
                                selected_attacker = None
                                selected_hero = False
                                hover_slot_index = slot_idx
                                continue
                            else:
                                slot_rect = slots[slot_idx]
                                dst = pygame.Rect(slot_rect.centerx - CARD_W // 2, ROW_Y_ME, CARD_W, CARD_H)

                                def on_finish(i=idx, sl=slot_idx):
                                    try:
                                        ev = g.play_card(0, i, insert_at=sl)
                                        log_events(ev, g)
                                        apply_post_summon_hooks(g, ev)
                                        queue_spell_projectiles_from_events(g.active_player, ev)
                                        animate_from_events(g, ev)
                                        flash_from_events(g, ev)
                                    except IllegalAction:
                                        pass

                                _animate_hand_card_play(idx, cid, src_rect, dst, 0, db[cid].name, on_finish)
                                selected_attacker = None    # <-- add
                                selected_hero = False       # <-- add
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