# ai.py
from typing import Tuple, Optional, List
from engine import Game, IllegalAction

# Lightweight utility: safely simulate a command on a *copy* of the game.
def clone_game(g: Game) -> Game:
    import copy
    # shallow copy won't cut it; do a deep copy (cards_db is static)
    g2 = copy.deepcopy(g)
    g2.cards_db = g.cards_db  # keep reference to shared db
    return g2

def _card_needs_target(cid: str) -> bool:
    targeted = {
        "FIREBALL_LITE","KOBOLD_PING","HOLY_LIGHT_LITE","BLESSING_OF_MIGHT_LITE",
        "BLESSING_OF_KINGS_LITE","SILENCE_LITE","POLYMORPH_LITE","GIVE_TAUNT",
        "GIVE_CHARGE","GIVE_RUSH","SWIPE_LITE"
    }
    return cid in targeted

def _legal_targets(g: Game, pid: int, cid: str) -> List[Tuple[Optional[int], Optional[int]]]:
    """Return list of (target_player, target_minion). None/None = no target."""
    c = g.cards_db[cid]
    if c.type != "SPELL" and c.type != "MINION":
        return [(None,None)]
    # MINION with battlecry target?
    if c.type == "MINION" and c.battlecry is None:
        return [(None,None)]
    # Map by our UI helper rules
    opp = 1 - pid
    r = []
    if cid == "FIREBALL_LITE" or cid == "KOBOLD_PING":
        # enemy minion ids and enemy face
        for m in g.players[opp].board:
            if m.is_alive(): r.append((None, m.id))
        r.append((opp, None))
        return r
    if cid == "HOLY_LIGHT_LITE":
        # any minion or either face
        for m in g.players[0].board:
            if m.is_alive(): r.append((None, m.id))
        for m in g.players[1].board:
            if m.is_alive(): r.append((None, m.id))
        r.append((0, None)); r.append((1, None))
        return r
    if cid in ("BLESSING_OF_MIGHT_LITE","BLESSING_OF_KINGS_LITE","GIVE_TAUNT","GIVE_CHARGE","GIVE_RUSH"):
        for m in g.players[pid].board:
            if m.is_alive(): r.append((None, m.id))
        return r
    if cid in ("SILENCE_LITE","POLYMORPH_LITE","SWIPE_LITE"):
        for m in g.players[opp].board:
            if m.is_alive(): r.append((None, m.id))
        return r
    # default: no target
    return [(None,None)]

def _score_state(g: Game, pid: int) -> int:
    """Crude heuristic: my hp/armor + board stats – opp hp/armor/board."""
    me, opp = g.players[pid], g.players[1-pid]
    def board_score(p):
        s = 0
        for m in p.board:
            if not m.is_alive(): continue
            s += m.attack*2 + m.health
            if m.taunt: s += 2
            if m.charge or m.rush: s += 1
        return s
    return (me.health + me.armor + board_score(me)) - (opp.health + opp.armor + board_score(opp))

