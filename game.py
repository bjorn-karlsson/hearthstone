import pygame
import sys
from typing import Optional, Tuple, List, Dict, Any
import random

from engine import Game, load_cards_from_json, IllegalAction
from ai import pick_best_action

pygame.init()
# Fullscreen @ desktop resolution
screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
W, H = screen.get_size()
pygame.display.set_caption("Python Card Battler (Animated-Locked + Targets)")

FONT = pygame.font.SysFont(None, 22)
BIG  = pygame.font.SysFont(None, 32)
RULE_FONT = pygame.font.SysFont(None, 18)  # smaller for rules text


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

RARITY_COLORS = {
    "COMMON":     (235, 235, 235),  # white
    "RARE":       (80, 140, 240),   # blue
    "EPIC":       (165, 95, 210),   # purple
    "LEGENDARY":  (255, 140, 20),   # orange
}

# Layout
CARD_W, CARD_H = 125, 200   # bigger cards so text fits
MARGIN = 12                 # gap between cards
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
AI_THINK_MS     = 250

# --------- Randomized starter deck ----------
def make_starter_deck(db, seed=None):
    rng = random.Random(seed)

    # What you'd *like* to include:
    desired = [
        # 1-cost
        "LEPER_GNOME", "CHARGING_BOAR", "SHIELD_BEARER", "BLESSING_OF_MIGHT_LITE", "GIVE_TAUNT",
        # 2-cost
        "RIVER_CROCOLISK", "KOBOLD_PING", "RUSHER", "NERUBIAN_EGG", "HOLY_LIGHT",
        # 3-cost
        "TAUNT_BEAR", "WOLFRIDER", "EARTHEN_RING", "HARVEST_GOLEM", "ARCANE_MISSILES_LITE",
        "CHARGE_RUSH_2_2",
        # 4-cost
        "CHILLWIND_YETI", "FIREBALL_LITE", "BLESSING_OF_KINGS_LITE",
        "POLYMORPH_LITE", "ARCANE_INTELLECT_LITE", "ARCANE_INTELLECT",
        # 5+ cost
        "CONSECRATION_LITE", "BOULDERFIST_OGRE", "FLAMESTRIKE_LITE", "RAISE_WISPS", "FERAL_SPIRIT_LITE",
        "MUSTER_FOR_BATTLE_LITE", "SILENCE_LITE", "GIVE_CHARGE", "GIVE_RUSH", "TAUNT_BEAR", "LEGENDARY_LEROY_JENKINS"
    ]

    #desired = ["MUSTER_FOR_BATTLE_LITE"]  * 30

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
db = load_cards_from_json("cards.json")
STARTER_DECK_PLAYER = make_starter_deck(db, random.randint(1, 5000000))
STARTER_DECK_AI = make_starter_deck(db, random.randint(1, 50000))

# ---------- Drawing helpers (reworked cards) ----------

def draw_rarity_droplet(r: pygame.Rect, rarity: Optional[str]):
    """Small gem centered at bottom of the card."""
    if not rarity:
        rarity = "COMMON"
    key = str(rarity).upper()
    color = RARITY_COLORS.get(key, RARITY_COLORS[key])

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

def draw_text_box(r: pygame.Rect, text: str, max_lines: int, font=RULE_FONT):
    # Top padding
    top_pad = 45

    # Reserve bottom area: name footer + stats + gaps
    name_h  = 22
    stats_h = 28
    gap     = 4
    bottom_reserved = name_h + stats_h + gap + 6

    box = pygame.Rect(r.x+10, r.y+top_pad, r.w-20, r.h - top_pad - bottom_reserved)
    pygame.draw.rect(screen, (28, 28, 34), box, border_radius=8)

    lines = wrap_text(text, font, box.w-12)[:max_lines]
    y = box.y + 6
    for ln in lines:
        surf = font.render(ln, True, WHITE)
        screen.blit(surf, (box.x+6, y))
        y += surf.get_height() + 2

