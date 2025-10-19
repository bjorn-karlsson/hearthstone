
from collections import deque
import pygame

from engine import Game



# --- Debug / dev toggles ---
SHOW_ENEMY_HAND = False
DEBUG_BTN_RECT = None

DEBUG = True

# --- Pygame ---
pygame.init()
# Fullscreen @ desktop resolution
screen = pygame.display.set_mode((0, 0))
W, H = screen.get_size()
pygame.display.set_caption("Python Card Battler (Animated-Locked + Targets)")

FONT = pygame.font.SysFont(None, 22)
BIG  = pygame.font.SysFont(None, 26)
RULE_FONT = pygame.font.SysFont(None, 20)  # smaller for rules text

LAST_HAND_COUNT = {0: 0, 1: 0}

GLOBAL_GAME: Game


# Colors
NEUTRAL_BG = (90, 90, 90)  # fallback gray
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
    "SHAMAN":  (25, 105, 185),  # deep cyan/blue
    "ROGUE":   (80, 80, 80),    # charcoal/steel
    "PRIEST":  (170, 170, 170), # light/holy white
    "DRUID":   (165, 110, 30),  # warm amber/bark
}

# Hide specific hand indices while an animation is flying toward them
HIDDEN_HAND_INDICES_ME: set[int] = set()
HIDDEN_HAND_INDICES_EN: set[int] = set()

# Track where minions were on the previous frame (for deaths, etc.)
LAST_MINION_RECTS: dict[int, pygame.Rect] = {}

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
ANIM_DRAW_MS    = 750
AI_THINK_MS     = 450
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