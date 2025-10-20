# ai.py
import copy
from typing import Optional, Tuple, List, Dict, Any
from engine import Game, IllegalAction
from functools import lru_cache
Action = Tuple[str, ...]  # ('end',) or ('play', idx, target_player, target_minion) or ('attack', attacker_id, target_player, target_minion)


# If you let AI see The Coin:
THE_COIN          = {"THE_COIN"}



def _targeting_of(g: Game, cid: str) -> str:
    return (g.cards_db.get("_TARGETING", {}).get(cid, "none") or "none").lower()

def _has_friendly_target_for_buff(g: Game, pid: int, cid: str) -> Optional[int]:
    """
    If the card targets a friendly minion (optionally tribe-gated), return
    the best target id; else None.
    """
    t = _targeting_of(g, cid)
    if t in ("friendly_minion", "any_minion"):  # we only pick friendlies for buffs
        return best_friendly_to_buff(g, pid, cid)
    if t.startswith("friendly_tribe:") or t.startswith("any_tribe:"):
        tribe = t.split(":", 1)[1]
        candidates = [m for m in g.players[pid].board
                      if m.is_alive() and str(getattr(m, "minion_type", "none")).lower() == tribe]
        if not candidates:
            return None
        # reuse your existing value model
        return max(candidates, key=lambda m: value_score_friendly_minion_for_buff(m, cid)).id
    # if it targets enemy/broad characters, this helper isn’t for that
    return None


def _needs_any_target(g: Game, cid: str) -> bool:
    """True if the card requires a target when played (minion or character)."""
    t = _targeting_of(g, cid)
    if t in ("none", ""):
        return False
    # character targets always need something picked
    if t in ("any_character", "friendly_character", "enemy_character"):
        return True
    # explicit minion targets
    if t in ("friendly_minion", "enemy_minion", "any_minion"):
        return True
    # tribe-targeted forms: friendly_tribe:beast / enemy_tribe:mech / any_tribe:dragon
    return t.startswith("friendly_tribe:") or t.startswith("enemy_tribe:") or t.startswith("any_tribe:")


def _raw_root(g: Game) -> Dict[str, Any]:
    return g.cards_db.get("_RAW", {})

def _raw_tokens(g: Game) -> Dict[str, Any]:
    rr = _raw_root(g)
    return rr.get("tokens", rr.get("TOKENS", {})) or {}

@lru_cache(maxsize=None)
def _token_tribe(g_id: int, tok_id: str) -> str:
    """Resolve a token's tribe from RAW tokens or normal DB; lowercased ('beast', 'none', ...)."""
    # NOTE: g_id is only here to keep cache per-Game instance
    t = _raw_tokens(_GAME_BY_ID[g_id]).get(tok_id, {})
    tribe = (t.get("minion_type") or t.get("race") or "None")
    if tribe == "None":
        # try resolved card object if tokens were promoted into the DB
        c = _GAME_BY_ID[g_id].cards_db.get(tok_id)
        tribe = getattr(c, "minion_type", "None") if c else "None"
    return str(tribe).lower()

def _game_id(g: Game) -> int:
    return id(g)

# Small registry to make lru_cache work with 'g'
_GAME_BY_ID: Dict[int, Game] = {}

def _lower(x): return str(x).lower() if isinstance(x, str) else x

def _parse_targeting_tribe(raw: Dict[str, Any]) -> Optional[str]:
    tg = _lower(raw.get("targeting",""))
    if "friendly_tribe:" in tg:
        return tg.split("friendly_tribe:",1)[1].strip()
    return None

def _has_spell_damage(raw: Dict[str, Any]) -> int:
    # integer spell damage if present
    sd = raw.get("spell_damage")
    try:
        return int(sd) if sd is not None else 0
    except Exception:
        return 0

