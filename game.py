import pygame
import sys
from typing import Optional, Tuple, List, Dict, Any
import math
import time

from engine import Game, make_db, apply_post_summon_hooks, IllegalAction, Event
from ai import pick_best_action  # we'll call this per-step

pygame.init()
W, H = 1024, 720
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("Python Card Battler (Animated)")

FONT = pygame.font.SysFont(None, 22)
BIG  = pygame.font.SysFont(None, 32)

# Colors
BG = (20, 25, 30)
WHITE = (230, 230, 230)
GREY = (130, 140, 150)
GREEN = (70, 180, 90)
RED   = (200, 60, 60)
BLUE  = (80, 120, 210)
YELLOW = (230, 200, 90)
CARD_BG_HAND = (40, 70, 100)
CARD_BG_MY   = (60, 90, 60)
CARD_BG_EN   = (60, 60, 90)

# Layout
CARD_W, CARD_H = 120, 84
MARGIN = 10
ROW_Y_ENEMY = 160
ROW_Y_ME    = 360
ROW_Y_HAND  = 540

# Animation tuning (ms)
ANIM_PLAY_MS    = 550
ANIM_ATTACK_MS  = 420
ANIM_RETURN_MS  = 320
ANIM_FLASH_MS   = 220
AI_THINK_DELAY  = 1000  # small pause before AI acts (ms)

STARTER_DECK = [
    "SHIELD_BEARER","LEPER_GNOME","RIVER_CROCOLISK","RUSHER","KOBOLD_PING",
    "WOLFRIDER","CHILLWIND_YETI","FIREBALL_LITE","ARCANE_MISSILES_LITE",
    "BOULDERFIST_OGRE"
] * 3

# ---------------- UI helpers ----------------

def draw_rect_text(r, color, text="", tcolor=WHITE, center=False):
    pygame.draw.rect(screen, color, r, border_radius=8)
    if text:
        surf = FONT.render(text, True, tcolor)
        if center:
            screen.blit(surf, surf.get_rect(center=(r.x + r.w/2, r.y + r.h/2)))
        else:
            screen.blit(surf, (r.x + 6, r.y + 6))

def draw_multiline(text: str, rect: pygame.Rect, color):
    y = rect.y + 6
    for ln in text.split("\n"):
        if not ln: 
            y += 18
            continue
        surf = FONT.render(ln, True, color)
        screen.blit(surf, (rect.x + 6, y))
        y += 18

