# ai.py
from typing import Optional, Tuple, List, Dict, Any
from engine import Game, IllegalAction

Action = Tuple[str, ...]  # ('end',) or ('play', idx, target_player, target_minion) or ('attack', attacker_id, target_player, target_minion)


# If you let AI see The Coin:
THE_COIN          = {"THE_COIN"}



def _raw(g: Game, cid: str) -> Dict[str, Any]:
    return g.cards_db.get("_RAW", {}).get(cid, {})

def _card_effects(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    # prefer on_cast for spells, battlecry for minions; support both
    effs = []
    if isinstance(raw.get("on_cast"), list):
        effs += raw["on_cast"]
    if isinstance(raw.get("battlecry"), list):
        effs += raw["battlecry"]
    return effs

def classify_card(g: Game, cid: str) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (kind, info) where kind in:
      'heal','buff','disable','burn','aoe','random_dmg','draw','summon','generic_minion','unknown'
    """
    raw = _raw(g, cid)
    card = g.cards_db[cid]
    effs = _card_effects(raw)

    # scan effects
    has = lambda name: any(e.get("effect") == name for e in effs)
    get_first = lambda name, key, default=0: next((int(e.get(key, default)) for e in effs if e.get("effect")==name and isinstance(e.get(key, None),(int,str))), default)

    if has("heal"):
        amt = get_first("heal", "amount", 0)
        return "heal", {"amount": amt, "targeting": raw.get("targeting", "").lower()}
    if has("add_stats") or has("add_attack") or has("add_keyword"):
        return "buff", {"targeting": raw.get("targeting", "").lower()}
    if has("silence") or has("transform"):
        return "disable", {"targeting": raw.get("targeting", "").lower()}
    if has("aoe_damage") or has("aoe_damage_minions"):
        amt = get_first("aoe_damage", "amount", get_first("aoe_damage_minions","amount",0))
        return "aoe", {"amount": amt}
    if has("random_pings"):
        cnt = get_first("random_pings", "count", 0)
        return "random_dmg", {"count": cnt}
    if has("deal_damage"):
        amt = get_first("deal_damage", "amount", 0)
        tgt = next((e.get("target") for e in effs if e.get("effect")=="deal_damage" and "target" in e), None)
        return "burn", {"amount": amt, "target": (tgt or raw.get("targeting","")).lower()}
    if has("draw"):
        cnt = get_first("draw","count",1)
        return "draw", {"count": cnt}
    if has("summon"):
        # rough count (multiple 'summon' effects add up)
        total = 0
        for e in effs:
            if e.get("effect") == "summon":
                total += int(e.get("count", 1))
        return "summon", {"count": total}

    if card.type == "MINION":
        return "generic_minion", {"attack": card.attack, "health": card.health, "cost": card.cost}

    return "unknown", {}

# --- Hero power gating/usage for AI ---

def can_use_hero_power_ai(g: Game, pid: int) -> bool:
    """Copy of the UI gating but engine-only; avoids importing UI code."""
    p = g.players[pid]
    cost = getattr(p.hero.power, "cost", 2)
    if p.mana < cost or p.hero_power_used_this_turn:
        return False
    # Example: Paladin still needs board space
    if p.hero.id.upper() == "PALADIN" and len(p.board) >= 7:
        return False
    return True


def maybe_use_hero_power(g: Game, pid: int):
    if g.active_player != pid:
        return []
    try:
        if not can_use_hero_power_ai(g, pid):
            return []

        hero_id = g.players[pid].hero.id.upper()
        me = g.players[pid]
        opp = g.players[1 - pid]

        if hero_id == "HUNTER":
            return g.use_hero_power(pid)

        if hero_id == "WARRIOR":
            return g.use_hero_power(pid)

        if hero_id == "WARLOCK":
            if len(me.hand) >= 9:
                return []
            if me.health <= 10:
                return []
            return g.use_hero_power(pid)

        if hero_id == "PALADIN":
            if len(me.board) < 7:
                return g.use_hero_power(pid)
            return []

        if hero_id == "MAGE":
            taunt_1hp = [m for m in opp.board if m.is_alive() and m.taunt and m.health <= 1]
            if taunt_1hp:
                return g.use_hero_power(pid, target_minion=taunt_1hp[0].id)
            ones = [m for m in opp.board if m.is_alive() and m.health <= 1]
            if ones:
                return g.use_hero_power(pid, target_minion=ones[0].id)
            return g.use_hero_power(pid, target_player=(1 - pid))

        return []
    except IllegalAction:
        return []


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
    p = g.players[pid]
    try:
        idx = next(i for i, x in enumerate(p.hand) if x == cid)
    except StopIteration:
        return None
    card = g.cards_db[cid]
    if card.cost > p.mana:
        return None

    #hard stop—no minion plays on full board, and also abort if this card summons when full
    if card.type == "MINION" and len(p.board) >= 7:
        return None
    raw = _raw(g, cid)
    if any(e.get("effect") == "summon" for e in _card_effects(raw)) and len(p.board) >= 7:
        return None

    kind, info = classify_card(g, cid)

    # ---- Heals
    if kind == "heal":
        amt = int(info.get("amount", 0))
        tp, tm, sc = best_heal_target(g, pid, amt)
        if tp is None and tm is None:
            return None
        return idx, tp, tm, sc + 350

    # ---- Buffs
    if kind == "buff":
        tm = best_friendly_to_buff(g, pid, cid)
        if tm is None:
            return None
        m = g.find_minion(tm)[2]
        base = 80 + m.attack * 2 + getattr(m, "cost", 0)
        return idx, None, tm, base

    # ---- Disables (silence/transform)
    if kind == "disable":
        tm = best_enemy_to_silence_or_poly(g, pid)
        if tm is None:
            return None
        threat = threat_score_enemy_minion(g.find_minion(tm)[2])
        return idx, None, tm, 120 + threat

    # ---- Burn (single target / face)
    if kind == "burn":
        opp = 1 - pid
        amt = int(info.get("amount", 0))
        can_go_face = can_face(g, pid)
        # lethal check
        if can_go_face and g.players[opp].health <= amt:
            return idx, opp, None, 1000
        # removal
        enemies = [m for m in g.players[opp].board if m.is_alive() and m.health <= amt]
        if enemies:
            target = max(enemies, key=threat_score_enemy_minion)
            return idx, None, target.id, 240 + threat_score_enemy_minion(target)
        return None

    # ---- AoE
    if kind == "aoe":
        enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
        if not enemies:
            return None
        # simple heuristic
        hits = len(enemies)
        lowhp_hits = sum(1 for m in enemies if m.health <= int(info.get("amount", 0)))
        score = 80 + hits * 20 + lowhp_hits * 20
        if hits >= 2 or lowhp_hits >= 1:
            return idx, None, None, score
        return None

    # ---- Random pings
    if kind == "random_dmg":
        enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
        if not enemies and not can_face(g, pid):
            return None
        v = 50 + len(enemies) * 15 + (10 if can_face(g, pid) else 0)
        return idx, None, None, v

    # ---- Draw
    if kind == "draw":
        if len(p.hand) >= 9:
            return None
        return idx, None, None, 65

    # ---- Summon / tokens
    if kind == "summon":
        if len(p.board) >= 7:
            return None
        return idx, None, None, 70 + info.get("count", 1) * 5

    # ---- Generic minions (curve + stats)
    if kind == "generic_minion":
        if len(p.board) >= 7:
            return None
        stat_val = card.attack * 3 + card.health * 2
        curve_val = min(card.cost, p.mana) * 8
        return idx, None, None, 60 + stat_val + curve_val

    # Unknown: skip
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

def _face_allowed_for_attacker(g: Game, pid: int, m) -> bool:
    if not can_face(g, pid):
        return False
    # Rush can never go face on the summoning turn
    if getattr(m, "rush", False) and getattr(m, "summoned_this_turn", True):
        return False
    return True

def _face_priority_score(g: Game, pid: int, attacker) -> int:
    """
    Estimate how good going face is with this attacker.
    Boosts when opponent is low, when we can set up lethal soon, and for high attack.
    """
    opp = 1 - pid
    # base from attack (more attack => more valuable face hit)
    score = 80 + attacker.attack * 12

    # race/lethal pressure
    opp_hp = g.players[opp].health
    # if this hit represents >= 20% of their remaining health, reward it
    score += int( (attacker.attack / max(1, opp_hp)) * 120 )

    # If we already have lots of board damage ready, prefer racing
    total_ready = sum(m.attack for m in _ally_minions(g, pid) if minion_ready(m) and not (getattr(m, "rush", False) and getattr(m, "summoned_this_turn", True)))
    score += min(total_ready * 4, 60)

    # If there are taunts, face is illegal anyway; caller checks that.
    return score

def pick_attack(g: Game, pid: int) -> Optional[Tuple[Action, int]]:
    opp = 1 - pid
    enemies = _enemy_minions(g, pid)
    taunts  = [m for m in enemies if m.taunt and m.is_alive()]

    for a in _ally_minions(g, pid):
        if not minion_ready(a):
            continue

        # 1) Evaluate best trade (respect taunts if any)
        pool = taunts if taunts else enemies
        best_trade = None
        best_trade_score = -1
        for m in pool:
            kill_enemy = a.attack >= m.health
            die_self   = m.attack >= a.health

            m_val = threat_score_enemy_minion(m)
            score = 0
            if kill_enemy and not die_self:
                score = 240 + m_val                    # very good trade
            elif kill_enemy and die_self:
                score = 140 + int(m_val * 0.6)         # even trade weighted by target value
            else:
                # chip into a high-value minion is ok but not great
                score = 50 + min(a.attack, m.health) + int(m_val * 0.1)

            # Don’t dump huge attack into a truly worthless target unless it’s a taunt
            if not m.taunt and m.attack == 0 and m.health <= 1 and a.attack >= 4:
                score -= 80

            if score > best_trade_score:
                best_trade_score = score
                best_trade = m

        # 2) Evaluate face (if legal for this attacker)
        best_face = None
        best_face_score = -1
        if _face_allowed_for_attacker(g, pid, a) and not taunts:
            face_score = _face_priority_score(g, pid, a)
            best_face, best_face_score = (opp, None), face_score

        # 3) Special casing for “charge” burst (e.g., Leeroy): lean to face unless trade is clearly great
        if getattr(a, "charge", False) and not taunts:
            # require a *really* valuable trade to override face with charge
            if best_trade_score >= best_face_score + 120:
                return (('attack', a.id, None, best_trade.id), best_trade_score)
            else:
                return (('attack', a.id, opp, None), best_face_score)

        # 4) Normal choice: whichever is better
        if best_trade is None and best_face is None:
            continue
        if best_face_score > best_trade_score:
            return (('attack', a.id, opp, None), best_face_score)
        else:
            return (('attack', a.id, None, best_trade.id), best_trade_score)

    return None


# ----------------- DEVELOPMENT / CASTS -----------------
def pick_best_play(g: Game, pid: int) -> Optional[Tuple[Action, int]]:
    p = g.players[pid]
    best = None
    best_score = -1

    # useful cards only
    for i, cid in enumerate(p.hand):
        usable = has_useful_play_for_card(g, pid, cid)
        if not usable:
            continue
        idx, tp, tm, score = usable
        if score > best_score:
            best_score = score
            best = ('play', idx, tp, tm)

    # Consider Coin only if it's **our turn** (it is, but keep it explicit) and in hand
    if g.active_player == pid and any(c in THE_COIN for c in p.hand):
        mana_now = p.mana
        p.mana += 1  # simulate
        try:
            coin_best = None
            coin_score = -1
            coin_best_is_minion = False

            for i, cid in enumerate(p.hand):
                if cid in THE_COIN:
                    continue
                usable = has_useful_play_for_card(g, pid, cid)
                if not usable:
                    continue
                idx2, tp2, tm2, sc2 = usable

                # If board is full, do not consider a minion/summon as a candidate
                cobj = g.cards_db[cid]
                if cobj.type == "MINION" and len(p.board) >= 7:
                    continue

                if sc2 > coin_score:
                    coin_score = sc2
                    coin_best = (idx2, tp2, tm2)
                    coin_best_is_minion = (cobj.type == "MINION")

            # Only Coin if it unlocks a significantly better *legal* play
            if coin_best and coin_score >= best_score + 40:
                coin_idx = next(i for i, x in enumerate(p.hand) if x in THE_COIN)
                return (('play', coin_idx, None, None), coin_score + 1)
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