def draw_minion_stats(r: pygame.Rect, attack: int, health: int, max_health: int):
    # Attack bottom-left
    atk_rect = pygame.Rect(r.x + 10, r.bottom - 28, 28, 22)
    pygame.draw.rect(screen, (40, 35, 25), atk_rect, border_radius=6)
    ta = FONT.render(str(attack), True, ATTK_COLOR)
    screen.blit(ta, ta.get_rect(center=atk_rect.center))
    # Health bottom-right
    hp_rect = pygame.Rect(r.right - 38, r.bottom - 28, 28, 22)
    pygame.draw.rect(screen, (40, 35, 35), hp_rect, border_radius=6)
    hp_col = HP_HURT if health < max_health else HP_OK
    th = FONT.render(str(health), True, hp_col)
    screen.blit(th, th.get_rect(center=hp_rect.center))

def draw_card_frame(r: pygame.Rect, color_bg, *, card_obj=None, minion_obj=None, in_hand: bool):
    pygame.draw.rect(screen, color_bg, r, border_radius=12)
    rarity_to_draw = None

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
        final_text = header if header and not text else (header + ("\n" + text if text else ""))

        draw_text_box(r, final_text, max_lines=6, font=RULE_FONT)   # <-- smaller font + more lines
        draw_name_footer(r, card_obj.name)
        draw_rarity_droplet(r, getattr(card_obj, "rarity", "Common"))
        if card_obj.type == "MINION":
            draw_minion_stats(r, card_obj.attack, card_obj.health, card_obj.health)

    elif minion_obj:
        draw_cost_gem(r, getattr(minion_obj, "cost", 0))
        #draw_name_bar(r, minion_obj.name)
        short = []
        if getattr(minion_obj, "taunt", False):  short.append("Taunt")
        if getattr(minion_obj, "charge", False): short.append("Charge")
        if getattr(minion_obj, "rush", False):   short.append("Rush")
        desc = " / ".join(short)
        draw_text_box(r, desc, max_lines=2, font=RULE_FONT)
        draw_minion_stats(r, minion_obj.attack, minion_obj.health, minion_obj.max_health)

        draw_name_footer(r, minion_obj.name)
        # prefer minion.rarity; fallback to Common
        draw_rarity_droplet(r, getattr(minion_obj, "rarity", "Common"))
        draw_minion_stats(r, minion_obj.attack, minion_obj.health, minion_obj.max_health)


def draw_layered_borders(r: pygame.Rect, *, taunt: bool, rush: bool, ready: bool):
    if taunt: pygame.draw.rect(screen, GREY, r, 3, border_radius=10)
    if rush:  pygame.draw.rect(screen, RED,  r.inflate(4, 4), 3, border_radius=12)
    if ready: pygame.draw.rect(screen, GREEN,r.inflate(10,10), 3, border_radius=16)

