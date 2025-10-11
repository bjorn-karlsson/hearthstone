# ai.py
from typing import Optional, Tuple, List
from engine import Game, IllegalAction

Action = Tuple[str, ...]  # ('end',) or ('play', idx, target_player, target_minion) or ('attack', attacker_id, target_player, target_minion)

# --- Card groups (update if you add new scripts) ---
HEAL_SPELLS       = {"HOLY_LIGHT_LITE"}           # spell: heal 6 any character
HEAL_BC_MINIONS   = {"EARTHEN_RING"}              # minion: battlecry heal 3 any character
DIRECT_FACE_DMGS  = {"FIREBALL_LITE"}             # direct face damage we can count for lethal
RANDOM_DMG_AOES   = {"ARCANE_MISSILES_LITE"}      # random split; we evaluate value
AOE_BOARD_WIPES   = {"CONSECRATION_LITE", "FLAMESTRIKE_LITE"}  # minion-clear biased
BUFF_MINION       = {"BLESSING_OF_MIGHT_LITE", "BLESSING_OF_KINGS_LITE", "GIVE_TAUNT", "GIVE_CHARGE", "GIVE_RUSH"}
HARD_DISABLE      = {"SILENCE_LITE", "POLYMORPH_LITE"}
DRAW_SPELLS       = {"ARCANE_INTELLECT_LITE", "ARCANE_INTELLECT"}
TOKEN_SUMMONERS   = {"MUSTER_FOR_BATTLE_LITE", "RAISE_WISPS", "FERAL_SPIRIT_LITE", "CHARGE_RUSH_2_2"}

# If you let AI see The Coin:
THE_COIN          = {"THE_COIN"}

# ----------------- Small helpers -----------------

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
        return True  # engine prevents face on-summon for Rush
    return False

def _ally_minions(g: Game, pid: int):
    return [m for m in g.players[pid].board if m.is_alive()]

def _enemy_minions(g: Game, pid: int):
    return [m for m in g.players[1 - pid].board if m.is_alive()]

# ----------------- Target/value heuristics -----------------

def threat_score_enemy_minion(m) -> int:
    # Higher is more threatening
    kw_bonus = (6 if getattr(m, "taunt", False) else 0) \
             + (4 if getattr(m, "charge", False) else 0) \
             + (3 if getattr(m, "rush", False) else 0)
    # Use original card cost if present; else approximate by stats
    cost_hint = getattr(m, "cost", 0)
    stat_val  = m.attack * 3 + m.max_health * 2
    return stat_val + kw_bonus + cost_hint * 2

def value_score_friendly_minion_for_buff(m, spell_id: str) -> int:
    # We like buffing minions that already have decent attack or protective keywords
    kw_bonus = (8 if getattr(m, "taunt", False) else 0) \
             + (3 if getattr(m, "charge", False) else 0) \
             + (2 if getattr(m, "rush", False) else 0)
    # extra nudge per buff type
    nudge = 0
    if spell_id == "BLESSING_OF_MIGHT_LITE": nudge += 5
    if spell_id == "BLESSING_OF_KINGS_LITE": nudge += 7
    if spell_id in {"GIVE_TAUNT", "GIVE_CHARGE", "GIVE_RUSH"}: nudge += 6
    return m.attack * 4 + m.max_health + kw_bonus + nudge + getattr(m, "cost", 0)

def best_enemy_to_silence_or_poly(g: Game, pid: int) -> Optional[int]:
    candidates = _enemy_minions(g, pid)
    if not candidates:
        return None
    target = max(candidates, key=threat_score_enemy_minion)
    return target.id

def best_friendly_to_buff(g: Game, pid: int, spell_id: str) -> Optional[int]:
    allies = _ally_minions(g, pid)
    if not allies:
        return None
    target = max(allies, key=lambda m: value_score_friendly_minion_for_buff(m, spell_id))
    return target.id

def best_heal_target(g: Game, pid: int, heal_amount: int) -> Tuple[Optional[int], Optional[int], int]:
    """
    Returns (target_player, target_minion, score).
    Pick the ally character (face or minion) that gains the most effective health.
    """
    p = g.players[pid]
    best_tp, best_tm, best_score = None, None, -1

    # Face
    missing_face = max(0, 30 - p.health)
    if missing_face > 0:
        eff = min(heal_amount, missing_face)
        score = eff * 8 + (10 if p.health <= 15 else 0)
        if score > best_score:
            best_tp, best_tm, best_score = pid, None, score

    # Damaged ally minions
    for m in p.board:
        if not m.is_alive():
            continue
        missing = max(0, m.max_health - m.health)
        if missing <= 0:
            continue
        eff   = min(heal_amount, missing)
        bonus = (8 if m.taunt else 0) + m.attack + getattr(m, "cost", 0)
        score = eff * 7 + bonus
        if score > best_score:
            best_tp, best_tm, best_score = None, m.id, score

    return best_tp, best_tm, best_score

# ----------------- Play gating (do nothing if useless) -----------------

