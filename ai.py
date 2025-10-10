# ai.py
from typing import Optional, Tuple, List
from engine import Game, IllegalAction

Action = Tuple[str, ...]  # ('end',) or ('play', idx, target_player, target_minion) or ('attack', attacker_id, target_player, target_minion)

HEAL_SPELLS = {"HOLY_LIGHT_LITE"}      # heals 6, any character
HEAL_BC_MINIONS = {"EARTHEN_RING"}     # battlecry heal 3, any character

def can_face(g: Game, pid: int) -> bool:
    opp = 1 - pid
    return not any(m.taunt and m.is_alive() for m in g.players[opp].board)

def minion_ready(m) -> bool:
    if m.attack <= 0 or m.has_attacked_this_turn or not m.is_alive():
        return False
    if not getattr(m, "summoned_this_turn", True):
        return True
    if getattr(m, "charge", False):
        return True
    if getattr(m, "rush", False):
        # rush can only hit minions; UI/legal guards face later
        return True
    return False

# ---------- HEAL TARGETING ----------

def best_heal_target(g: Game, pid: int, heal_amount: int) -> Tuple[Optional[int], Optional[int], int]:
    """
    Returns (target_player, target_minion, score).
    Pick the ally character (face or minion) that gains the most effective health.
    """
    p = g.players[pid]
    best_tp, best_tm, best_score = None, None, -1

    # Ally face if below 24 gets priority comparable to saving a minion
    missing_face = max(0, 30 - p.health)
    if missing_face > 0:
        eff = min(heal_amount, missing_face)
        score = eff * 8 + (10 if p.health <= 15 else 0)
        if score > best_score:
            best_tp, best_tm, best_score = pid, None, score

    # Damaged ally minions – prefer taunts / high attack / about to trade
    for m in p.board:
        if not m.is_alive(): 
            continue
        missing = max(0, m.max_health - m.health)
        if missing <= 0:
            continue
        eff = min(heal_amount, missing)
        # heuristics: value taunts and higher attack
        bonus = (8 if m.taunt else 0) + m.attack
        score = eff * 7 + bonus
        if score > best_score:
            best_tp, best_tm, best_score = None, m.id, score

    return best_tp, best_tm, best_score

def pick_best_heal_play(g: Game, pid: int) -> Optional[Tuple[Action, int]]:
    p = g.players[pid]
    # 1) Holy Light (spell heal 6)
    for i, cid in enumerate(p.hand):
        if cid in HEAL_SPELLS and g.cards_db[cid].cost <= p.mana:
            tp, tm, sc = best_heal_target(g, pid, heal_amount=6)
            if tp is not None or tm is not None:
                return (('play', i, tp, tm), sc + 400)  # high preference if useful

    # 2) Earthen Ring (minion with battlecry heal 3)
    for i, cid in enumerate(p.hand):
        if cid in HEAL_BC_MINIONS and g.cards_db[cid].cost <= p.mana:
            tp, tm, sc = best_heal_target(g, pid, heal_amount=3)
            if tp is not None or tm is not None:
                # prefer if board slot available
                if len(p.board) < 7:
                    return (('play', i, tp, tm), sc + 300)
    return None

# ---------- ATTACK CHOICES ----------

def pick_attack(g: Game, pid: int) -> Optional[Tuple[Action, int]]:
    opp = 1 - pid
    # try value trades first
    for a in g.players[pid].board:
        if not minion_ready(a):
            continue
        # legal enemy targets
        enemy_taunts = [m for m in g.players[opp].board if m.taunt and m.is_alive()]
        pool = enemy_taunts if enemy_taunts else [m for m in g.players[opp].board if m.is_alive()]
        # evaluate trades: kill without dying > mutual death > chip
        best = None
        best_score = -1
        for m in pool:
            # quick outcome eval
            kill_enemy = a.attack >= m.health
            die_self   = m.attack >= a.health
            score = 0
            if kill_enemy and not die_self: score = 120 + m.attack * 5 + m.health
            elif kill_enemy and die_self:   score = 70  + m.attack * 4
            elif not kill_enemy and not die_self: score = 25 + min(a.attack, m.health)
            if score > best_score:
                best, best_score = m, score
        if best is not None:
            return (('attack', a.id, None, best.id), best_score)

    # if no good trades or nothing to hit, go face when allowed
    if can_face(g, pid):
        for a in g.players[pid].board:
            if not minion_ready(a):
                continue
            # rush cannot go face on summon; engine will also guard, but keep here
            if getattr(a, "rush", False) and getattr(a, "summoned_this_turn", True):
                continue
            return (('attack', a.id, opp, None), 60 + a.attack)
    return None