# ---------- Layout ----------
def _centered_row_rects(n: int, y: int) -> List[pygame.Rect]:
    if n <= 0: return []
    total_w = n * CARD_W + (n - 1) * MARGIN
    start_x = max((W - total_w) // 2, MARGIN)
    return [pygame.Rect(start_x + i * (CARD_W + MARGIN), y, CARD_W, CARD_H) for i in range(n)]

def _stacked_hand_rects(n: int, y: int) -> List[pygame.Rect]:
    """Return overlapped, centered rects for the hand (Hearthstone-ish stack)."""
    if n <= 0: return []
    step = max(1, int(CARD_W * (1.0 - HAND_OVERLAP)))  # horizontal step between cards
    total_w = step * (n - 1) + CARD_W
    start_x = max((W - total_w) // 2, MARGIN)
    return [pygame.Rect(start_x + i * step, y, CARD_W, CARD_H) for i in range(n)]

def layout_board(g: Game) -> Dict[str, Any]:
    hot = {"hand": [], "my_minions": [], "enemy_minions": [], "end_turn": None,
           "face_enemy": None, "face_me": None}

    # Enemy row
    for m, r in zip(g.players[1].board, _centered_row_rects(len(g.players[1].board), ROW_Y_ENEMY)):
        hot["enemy_minions"].append((m.id, r))

    # My row
    for m, r in zip(g.players[0].board, _centered_row_rects(len(g.players[0].board), ROW_Y_ME)):
        hot["my_minions"].append((m.id, r))

    # Hand row (stacked/overlapped)
    for (i, cid), r in zip(list(enumerate(g.players[0].hand)), _stacked_hand_rects(len(g.players[0].hand), ROW_Y_HAND)):
        hot["hand"].append((i, cid, r))

    # Faces
    hot["face_enemy"] = pygame.Rect(W//2 - 100, ROW_Y_ENEMY - 75, 200, 52)

    face_me_y = ROW_Y_ME + CARD_H + 24
    max_face_me_y = ROW_Y_HAND - 68
    face_me_y = min(face_me_y, max_face_me_y)
    hot["face_me"] = pygame.Rect(W//2 - 100, face_me_y, 200, 52)

    # End turn
    hot["end_turn"] = pygame.Rect(W - 170, H - 70, 150, 50)
    return hot

def scale_rect_about_center(r: pygame.Rect, s: float, lift: int = 0) -> pygame.Rect:
    w, h = int(r.w * s * 1.2), int(r.h * s * 1.2)
    cx, cy = r.centerx, r.centery - lift * 1.5
    return pygame.Rect(cx - w // 2, cy - h // 2, w, h)

def hand_hover_index(hot, mx, my) -> Optional[int]:
    """Return the hand index under the mouse (consider a slightly enlarged hitbox)."""
    for i, cid, r in hot["hand"]:
        hit = scale_rect_about_center(r, 1.10, HOVER_LIFT // 2)  # generous hit area
        if hit.collidepoint(mx, my):
            return i
    return None


def draw_headers(g: Game):
    centered_text(f"AI — HP:{g.players[1].health}  Hand:{len(g.players[1].hand)}  Mana:{g.players[1].mana}/{g.players[1].max_mana}", 24)
    centered_text(f"You — HP:{g.players[0].health}  Hand:{len(g.players[0].hand)}  Mana:{g.players[0].mana}/{g.players[0].max_mana}", H - 10)  # was H - 24

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
def targets_for_spell(g: Game, cid: str):
    """
    Return legal target sets for a given card id.
    Returns: (enemy_min_ids, my_min_ids, enemy_face_ok, my_face_ok)
    """
    # ----- Damage spells -----
    if cid in ("FIREBALL_LITE",):
        enemy_min = {m.id for m in g.players[1].board if m.is_alive()}
        return enemy_min, set(), True, False

    if cid in ("SWIPE_LITE",):
        enemy_min = {m.id for m in g.players[1].board if m.is_alive()}
        return enemy_min, set(), False, False

    # Pinger battlecry (minion that deals 1 on play)
    if cid in ("KOBOLD_PING",):
        enemy_min = {m.id for m in g.players[1].board if m.is_alive()}
        return enemy_min, set(), True, False

    # ----- Buffs (friendly minions only) -----
    if cid in ("BLESSING_OF_MIGHT_LITE", "BLESSING_OF_KINGS_LITE", "GIVE_TAUNT", "GIVE_CHARGE", "GIVE_RUSH"):
        my_min = {m.id for m in g.players[0].board if m.is_alive()}
        return set(), my_min, False, False

    # ----- Transform / Silence (any minion) -----
    if cid in ("SILENCE_LITE", "POLYMORPH_LITE"):
        enemy_min = {m.id for m in g.players[1].board if m.is_alive()}
        my_min = {m.id for m in g.players[0].board if m.is_alive()}
        return enemy_min, my_min, False, False

    # ----- Heals -----
    # Spell heal (choose any character)
    if cid in ("HOLY_LIGHT",):
        enemy_min = {m.id for m in g.players[1].board if m.is_alive()}
        my_min    = {m.id for m in g.players[0].board if m.is_alive()}
        return enemy_min, my_min, True, True

    # Battlecry heal: EARTHEN_RING (minion) – choose ANY character (faces or minions on both sides)
    if cid in ("EARTHEN_RING",):
        enemy_min = {m.id for m in g.players[1].board if m.is_alive()}
        my_min    = {m.id for m in g.players[0].board if m.is_alive()}
        return enemy_min, my_min, True, True

    # Non-targeted by default
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

# ---------- Rendering ----------
def draw_board(g: Game, hot, hidden_minion_ids: Optional[set] = None,
               highlight_enemy_minions: Optional[set] = None,
               highlight_my_minions: Optional[set] = None,
               highlight_enemy_face: bool = False,
               highlight_my_face: bool = False):
    hidden_minion_ids = hidden_minion_ids or set()
    highlight_enemy_minions = highlight_enemy_minions or set()
    highlight_my_minions = highlight_my_minions or set()

    # Faces
    pygame.draw.rect(screen, (158, 73, 73), hot["face_enemy"], border_radius=10)
    screen.blit(FONT.render("Enemy Face", True, WHITE), (hot["face_enemy"].x+44, hot["face_enemy"].y+16))
    pygame.draw.rect(screen, (73, 158, 93), hot["face_me"],    border_radius=10)
    screen.blit(FONT.render("Your Face", True, WHITE), (hot["face_me"].x+54, hot["face_me"].y+16))

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

    # End turn
    pygame.draw.rect(screen, BLUE if g.active_player == 0 else (90, 90, 90), hot["end_turn"], border_radius=8)
    t = FONT.render("End Turn", True, WHITE)
    screen.blit(t, t.get_rect(center=hot["end_turn"].center))

    

    # Face highlights
    if highlight_enemy_face:
        pygame.draw.rect(screen, RED, hot["face_enemy"].inflate(8, 8), 3, border_radius=12)
    if highlight_my_face:
        pygame.draw.rect(screen, RED, hot["face_me"].inflate(8, 8), 3, border_radius=12)

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
        if not self.queue: return hidden_ids
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
            overlay = pygame.Surface((W, H), pygame.SRCALPHA)
            overlay.fill((0,0,0, min(120, int(150 * t))))
            screen.blit(overlay, (0,0))
            centered_text("AI is thinking...", H//2)

        if step.done():
            self.queue.pop(0)
            if step.on_finish:
                try: step.on_finish()
                except Exception as e: print("Animation callback error:", repr(e))
        return hidden_ids

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


# ---------- Main loop ----------
GLOBAL_GAME: Game

def start_game(seed=1317) -> Game:
    g = Game(db, STARTER_DECK_PLAYER.copy(), STARTER_DECK_AI.copy(), seed=seed)
    apply_post_summon_hooks(g, g.start_game())
    return g

def main():
    global GLOBAL_GAME
    clock = pygame.time.Clock()
    g = start_game()
    GLOBAL_GAME = g

    selected_attacker: Optional[int] = None
    waiting_target_for_play: Optional[Tuple[int, str, pygame.Rect]] = None
    hilite_enemy_min: set = set()
    hilite_my_min: set = set()
    hilite_enemy_face: bool = False
    hilite_my_face: bool = False

    RUNNING = True
    while RUNNING:
        clock.tick(60)
        screen.fill(BG)
        hot = layout_board(g)

        draw_headers(g)
        hidden = ANIMS.update_and_draw(g, hot)
        draw_board(g, hot,
                   hidden_minion_ids=hidden,
                   highlight_enemy_minions=hilite_enemy_min,
                   highlight_my_minions=hilite_my_min,
                   highlight_enemy_face=hilite_enemy_face,
                   highlight_my_face=hilite_my_face)

        # GG
        if g.players[0].health <= 0 or g.players[1].health <= 0:
            winner = "AI" if g.players[0].health <= 0 else "You"
            centered_text(f"Game over! {winner} wins. ESC to quit.", H//2 + 8)
            for event in pygame.event.get():
                if event.type == pygame.QUIT: RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: RUNNING = False
            pygame.display.flip()
            continue

        # ----- AI turn -----
        if g.active_player == 1:
            if not ANIMS.busy():
                def decide():
                    act, _ = pick_best_action(g, 1)
                    kind = act[0]
                    if kind == 'end':
                        def do_end():
                            try: g.end_turn(1)
                            except IllegalAction: pass
                        ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=do_end))

                    elif kind == 'play':
                        _, idx, tp, tm = act
                        cid = g.players[1].hand[idx]
                        src = pygame.Rect(W//2 - CARD_W//2, 20, CARD_W, CARD_H)
                        def do_on_finish(i=idx, tpp=tp, tmm=tm):
                            try:
                                ev = g.play_card(1, i, target_player=tpp, target_minion=tmm)
                                apply_post_summon_hooks(g, ev)
                                post = layout_board(g)
                                for e in ev:
                                    if e.kind == "PlayerDamaged":
                                        face = my_face_rect(post) if e.payload["player"] == 0 else enemy_face_rect(post)
                                        enqueue_flash(face)
                                    elif e.kind == "MinionDamaged":
                                        mloc = g.find_minion(e.payload["minion"])
                                        if mloc:
                                            pid2, _, m2 = mloc
                                            post2 = layout_board(g)
                                            coll = "my_minions" if pid2 == 0 else "enemy_minions"
                                            for mid2, r2 in post2[coll]:
                                                if mid2 == m2.id: enqueue_flash(r2); break
                            except IllegalAction:
                                pass
                        dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ENEMY, CARD_W, CARD_H)
                        ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}))
                        ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                            {"src": src, "dst": dst, "label": db[cid].name,
                                             "color": CARD_BG_EN}, on_finish=do_on_finish))

                    elif kind == 'attack':
                        _, aid, tp, tm = act
                        before = layout_board(g)
                        tr = None
                        if tm is not None:
                            for mid, r in before["my_minions"]:
                                if mid == tm: tr = r; break
                        if tr is None: tr = my_face_rect(before)
                        def on_hit(aid=aid, tpp=tp, tmm=tm):
                            try: g.attack(1, attacker_id=aid, target_player=tpp, target_minion=tmm)
                            except IllegalAction: return
                            post = layout_board(g)
                            if tmm is None:
                                enqueue_flash(my_face_rect(post))
                            else:
                                for mid, r in post["my_minions"]:
                                    if mid == tmm: enqueue_flash(r); break
                        enqueue_attack_anim(before, attacker_mid=aid, target_rect=tr, enemy=True, on_hit=on_hit)

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
                        try: g.end_turn(0)
                        except IllegalAction: pass
                        selected_attacker = None
                        waiting_target_for_play = None
                        hilite_enemy_min.clear(); hilite_my_min.clear()
                        hilite_enemy_face = False; hilite_my_face = False
                        continue

                    # If selecting target for a spell
                    if waiting_target_for_play is not None:
                        idx, cid, src_rect = waiting_target_for_play
                        enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_spell(g, cid)

                        # Enemy face?
                        if enemy_face_ok and enemy_face_rect(hot).collidepoint(mx, my):
                            def on_finish(i=idx):
                                try:
                                    ev = g.play_card(0, i, target_player=1)
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

                    # Click hand to play
                    clicked_hand = False
                    for i, cid, r in hot["hand"]:
                        if r.collidepoint(mx, my):
                            clicked_hand = True
                            enemy_mins, my_mins, enemy_face_ok, my_face_ok = targets_for_spell(g, cid)
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
                                        apply_post_summon_hooks(g, ev)
                                    except IllegalAction: pass
                                dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ME, CARD_W, CARD_H)
                                ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                                    {"src": r.copy(), "dst": dst, "label": db[cid].name},
                                                    on_finish=on_finish))
                                hilite_enemy_min.clear(); hilite_my_min.clear()
                                hilite_enemy_face = False; hilite_my_face = False
                            selected_attacker = None
                            break
                    if clicked_hand:
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

                    # If an attacker is selected, attempt to attack a highlighted target
                    if selected_attacker is not None:
                        did = False
                        for emid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my) and emid in hilite_enemy_min:
                                def on_hit(attacker=selected_attacker, em=emid):
                                    try: g.attack(0, attacker, target_minion=em)
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
                                try: g.attack(0, attacker, target_player=1)
                                except IllegalAction: return
                                enqueue_flash(enemy_face_rect(layout_board(g)))
                            enqueue_attack_anim(hot, attacker_mid=selected_attacker, target_rect=enemy_face_rect(hot), enemy=False, on_hit=on_hit)
                            selected_attacker = None
                            hilite_enemy_min.clear(); hilite_my_min.clear()
                            hilite_enemy_face = False; hilite_my_face = False

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