def has_useful_play_for_card(g: Game, pid: int, cid: str) -> Optional[Tuple[int, Optional[int], Optional[int], int]]:
    """
    Returns a tuple (hand_index, target_player, target_minion, value_score)
    *only if* the card has a meaningful effect right now. Otherwise returns None.
    Chooses the *best* target when applicable.
    """
    p = g.players[pid]
    # find card index (first match)
    try:
        idx = next(i for i, x in enumerate(p.hand) if x == cid)
    except StopIteration:
        return None

    card = g.cards_db[cid]
    if card.cost > p.mana:
        return None

    # Heals
    if cid in HEAL_SPELLS:
        tp, tm, sc = best_heal_target(g, pid, 6)
        if tp is None and tm is None:
            return None
        return idx, tp, tm, sc + 400

    if cid in HEAL_BC_MINIONS:
        if len(p.board) >= 7:    # no room => pointless
            return None
        tp, tm, sc = best_heal_target(g, pid, 3)
        if tp is None and tm is None:
            return None
        return idx, tp, tm, sc + 300

    # Buffs: require at least one ally on board
    if cid in BUFF_MINION:
        tm = best_friendly_to_buff(g, pid, cid)
        if tm is None:
            return None
        # modest value; tweaked by spell identity
        base = 60 if cid == "BLESSING_OF_MIGHT_LITE" else 85 if cid == "BLESSING_OF_KINGS_LITE" else 70
        return idx, None, tm, base + 2 * getattr(g.find_minion(tm)[2], "attack", 0)

    # Silence / Polymorph: require an enemy
    if cid in HARD_DISABLE:
        tm = best_enemy_to_silence_or_poly(g, pid)
        if tm is None:
            return None
        return idx, None, tm, 120 + threat_score_enemy_minion(g.find_minion(tm)[2])

    # Direct damage: Fireball (prefer lethal or premium removal)
    if cid in DIRECT_FACE_DMGS:
        opp = 1 - pid
        can_go_face = can_face(g, pid)
        # lethal check vs face
        if can_go_face and g.players[opp].health <= 6:
            return idx, opp, None, 1000
        # premium removal: pick best enemy we can kill with 6 dmg
        enemies = _enemy_minions(g, pid)
        killables = [m for m in enemies if m.health <= 6]
        if killables:
            target = max(killables, key=threat_score_enemy_minion)
            return idx, None, target.id, 250 + threat_score_enemy_minion(target)
        # else keep it for later (don’t waste)
        return None

    # Random missiles: require enough value (more enemies -> better)
    if cid in RANDOM_DMG_AOES:
        enemies = _enemy_minions(g, pid)
        if not enemies and not can_face(g, pid):
            return None  # would hit nothing “significant”
        # rough value: sum of min(3, total enemy hp) and small face chip if open
        total_hp = sum(m.health for m in enemies)
        face_bonus = 6 if can_face(g, pid) else 0
        v = min(3, total_hp) * 20 + face_bonus
        if v < 30:
            return None
        return idx, None, None, 60 + v

    # AoE wipes: prefer when we hit at least 2 units or a lot of hp
    if cid in AOE_BOARD_WIPES:
        enemies = _enemy_minions(g, pid)
        if not enemies:
            return None
        if cid == "CONSECRATION_LITE":
            hits = len(enemies)
            total = sum(1 for m in enemies if m.health <= 2)
            score = 70 + hits * 25 + total * 15
            if hits >= 2 or total >= 1:
                return idx, None, None, score
            return None
        if cid == "FLAMESTRIKE_LITE":
            hits = len([m for m in enemies if m.health <= 4])
            score = 90 + hits * 40 + len(enemies) * 10
            if hits >= 2:
                return idx, None, None, score
            return None

    # Draw spells: generally ok unless hand is near full
    if cid in DRAW_SPELLS:
        if len(p.hand) >= 9:  # avoid burns
            return None
        return idx, None, None, 65

    # Token / summoning spells: ensure board space
    if cid in TOKEN_SUMMONERS:
        if len(p.board) >= 7:
            return None
        return idx, None, None, 70

    # Generic minions: ensure space
    if card.type == "MINION":
        if len(p.board) >= 7:
            return None
        # value: prefer spending mana efficiently and higher stats
        stat_val = card.attack * 3 + card.health * 2
        curve_val = min(card.cost, g.players[pid].mana) * 8
        return idx, None, None, 60 + stat_val + curve_val

    # Unknown card: be conservative
    return None

# ----------------- LETHAL PLANNER -----------------

def direct_damage_in_hand(g: Game, pid: int) -> int:
    dmg = 0
    p = g.players[pid]
    for cid in p.hand:
        if cid == "FIREBALL_LITE" and g.cards_db[cid].cost <= p.mana:
            dmg += 6
            # NOTE: if you have multiple Fireballs and enough mana for both,
            # this simple count underestimates — next frame will re-evaluate after the first cast.
    return dmg