def _try(g: Game, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except IllegalAction:
        return None

def _find_lethal(g: Game, pid: int):
    """Very simple: if I can kill face with any combination of direct-damage spells + attacks right now."""
    opp = 1 - pid
    # Available direct damage spells
    dmg_spells = []
    for i, cid in enumerate(g.players[pid].hand):
        c = g.cards_db[cid]
        if c.type == "SPELL" and cid in ("FIREBALL_LITE", "ARCANE_MISSILES_LITE", "CONSECRATION_LITE"):
            dmg_spells.append((i, cid))
    # Attacks that can go face (respect Taunt handled by engine)
    face_attackers = []
    for m in g.players[pid].board:
        if m.attack > 0 and not m.has_attacked_this_turn:
            face_attackers.append(m)
    # quick optimistic check
    approx = sum(m.attack for m in face_attackers) + 4*sum(1 for _,cid in dmg_spells if cid=="FIREBALL_LITE")
    if g.players[opp].health - approx > 0:
        return None

    # Try greedily: cast damage spells to face, then attack face with all
    sim = clone_game(g)
    # cast spells
    for i, cid in list(dmg_spells):
        c = sim.cards_db[cid]
        if cid == "FIREBALL_LITE":
            if _try(sim, sim.play_card, pid, i, target_player=1-pid) is None: 
                continue
        elif cid == "ARCANE_MISSILES_LITE":
            if _try(sim, sim.play_card, pid, i) is None:
                continue
        elif cid == "CONSECRATION_LITE":
            if _try(sim, sim.play_card, pid, i) is None:
                continue
    # attack face
    for m in list(sim.players[pid].board):
        _try(sim, sim.attack, pid, m.id, target_player=1-pid)
    if sim.players[1-pid].health <= 0:
        # Return a first lethal action from original g (spell or attack)
        # choose a face-damaging move available now
        # 1) a direct face spell if any
        for i, cid in dmg_spells:
            if cid == "FIREBALL_LITE":
                return ('play', i, 1-pid, None)
            if cid in ("ARCANE_MISSILES_LITE","CONSECRATION_LITE"):
                return ('play', i, None, None)
        # 2) otherwise, attack face with any attacker
        for m in g.players[pid].board:
            if _try(g, g.attack, pid, m.id, target_player=1-pid) is not None:
                return ('attack', m.id, 1-pid, None)
    return None

def pick_best_action(g: Game, pid: int):
    """
    Returns a tuple (action, score):
      action = ('end',) or ('play', hand_index, target_player, target_minion) or ('attack', attacker_minion_id, target_player, target_minion)
    """
    # 1) Lethal now?
    lethal = _find_lethal(g, pid)
    if lethal:
        return lethal, 10_000

    best = ('end',)
    best_score = -10**9
    opp = 1 - pid

    # 2) Consider plays
    for i, cid in enumerate(g.players[pid].hand):
        c = g.cards_db[cid]
        if g.players[pid].mana < c.cost:
            continue
        if _card_needs_target(cid):
            for (tp, tm) in _legal_targets(g, pid, cid):
                sim = clone_game(g)
                if _try(sim, sim.play_card, pid, i, target_player=tp, target_minion=tm) is None:
                    continue
                s = _score_state(sim, pid)
                # prefer value: damage/buffs that swing board; small bias for tempo
                if s > best_score:
                    best = ('play', i, tp, tm)
                    best_score = s
        else:
            sim = clone_game(g)
            if _try(sim, sim.play_card, pid, i) is None:
                continue
            s = _score_state(sim, pid)
            if s > best_score:
                best = ('play', i, None, None)
                best_score = s

    # 3) Consider attacks (prefer good trades; face only if no good trades)
    had_good_trade = False
    for m in g.players[pid].board:
        if m.attack <= 0 or m.has_attacked_this_turn or not m.is_alive():
            continue
        # try vs enemy minions first
        for em in g.players[opp].board:
            if not em.is_alive(): continue
            sim = clone_game(g)
            if _try(sim, sim.attack, pid, m.id, target_minion=em.id) is None:
                continue
            # good trade heuristic: kill or at least not die for nothing
            killed = not any(mm.id == em.id and mm.is_alive() for mm in sim.players[opp].board)
            survived = any(mm.id == m.id and mm.is_alive() for mm in sim.players[pid].board)
            s = _score_state(sim, pid) + (6 if killed else 0) + (2 if survived else 0)
            if s > best_score:
                best = ('attack', m.id, None, em.id)
                best_score = s
                had_good_trade = True
    # face if we didn't find strong trades
    if not had_good_trade:
        for m in g.players[pid].board:
            sim = clone_game(g)
            if _try(sim, sim.attack, pid, m.id, target_player=opp) is None:
                continue
            s = _score_state(sim, pid)
            # small aggression bonus if we already lead on board
            if s > best_score - 1:
                best = ('attack', m.id, opp, None)
                best_score = s

    return best, best_score