def _collect_effect_lists(raw: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    """Return all top-level effect lists that may contain summons or conditionals."""
    lists = []
    for k in ("on_cast","battlecry","deathrattle"):
        v = raw.get(k)
        if isinstance(v, list): lists.append(v)
    # triggers: effects live inside each trigger item
    for tr in raw.get("triggers", []) or []:
        effs = tr.get("effects", [])
        if isinstance(effs, list): lists.append(effs)
    return lists

def _iter_nested_effects(effs: List[Dict[str, Any]]):
    """Depth-first iterate over nested effect dictionaries ('then'/'else')."""
    stk = list(effs)[::-1]
    while stk:
        e = stk.pop()
        yield e
        for branch in ("then","else","effects"):  # effects (inside triggers) may nest again
            v = e.get(branch)
            if isinstance(v, list):
                stk.extend(v[::-1])

def _summoned_tribes(g: Game, raw: Dict[str, Any]) -> set:
    """Which tribes can this card create when played (from on_cast/bc/dr/…)?"""
    tribes = set()
    gid = _game_id(g)
    for effs in _collect_effect_lists(raw):
        for e in _iter_nested_effects(effs):
            if _lower(e.get("effect")) == "summon":
                cid = e.get("card_id")
                if isinstance(cid, str):
                    tribes.add(_token_tribe(gid, cid))
            if _lower(e.get("effect")) == "summon_from_pool":
                for tok in e.get("pool", []) or []:
                    tribes.add(_token_tribe(gid, tok))
    return {t for t in tribes if t and t != "none"}

def _enabler_need(raw: Dict[str, Any]) -> Optional[str]:
    """
    If this card has a 'friendly_summon' trigger, return required tribe:
    'any' or 'beast'/'murloc'/..., else None.
    """
    for tr in raw.get("triggers", []) or []:
        if _lower(tr.get("on")) == "friendly_summon":
            effs = tr.get("effects", []) or []
            # If there is a tribe gate, pick it; otherwise 'any'
            for e in effs:
                if _lower(e.get("effect")) == "if_summoned_tribe":
                    return _lower(e.get("tribe")) or "any"
            return "any"
    # Auras that boost a tribe can be treated as (weak) enablers for ordering
    aura = raw.get("aura", {})
    tribe = _lower(aura.get("tribe")) if isinstance(aura, dict) else None
    if tribe: return tribe  # weak
    return None

def _control_tribe_payoff(raw: Dict[str, Any]) -> Optional[str]:
    """Return tribe gate from condition like 'if_control_tribe' (e.g., Kill Command)."""
    for effs in _collect_effect_lists(raw):
        for e in _iter_nested_effects(effs):
            if _lower(e.get("effect")) == "if_control_tribe":
                return _lower(e.get("tribe"))
    return None

@lru_cache(maxsize=4096)
def _facts(g_id: int, cid: str) -> Dict[str, Any]:
    g = _GAME_BY_ID[g_id]
    raw = _raw(g, cid) or {}
    card = g.cards_db[cid]
    return {
        "type": getattr(card, "type", None),
        "cost": getattr(card, "cost", 0),
        "tribe": _lower(getattr(card, "minion_type", "None")),
        "enabler_need": _enabler_need(raw),                    # 'any' / 'beast' / None
        "summons_tribes": _summoned_tribes(g, raw),            # {'beast', 'murloc', ...}
        "targeting_tribe": _parse_targeting_tribe(raw),        # e.g., 'beast' for Houndmaster
        "control_tribe_gate": _control_tribe_payoff(raw),      # e.g., 'beast' for Kill Command
        "spell_damage": _has_spell_damage(raw),                # int
    }


# 

def _raw(g: Game, cid: str) -> Dict[str, Any]:
    return g.cards_db.get("_RAW", {}).get(cid, {})

def _card_effects(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    # prefer on_cast for spells, battlecry for minions; support both
    flat: List[Dict[str, Any]] = []
    for effs in _collect_effect_lists(raw):
        for e in _iter_nested_effects(effs):
            if isinstance(e, dict) and e.get("effect"):
                flat.append(e)
    return flat


def _minion_value_generic(m) -> int:
    """Cross-side minion value. Reuses enemy threat score; OK for ally too."""
    return threat_score_enemy_minion(m)

def _board_value(g: Game, pid: int) -> int:
    """Sum of generic value of all living minions on PID's side."""
    return sum(_minion_value_generic(m) for m in g.players[pid].board if m.is_alive())

def _best_minion_value(g: Game, pid: int) -> int:
    vals = [_minion_value_generic(m) for m in g.players[pid].board if m.is_alive()]
    return max(vals) if vals else 0

def _damaged_enemies(g: Game, pid: int):
    opp = 1 - pid
    return [m for m in g.players[opp].board if m.is_alive() and m.health < m.max_health]

def _lowest_removal_alt_cost(g: Game, pid: int) -> int:
    """
    Very rough "do we have other removal?" signal.
    Returns the min effective cost of any 'disable'/'hard_remove_damaged'/'burn' spell in hand, else big.
    """
    p = g.players[pid]
    best = 99
    for cid in p.hand:
        raw_kind, _ = classify_card(g, cid)
        if raw_kind in ("disable", "hard_remove_damaged", "burn", "aoe", "random_dmg"):
            c = g.cards_db[cid]
            cost = getattr(g, "get_effective_cost", lambda _pid, _cid: c.cost)(pid, cid)
            if cost <= p.mana:
                best = min(best, cost)
    return best


# --- Hero power gating/usage for AI ---

def can_use_hero_power_ai(g: Game, pid: int) -> bool:
    """Copy of the UI gating but engine-only; avoids importing UI code."""
    p = g.players[pid]
    if p.hero is None:
        return False
    cost = getattr(p.hero.power, "cost", 2)
    if p.mana < cost or p.hero_power_used_this_turn:
        return False

    hid = p.hero.id.upper()

    # Paladin / Shaman: need board space
    if hid in ("PALADIN", "SHAMAN") and len(p.board) >= 7:
        return False

    # Priest: needs *some* damaged friendly character (face or minion) to make sense
    if hid == "PRIEST":
        if p.health < p.max_health:
            return True
        if any(m.is_alive() and m.health < m.max_health for m in p.board):
            return True
        return False

    # Others: generic gating is fine
    return True

def maybe_use_hero_power(g: Game, pid: int):
    """
    Use hero power late in turn, conservatively:
      - Tactical/emergency cases first.
      - Otherwise only if we'd float >= cost mana and no clearly-better play.
    """
    if g.active_player != pid:
        return []

    p = g.players[pid]
    hero = p.hero
    if hero is None:
        return []
    cost = getattr(hero.power, "cost", 2)
    if p.mana < cost or p.hero_power_used_this_turn:
        return []

    hero_id = hero.id.upper()
    me  = g.players[pid]
    opp = g.players[1 - pid]

    # --- Tactical high-value uses ---
    if hero_id == "HUNTER":
        if opp.health <= 2:
            return g.use_hero_power(pid)

    if hero_id == "MAGE":
        if opp.health <= 1:
            return g.use_hero_power(pid, target_player=1 - pid)
        taunt_1hp = [m for m in opp.board if m.is_alive() and m.taunt and m.health <= 1]
        if taunt_1hp:
            return g.use_hero_power(pid, target_minion=taunt_1hp[0].id)
        ones = [m for m in opp.board if m.is_alive() and m.health <= 1]
        if ones:
            return g.use_hero_power(pid, target_minion=ones[0].id)

    if hero_id == "WARRIOR":
        if me.health <= 12:
            return g.use_hero_power(pid)

    if hero_id == "WARLOCK":
        if not (len(me.hand) < 9 and me.health > 12):
            return []
        # (continue down to the "float mana" check before actually tapping)

    if hero_id == "PRIEST":
        # Heal highest-value friendly damage (face or minion)
        tp, tm, sc = best_heal_target(g, pid, 2)  # default Priest heal = 2
        if tp is not None or tm is not None:
            return g.use_hero_power(pid, target_player=tp, target_minion=tm)

    if hero_id == "PALADIN":
        if len(me.board) >= 7:
            return []

    if hero_id == "SHAMAN":
        # Totemic Call only if space and we’re otherwise floating
        if len(me.board) >= 7:
            return []

    if hero_id == "ROGUE":
        # Dagger Up if unarmed (or weapon is basically spent) and we’re floating
        w = me.weapon
        if (w is None) or (w.attack <= 1 and w.durability <= 1):
            # fall through to float check

            pass
        else:
            # keeping a good weapon; skip unless floating later
            pass

    # --- Only if we'd otherwise float the mana AND there's no clearly-better play ---
    best_play = pick_best_play(g, pid)
    if best_play is not None:
        return []

    # Spend on power by class defaults
    if hero_id == "HUNTER":
        return g.use_hero_power(pid)
    if hero_id == "MAGE":
        return g.use_hero_power(pid, target_player=(1 - pid))
    if hero_id == "PALADIN":
        if len(me.board) < 7:
            return g.use_hero_power(pid)
        return []
    if hero_id == "WARLOCK":
        if len(me.hand) < 9 and me.health > 12:
            return g.use_hero_power(pid)
        return []
    if hero_id == "WARRIOR":
        return g.use_hero_power(pid)
    if hero_id == "PRIEST":
        tp, tm, _ = best_heal_target(g, pid, 2)
        if tp is not None or tm is not None:
            return g.use_hero_power(pid, target_player=tp, target_minion=tm)
        return []
    if hero_id == "ROGUE":
        return g.use_hero_power(pid)
    if hero_id == "DRUID":
        return g.use_hero_power(pid)
    if hero_id == "SHAMAN":
        if len(me.board) < 7:
            return g.use_hero_power(pid)
        return []

    return []

# ----------------- Small helpers -----------------

def can_face(g: Game, pid: int) -> bool:
    opp = 1 - pid
    return not any(m.taunt and m.is_alive() for m in g.players[opp].board)

def minion_ready(m) -> bool:
    if getattr(m, "cant_attack", False):
        return False
    if getattr(m, "frozen", False):
        return False
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
    kw_bonus = (6 if getattr(m, "taunt", False) else 0) \
             + (4 if getattr(m, "charge", False) else 0) \
             + (3 if getattr(m, "rush", False) else 0) \
             + (5 if getattr(m, "divine_shield", False) else 0)  # NEW
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
    missing_face = max(0, p.max_health - p.health)
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

def _best_faceless_target(g: Game, pid: int, allow_enemy: bool) -> Optional[int]:
    # Prefer copying our own biggest/current best body; fall back to enemy if allowed and better.
    allies = [m for m in g.players[pid].board if m.is_alive()]
    enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
    cand = []
    if allies:
        cand.append(max(allies, key=_minion_value_generic))
    if allow_enemy and enemies:
        cand.append(max(enemies, key=_minion_value_generic))
    return max(cand, key=_minion_value_generic).id if cand else None

def _pick_shadowflame_sacrifice(g: Game, pid: int) -> Optional[int]:
    """Pick our friendly minion to sack that maximizes (enemy threat removed - our value lost)."""
    me = g.players[pid]; opp = g.players[1 - pid]
    best_mid, best_gain = None, 0
    for m in me.board:
        if not m.is_alive(): continue
        dmg = max(0, m.attack)
        if dmg <= 0: continue
        # Value removed on enemy board
        removed = 0
        for e in opp.board:
            if not e.is_alive(): continue
            if e.health <= dmg: removed += threat_score_enemy_minion(e)
            else:
                # partial chip: small benefit
                removed += min(dmg, e.health) * 4
        loss = _minion_value_generic(m)
        gain = removed - loss
        # prefer sacking 'dead weight' like Ancient Watcher (can't attack)
        if getattr(m, "cant_attack", False): gain += 40
        if gain > best_gain:
            best_gain, best_mid = gain, m.id
    return best_mid

def _estimate_drake_extra_hp(g: Game, pid: int) -> int:
    # After playing Drake, hand size decreases by 1; battlecry adds +HP equal to cards in hand then.
    # So bonus ≈ len(hand) - 1 (clamped >= 0)
    return max(0, len(g.players[pid].hand) - 1)


def _friendly_watcher_to_silence(g: Game, pid: int) -> Optional[int]:
    for m in _ally_minions(g, pid):
        if getattr(m, "cant_attack", False) and m.attack >= 4:
            return m.id
    return None

# ----------------- Play gating (do nothing if useless) -----------------


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
    deals_damage = has("deal_damage") or has("deal_damage_range") or has("random_enemy_damage")

    if has("set_health"):
        amt = get_first("set_health", "amount", 1)
        # Treat as a removal enabler; never use on friendlies
        return "set_health_debuff", {"amount": amt, "targeting": raw.get("targeting", "").lower()}

    if has("heal") and not deals_damage:
        amt = get_first("heal", "amount", 0)
        return "heal", {"amount": amt, "targeting": (raw.get("targeting","") or "").lower()}
    
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
    
    # --- Hard destroy (e.g., Siphon Soul)
    if has("destroy"):
        return "hard_remove", {"targeting": raw.get("targeting", "").lower()}

    # --- Shadowflame: destroy *friendly* target, AOE = its current Attack
    if has("shadowflame"):
        return "shadowflame", {}

    # --- Jaraxxus / hero replacement
    if has("replace_hero"):
        return "hero_replace", {}

    # --- Faceless Manipulator (copy self as target minion)
    if has("copy_self_as_target_minion"):
        return "copy_minion", {"targeting": raw.get("targeting", "").lower()}

    # --- Twilight Drake hint: gains health from hand size
    if has("add_self_health_from_hand"):
        return "drake_like", {}

        # --- Damage range (e.g., Crackle 3–6)
    if has("deal_damage_range"):
        # Use min/max if present; target from raw targeting
        mn = get_first("deal_damage_range", "min", 0)
        mx = get_first("deal_damage_range", "max", 0)
        return "burn_range", {"min": mn, "max": mx, "target": raw.get("targeting","").lower()}

    # Detect "damage + heal to friendly face" pattern (Holy Fire)
    heals_friendly_face = False
    if deals_damage and has("heal"):
        for e in effs:
            if e.get("effect") == "heal" and str(e.get("target","")).lower() == "friendly_face":
                heals_friendly_face = True
                break

    # --- Mortal Coil pattern: draw if the target died
    if has("deal_damage") and any(e.get("effect") == "if_target_died_then" for e in effs):
        amt = get_first("deal_damage", "amount", 0)
        draw_count = 0
        for e in effs:
            if e.get("effect") == "if_target_died_then":
                for te in (e.get("then") or []):
                    if te.get("effect") == "draw":
                        try: draw_count = int(te.get("count", 1))
                        except: draw_count = 1
                        break
        info = {
            "amount": amt,
            "draw_if_kills": True,
            "draw_count": max(1, draw_count),
            "target": (raw.get("targeting","") or "").lower()
        }
        return "burn", info  # reuse existing 'burn' handler with new flags

    # (keep your normal 'deal_damage' handler below — it’ll catch the rest)

    # --- Equip weapon from spells/battlecries (Muster/Arathi)
    if has("equip_weapon"):
        return "equip_weapon", {}

    # --- Mind Control (treat as premium hard remove + swing)
    if has("mind_control"):
        return "mind_control", {"targeting": (raw.get("targeting","") or "").lower()}

    # --- Conditional destroy by Attack (SW:P / SW:D / BGH)
    if any(e.get("effect") == "if_target_attack_at_most" for e in effs) \
       or any(e.get("effect") == "if_target_attack_at_least" for e in effs):
        # Collect the strongest gate present
        at_most  = next((int(e.get("amount", 0)) for e in effs if e.get("effect")=="if_target_attack_at_most"), None)
        at_least = next((int(e.get("amount", 0)) for e in effs if e.get("effect")=="if_target_attack_at_least"), None)
        return "hard_remove_conditional_attack", {
            "at_most": at_most, "at_least": at_least,
            "targeting": (raw.get("targeting","") or "").lower()
        }

    # --- AoE heal variants (Healing Totem / Holy Nova half)
    if has("aoe_heal") or has("aoe_heal_minions"):
        amt = get_first("aoe_heal", "amount", get_first("aoe_heal_minions","amount",0))
        return "heal_aoe", {"amount": amt}

    # --- Temp buff forms should still act like buffs
    if has("temp_modify") or has("temp_modify_random") \
       or has("temp_modify_aoe") or has("temp_add_attack_to_character"):
        return "buff", {"targeting": (raw.get("targeting","") or "").lower()}


    # Single-target damage (e.g., Slam/Arcane Shot/Fireball)
    if has("deal_damage"):
        amt = get_first("deal_damage", "amount", 0)
        tgt = next((e.get("target") for e in effs if e.get("effect")=="deal_damage" and "target" in e), None)
        
        info = {
            "amount": amt,
            "target": (raw.get("targeting","") or "").lower(),
            "heals_friendly_face": heals_friendly_face,
            "draw_if_survives": False,
            "draw_count": 0,
        }

        for e in effs:
            if e.get("effect") == "if_target_survived_then":
                for te in (e.get("then") or []):
                    if te.get("effect") == "draw":
                        info["draw_if_survives"] = True
                        try: info["draw_count"] = int(te.get("count", 1))
                        except: info["draw_count"] = 1
                        break
        return "burn", info


    if has("draw"):
        cnt = get_first("draw","count",1)
        return "draw", {"count": cnt}

    if has("summon"):
        total = 0
        for e in effs:
            if e.get("effect") == "summon":
                total += int(e.get("count", 1))
        return "summon", {"count": total}

    # --- NEW: hard remove (execute-like)
    if has("execute"):
        return "hard_remove_damaged", {"targeting": raw.get("targeting", "").lower()}

    if has("summon_from_pool"):
        total = 0
        for e in effs:
            if e.get("effect") == "summon_from_pool":
                total += int(e.get("count", 1))
        if total <= 0:
            total = 1
        return "summon", {"count": total}

    if has("random_enemy_damage"):
        amt = get_first("random_enemy_damage", "amount", 1)
        return "random_dmg", {"count": amt}

    if has("freeze"):
        aoe_targets = {"enemy_minions", "all_enemy_minions", "all_minions", "board_enemies"}
        for e in effs:
            if e.get("effect") == "freeze":
                tgt = str(e.get("target", "")).lower()
                if tgt in aoe_targets:
                    return "freeze_aoe", {}
        return "freeze", {"targeting": raw.get("targeting", "").lower()}

    if has("brawl"):
        return "brawl", {}

    if card.type == "MINION":
        return "generic_minion", {"attack": card.attack, "health": card.health, "cost": card.cost}

    return "unknown", {
        "targeting": (raw.get("targeting", "") or "").lower(),
        "cost": getattr(card, "cost", 0),
        "type": getattr(card, "type", None),
    }

def has_useful_play_for_card(g: Game, pid: int, cid: str) -> Optional[Tuple[int, Optional[int], Optional[int], int]]:
    p = g.players[pid]
    try:
        idx = next(i for i, x in enumerate(p.hand) if x == cid)
    except StopIteration:
        return None
    card = g.cards_db[cid]

    eff_cost = getattr(g, "get_effective_cost", lambda _pid, _cid: card.cost)(pid, cid)
    if eff_cost > p.mana:
        return None

    # --- Secrets (new): avoid duplicates; value higher if threats are likely, or if we have Eaglehorn Bow ---
    if card.type == "SECRET":
        try:
            s = g.players[pid].active_secrets or []
            already = any(
                (x == cid) or
                (isinstance(x, dict) and (x.get("card_id") == cid or x.get("id") == cid))
                for x in s
            )
        except Exception:
            already = False
        if already:
            return None
        score = 70
        if opponent_has_ready_threats(g, pid): score += 40
        w = g.players[pid].weapon
        if w and getattr(w, "card_id", "") == "EAGLEHORN_BOW": score += 35
        return idx, None, None, score

    # --- Weapons (new): prefer when unarmed, or upgrading meaningfully ---
    if card.type == "WEAPON":
        w = g.players[pid].weapon
        if w is None:
            return idx, None, None, 180 + card.attack * 20
        replace_penalty = 0
        if w.attack > card.attack:
            replace_penalty -= 80
        if w.durability >= 2:
            replace_penalty -= 30
        base = 120 + (card.attack - w.attack) * 15 + replace_penalty
        return idx, None, None, base

    # prevent illegal summons on full board
    if card.type == "MINION" and len(p.board) >= 7:
        return None
    raw = _raw(g, cid)
    if any(e.get("effect") == "summon" for e in _card_effects(raw)) and len(p.board) >= 7:
        return None

    try:
        kind, info = classify_card(g, cid)
    except Exception:
        # Defensive: skip just this card instead of nuking the whole decision step
        return None

    if kind == "equip_weapon":
        me = g.players[pid]
        w = me.weapon
        # Value like your WEAPON branch, but slightly discounted (you also got the minions/effects already)
        base = 120
        if w is None:
            base += 60
        else:
            if w.durability >= 2: base -= 20
        return idx, None, None, base
    
    if kind == "mind_control":
        enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
        if not enemies:
            return None
        tgt = max(enemies, key=threat_score_enemy_minion)
        # Very high score: remove threat + add it to our board
        return idx, None, tgt.id, 420 + threat_score_enemy_minion(tgt)

    if kind == "hard_remove_conditional_attack":
        enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
        at_most  = info.get("at_most")
        at_least = info.get("at_least")
        def ok(m):
            if at_most  is not None and m.attack <= int(at_most):   return True
            if at_least is not None and m.attack >= int(at_least):  return True
            return False
        cand = [m for m in enemies if ok(m)]
        if not cand:
            return None
        tgt = max(cand, key=threat_score_enemy_minion)
        return idx, None, tgt.id, 300 + threat_score_enemy_minion(tgt)
    
    if kind == "heal_aoe":
        amt = int(info.get("amount", 0))
        me = g.players[pid]
        healed = 0
        for m in me.board:
            if m.is_alive() and m.health < m.max_health:
                healed += min(amt, m.max_health - m.health)
        face_miss = max(0, me.max_health - me.health)
        healed += min(amt, face_miss)  # if card heals characters
        if healed <= 0:
            return None
        # more value when we’re behind on board
        behind = max(0, _board_value(g, 1 - pid) - _board_value(g, pid)) // 10
        return idx, None, None, 80 + healed * 10 + behind
    
    # ---- Hero replacement (Jaraxxus)
    if kind == "hero_replace":
        # Prefer when low life or floating late-game mana
        low = g.players[pid].health <= 14
        late = g.players[pid].mana >= 9
        sc = 200 + (120 if low else 0) + (40 if late else 0)
        return idx, None, None, sc

    # ---- Hard remove (Siphon Soul-like)
    if kind == "hard_remove":
        enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
        if not enemies:
            return None
        # take the biggest threat
        tgt = max(enemies, key=threat_score_enemy_minion)
        return idx, None, tgt.id, 260 + threat_score_enemy_minion(tgt)

    # ---- Shadowflame
    if kind == "shadowflame":
        # Need a friendly body to sack and enemies to hit
        if not g.players[1 - pid].board:
            return None
        sac = _pick_shadowflame_sacrifice(g, pid)
        if sac is None:
            return None
        # Score from net gain (helper baked it). Add urgency if behind.
        urgency = 50 if opponent_has_ready_threats(g, pid) else 0
        return idx, None, sac, 220 + urgency

    # ---- Faceless Manipulator
    if kind == "copy_minion":
        # Default Faceless is friendly_minion; allow enemy if DB says any_minion
        t = info.get("targeting", "")
        allow_enemy = t in ("any_minion",)
        tm = _best_faceless_target(g, pid, allow_enemy)
        if tm is None:
            return None
        base = 180 + _minion_value_generic(g.find_minion(tm)[2]) // 3
        return idx, None, tm, base

    # ---- Twilight Drake valuation bump
    if kind == "drake_like":
        # Treat like a chunky midgame minion with bonus health ≈ hand size - 1
        bonus_hp = _estimate_drake_extra_hp(g, pid)
        stat_val  = (card.attack) * 3 + (card.health + bonus_hp) * 2
        curve_val = min(card.cost, p.mana) * 8
        sc = 60 + stat_val + curve_val + (10 if bonus_hp >= 4 else 0)
        # Needs board space
        if len(p.board) >= 7:
            return None
        return idx, None, None, sc


    # ---- Set-health debuff (Hunter's Mark style)
    if kind == "set_health_debuff":
        enemies = [m for m in g.players[1 - pid].board if m.is_alive() and m.health > int(info.get("amount", 1))]
        if not enemies:
            return None
        target = max(enemies, key=threat_score_enemy_minion)
        sc = 200 + threat_score_enemy_minion(target)
        return idx, None, target.id, sc

    # ---- Heals
    if kind == "heal":
        amt = int(info.get("amount", 0))
        tp, tm, sc = best_heal_target(g, pid, amt)
        if tp is None and tm is None:
            return None
        return idx, tp, tm, sc + 350

    # ---- Buffs
    if kind == "buff":
        targeting = _targeting_of(g, cid)
        if _needs_any_target(g, cid):
            tm = _has_friendly_target_for_buff(g, pid, cid)
            if tm is None:
                return None
            m = g.find_minion(tm)[2]
            base = 80 + m.attack * 2 + getattr(m, "cost", 0)
            return idx, None, tm, base
        stat_val = getattr(card, "attack", 0) * 3 + getattr(card, "health", 0) * 2
        curve_val = min(card.cost, p.mana) * 6
        return idx, None, None, 40 + stat_val + curve_val

    # ---- Disables (silence/transform)
    if kind == "disable":
        tm_self = _friendly_watcher_to_silence(g, pid)
        if tm_self is not None:
            return idx, None, tm_self, 160 + g.find_minion(tm_self)[2].attack * 10
        
        tm = best_enemy_to_silence_or_poly(g, pid)
        if tm is None:
            return None
        threat = threat_score_enemy_minion(g.find_minion(tm)[2])
        return idx, None, tm, 120 + threat

    # ---- AoE
    if kind == "aoe":
        enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
        if not enemies:
            return None
        hits = len(enemies)
        lowhp_hits = sum(1 for m in enemies if m.health <= int(info.get("amount", 0)))
        score = 80 + hits * 20 + lowhp_hits * 20
        if hits >= 2 or lowhp_hits >= 1:
            return idx, None, None, score
        return None

    # ---- Draw
    if kind == "draw":
        if len(p.hand) >= 9:
            return None
        return idx, None, None, 65

    # ---- Summon / tokens
    if kind == "summon":
        score = 70 + info.get("count", 1) * 5
        enablers_board = sum(1 for m in g.players[pid].board if _facts(_game_id(g), getattr(m, "card_id", m.name))["enabler_need"])
        score += enablers_board * 40
        for cid2 in p.hand:
            if cid2 == cid: continue
            f2 = _facts(_game_id(g), cid2)
            if f2["enabler_need"] and f2["cost"] <= p.mana and (p.mana - g.cards_db[cid].cost) >= 0:
                score += 50
                break
        return idx, None, None, score

    # ---- Tribe-locked buffs: defer until we can create a target (unchanged)
    gid = _game_id(g); _GAME_BY_ID[gid] = g
    F = _facts(gid, cid)
    if F["targeting_tribe"]:
        tribe = F["targeting_tribe"]
        has_now = any(m.is_alive() and _lower(getattr(m, "minion_type", "none")) == tribe for m in g.players[pid].board)
        if not has_now and len(g.players[pid].board) < 7:
            for cid2 in g.players[pid].hand:
                if cid2 == cid: continue
                f2 = _facts(gid, cid2)
                c2 = g.cards_db[cid2]
                cost2 = getattr(c2, "cost", 0)
                creates_tribe = (f2["type"] == "MINION" and f2["tribe"] == tribe) or (tribe in (f2["summons_tribes"] or set()))
                if creates_tribe and (cost2 + F["cost"] <= g.players[pid].mana):
                    return None

    if kind == "burn" and info.get("draw_if_kills"):
        enemies = [m for m in g.players[1 - pid].board if m.is_alive() and m.health <= int(info.get("amount", 0))]
        if not enemies:
            return None
        tgt = max(enemies, key=threat_score_enemy_minion)
        # strongly prefer picking off 1-HP things for the cantrip
        return idx, None, tgt.id, 320 + threat_score_enemy_minion(tgt)
    
    # ---- Burn (single-target / face)  ***Slam logic is here***
    if kind == "burn":
        opp = 1 - pid
        amt = int(info.get("amount", 0))
        tstr = info.get("target","")
        # (1) lethal face
        if tstr.endswith("character") and can_face(g, pid) and g.players[opp].health <= amt:
            return idx, opp, None, 1000

        # (2) hard removal if it kills a minion
        enemies = [m for m in g.players[opp].board if m.is_alive()]
        killables = [m for m in enemies if m.health <= amt]
        if killables:
            target = max(killables, key=threat_score_enemy_minion)
            return idx, None, target.id, 240 + threat_score_enemy_minion(target)

        # (3) NEW — chip + draw (Slam-like): if it *doesn't* kill and we draw cards, use it
        if info.get("draw_if_survives", False):
            # prefer high-value, non-Divine Shield, taunt-y bodies that survive the 2
            cand = []
            for m in enemies:
                if m.health > amt:  # must survive
                    sc = threat_score_enemy_minion(m) * 0.35
                    if m.taunt: sc += 25
                    if getattr(m, "divine_shield", False): sc -= 35  # draw still happens, but no damage taken (hurts Execute setup)
                    cand.append((sc, m))
            if cand:
                cand.sort(key=lambda x: x[0], reverse=True)
                target = cand[0][1]

                # Bonus for Slam -> Execute setup this turn
                have_execute = any(x == "EXECUTE" for x in p.hand)
                if have_execute and (p.mana - eff_cost) >= getattr(g.cards_db["EXECUTE"], "cost", 1):
                    if not getattr(target, "divine_shield", False):
                        # If target currently not damaged, Slam would enable Execute
                        if target.health == target.max_health or True:
                            setup_bonus = 140 + int(threat_score_enemy_minion(target) * 0.25)
                        else:
                            setup_bonus = 80
                    else:
                        setup_bonus = 20  # shield blocks damage tag; still a tiny bonus for the draw
                else:
                    setup_bonus = 0

                draw_val = 85 * max(1, int(info.get("draw_count", 1)))
                chip_val = min(amt, target.health) * 10
                return idx, None, target.id, int(110 + draw_val + chip_val + cand[0][0] + setup_bonus)

        # (4) face chip when appropriate (Hunters etc.)
        if tstr.endswith("character") and can_face(g, pid):
            hero = g.players[pid].hero.id.upper()
            opp_hp = g.players[opp].health
            opp_max = g.players[opp].max_health 
            racey_class = (hero == "HUNTER")
            pressure = (opp_hp <= 12) or racey_class
            if pressure:
                chip_score = 120 + amt * 40 + int((opp_max - min(opp_hp, opp_max)) * 3)
                return idx, opp, None, chip_score

        return None

    if kind == "burn_range":
        opp = 1 - pid
        mn = int(info.get("min", 0)); mx = int(info.get("max", 0))
        # sure lethal to face only if min kills and face allowed
        if info.get("target","").endswith("character") and can_face(g, pid) and g.players[opp].health <= mn:
            return idx, opp, None, 900
        enemies = [m for m in g.players[opp].board if m.is_alive()]
        # sure killables (health <= min) are great
        sure = [m for m in enemies if m.health <= mn]
        if sure:
            tgt = max(sure, key=threat_score_enemy_minion)
            return idx, None, tgt.id, 220 + threat_score_enemy_minion(tgt)
        # probable (health <= avg) are ok if we need tempo
        avg = (mn + mx) / 2
        prob = [m for m in enemies if m.health <= avg]
        if prob and opponent_has_ready_threats(g, pid):
            tgt = max(prob, key=threat_score_enemy_minion)
            return idx, None, tgt.id, 150 + threat_score_enemy_minion(tgt) // 2
        # chip face if pressuring
        if info.get("target","").endswith("character") and can_face(g, pid):
            hero = g.players[pid].hero.id.upper()
            if hero == "HUNTER" or g.players[opp].health <= 12:
                return idx, opp, None, 110 + int(avg) * 30
        return None

    # ---- Generic minions (unchanged except existing enabler heuristics)
    if kind == "generic_minion":
        if len(p.board) >= 7:
            return None

        gid = _game_id(g); _GAME_BY_ID[gid] = g
        F = _facts(gid, cid)
        card_cost = F["cost"]

        stat_val  = card.attack * 3 + card.health * 2
        curve_val = min(card.cost, p.mana) * 8
        base = 60 + stat_val + curve_val

        remaining = p.mana - card_cost

        need = F["enabler_need"]
        if need:
            triggers = 0
            for cid2 in p.hand:
                if cid2 == cid:
                    continue
                c2 = g.cards_db[cid2]
                cost2 = getattr(c2, "cost", 0)
                if cost2 > remaining:
                    continue
                f2 = _facts(gid, cid2)
                if need == "any" and f2["type"] == "MINION":
                    triggers += 1
                else:
                    if (f2["type"] == "MINION" and f2["tribe"] == need) or (need in f2["summons_tribes"]):
                        triggers += 1
            base += 90 + 30 * triggers

        for en in p.hand:
            if en == cid:
                continue
            f_en = _facts(gid, en)
            if f_en["enabler_need"] and f_en["cost"] <= p.mana and (p.mana - card_cost) < f_en["cost"]:
                base -= 80
                break

        if F["tribe"] and F["tribe"] != "none" and len(p.board) < 7:
            for cid2 in p.hand:
                if cid2 == cid:
                    continue
                f2 = _facts(gid, cid2)
                if f2["targeting_tribe"] == F["tribe"] and f2["cost"] <= remaining:
                    base += 120
                    break

        if F["spell_damage"] > 0:
            dmg_spells_affordable_after = 0
            for cid2 in p.hand:
                if cid2 == cid:
                    continue
                if g.cards_db[cid2].type != "SPELL":
                    continue
                raw2 = _raw(g, cid2) or {}
                is_burn = any((_lower(e.get("effect")) in ("deal_damage","random_pings")) for e in _iter_nested_effects(next(iter(_collect_effect_lists(raw2)), [])) ) \
                          or any((_lower(e.get("effect")) in ("deal_damage","random_pings")) for e in _iter_nested_effects([x for xs in _collect_effect_lists(raw2) for x in xs]))
                if is_burn and getattr(g.cards_db[cid2], "cost", 0) <= remaining:
                    dmg_spells_affordable_after += 1
            base += 40 + 20 * dmg_spells_affordable_after

        return idx, None, None, base

    # ---- HARD REMOVE DAMAGED (Execute-like)
    if kind == "hard_remove_damaged":
        cand = _damaged_enemies(g, pid)
        if not cand:
            return None
        tgt = max(cand, key=threat_score_enemy_minion)
        bump = 50 if any(m.taunt and m.is_alive() for m in _enemy_minions(g, pid)) else 0
        return idx, None, tgt.id, 260 + threat_score_enemy_minion(tgt) + bump

    # ---- FREEZE single & AOE (unchanged) ----
    if kind == "freeze":
        enemies = [m for m in _enemy_minions(g, pid)]
        if not enemies:
            return None
        def _freeze_score(m):
            s = m.attack * 15 + (40 if m.taunt else 0)
            if not minion_ready(m):
                s -= 40
            return s
        tgt = max(enemies, key=_freeze_score)
        if _freeze_score(tgt) < 20:
            return None
        return idx, None, tgt.id, 120 + _freeze_score(tgt)

    if kind == "freeze_aoe":
        enemies = [m for m in _enemy_minions(g, pid)]
        if not enemies:
            return None
        ready = [m for m in enemies if minion_ready(m)]
        taunts = [m for m in enemies if m.taunt and m.is_alive()]
        total_ready_attack = sum(m.attack for m in ready)
        score = 100 + len(ready) * 35 + len(taunts) * 15 + total_ready_attack * 3
        if g.players[pid].health <= 12:
            score += 40
        if len(ready) >= 1 or len(taunts) >= 1:
            return idx, None, None, score
        return None

    if kind == "brawl":
        me, opp = pid, 1 - pid
        my_list   = [m for m in g.players[me].board  if m.is_alive()]
        opp_list  = [m for m in g.players[opp].board if m.is_alive()]
        n_my, n_opp = len(my_list), len(opp_list)
        total = n_my + n_opp
        if total <= 1:
            return None
        my_val_sum   = sum(_minion_value_generic(m) for m in my_list)
        opp_val_sum  = sum(_minion_value_generic(m) for m in opp_list)
        my_best      = max([_minion_value_generic(m) for m in my_list], default=0)
        opp_best     = max([_minion_value_generic(m) for m in opp_list], default=0)
        ev_after = (n_my/total) * my_best + (n_opp/total) * opp_best
        cur_diff = opp_val_sum - my_val_sum
        benefit = cur_diff - ( (n_opp/total)*opp_best - (n_my/total)*my_best )
        taunts_block = any(m.taunt and m.is_alive() for m in opp_list) and not can_face(g, pid)
        low_hp = g.players[pid].health <= 12
        many_threats = sum(1 for m in opp_list if minion_ready(m)) >= 2
        urgency = (80 if taunts_block else 0) + (60 if low_hp else 0) + (40 if many_threats else 0)
        if cur_diff < -150:
            benefit -= 120
        alt = _lowest_removal_alt_cost(g, pid)
        if alt <= 3:
            benefit -= 60
        score = int(140 + benefit * 0.35 + urgency)
        if score < 140:
            return None
        return idx, None, None, score

    # Final safety for targeted unknowns
    if _needs_any_target(g, cid):
        t = _targeting_of(g, cid)
        if t.startswith("enemy_") or t in ("enemy_character",):
            enemies = _enemy_minions(g, pid)
            if not enemies and t.endswith("character"):
                return idx, (1 - pid), None, 50
            if enemies:
                m = max(enemies, key=threat_score_enemy_minion)
                return idx, None, m.id, 120 + threat_score_enemy_minion(m)
            return None
        if t.startswith("friendly_") or t in ("friendly_character",):
            tm = _has_friendly_target_for_buff(g, pid, cid)
            if tm is not None:
                m = g.find_minion(tm)[2]
                return idx, None, tm, 60 + m.attack * 2 + getattr(m, "cost", 0)
            return None
        return None

    if kind == "random_dmg":
        enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
        v = 40 + len(enemies) * 12 + (8 if can_face(g, pid) else 0)
        return idx, None, None, v

    if kind == "unknown":
        targeting = (info.get("targeting") or "").lower()
        typ = str(info.get("type") or "")
        cost = int(info.get("cost") or 0)

        # Targeted unknowns:
        # - If it wants an enemy target, pick the best threat (acts like a soft removal/bounce/hex-ish guess).
        # - If it allows character targets, face is allowed only if taunts aren’t up and we’re applying pressure.
        if _needs_any_target(g, cid):
            enemies = _enemy_minions(g, pid)
            if targeting.startswith("enemy_") or targeting in ("enemy_character",):
                if enemies:
                    m = max(enemies, key=threat_score_enemy_minion)
                    # modest score; unknown could be soft disable, ping, or debuff
                    return idx, None, m.id, 80 + threat_score_enemy_minion(m) // 6
                # if character-legal and board is open, consider face poke (very small score)
                if targeting.endswith("character") and can_face(g, pid):
                    return idx, (1 - pid), None, 70
                return None

            # Friendly-targeting unknown (likely a buff or protect effect): choose our best buff target.
            if targeting.startswith("friendly_") or targeting in ("friendly_character",):
                tm = _has_friendly_target_for_buff(g, pid, cid)
                if tm is not None:
                    m = g.find_minion(tm)[2]
                    return idx, None, tm, 75 + m.attack * 2 + getattr(m, "cost", 0)
                return None

            # Tribe-locked friendly target: let earlier tribe deferral logic decide (already handled above).
            return None

        # Untargeted unknowns:
        # - Don’t spam them early. Use if we’d otherwise float mana or are near hand burn, with a small score.
        float_mana = g.players[pid].mana - eff_cost
        near_burn  = len(g.players[pid].hand) >= 9
        late_game  = g.turn >= 7
        if float_mana >= 1 or near_burn or late_game:
            base = 60 + cost * 10
            # tiny urgency bump if we’re behind on board
            base += max(0, (_board_value(g, 1 - pid) - _board_value(g, pid)) // 12)
            return idx, None, None, base

        return None

    return None


def _best_board_pos_for_adjacency(g, pid, cid) -> int | None:
    """
    Choose the insertion index 0..len(board) that maximizes immediate value
    of adjacency effects (aura or battlecry).
    """
    me = g.players[pid]
    N = len(me.board)
    if N == 0:
        return 0

    raw = _raw(g, cid)

    def value_after_inserting_at(pos: int) -> int:
        # Left/right neighbor ids at that pos
        left  = me.board[pos-1] if pos-1 >= 0     else None
        right = me.board[pos]   if pos   <  N     else None

        v = 0
        # Aura case (Dire Wolf Alpha): +1 atk to *adjacent* friendlies
        for a in (raw.get("auras") or []):
            if a.get("scope") == "adjacent_friendly_minions":
                bonus = int(a.get("attack", 0))
                if left:  v += (left.attack + bonus) * 6
                if right: v += (right.attack + bonus) * 6

        # Defender of Argus battlecry: +1/+1 + taunt to adjacents
        for eff in (raw.get("battlecry") or []):
            if eff.get("effect") == "adjacent_buff":
                atk = int(eff.get("attack", 0)); hp = int(eff.get("health", 0))
                taunt = bool(eff.get("taunt", False))
                def _score_minion(m):
                    s = atk * 6 + hp * 4 + (12 if taunt else 0)
                    # prefer buffing high-attack or taunt bodies
                    s += m.attack * 3 + (10 if m.taunt else 0) + getattr(m, "cost", 0)
                    return s
                if left:  v += _score_minion(left)
                if right: v += _score_minion(right)

        # Mild penalty for inserting at extreme ends (usually fewer adjacents)
        if pos == 0 or pos == N: v -= 8
        return v

    best_pos, best_v = 0, -10**9
    for pos in range(N + 1):
        sc = value_after_inserting_at(pos)
        if sc > best_v:
            best_v, best_pos = sc, pos
    return best_pos

def _is_adjacency_aura(g, cid):
    raw = _raw(g, cid)
    # Dire Wolf Alpha style
    for a in (raw.get("auras") or []):
        if a.get("scope") == "adjacent_friendly_minions":
            return True
    # Defender of Argus style
    for eff in (raw.get("battlecry") or []):
        if eff.get("effect") == "adjacent_buff":
            return True
    return False

# ----------------- LETHAL PLANNER -----------------

# --- Threat detection (don’t count frozen minions as ready)
def opponent_has_ready_threats(g: Game, pid: int) -> bool:
    opp = 1 - pid
    # Hero threat already respects Freeze via engine
    if g.hero_can_attack(opp):
        return True
    for m in g.players[opp].board:
        if minion_ready(m):  # NEW: respects frozen/summon rules/etc.
            return True
    return False



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
    if getattr(m, "frozen", False):
        return False
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
    best: Optional[Action] = None
    best_score = -1
    best_board_pos: Optional[int] = None

    # useful cards only
    for i, cid in enumerate(p.hand):
        usable = has_useful_play_for_card(g, pid, cid)
        if not usable:
            continue
        idx, tp, tm, score = usable

        # If this is an adjacency-sensitive minion, compute best insertion slot
        bpos: Optional[int] = None
        try:
            if g.cards_db[cid].type == "MINION" and _is_adjacency_aura(g, cid):
                bpos = _best_board_pos_for_adjacency(g, pid, cid)
                if bpos is not None:
                    score += 30  # small bonus for securing adjacency value
        except Exception:
            bpos = None  # fail safe

        if score > best_score:
            best_score = score
            # Return 5-tuple so UI can pass board_pos down
            if bpos is not None:
                best = ('play', idx, tp, tm, bpos)  # type: ignore
                best_board_pos = bpos
            else:
                best = ('play', idx, tp, tm)
                best_board_pos = None

    # Consider Coin only if it's our turn and in hand
    if g.active_player == pid and any(c in THE_COIN for c in p.hand):
        mana_now = p.mana
        p.mana += 1  # simulate
        try:
            coin_best = None
            coin_score = -1
            coin_best_pos: Optional[int] = None

            for i, cid in enumerate(p.hand):
                if cid in THE_COIN:
                    continue
                usable = has_useful_play_for_card(g, pid, cid)
                if not usable:
                    continue
                idx2, tp2, tm2, sc2 = usable

                cobj = g.cards_db[cid]
                if cobj.type == "MINION" and len(p.board) >= 7:
                    continue

                # adjacency calc under Coin mana
                bpos2: Optional[int] = None
                try:
                    if cobj.type == "MINION" and _is_adjacency_aura(g, cid):
                        bpos2 = _best_board_pos_for_adjacency(g, pid, cid)
                        if bpos2 is not None:
                            sc2 += 30
                except Exception:
                    bpos2 = None

                if sc2 > coin_score:
                    coin_score = sc2
                    coin_best = (idx2, tp2, tm2)
                    coin_best_pos = bpos2

            # Only Coin if it unlocks a significantly better legal play
            if coin_best and coin_score >= best_score + 40:
                coin_idx = next(i for i, x in enumerate(p.hand) if x in THE_COIN)
                # We just return playing Coin; the follow-up play will be picked on the next frame.
                return (('play', coin_idx, None, None), coin_score + 1)
        finally:
            p.mana = mana_now

    if best is not None:
        return (best, best_score)
    return None


# ----------------- Think ahead -----------------


def eval_state(g: Game, pid: int) -> int:
    """Higher is better for pid. Cheap, deterministic."""
    me, opp = g.players[pid], g.players[1 - pid]

    def board_score(p):
        s = 0
        for m in p.board:
            if not m.is_alive(): continue
            kw = (6 if m.taunt else 0) + (4 if m.charge else 0) + (3 if m.rush else 0) + (3 if m.divine_shield else 0)
            s += m.attack * 4 + m.health * 3 + kw + getattr(m, "cost", 0)
        if p.weapon:
            s += p.weapon.attack * 8 + p.weapon.durability * 3
        return s

    # Health & armor are slow-moving tempos; weight lower than board presence.
    my_hp  = min(me.max_health, me.health + me.armor)
    op_hp  = min(opp.max_health, opp.health + opp.armor)
    hand_bonus = min(len(me.hand), 10) * 6 - min(len(opp.hand), 10) * 6

    return (
        (board_score(me) - board_score(opp)) * 1
        + (my_hp - op_hp) * 2
        + hand_bonus
        + (10 if can_face(g, pid) else 0)
    )
def enumerate_actions(g: Game, pid: int) -> List[Action]:
    acts: List[Action] = []

    # Attacks
    for a in _ally_minions(g, pid):
        if not minion_ready(a): continue
        enemies = _enemy_minions(g, pid)
        taunts  = [m for m in enemies if m.taunt]
        pool = taunts if taunts else enemies
        for m in pool:
            acts.append(('attack', a.id, None, m.id))
        if not taunts and _face_allowed_for_attacker(g, pid, a):
            acts.append(('attack', a.id, 1 - pid, None))

    # Plays
    p = g.players[pid]
    for i, cid in enumerate(p.hand):
        usable = has_useful_play_for_card(g, pid, cid)
        if not usable: continue
        idx, tp, tm, _ = usable
        acts.append(('play', idx, tp, tm))

    # Hero power (expanded targets for Mage & Priest)
    if can_use_hero_power_ai(g, pid):
        hero = g.players[pid].hero
        hid = hero.id.upper()
        if hid == "MAGE":
            acts.append(('power', pid, 1 - pid, None))
            for m in _enemy_minions(g, pid):
                if m.health <= 1:
                    acts.append(('power', pid, None, m.id))
        elif hid == "PRIEST":
            # Heal damaged face
            if p.health < p.max_health:
                acts.append(('power', pid, pid, None))
            # Heal any damaged friendly minion
            for m in _ally_minions(g, pid):
                if m.health < m.max_health:
                    acts.append(('power', pid, None, m.id))
        else:
            # No-target powers (Hunter/Warrior/Warlock/Paladin/Druid/Rogue/Shaman)
            acts.append(('power', pid, None, None))

    acts.append(('end',))
    return acts


def simulate_apply(g: Game, action: Action) -> None:
    kind = action[0]
    if kind == 'end':
        g.end_turn(g.active_player); return
    if kind == 'attack':
        _, attacker_id, tp, tm = action
        g.attack(g.active_player, attacker_id, target_player=tp, target_minion=tm); return
    if kind == 'play':
        _, idx, tp, tm = action
        g.play_card(g.active_player, idx, target_player=tp, target_minion=tm); return
    if kind == 'power':
        _, pid, tp, tm = action
        g.use_hero_power(pid, target_player=tp, target_minion=tm); return

def search_best(g: Game, pid: int, depth: int = 2, beam: int = 6) -> Tuple[Action, int]:
    # seed candidates with current plausible actions ordered by heuristic score
    actions = enumerate_actions(g, pid)

    # Score each first move by rollout
    scored: List[Tuple[int, Action]] = []
    for a in actions:
        g2 = copy.deepcopy(g)
        simulate_apply(g2, a)
        val = eval_state(g2, pid)
        scored.append((val, a))

    # Keep top beam
    scored.sort(reverse=True, key=lambda x: x[0])
    frontier = scored[:beam]

    # Expand further depths
    for _ in range(1, depth):
        new_frontier: List[Tuple[int, Action]] = []
        for base_val, first_action in frontier:
            g2 = copy.deepcopy(g)
            simulate_apply(g2, first_action)

            # Opponent “reply” (greedy, no recursion)
            if g2.active_player != pid:
                opp_att = pick_attack(g2, 1 - pid)
                if opp_att:
                    simulate_apply(g2, opp_att[0])
                else:
                    opp_play = pick_best_play(g2, 1 - pid)
                    if opp_play:
                        simulate_apply(g2, opp_play[0])

            # One more move for us (optional for depth 3)
            # g2 now is our next turn start in many cases; evaluation still meaningful.
            val = eval_state(g2, pid)
            new_frontier.append((val, first_action))

        new_frontier.sort(reverse=True, key=lambda x: x[0])
        frontier = new_frontier[:beam]

    # Pick the action that led to the best projected value
    best_val, best_action = frontier[0]
    return best_action, best_val


def _warrior_power_then_shield_slam_tactic(g: Game, pid: int):
    p = g.players[pid]
    if g.players[pid].hero.id.upper() != "WARRIOR":
        return None
    if p.hero_power_used_this_turn:
        return None
    # Need 3 mana: (2) Armor Up! + (1) Shield Slam
    if p.mana < 3:
        return None

    # Is Shield Slam in hand?
    slam_idx = None
    for i, cid in enumerate(p.hand):
        raw = _raw(g, cid)
        if any(e.get("effect") == "deal_damage_equal_armor" for e in _card_effects(raw)):
            slam_idx = i; break
    if slam_idx is None:
        return None

    # Would +2 armor make a high-value kill possible?
    future_armor = p.armor + 2
    enemies = [m for m in g.players[1 - pid].board if m.is_alive()]
    if not enemies:
        return None
    killables = [m for m in enemies if m.health <= future_armor]
    if not killables:
        return None

    # If there is a juicy target (e.g., Antonidas), choose power first.
    best = max(killables, key=threat_score_enemy_minion)
    # Return the hero power action the game loop knows how to execute:
    return ('power', pid, None, None), 999  # very high score so it wins

def pick_best_action(g: Game, pid: int) -> Tuple[Action, int]:
    _GAME_BY_ID[_game_id(g)] = g


    tactic = _warrior_power_then_shield_slam_tactic(g, pid)
    if tactic:
        return tactic
    
    # Try tactical lethal as before
    lethal = find_lethal_action(g, pid)
    if lethal: return lethal

    # Shallow look-ahead (depth=2, beam=6 is fast)
    try:
        action, score = search_best(g, pid, depth=2, beam=6)
        return action, score
    except Exception:
        # Fallback to old heuristics if something explodes
        pass

    # Old pipeline fallback:
    att = pick_attack(g, pid)
    if att: return att
    play = pick_best_play(g, pid)
    if play: return play
    return ('end',), 0