def centered_text(text: str, y: int, font=BIG, color=WHITE):
    surf = font.render(text, True, color)
    screen.blit(surf, surf.get_rect(center=(W//2, y)))

def card_label_for_hand(g: Game, cid: str) -> str:
    c = g.cards_db[cid]
    s1 = f"{c.name}"
    s2 = f"Cost:{c.cost} {c.type}"
    s3 = ""
    if c.type == "MINION":
        flags = []
        if "Taunt" in c.keywords: flags.append("T")
        if "Charge" in c.keywords: flags.append("C")
        if "Rush" in c.keywords:   flags.append("R")
        s3 = f"{c.attack}/{c.health}" + (f" [{' '.join(flags)}]" if flags else "")
    return "\n".join([s1, s2, s3])

def minion_label(m) -> str:
    flags = []
    if m.taunt: flags.append("T")
    if m.charge: flags.append("C")
    if m.rush: flags.append("R")
    if m.summoned_this_turn: flags.append("S")
    if m.has_attacked_this_turn: flags.append("X")
    fs = f" [{' '.join(flags)}]" if flags else ""
    return f"{m.name}\n{m.attack}/{m.health}{fs}"

# ---------------- Layout model ----------------

def layout_board(g: Game) -> Dict[str, Any]:
    hot = {"hand": [], "my_minions": [], "enemy_minions": [], "end_turn": None, "face_enemy": None}
    # Enemy board
    x = MARGIN
    for m in g.players[1].board:
        r = pygame.Rect(x, ROW_Y_ENEMY, CARD_W, CARD_H)
        hot["enemy_minions"].append((m.id, r))
        x += CARD_W + MARGIN
    # My board
    x = MARGIN
    for m in g.players[0].board:
        r = pygame.Rect(x, ROW_Y_ME, CARD_W, CARD_H)
        hot["my_minions"].append((m.id, r))
        x += CARD_W + MARGIN
    # Hand
    x = MARGIN
    for i, cid in enumerate(g.players[0].hand):
        r = pygame.Rect(x, ROW_Y_HAND, CARD_W, CARD_H)
        hot["hand"].append((i, cid, r))
        x += CARD_W + MARGIN
    # End turn & enemy face zones
    hot["end_turn"] = pygame.Rect(W - 150, H - 60, 140, 40)
    hot["face_enemy"] = pygame.Rect(W//2 - 90, 60, 180, 50)
    return hot

def draw_player_headers(g: Game):
    # Top (AI)
    centered_text(f"AI — HP:{g.players[1].health}  Hand:{len(g.players[1].hand)}  Mana:{g.players[1].mana}/{g.players[1].max_mana}", 24)
    # Bottom (You)
    centered_text(f"You — HP:{g.players[0].health}  Hand:{len(g.players[0].hand)}  Mana:{g.players[0].mana}/{g.players[0].max_mana}", H - 28)

def draw_board(g: Game, hot, hidden_minion_ids: Optional[set] = None):
    hidden_minion_ids = hidden_minion_ids or set()
    # Enemy minions
    for mid, r in hot["enemy_minions"]:
        pid, idx, m = g.find_minion(mid)
        if m.id in hidden_minion_ids: 
            continue
        draw_rect_text(r, CARD_BG_EN)
        draw_multiline(minion_label(m), r, WHITE)
        if m.taunt:
            pygame.draw.rect(screen, YELLOW, r, 3, border_radius=8)

    # My minions
    for mid, r in hot["my_minions"]:
        pid, idx, m = g.find_minion(mid)
        if m.id in hidden_minion_ids:
            continue
        draw_rect_text(r, CARD_BG_MY)
        draw_multiline(minion_label(m), r, WHITE)

    # My hand
    for i, cid, r in hot["hand"]:
        draw_rect_text(r, CARD_BG_HAND)
        draw_multiline(card_label_for_hand(g, cid), r, WHITE)

    # End turn
    draw_rect_text(hot["end_turn"], BLUE if g.active_player == 0 else GREY, "End Turn", WHITE, center=True)

    # Enemy face
    pygame.draw.rect(screen, (150, 70, 70), hot["face_enemy"], border_radius=8)
    t = FONT.render("Enemy Face", True, WHITE)
    screen.blit(t, t.get_rect(center=hot["face_enemy"].center))

# ---------------- Animation system ----------------

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def ease_out(t: float) -> float:
    # quadratic ease-out
    return 1 - (1 - t) * (1 - t)

class AnimStep:
    def __init__(self, kind: str, duration_ms: int, data: dict):
        self.kind = kind
        self.duration_ms = duration_ms
        self.data = data
        self.start_ms = None

    def start(self):
        self.start_ms = pygame.time.get_ticks()

    def progress(self) -> float:
        if self.start_ms is None:
            return 0.0
        t = (pygame.time.get_ticks() - self.start_ms) / self.duration_ms
        return min(max(t, 0.0), 1.0)

    def done(self) -> bool:
        return self.progress() >= 1.0

class AnimQueue:
    def __init__(self):
        self.queue: List[AnimStep] = []

    def push(self, step: AnimStep):
        self.queue.append(step)

    def busy(self) -> bool:
        return len(self.queue) > 0

    def update_and_draw(self, g: Game, hot):
        """Advance head animation and render overlay visuals. 
           Return set of minion_ids to hide while animating (e.g., during play)."""
        if not self.queue:
            return set()
        step = self.queue[0]
        if step.start_ms is None:
            step.start()

        hide_ids = set()
        t = ease_out(step.progress())

        if step.kind == "play_move":
            # Draw flying card from src -> dst; hide the real minion at dst while animating
            src: pygame.Rect = step.data["src"]
            dst: pygame.Rect = step.data["dst"]
            color = step.data.get("color", CARD_BG_HAND)
            minion_id = step.data.get("spawn_minion_id")
            x = lerp(src.x, dst.x, t)
            y = lerp(src.y, dst.y, t)
            r = pygame.Rect(int(x), int(y), CARD_W, CARD_H)
            draw_rect_text(r, color)
            lbl = step.data.get("label", "")
            if lbl: draw_multiline(lbl, r, WHITE)
            if minion_id:
                hide_ids.add(minion_id)

        elif step.kind == "attack_dash":
            # Move a ghost over the attacker along a path to target and back (two phases split into two steps)
            src: pygame.Rect = step.data["src"]
            dst: pygame.Rect = step.data["dst"]
            color = step.data.get("color", CARD_BG_MY)
            x = lerp(src.x, dst.x, t)
            y = lerp(src.y, dst.y, t)
            r = pygame.Rect(int(x), int(y), CARD_W, CARD_H)
            draw_rect_text(r, color)
            if "label" in step.data:
                draw_multiline(step.data["label"], r, WHITE)

        elif step.kind == "flash":
            # Quick white flash on a rect
            target: pygame.Rect = step.data["rect"]
            alpha = int(255 * (1.0 - t))
            s = pygame.Surface((target.w, target.h), pygame.SRCALPHA)
            s.fill((255, 255, 255, alpha))
            screen.blit(s, (target.x, target.y))

        elif step.kind == "think_pause":
            # subtle overlay to indicate AI is thinking
            overlay = pygame.Surface((W, H), pygame.SRCALPHA)
            overlay.fill((0,0,0, min(120, int(150 * t))))
            screen.blit(overlay, (0,0))
            centered_text("AI is thinking...", H//2, BIG, WHITE)

        if step.done():
            self.queue.pop(0)

        return hide_ids

ANIMS = AnimQueue()

# Helpers to enqueue animations from game events / actions
def enqueue_play_animation(g: Game, before_hot, after_hot, played_from_rect: pygame.Rect, spawned_mid: Optional[int], label: str, is_enemy: bool=False):
    """Animate card moving from hand (or face zone) to the slot on board.
       We'll hide the spawned minion ID while moving."""
    if spawned_mid:
        # find its new rect
        coll = "enemy_minions" if is_enemy else "my_minions"
        dst = None
        for mid, r in after_hot[coll]:
            if mid == spawned_mid:
                dst = r
                break
        if dst is None:
            return
        ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS, {
            "src": played_from_rect,
            "dst": dst,
            "label": label,
            "spawn_minion_id": spawned_mid,
            "color": CARD_BG_HAND if not is_enemy else CARD_BG_EN
        }))

def enqueue_attack_animation(g: Game, hot, attacker_mid: int, target_rect: pygame.Rect, enemy: bool=False):
    # source rect is current attacker rect
    coll = "enemy_minions" if enemy else "my_minions"
    src = None
    label = ""
    for mid, r in hot[coll]:
        if mid == attacker_mid:
            src = r
            pid, idx, m = g.find_minion(attacker_mid)
            label = f"{m.name}\n{m.attack}/{m.health}"
            break
    if src is None: 
        return
    # dash forward
    ANIMS.push(AnimStep("attack_dash", ANIM_ATTACK_MS, {"src": src, "dst": target_rect, "label": label, "color": CARD_BG_MY if not enemy else CARD_BG_EN}))
    # dash back
    ANIMS.push(AnimStep("attack_dash", ANIM_RETURN_MS, {"src": target_rect, "dst": src, "label": label, "color": CARD_BG_MY if not enemy else CARD_BG_EN}))

def enqueue_flash(rect: pygame.Rect):
    ANIMS.push(AnimStep("flash", ANIM_FLASH_MS, {"rect": rect}))

def enemy_face_rect(hot): 
    return hot["face_enemy"]

# ---------------- Main loop ----------------

def start_game(seed=1337) -> Game:
    db = make_db()
    g = Game(db, STARTER_DECK.copy(), STARTER_DECK.copy(), seed=seed)
    apply_post_summon_hooks(g, g.start_game())
    return g

def main():
    clock = pygame.time.Clock()
    g = start_game()
    selected_attacker: Optional[int] = None
    waiting_target_for_play: Optional[Tuple[int, str, pygame.Rect]] = None  # (hand_index, card_id, from_rect)
    msg = "Your turn! Click cards to play, your minions to attack, or End Turn."
    ai_wait_until = 0  # timestamp for AI pause
    pending_ai_end = False  # last AI action was end

    RUNNING = True
    while RUNNING:
        dt = clock.tick(60)
        screen.fill(BG)
        hot = layout_board(g)

        draw_player_headers(g)

        # Render board; if animating, hide certain minions for nicer visuals
        hidden = ANIMS.update_and_draw(g, hot)
        draw_board(g, hot, hidden_minion_ids=hidden)

        # Game over line
        if g.players[0].health <= 0 or g.players[1].health <= 0:
            winner = "AI" if g.players[0].health <= 0 else "You"
            centered_text(f"Game over! {winner} wins. ESC to quit.", H//2 + 8, BIG, WHITE)
            for event in pygame.event.get():
                if event.type == pygame.QUIT: RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: RUNNING = False
            pygame.display.flip()
            continue

        # AI turn handling (stepwise, one action -> animation -> next)
        if g.active_player == 1:
            # If animating, don't do anything yet
            if not ANIMS.busy() and pygame.time.get_ticks() >= ai_wait_until:
                # short "thinking" pause before each action
                ANIMS.push(AnimStep("think_pause", AI_THINK_DELAY, {}))
                ai_wait_until = pygame.time.get_ticks() + AI_THINK_DELAY

                # Decide next action
                act, _ = pick_best_action(g, 1)
                kind = act[0]

                if kind == 'end':
                    try:
                        g.end_turn(1)
                    except IllegalAction:
                        pass
                elif kind == 'play':
                    _, idx, tp, tm = act
                    # Remember pre-layout for animation source
                    before = layout_board(g)
                    # If enemy plays from hand, source rect is enemy "hand" (we don't render their hand).
                    # We'll fake it: pick from top-center.
                    fake_src = pygame.Rect(W//2 - CARD_W//2, 20, CARD_W, CARD_H)
                    cid = g.players[1].hand[idx]
                    label = g.cards_db[cid].name
                    ev = g.play_card(1, idx, target_player=tp, target_minion=tm)
                    apply_post_summon_hooks(g, ev)
                    # find a MinionSummoned for enemy to animate
                    spawned = None
                    for e in ev:
                        if e.kind == "MinionSummoned" and e.payload.get("player") == 1:
                            spawned = e.payload["minion"]
                            break
                    after = layout_board(g)
                    if spawned:
                        enqueue_play_animation(g, before, after, fake_src, spawned, label, is_enemy=True)
                    # Target flashes (spells or BC)
                    for e in ev:
                        if e.kind in ("PlayerDamaged","MinionDamaged"):
                            if e.kind == "PlayerDamaged" and e.payload["player"] == 0:
                                enqueue_flash(enemy_face_rect(after))  # enemy hit YOU? flash your header? keep it simple
                            if e.kind == "PlayerDamaged" and e.payload["player"] == 0:
                                pass
                            if e.kind == "MinionDamaged":
                                # find minion rect (mine or theirs)
                                mloc = g.find_minion(e.payload["minion"])
                                if mloc:
                                    pid, idx, m = mloc
                                    after = layout_board(g)
                                    coll = "my_minions" if pid == 0 else "enemy_minions"
                                    for mid, r in after[coll]:
                                        if mid == m.id:
                                            enqueue_flash(r)
                                            break

                elif kind == 'attack':
                    _, aid, tp, tm = act
                    before = layout_board(g)
                    if tm is not None:
                        # find target rect
                        tr = None
                        for mid, r in before["my_minions"]:  # AI attacks your minions
                            if mid == tm:
                                tr = r
                                break
                    else:
                        tr = enemy_face_rect(before)  # attacking your face
                    enqueue_attack_animation(g, before, attacker_mid=aid, target_rect=tr, enemy=True)
                    # Apply after enqueuing to preserve start position for animation
                    try:
                        g.attack(1, attacker_id=aid, target_player=tp, target_minion=tm)
                    except IllegalAction:
                        pass
                # After any AI action, continue loop (animations will play)
        else:
            # Human input only if not animating
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    RUNNING = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not ANIMS.busy():
                    mx, my = event.pos

                    # End turn
                    if hot["end_turn"].collidepoint(mx, my):
                        try:
                            g.end_turn(0)
                        except IllegalAction:
                            pass
                        continue

                    # If waiting to target a spell/battlecry play
                    if waiting_target_for_play is not None:
                        idx, cid, src_rect = waiting_target_for_play
                        # Face?
                        if hot["face_enemy"].collidepoint(mx, my):
                            ev = g.play_card(0, idx, target_player=1)
                            apply_post_summon_hooks(g, ev)
                            after = layout_board(g)
                            spawned = None
                            for e in ev:
                                if e.kind == "MinionSummoned" and e.payload.get("player") == 0:
                                    spawned = e.payload["minion"]
                                    break
                            enqueue_play_animation(g, hot, after, src_rect, spawned, g.cards_db[cid].name)
                            # flash where damage happened
                            for e in ev:
                                if e.kind == "PlayerDamaged" and e.payload["player"] == 1:
                                    enqueue_flash(hot["face_enemy"])
                            waiting_target_for_play = None
                            continue
                        # Enemy minion targeting
                        targeted = False
                        for mid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my):
                                ev = g.play_card(0, idx, target_minion=mid)
                                apply_post_summon_hooks(g, ev)
                                after = layout_board(g)
                                spawned = None
                                for e in ev:
                                    if e.kind == "MinionSummoned" and e.payload.get("player") == 0:
                                        spawned = e.payload["minion"]
                                        break
                                enqueue_play_animation(g, hot, after, src_rect, spawned, g.cards_db[cid].name)
                                # flash the hit target
                                enqueue_flash(r)
                                waiting_target_for_play = None
                                targeted = True
                                break
                        if targeted:
                            continue

                    # Click a hand card to play
                    for i, cid, r in hot["hand"]:
                        if r.collidepoint(mx, my):
                            # targeted ones require a second click
                            if cid in ("FIREBALL_LITE", "KOBOLD_PING"):
                                waiting_target_for_play = (i, cid, r.copy())
                            else:
                                # Non-targeted: play immediately, animate to new slot (if minion)
                                before = layout_board(g)
                                ev = g.play_card(0, i)
                                apply_post_summon_hooks(g, ev)
                                after = layout_board(g)
                                spawned = None
                                for e in ev:
                                    if e.kind == "MinionSummoned" and e.payload.get("player") == 0:
                                        spawned = e.payload["minion"]
                                        break
                                enqueue_play_animation(g, before, after, r.copy(), spawned, g.cards_db[cid].name)
                                # flash for spell pings
                                for e in ev:
                                    if e.kind == "PlayerDamaged" and e.payload["player"] == 1:
                                        enqueue_flash(after["face_enemy"])
                                    if e.kind == "MinionDamaged":
                                        mloc = g.find_minion(e.payload["minion"])
                                        if mloc:
                                            pid, idx, m = mloc
                                            after = layout_board(g)
                                            coll = "my_minions" if pid == 0 else "enemy_minions"
                                            for mid, rr in after[coll]:
                                                if mid == m.id:
                                                    enqueue_flash(rr)
                                                    break
                            selected_attacker = None
                            break

                    # Select attacker (your minion)
                    for mid, r in hot["my_minions"]:
                        if r.collidepoint(mx, my):
                            selected_attacker = mid
                            break

                    # If we have an attacker selected, check enemy minion or face
                    if selected_attacker is not None:
                        # Minion target
                        hit = False
                        for emid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my):
                                # animate attack first
                                enqueue_attack_animation(g, hot, attacker_mid=selected_attacker, target_rect=r, enemy=False)
                                try:
                                    g.attack(0, selected_attacker, target_minion=emid)
                                except IllegalAction:
                                    pass
                                selected_attacker = None
                                hit = True
                                break
                        if hit:
                            continue
                        # Face target
                        if hot["face_enemy"].collidepoint(mx, my):
                            enqueue_attack_animation(g, hot, attacker_mid=selected_attacker, target_rect=hot["face_enemy"], enemy=False)
                            try:
                                g.attack(0, selected_attacker, target_player=1)
                            except IllegalAction:
                                pass
                            selected_attacker = None

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