# ---------- PLAY NON-TARGETED / BOARD DEVELOPMENT ----------

def pick_dev_play(g: Game, pid: int) -> Optional[Tuple[Action, int]]:
    p = g.players[pid]
    best = None
    best_score = -1
    for i, cid in enumerate(p.hand):
        card = g.cards_db[cid]
        if card.cost > p.mana:
            continue
        # skip targeted cards here (they are handled elsewhere)
        if cid in HEAL_SPELLS or cid in HEAL_BC_MINIONS:
            continue
        # very rough value: minions > draw > damage if face reachable
        score = 0
        if card.type == "MINION" and len(p.board) < 7:
            score = 50 + card.attack * 3 + card.health * 2 + (8 if "Taunt" in card.keywords else 0) + (6 if "Charge" in card.keywords else 0)
            best = ('play', i, None, None)
        elif cid == "ARCANE_INTELLECT_LITE":
            score = 55
            best = ('play', i, None, None)
        elif cid == "FIREBALL_LITE":
            # keep for removal or face if lethal-ish
            if can_face(g, pid) and g.players[1 - pid].health <= 6:
                score = 80
                best = ('play', i, 1 - pid, None)
            else:
                # leave evaluation lower; removal is handled by attack/trade phase
                score = 35
                best = ('play', i, None, None)  # engine will default to enemy face if no target passed
        elif cid in ("CONSECRATION_LITE", "FLAMESTRIKE_LITE", "ARCANE_MISSILES_LITE", "MUSTER_FOR_BATTLE_LITE",
                     "RAISE_WISPS", "FERAL_SPIRIT_LITE", "CHARGE_RUSH_2_2", "GIVE_TAUNT", "GIVE_CHARGE", "GIVE_RUSH",
                     "BLESSING_OF_MIGHT_LITE", "BLESSING_OF_KINGS_LITE", "SILENCE_LITE", "POLYMORPH_LITE"):
            score = 40  # generic development/removal; your deck scripts handle effect
            best = ('play', i, None, None)

        if score > best_score and best is not None:
            best_score = score
            best_action = best
    if best_score >= 0:
        return (best_action, best_score)
    return None

# ---------- TOP-LEVEL PICK ----------

def pick_best_action(g: Game, pid: int) -> Tuple[Action, int]:
    """
    Returns the single best action for this turn step.
    Priority: lethal -> heal if valuable -> good attack -> develop board -> end.
    """
    # 0) If we can finish the opponent with ready attacks, try it
    if can_face(g, pid):
        face_dmg = sum(m.attack for m in g.players[pid].board
                       if minion_ready(m))
        if face_dmg >= g.players[1 - pid].health:
            # swing with the first ready minion, rest will follow on next frames
            for m in g.players[pid].board:
                if minion_ready(m):
                    return ('attack', m.id, 1 - pid, None), 10_000

    # 1) Healing if useful
    hp = g.players[pid].health
    allies_damaged = any(m.is_alive() and m.health < m.max_health for m in g.players[pid].board)
    if hp < 26 or allies_damaged:
        heal = pick_best_heal_play(g, pid)
        if heal:
            return heal

    # 2) Trades / attacks
    att = pick_attack(g, pid)
    if att:
        return att

    # 3) Develop / cast non-targeted stuff
    dev = pick_dev_play(g, pid)
    if dev:
        return dev

    # 4) Nothing else: end turn
    return ('end',), 0
