import pygame
import sys
from typing import Optional, Tuple, List, Dict, Any

from engine import Game, make_db, apply_post_summon_hooks, IllegalAction
from ai import pick_best_action  # stepwise AI

pygame.init()
W, H = 1024, 720
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("Python Card Battler (Animated-Locked)")

FONT = pygame.font.SysFont(None, 22)
BIG  = pygame.font.SysFont(None, 32)

# Colors
BG = (20, 25, 30)
WHITE = (230, 230, 230)
GREY = (150, 150, 150)
GREEN = (60, 200, 90)
RED   = (210, 70, 70)
BLUE  = (80, 140, 240)
YELLOW = (230, 200, 90)
CARD_BG_HAND = (45, 75, 110)
CARD_BG_MY   = (60, 100, 70)
CARD_BG_EN   = (70, 70, 100)
COST_BADGE   = (60, 120, 230)

# Layout
CARD_W, CARD_H = 120, 84
MARGIN = 10
ROW_Y_ENEMY = 160
ROW_Y_ME    = 360
ROW_Y_HAND  = 540

# Animation timing (ms)
ANIM_PLAY_MS    = 550
ANIM_ATTACK_MS  = 420
ANIM_RETURN_MS  = 320
ANIM_FLASH_MS   = 220
AI_THINK_MS     = 250

STARTER_DECK = [
    "SHIELD_BEARER","LEPER_GNOME","RIVER_CROCOLISK","RUSHER","KOBOLD_PING",
    "WOLFRIDER","CHILLWIND_YETI","FIREBALL_LITE","ARCANE_MISSILES_LITE",
    "BOULDERFIST_OGRE"
] * 3

# ------------- Drawing helpers -------------

def draw_cost_badge(r: pygame.Rect, cost: int):
    badge = pygame.Rect(r.x + 6, r.y + 4, 24, 20)
    pygame.draw.rect(screen, COST_BADGE, badge, border_radius=6)
    t = FONT.render(str(cost), True, WHITE)
    screen.blit(t, t.get_rect(center=badge.center))

def draw_layered_borders(r: pygame.Rect, *, taunt: bool, rush: bool, ready: bool):
    # layered outlines
    if taunt:
        pygame.draw.rect(screen, GREY, r, 3, border_radius=8)
    if rush:
        pygame.draw.rect(screen, RED, r.inflate(4, 4), 3, border_radius=10)
    if ready:
        pygame.draw.rect(screen, GREEN, r.inflate(10, 10), 3, border_radius=14)

def draw_card_box(r: pygame.Rect, color, title: str, subtitle: str = "", footer: str = ""):
    pygame.draw.rect(screen, color, r, border_radius=8)
    if title:
        t = FONT.render(title, True, WHITE)
        screen.blit(t, (r.x + 36, r.y + 6))
    if subtitle:
        s = FONT.render(subtitle, True, WHITE)
        screen.blit(s, (r.x + 6, r.y + 28))
    if footer:
        f = FONT.render(footer, True, WHITE)
        screen.blit(f, (r.x + 6, r.y + 50))