def ready_face_damage(g: Game, pid: int) -> int:
    if not can_face(g, pid):
        return 0
    total = 0
    for m in _ally_minions(g, pid):
        if not minion_ready(m):
            continue
        # Rush can’t hit face on summon – engine also enforces it,
        # but we make the intent clear here.
        if getattr(m, "rush", False) and getattr(m, "summoned_this_turn", True):
            continue
        total += m.attack
    return total

def find_lethal_action(g: Game, pid: int) -> Optional[Tuple[Action, int]]:
    opp = 1 - pid
    face_now = ready_face_damage(g, pid)
    spell_now = direct_damage_in_hand(g, pid)
    if face_now + spell_now >= g.players[opp].health and (face_now > 0 or spell_now > 0):
        # Prefer an immediate face attack if we have it; otherwise cast a burn spell at face
        # 1) Attack with any ready attacker
        if face_now > 0:
            for m in _ally_minions(g, pid):
                if minion_ready(m):
                    if not (getattr(m, "rush", False) and getattr(m, "summoned_this_turn", True)):
                        return (('attack', m.id, opp, None), 10_000)
        # 2) Else cast burn to face
        p = g.players[pid]
        for i, cid in enumerate(p.hand):
            if cid == "FIREBALL_LITE" and g.cards_db[cid].cost <= p.mana:
                return (('play', i, opp, None), 9_000)
    return None

# ----------------- ATTACK PICKER (trades first) -----------------

def pick_attack(g: Game, pid: int) -> Optional[Tuple[Action, int]]:
    opp = 1 - pid
    # Value trades first
    for a in _ally_minions(g, pid):
        if not minion_ready(a):
            continue
        taunts = [m for m in _enemy_minions(g, pid) if m.taunt]
        pool = taunts if taunts else _enemy_minions(g, pid)
        best = None
        best_score = -1
        for m in pool:
            kill_enemy = a.attack >= m.health
            die_self   = m.attack >= a.health
            # weight enemy’s threat & cost
            m_val = threat_score_enemy_minion(m)
            score = 0
            if kill_enemy and not die_self:
                score = 200 + m_val
            elif kill_enemy and die_self:
                score = 120 + int(m_val * 0.6)
            else:
                # chip: prefer softening high-threat targets
                score = 40 + min(a.attack, m.health) + int(m_val * 0.1)
            if score > best_score:
                best, best_score = m, score
        if best is not None:
            return (('attack', a.id, None, best.id), best_score)

    # If no good trades or nothing to hit, go face when allowed
    if can_face(g, pid):
        for a in _ally_minions(g, pid):
            if not minion_ready(a):
                continue
            if getattr(a, "rush", False) and getattr(a, "summoned_this_turn", True):
                continue
            return (('attack', a.id, opp, None), 80 + a.attack)
    return None

# ----------------- DEVELOPMENT / CASTS -----------------

def pick_best_play(g: Game, pid: int) -> Optional[Tuple[Action, int]]:
    """
    Consider all cards in hand and select the *useful* one with the highest value.
    Also (optionally) consider spending The Coin if it unlocks a strictly better play.
    """
    p = g.players[pid]
    best = None
    best_score = -1

    # direct pass: useful cards only
    for i, cid in enumerate(p.hand):
        usable = has_useful_play_for_card(g, pid, cid)
        if not usable:
            continue
        idx, tp, tm, score = usable
        if score > best_score:
            best_score = score
            best = ('play', idx, tp, tm)

    # Optional: Coin trick — if we have The Coin and it unlocks a significantly better play
    if any(c in THE_COIN for c in p.hand):
        # simulate +1 mana budget and scan again
        mana_now = p.mana
        p.mana += 1
        try:
            coin_best = None
            coin_score = -1
            for i, cid in enumerate(p.hand):
                if cid in THE_COIN:
                    continue
                usable = has_useful_play_for_card(g, pid, cid)
                if not usable:
                    continue
                _, tp, tm, score = usable
                if score > coin_score:
                    coin_score = score
                    coin_best = (cid, tp, tm)
            # If using Coin yields a *much* better play, do it
            if coin_best and coin_score >= best_score + 40:
                # First, play Coin
                coin_idx = next(i for i, x in enumerate(p.hand) if x in THE_COIN)
                return (('play', coin_idx, None, None), coin_score + 1)  # next frame will use the unlocked play
        finally:
            p.mana = mana_now

    if best is not None:
        return (best, best_score)
    return None

# ----------------- TOP-LEVEL POLICY -----------------

def pick_best_action(g: Game, pid: int) -> Tuple[Action, int]:
    """
    Priority: lethal -> best attack/trade -> best useful play (spells/minions) -> end.
    Also *never* casts a spell that does nothing.
    """

    # 0) Lethal now?
    lethal = find_lethal_action(g, pid)
    if lethal:
        return lethal

    # 1) Trades / attacks
    att = pick_attack(g, pid)
    if att:
        return att

    # 2) Best *useful* play (development / removal / buffs / etc.)
    play = pick_best_play(g, pid)
    if play:
        return play

    # 3) Nothing else
    return ('end',), 0
