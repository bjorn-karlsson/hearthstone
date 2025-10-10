"""
Simple AI for the engine:
- Generates candidate actions (play cards, attack with minions, end turn).
- Simulates each on a deepcopy, evaluates result, picks the best (greedy).
- Prefers lethal; otherwise maximizes board + health advantage.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
import copy

from engine import Game, IllegalAction, apply_post_summon_hooks

# Action encoding
# ('play', hand_index, target_player, target_minion)
# ('attack', attacker_id, target_player, target_minion)
# ('end',)

def evaluate(g: Game, pid: int) -> float:
    """Heuristic: own HP, tempo, board stats, slight hand size; subtract opponent."""
    me = g.players[pid]
    op = g.players[1 - pid]

    def board_score(p):
        s = 0.0
        for m in p.board:
            if not m.is_alive():
                continue
            s += m.attack * 1.8 + m.health * 0.9
            if m.taunt: s += 1.0
            if not m.summoned_this_turn and not m.has_attacked_this_turn:
                s += 0.5  # ready to act
        return s

    score = 0.0
    score += me.health * 2.0 - op.health * 2.2  # value enemy HP slightly higher (push face when good)
    score += board_score(me) - board_score(op)
    score += 0.1 * (len(me.hand) - len(op.hand))
    score += 0.05 * (me.mana - op.mana)
    # Sudden death bonus if someone is at/below 0 handled by real defeat elsewhere
    return score

def clone_and_apply(g: Game, action: Tuple) -> Optional[Game]:
    newg = copy.deepcopy(g)
    pid = newg.active_player
    try:
        if action[0] == 'play':
            _, idx, tp, tm = action
            ev = newg.play_card(pid, idx, target_player=tp, target_minion=tm)
            apply_post_summon_hooks(newg, ev)
        elif action[0] == 'attack':
            _, aid, tp, tm = action
            newg.attack(pid, attacker_id=aid, target_player=tp, target_minion=tm)
        elif action[0] == 'end':
            newg.end_turn(pid)
        else:
            return None
        return newg
    except IllegalAction:
        return None

def _card_needs_target(g: Game, cid: str) -> bool:
    # In our tiny set: Fireball lite needs (optional) target; Kobold Pinger BC benefits from target.
    # We will still try face by default if no minions.
    return cid in ("FIREBALL_LITE", "KOBOLD_PING")

def generate_actions(g: Game) -> List[Tuple]:
    pid = g.active_player
    me = g.players[pid]
    opid = 1 - pid
    actions: List[Tuple] = []

    # Plays
    for i, cid in enumerate(me.hand):
        card = g.cards_db[cid]
        if card.cost > me.mana:
            continue
        if card.type == "MINION":
            # With or without BC target
            if _card_needs_target(g, cid):
                # Try targeting best enemy minion, else face
                enemy_minions = [m for m in g.players[opid].board if m.is_alive()]
                # Prefer low-health killable minions
                for m in sorted(enemy_minions, key=lambda m: (m.health, -m.attack)):
                    actions.append(('play', i, None, m.id))
                actions.append(('play', i, opid, None))  # face ping if allowed
            else:
                actions.append(('play', i, None, None))
        else:  # SPELL
            if _card_needs_target(g, cid):
                enemy_minions = [m for m in g.players[opid].board if m.is_alive()]
                for m in sorted(enemy_minions, key=lambda m: (m.health, -m.attack)):
                    actions.append(('play', i, None, m.id))
                actions.append(('play', i, opid, None))
            else:
                actions.append(('play', i, None, None))

    # Attacks (try all legal pairings; illegal ones get filtered in simulation)
    for m in me.board:
        if not m.is_alive() or m.has_attacked_this_turn:
            continue
        # Try enemy minions first (respect taunts via engine)
        for em in g.players[opid].board:
            if not em.is_alive():
                continue
            actions.append(('attack', m.id, None, em.id))
        # Try face
        actions.append(('attack', m.id, opid, None))

    # Always allow end turn
    actions.append(('end',))
    return actions

def pick_best_action(g: Game, pid: int) -> Tuple[Tuple, Optional[Game]]:
    """Greedy one-ply: lethal > best eval."""
    best = None
    best_g = None
    best_score = -1e18

    for act in generate_actions(g):
        ng = clone_and_apply(g, act)
        if ng is None:
            continue
        # If lethal achieved right now, prioritize immediately
        if ng.players[1 - pid].health <= 0:
            return act, ng
        sc = evaluate(ng, pid)
        if sc > best_score:
            best_score, best, best_g = sc, act, ng
    return (best if best else ('end',)), best_g

def play_full_turn(g: Game, pid: int, max_steps: int = 10):
    """Let AI take up to max_steps actions; stops on end-turn or when no progress."""
    steps = 0
    while g.active_player == pid and steps < max_steps:
        act, ng = pick_best_action(g, pid)
        if act[0] == 'end' or ng is None:
            # end the turn
            try:
                g.end_turn(pid)
            except IllegalAction:
                break
            return
        # apply on real game
        # We re-run the act on real game to get real events & IDs
        try:
            if act[0] == 'play':
                _, idx, tp, tm = act
                ev = g.play_card(pid, idx, target_player=tp, target_minion=tm)
                apply_post_summon_hooks(g, ev)
            elif act[0] == 'attack':
                _, aid, tp, tm = act
                g.attack(pid, attacker_id=aid, target_player=tp, target_minion=tm)
        except IllegalAction:
            # If something changed race-condition-like, just end turn
            try:
                g.end_turn(pid)
            except IllegalAction:
                pass
            return
        steps += 1
    # Safety end
    if g.active_player == pid:
        try:
            g.end_turn(pid)
        except IllegalAction:
            pass