def centered_text(text: str, y: int, font=BIG, color=WHITE):
    surf = font.render(text, True, color)
    screen.blit(surf, surf.get_rect(center=(W//2, y)))

def layout_board(g: Game) -> Dict[str, Any]:
    hot = {"hand": [], "my_minions": [], "enemy_minions": [], "end_turn": None,
           "face_enemy": None, "face_me": None}
    x = MARGIN
    for m in g.players[1].board:
        hot["enemy_minions"].append((m.id, pygame.Rect(x, ROW_Y_ENEMY, CARD_W, CARD_H)))
        x += CARD_W + MARGIN
    x = MARGIN
    for m in g.players[0].board:
        hot["my_minions"].append((m.id, pygame.Rect(x, ROW_Y_ME, CARD_W, CARD_H)))
        x += CARD_W + MARGIN
    x = MARGIN
    for i, cid in enumerate(g.players[0].hand):
        hot["hand"].append((i, cid, pygame.Rect(x, ROW_Y_HAND, CARD_W, CARD_H)))
        x += CARD_W + MARGIN
    hot["end_turn"] = pygame.Rect(W - 150, H - 60, 140, 40)
    hot["face_enemy"] = pygame.Rect(W//2 - 90, 60, 180, 50)      # top (AI)
    hot["face_me"]    = pygame.Rect(W//2 - 90, H - 110, 180, 50) # bottom (You)
    return hot

def draw_headers(g: Game):
    centered_text(f"AI — HP:{g.players[1].health}  Hand:{len(g.players[1].hand)}  Mana:{g.players[1].mana}/{g.players[1].max_mana}", 24)
    centered_text(f"You — HP:{g.players[0].health}  Hand:{len(g.players[0].hand)}  Mana:{g.players[0].mana}/{g.players[0].max_mana}", H - 24)

def minion_ready_to_act(g: Game, m) -> bool:
    if m.has_attacked_this_turn:
        return False
    if not m.summoned_this_turn:
        return True
    if m.charge:
        return True
    if m.rush and any(mm.is_alive() for mm in g.players[1 - m.owner].board):
        return True
    return False

def draw_board(g: Game, hot, hidden_minion_ids: Optional[set] = None):
    hidden_minion_ids = hidden_minion_ids or set()

    # Enemy minions
    for mid, r in hot["enemy_minions"]:
        minfo = g.find_minion(mid)
        if not minfo:
            continue  # minion died after layout; skip this stale slot
        pid, idx, m = minfo
        if m.id in hidden_minion_ids:
            continue
        draw_card_box(r, CARD_BG_EN, m.name, f"ATK {m.attack} / HP {m.health}")
        draw_layered_borders(r, taunt=m.taunt, rush=m.rush, ready=minion_ready_to_act(g, m))

    # My minions
    for mid, r in hot["my_minions"]:
        minfo = g.find_minion(mid)
        if not minfo:
            continue  # minion died after layout; skip this stale slot
        pid, idx, m = minfo
        if m.id in hidden_minion_ids:
            continue
        draw_card_box(r, CARD_BG_MY, m.name, f"ATK {m.attack} / HP {m.health}")
        draw_layered_borders(r, taunt=m.taunt, rush=m.rush, ready=minion_ready_to_act(g, m))

    # My hand
    for i, cid, r in hot["hand"]:
        c = g.cards_db[cid]
        subtitle = c.type
        footer = f"{c.attack}/{c.health}" if c.type == "MINION" else ""
        draw_card_box(r, CARD_BG_HAND, c.name, subtitle, footer)
        draw_cost_badge(r, c.cost)

    # End turn
    pygame.draw.rect(screen, BLUE if g.active_player == 0 else (90, 90, 90), hot["end_turn"], border_radius=8)
    t = FONT.render("End Turn", True, WHITE)
    screen.blit(t, t.get_rect(center=hot["end_turn"].center))

    # Faces
    pygame.draw.rect(screen, (150, 70, 70), hot["face_enemy"], border_radius=8)
    screen.blit(FONT.render("Enemy Face", True, WHITE), (hot["face_enemy"].x+44, hot["face_enemy"].y+16))
    pygame.draw.rect(screen, (70, 140, 70), hot["face_me"], border_radius=8)
    screen.blit(FONT.render("Your Face", True, WHITE), (hot["face_me"].x+54, hot["face_me"].y+16))
# ------------- Animation system -------------

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def ease_out(t: float) -> float:
    return 1 - (1 - t) * (1 - t)

class AnimStep:
    def __init__(self, kind: str, duration_ms: int, data: dict, on_finish=None):
        self.kind = kind
        self.duration_ms = duration_ms
        self.data = data
        self.on_finish = on_finish
        self.start_ms = None

    def start(self):
        self.start_ms = pygame.time.get_ticks()

    def progress(self) -> float:
        if self.start_ms is None:
            return 0.0
        t = (pygame.time.get_ticks() - self.start_ms) / self.duration_ms
        return 0.0 if t < 0 else (1.0 if t > 1.0 else t)

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
        hidden_ids = set()
        if not self.queue:
            return hidden_ids
        step = self.queue[0]
        if step.start_ms is None:
            step.start()

        t = ease_out(step.progress())

        # draw current anim
        if step.kind == "play_move":
            src: pygame.Rect = step.data["src"]
            dst: pygame.Rect = step.data["dst"]
            color = step.data.get("color", CARD_BG_HAND)
            lbl = step.data.get("label", "")
            x = int(lerp(src.x, dst.x, t))
            y = int(lerp(src.y, dst.y, t))
            r = pygame.Rect(x, y, CARD_W, CARD_H)
            pygame.draw.rect(screen, color, r, border_radius=8)
            if lbl:
                screen.blit(FONT.render(lbl, True, WHITE), (r.x+6, r.y+6))
            # optionally hide spawned minion until placed
            spawn_mid = step.data.get("spawn_mid")
            if spawn_mid:
                hidden_ids.add(spawn_mid)

        elif step.kind == "attack_dash":
            src: pygame.Rect = step.data["src"]
            dst: pygame.Rect = step.data["dst"]
            color = step.data.get("color", CARD_BG_MY)
            x = int(lerp(src.x, dst.x, t))
            y = int(lerp(src.y, dst.y, t))
            r = pygame.Rect(x, y, CARD_W, CARD_H)
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
                # SAFETY: never let a callback crash the loop
                try:
                    step.on_finish()
                except Exception as e:
                    print("Animation callback error:", repr(e))

        return hidden_ids

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
    # forward, then execute on_hit, then schedule return if still alive
    def after_forward(attacker_mid=attacker_mid, coll=coll, target_rect=target_rect):
        # safe engine call
        try:
            on_hit()
        except Exception as e:
            print("on_hit error:", repr(e))
        # recompute rects after damage
        post = layout_board(GLOBAL_GAME)
        if any(mid == attacker_mid for mid, _ in post[coll]):
            # go back to current spot
            back_dst = None
            for mid, rr in post[coll]:
                if mid == attacker_mid:
                    back_dst = rr
                    break
            if back_dst:
                ANIMS.push(AnimStep("attack_dash", ANIM_RETURN_MS, {"src": target_rect, "dst": back_dst,
                                                                    "color": CARD_BG_EN if enemy else CARD_BG_MY}))
    ANIMS.push(AnimStep("attack_dash", ANIM_ATTACK_MS,
                        {"src": src, "dst": target_rect, "color": CARD_BG_EN if enemy else CARD_BG_MY},
                        on_finish=after_forward))

def enqueue_play_anim(pre_hot, post_hot, from_rect: pygame.Rect, spawned_mid: Optional[int], label: str, is_enemy: bool):
    if spawned_mid:
        coll = "enemy_minions" if is_enemy else "my_minions"
        dst = None
        for mid, r in post_hot[coll]:
            if mid == spawned_mid:
                dst = r
                break
        if dst:
            ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS,
                                {"src": from_rect, "dst": dst, "label": label,
                                 "spawn_mid": spawned_mid,
                                 "color": CARD_BG_EN if is_enemy else CARD_BG_HAND}))

def enqueue_flash(rect: pygame.Rect):
    ANIMS.push(AnimStep("flash", ANIM_FLASH_MS, {"rect": rect}))

def enemy_face_rect(hot): return hot["face_enemy"]
def my_face_rect(hot):    return hot["face_me"]

# ------------- Main loop -------------

GLOBAL_GAME: Game

def start_game(seed=1337) -> Game:
    db = make_db()
    g = Game(db, STARTER_DECK.copy(), STARTER_DECK.copy(), seed=seed)
    apply_post_summon_hooks(g, g.start_game())
    return g

def main():
    global GLOBAL_GAME
    clock = pygame.time.Clock()
    g = start_game()
    GLOBAL_GAME = g

    selected_attacker: Optional[int] = None
    waiting_target_for_play: Optional[Tuple[int, str, pygame.Rect, bool]] = None  # (hand_index, card_id, from_rect, targeted)

    RUNNING = True
    while RUNNING:
        clock.tick(60)
        screen.fill(BG)
        hot = layout_board(g)

        draw_headers(g)
        hidden = ANIMS.update_and_draw(g, hot)
        draw_board(g, hot, hidden_minion_ids=hidden)

        # GG
        if g.players[0].health <= 0 or g.players[1].health <= 0:
            winner = "AI" if g.players[0].health <= 0 else "You"
            centered_text(f"Game over! {winner} wins. ESC to quit.", H//2 + 8)
            for event in pygame.event.get():
                if event.type == pygame.QUIT: RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: RUNNING = False
            pygame.display.flip()
            continue

        # --- AI turn (stepwise; animation-locked) ---
        if g.active_player == 1:
            # Only decide when not animating
            if not ANIMS.busy():
                # think pause
                def decide():
                    act, _ = pick_best_action(g, 1)
                    kind = act[0]

                    if kind == 'end':
                        def do_end():
                            try: g.end_turn(1)
                            except IllegalAction: pass
                        # tiny pause then end
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
                                # flash actual targets
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
                                                if mid2 == m2.id:
                                                    enqueue_flash(r2); break
                            except IllegalAction:
                                # ignore illegal (state may have changed mid-anim)
                                pass
                            except Exception as e:
                                print("AI play on_finish error:", repr(e))

                        # simple think pause + fly to approx slot then apply
                        dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ENEMY, CARD_W, CARD_H)
                        ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}))
                        ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS, {"src": src, "dst": dst, "label": g.cards_db[cid].name,
                                                                        "color": CARD_BG_EN}, on_finish=do_on_finish))

                    elif kind == 'attack':
                        _, aid, tp, tm = act
                        before = layout_board(g)
                        # attack your minion or your face (bottom)
                        if tm is not None:
                            tr = None
                            for mid, r in before["my_minions"]:
                                if mid == tm:
                                    tr = r; break
                            if tr is None:
                                tr = my_face_rect(before)
                        else:
                            tr = my_face_rect(before)

                        def on_hit(aid=aid, tpp=tp, tmm=tm):
                            try:
                                g.attack(1, attacker_id=aid, target_player=tpp, target_minion=tmm)
                            except IllegalAction:
                                return
                            except Exception as e:
                                print("AI attack on_hit error:", repr(e)); return
                            # flashes
                            post = layout_board(g)
                            if tmm is None:
                                enqueue_flash(my_face_rect(post))
                            else:
                                for mid, r in post["my_minions"]:
                                    if mid == tmm:
                                        enqueue_flash(r); break

                        enqueue_attack_anim(before, attacker_mid=aid, target_rect=tr, enemy=True, on_hit=on_hit)

                ANIMS.push(AnimStep("think_pause", AI_THINK_MS, {}, on_finish=decide))

            # drain events but lock inputs during AI time
            for event in pygame.event.get():
                if event.type == pygame.QUIT: RUNNING = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE: RUNNING = False

        # --- Human turn ---
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
                        continue

                    # Targeted play awaiting?
                    if waiting_target_for_play is not None:
                        idx, cid, src_rect, _ = waiting_target_for_play
                        # Face?
                        if enemy_face_rect(hot).collidepoint(mx, my):
                            def on_finish(i=idx):
                                try:
                                    ev = g.play_card(0, i, target_player=1)
                                    apply_post_summon_hooks(g, ev)
                                    post = layout_board(g); enqueue_flash(enemy_face_rect(post))
                                except IllegalAction: pass
                            dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ME, CARD_W, CARD_H)
                            ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS, {"src": src_rect, "dst": dst, "label": g.cards_db[cid].name}, on_finish=on_finish))
                            waiting_target_for_play = None
                            continue
                        # Minion target
                        for mid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my):
                                def on_finish(i=idx, mid_target=mid):
                                    try:
                                        ev = g.play_card(0, i, target_minion=mid_target)
                                        apply_post_summon_hooks(g, ev)
                                        enqueue_flash(r)
                                    except IllegalAction:
                                        pass
                                ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS, {"src": src_rect, "dst": r, "label": g.cards_db[cid].name}, on_finish=on_finish))
                                waiting_target_for_play = None
                                break
                        continue

                    # Click hand to play
                    clicked_hand = False
                    for i, cid, r in hot["hand"]:
                        if r.collidepoint(mx, my):
                            clicked_hand = True
                            if cid in ("FIREBALL_LITE", "KOBOLD_PING"):
                                waiting_target_for_play = (i, cid, r.copy(), True)
                            else:
                                def on_finish(i=i):
                                    try:
                                        ev = g.play_card(0, i)
                                        apply_post_summon_hooks(g, ev)
                                    except IllegalAction:
                                        pass
                                dst = pygame.Rect(W - (CARD_W + MARGIN), ROW_Y_ME, CARD_W, CARD_H)
                                ANIMS.push(AnimStep("play_move", ANIM_PLAY_MS, {"src": r.copy(), "dst": dst, "label": g.cards_db[cid].name}, on_finish=on_finish))
                            selected_attacker = None
                            break
                    if clicked_hand:
                        continue

                    # Select attacker
                    for mid, r in hot["my_minions"]:
                        if r.collidepoint(mx, my):
                            selected_attacker = mid
                            break

                    if selected_attacker is not None:
                        # Attack minion
                        did = False
                        for emid, r in hot["enemy_minions"]:
                            if r.collidepoint(mx, my):
                                def on_hit(attacker=selected_attacker, em=emid):
                                    try:
                                        g.attack(0, attacker, target_minion=em)
                                    except IllegalAction:
                                        pass
                                enqueue_attack_anim(hot, attacker_mid=selected_attacker, target_rect=r, enemy=False, on_hit=on_hit)
                                selected_attacker = None
                                did = True
                                break
                        if did:
                            continue
                        # Attack face (enemy top)
                        if enemy_face_rect(hot).collidepoint(mx, my):
                            def on_hit(attacker=selected_attacker):
                                try:
                                    g.attack(0, attacker, target_player=1)
                                except IllegalAction:
                                    return
                                post = layout_board(g); enqueue_flash(enemy_face_rect(post))
                            enqueue_attack_anim(hot, attacker_mid=selected_attacker, target_rect=enemy_face_rect(hot), enemy=False, on_hit=on_hit)
                            selected_attacker = None

        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
