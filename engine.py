"""
Minimal Hearthstone-like rules engine in pure Python (fixed rush + coin).

Change log (key fixes)
- Add Minion.summoned_this_turn to model summoning sickness correctly.
- Rush: can attack MINIONS on summon, but never face on that turn.
- Charge: can attack anything on summon.
- Implement The Coin to actually grant +1 temporary mana (this turn).
"""

from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Callable, Any, Tuple
import random
import json
from pathlib import Path
from types import SimpleNamespace
from models import * 


class Game:
    def __init__(self, cards_db: Dict[str, Card], p0_deck: List[str], p1_deck: List[str],
                 seed: Optional[int] = None,
                 heroes: Tuple[Hero, Hero] = None):
        self.cards_db = cards_db
        self.players = [PlayerState(0, list(p0_deck)), PlayerState(1, list(p1_deck))]
        # Expect Hero objects
        if heroes is None:
            raise ValueError("Game requires (Hero, Hero)")
        self.players[0].hero = heroes[0]
        self.players[1].hero = heroes[1]
        self.active_player = 0
        self.turn = 0
        if seed is None:
            seed = random.randint(1, 2_147_483_647)
        self.rng = random.Random(seed)
        self.next_minion_id = 1
        self.history: List[Event] = []
        self.pending_battlecry: Optional[Dict[str, Any]] = None
        self.current_battlecry_minion_id: Optional[int] = None
        self.current_battlecry_owner: Optional[int] = None
        self._spell_countered = False

    def other(self, pid:int) -> int:
        return 1 - pid

    def _apply_temp_to_minion(self, m: Minion, caster_pid: int,
                              *, attack=0, health=0, max_health=0,
                              add_keywords: List[str] = None,
                              remove_keywords: List[str] = None) -> List[Event]:
        """
        Apply temporary deltas & keyword toggles that expire at end of caster_pid's turn.
        Stacks safely. Health reductions clamp current health if max drops later.
        """
        add_keywords = add_keywords or []
        remove_keywords = remove_keywords or []

        # --- record & apply stat deltas
        m.temp_stats.setdefault(caster_pid, {"attack":0,"health":0,"max_health":0})
        rec = m.temp_stats[caster_pid]
        rec["attack"] += int(attack)
        rec["health"] += int(health)
        rec["max_health"] += int(max_health)

        ev: List[Event] = []
        da, dh, dm = int(attack), int(health), int(max_health)

        if da:
            before = m.attack
            m.attack = max(0, m.attack + da)
            ev.append(Event("Buff", {"minion": m.id, "attack_delta": m.attack - before, "health_delta": 0}))

        if dm:
            before_max = m.max_health
            m.max_health = max(1, m.max_health + dm)
            # On a *max* increase, lift current HP by the delta
            if dm > 0:
                m.health += dm
            else:
                # clamp current HP down to new max
                if m.health > m.max_health:
                    m.health = m.max_health
            ev.append(Event("Buff", {"minion": m.id, "attack_delta": 0, "health_delta": m.max_health - before_max}))
        if dh:
            before_h = m.health
            # health delta does not change max; clamp to [0, max]
            m.health = max(0, min(m.max_health, m.health + dh))
            ev.append(Event("Buff", {"minion": m.id, "attack_delta": 0, "health_delta": m.health - before_h}))

        # --- keywords: keep stack counters so multiple sources are safe
        m.temp_keywords.setdefault(caster_pid, {})
        kw = m.temp_keywords[caster_pid]

        def _bump(k, n):
            k = k.lower().replace(" ", "_")
            kw[k] = kw.get(k, 0) + n
            # apply to live boolean flags
            if k == "taunt":           m.taunt = m.taunt or kw[k] > 0
            elif k == "charge":        m.charge = m.charge or kw[k] > 0
            elif k == "rush":          m.rush = m.rush or kw[k] > 0
            elif k in ("divine_shield","divine_shielded"):
                # divine shield treated like a boolean grant; temp stacks keep it on (won't re-pop bubbles).
                if kw[k] > 0: m.divine_shield = True

        for k in add_keywords:
            _bump(k, +1)
        for k in remove_keywords:
            _bump(k, -1)

        # keep enrage correct
        ev += self._update_enrage(m)
        return ev

    def _expire_temps_for_pid(self, ending_pid: int) -> List[Event]:
        """
        Revert *all* temporary effects that were scheduled to expire at end of ending_pid's turn:
        - minion stat/keyword temps (both sides)
        - player temp cost rules (for both players)
        """
        ev: List[Event] = []

        # --- Minions: revert stats + keywords for ending_pid
        for side in (0, 1):
            for m in list(self.players[side].board):
                # stats
                rec = m.temp_stats.pop(ending_pid, None)
                if rec:
                    da = rec.get("attack", 0)
                    dh = rec.get("health", 0)
                    dm = rec.get("max_health", 0)

                    if da:
                        before = m.attack
                        m.attack = max(0, m.attack - da)
                        ev.append(Event("BuffExpired", {"minion": m.id, "attack_delta": m.attack - before, "reason": "EndOfTurn"}))

                    if dm:
                        before_max = m.max_health
                        m.max_health = max(1, m.max_health - dm)
                        if m.health > m.max_health:
                            m.health = m.max_health
                        ev.append(Event("BuffExpired", {"minion": m.id, "attack_delta": 0, "health_delta": m.max_health - before_max, "reason": "EndOfTurn"}))

                    if dh:
                        before_h = m.health
                        m.health = max(0, min(m.max_health, m.health - dh))
                        ev.append(Event("BuffExpired", {"minion": m.id, "attack_delta": 0, "health_delta": m.health - before_h, "reason": "EndOfTurn"}))

                    ev += self._update_enrage(m)

                # keywords
                kw = m.temp_keywords.pop(ending_pid, None)
                if kw:
                    # recompute booleans by subtracting this pid's stacks
                    for k, n in kw.items():
                        # Remove stack and then recompute "any stacks > 0 across remaining pids"
                        pass
                    # recompute from remaining stacks
                    def _kw_total(name):
                        total = 0
                        for d in m.temp_keywords.values():
                            total += d.get(name, 0)
                        return total

                    # Update flags (don't remove permanent flags if base granted them)
                    if "taunt" in (kw or {}):
                        m.taunt = (m.taunt and _kw_total("taunt") > 0) or ("Taunt" in m.base_keywords)
                    if "charge" in (kw or {}):
                        m.charge = (m.charge and _kw_total("charge") > 0) or ("Charge" in m.base_keywords)
                    if "rush" in (kw or {}):
                        m.rush = (m.rush and _kw_total("rush") > 0) or ("Rush" in m.base_keywords)
                    if "divine_shield" in (kw or {}):
                        # do not force-remove a live shield if it came from elsewhere or from base card
                        m.divine_shield = m.divine_shield and (_kw_total("divine_shield") > 0 or ("Divine Shield" in m.base_keywords))

        # --- Player temp cost rules
        for pid in (0, 1):
            p = self.players[pid]
            keep: List[Dict[str, Any]] = []
            for mod in p.temp_cost_mods:
                if mod.get("expires_pid") == ending_pid and mod.get("expires_when") == "end_of_turn":
                    # drop (expired)
                    continue
                keep.append(mod)
            p.temp_cost_mods = keep

        return ev


    def find_minion(self, minion_id:int) -> Optional[Tuple[int, int, Minion]]:
        for pid in (0,1):
            for i, m in enumerate(self.players[pid].board):
                if m.id == minion_id:
                    return pid, i, m
        return None

    def get_taunts(self, pid:int) -> List[Minion]:
        return [m for m in self.players[pid].board if m.taunt and m.is_alive()]

    def get_spell_damage(self, owner: int) -> int:
        """Sum of spell damage provided by friendly minions that are alive and not silenced."""
        total = 0
        for m in self.players[owner].board:
            if m.is_alive() and not m.silenced:
                total += getattr(m, "spell_damage", 0)
        return total

    def deal_damage_to_player(self, pid:int, amount:int, source:str="") -> List[Event]:
        p = self.players[pid]
        dmg = amount
        if p.armor > 0:
            absorb = min(p.armor, dmg)
            p.armor -= absorb
            dmg -= absorb
        p.health -= dmg
        ev = [Event("PlayerDamaged", {"player": pid, "amount": dmg, "absorbed": amount - dmg, "source": source})]
        if p.health <= 0:
            ev.append(Event("PlayerDefeated", {"player": pid}))
        return ev

    def _run_minion_triggers(self, m: Minion, trigger_name: str, context: Optional[Dict[str, Any]] = None) -> List[Event]:
        fns = m.triggers_map.get(trigger_name, [])
        if not fns:
            return []
        src = SimpleNamespace(owner=m.owner, name=m.name, id=m.id)
        ev: List[Event] = []
        for fn in fns:
            ev += fn(self, src, context)
        return ev

    def _damage_minion(self, target: Minion, amount: int, source: str = "") -> List[Event]:
        """
        Applies damage to a minion, respecting Divine Shield.
        Emits:
        - DivineShieldPopped (when shield absorbs the hit)
        - MinionDamaged (when HP is reduced)
        - MinionDied (via destroy_minion) if lethal
        - Enrage updates as needed
        """
        if amount <= 0 or not target.is_alive():
            return []

        ev: List[Event] = []

        # Divine Shield absorbs the *first* source of damage entirely.
        if getattr(target, "divine_shield", False):
            target.divine_shield = False
            ev.append(Event("DivineShieldPopped", {
                "player": target.owner,
                "minion": target.id,
                "name": target.name
            }))
            return ev  # no HP loss
        
        # Normal damage flow
        target.health -= amount
        ev.append(Event("MinionDamaged", {
            "minion": target.id, "amount": amount, "source": source
        }))

        ev += self._fire_friendly_minion_damaged(target.owner, target.id, amount, source)
        # Fire “whenever this minion takes damage” hooks
        ev += self._run_minion_triggers(target, "self_damaged", {"amount": amount, "source": source})

        # Update Enrage / resolve death
        ev += self._update_enrage(target)
        if target.health <= 0:
            ev += self.destroy_minion(target, reason="LethalDamage")
        return ev

    def deal_damage_to_minion(self, target:Minion, amount:int, source:str="") -> List[Event]:
        return self._damage_minion(target, amount, source)

    def destroy_minion(self, target:Minion, reason:str="") -> List[Event]:
        ev: List[Event] = []
        loc = self.find_minion(target.id)
        if not loc:
            return ev
        pid, idx, m = loc

        # NEW: if the dying minion has an active aura, remove it first
        ev += self._disable_aura(m)

        self.players[pid].board.pop(idx)
        self.players[pid].dead_minions.append(m)
        ev.append(Event("MinionDied", {"minion": m.id, "owner": pid, "reason": reason, "name": m.name}))
        if m.deathrattle:
            ev += m.deathrattle(self, m)
        ev += self._refresh_stat_auras(pid)
        return ev

    def get_effective_cost(self, pid: int, cid: str) -> int:
        cobj = self.cards_db[cid]
        base = getattr(cobj, "cost", 0)
        delta = 0
        floor = 0  # per-auras may request a different min floor, but 0 is the default

        # --- NEW: intrinsic hand-size based cost mechanics (from cards.json raw fields)
        raw_map = self.cards_db.get("_RAW", {})
        raw = raw_map.get(cid, {}) if isinstance(raw_map, dict) else {}

        # Mountain Giant style: costs (N) less per OTHER card in your hand
        per_other_in_hand = int(raw.get("cost_less_per_other_card_in_hand", 0))
        if per_other_in_hand:
            hand_size = len(self.players[pid].hand)
            # “other” cards -> subtract this card itself if it’s in hand during evaluation
            # (When checking a card in hand, that’s always true.)
            other = max(0, hand_size - 1)
            delta -= per_other_in_hand * other

        # --- NEW: Molten Giant style: costs (N) less per damage your hero has taken
        per_damage_taken = int(raw.get("cost_less_per_damage_taken", 0))
        if per_damage_taken:
            # Armor does not count; only missing health from 30
            damage_taken = max(0, self.players[pid].max_health - self.players[pid].health)
            delta -= per_damage_taken * damage_taken

        for m in self.players[pid].board:
            if not m.is_alive() or m.silenced:
                continue

            # 5a) legacy single cost aura
            spec = getattr(m, "cost_aura_spec", None)
            if spec:
                scope = str(spec.get("scope", "friendly_spells")).lower()
                d     = int(spec.get("delta", 0))
                if scope in ("friendly_spells","spells"):
                    if _is_spell_like_card(cobj): delta += d
                elif scope.startswith("friendly_type:"):
                    want = scope.split(":", 1)[1].strip().upper()
                    if getattr(cobj, "type", "").upper() == want: delta += d

            # 5b) new list auras with kind:"cost"
            for a in getattr(m, "auras", []):
                if str(a.get("kind","")).lower() != "cost":
                    continue
                scope = str(a.get("scope", "friendly:SPELL")).lower()
                d     = int(a.get("delta", 0))
                fl    = int(a.get("floor", 0))
                floor = min(floor, fl)  # keep the lowest floor across auras (usually 0)

                apply = False
                if scope in ("friendly:spell","friendly:spells","spells"):
                    apply = _is_spell_like_card(cobj)
                elif scope.startswith("friendly:type:"):
                    want = scope.split(":", 2)[2].upper()
                    apply = (getattr(cobj, "type","").upper() == want)
                elif scope.startswith("friendly:tribe:"):
                    want = scope.split(":", 2)[2].lower()
                    apply = str(getattr(cobj, "minion_type","none")).lower() == want

                if apply:
                    delta += d

        for mod in self.players[pid].temp_cost_mods:
            scope = str(mod.get("scope", "spells")).lower()
            d     = int(mod.get("delta", 0))
            fl    = int(mod.get("floor", 0))
            floor = min(floor, fl)

            apply = False
            if scope in ("friendly:spell","friendly:spells","spells"):
                apply = (cobj.type == "SPELL")
            elif scope.startswith("friendly:type:"):
                want = scope.split(":", 2)[2].upper()
                apply = (getattr(cobj, "type","").upper() == want)
            elif scope.startswith("friendly:tribe:"):
                want = scope.split(":", 2)[2].lower()
                apply = str(getattr(cobj, "minion_type","none")).lower() == want

            if apply:
                delta += d



        return max(floor, base + delta)

    def _update_enrage(self, m: Minion) -> List[Event]:
        ev: List[Event] = []
        spec = getattr(m, "enrage_spec", None)
        if not spec:
            # if no enrage exists but flag is somehow on, clear it
            if m.enrage_active:
                # remove any lingering bonus (safety)
                bonus = int(spec.get("attack", 0)) if spec else 0
                if bonus:
                    m.attack -= bonus
                m.enrage_active = False
            return ev

        bonus = int(spec.get("attack", 0))
        should_be_active = (not m.silenced) and m.is_alive() and (m.health < m.max_health)

        if should_be_active and not m.enrage_active:
            if bonus:
                m.attack += bonus
            m.enrage_active = True
            ev.append(Event("Buff", {"minion": m.id, "attack_delta": bonus, "health_delta": 0}))
        elif (not should_be_active) and m.enrage_active:
            if bonus:
                m.attack -= bonus
            m.enrage_active = False
            ev.append(Event("Buff", {"minion": m.id, "attack_delta": -bonus, "health_delta": 0}))
        return ev


    def _remove_all_stat_auras(self, owner: int) -> List[Event]:
        ev: List[Event] = []
        for src in list(self.players[owner].board):
            if not src.is_alive() or src.silenced:
                continue
            # has any stats aura?
            has_stats = any(True for _ in self._iter_stat_auras(src))
            if has_stats:
                ev += self._disable_aura(src)
        return ev

    def _apply_all_stat_auras(self, owner: int) -> List[Event]:
        ev: List[Event] = []
        for src in list(self.players[owner].board):
            if not src.is_alive() or src.silenced:
                continue
            has_stats = any(True for _ in self._iter_stat_auras(src))
            if has_stats:
                ev += self._enable_aura(src)
        return ev

    # ---------- Aura helpers ----------
    def _aura_targets(self, owner: int, source_id: int, spec: Dict[str, Any]):
        """
        Returns a list of Minion objects to affect based on aura scope.
        Supported:
        - "other_friendly_minions"
        """
        scope = str(spec.get("scope", "other_friendly_minions")).lower()
        tribe = str(spec.get("tribe", "") or "").strip() 
        if scope == "other_friendly_minions":
            pool = [m for m in self.players[owner].board if m.is_alive() and m.id != source_id]
            if tribe:
                pool = [m for m in pool if _has_tribe(m, tribe)]     # NEW
            return pool
        
        if scope == "adjacent_friendly_minions":
            board = self.players[owner].board
            idx = next((i for i, m in enumerate(board) if m.id == source_id), -1)
            if idx == -1:
                return []
            neigh = []
            if idx - 1 >= 0 and board[idx - 1].is_alive():
                neigh.append(board[idx - 1])
            if idx + 1 < len(board) and board[idx + 1].is_alive():
                neigh.append(board[idx + 1])
            return neigh
        # Fallback: no targets
        return []

    def _apply_aura_delta(self, targets: List['Minion'], spec: Dict[str, Any], sign: int):
        """sign = +1 to apply, -1 to remove. Adjusts attack and max_health; clamps current health on removal."""
        a = int(spec.get("attack", 0)) * sign
        h = int(spec.get("health", 0)) * sign
        ev: List[Event] = []
        if a == 0 and h == 0:
            return ev
        for t in targets:
            if a:
                t.attack += a
            if h:
                before_max = t.max_health
                t.max_health += h
                if sign > 0:
                    # when max increases via aura, also lift current health by the delta
                    t.health += h
                else:
                    # clamp down if current is above new max
                    if t.health > t.max_health:
                        t.health = t.max_health
            ev.append(Event("Buff", {"minion": t.id, "attack_delta": a, "health_delta": h}))
            ev += self._update_enrage(t)
        return ev

    def _enable_aura(self, source: Minion) -> List[Event]:
        if not source.is_alive() or source.silenced:
            return []
        ev: List[Event] = []
        legacy_used = False

        specs = list(self._iter_stat_auras(source))
        cache = getattr(source, "_aura_targets_cache", None)
        if cache is None:
            cache = {}
            setattr(source, "_aura_targets_cache", cache)

        for i, spec in enumerate(specs):
            if spec.get("_legacy_stats"):
                legacy_used = True
            targets = self._aura_targets(source.owner, source.id, spec)
            # remember exactly who we buffed
            cache[i] = {t.id for t in targets}
            ev += self._apply_aura_delta(targets, spec, +1)

        if legacy_used:
            source.aura_active = True
        return ev

    def _disable_aura(self, source: Minion) -> List[Event]:
        ev: List[Event] = []
        specs = list(self._iter_stat_auras(source))
        cache = getattr(source, "_aura_targets_cache", {})  # may be missing

        for i, spec in enumerate(specs):
            # use the cached targets (who actually had the buff)
            idset = set(cache.get(i, set()))
            if not idset:
                continue
            # resolve ids -> current Minion objects (and still alive)
            tlist: List[Minion] = []
            for mid in list(idset):
                loc = self.find_minion(mid)
                if loc:
                    _, _, mm = loc
                    if mm.is_alive():
                        tlist.append(mm)
            ev += self._apply_aura_delta(tlist, spec, -1)
            # clear cache entry
            cache.pop(i, None)

        source.aura_active = False
        return ev

    def _iter_stat_auras(self, source: Minion):
        # legacy “aura_spec”
        if getattr(source, "aura_spec", None) and not source.silenced:
            # tag the dict so we can detect it if you want to keep source.aura_active
            spec = dict(source.aura_spec); spec.setdefault("_legacy_stats", True)
            yield spec
        # any “auras” with kind:"stats"
        if not source.silenced:
            for a in getattr(source, "auras", []):
                if str(a.get("kind","")).lower() == "stats":
                    yield a

    # ---------- Turn Flow ----------
    def start_game(self) -> List[Event]:
        ev: List[Event] = []

        # Randomize starting player (0 = You, 1 = AI)
        self.active_player = self.rng.choice([0, 1])
        first  = self.active_player
        second = self.other(first)

        # Mulligan-size draws
        ev += self.players[first].draw(self, 3)   # first: 3 cards
        ev += self.players[second].draw(self, 4)  # second: 4 cards

        # Give Coin to the player going second (if present in DB)
        if "THE_COIN" in self.cards_db:
            self.players[second].hand.append("THE_COIN")
            #ev.append(Event("CardCreated", {"player": second, "card": "THE_COIN"}))

        ev.append(Event("GameStart", {"active_player": self.active_player}))
        #ev += self.start_turn(self.active_player)
        self.history += ev
        return ev

    def start_first_turn(self) -> List[Event]:
        return self.start_turn(self.active_player)

    def start_turn(self, pid:int) -> List[Event]:
        p = self.players[pid]
        if pid == 0:
            self.turn += 1
        turn_number = self.turn if pid == 0 else max(1, self.turn)
        p.max_mana = min(10, p.max_mana + 1)
        p.mana = p.max_mana
        p.hero_power_used_this_turn = False
        p.hero_has_attacked_this_turn = False
        for m in p.board:
            m.exhausted = False
            m.has_attacked_this_turn = False
            m.summoned_this_turn = False
            m.can_attack = m.charge or (not m.exhausted)
        ev = [Event("TurnStart", {"player": pid, "turn": turn_number})]
        ev += p.draw(self, 1)
        return ev

    def end_turn(self, pid:int) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")
        self.active_player = self.other(pid)
        ev = []

        ev += self._fire_end_of_turn(pid)

        # now actually end the turn
        self.active_player = self.other(pid)
        ev.append(Event("TurnEnd", {"player": pid}))

        ev += self._expire_temps_for_pid(pid)

        # thaw after this player’s turn finishes
        ev += self._thaw_owner(pid)   # NEW

        ev += self.start_turn(self.active_player)
        self.history += ev
        return ev

    # ---------- Commands ----------
    def use_hero_power(self, pid:int,
                       target_player:Optional[int]=None,
                       target_minion:Optional[int]=None) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")
        p = self.players[pid]
        hero = p.hero
        if hero is None:
            raise IllegalAction("No hero")
        if p.hero_power_used_this_turn:
            raise IllegalAction("Hero power already used")
        if p.mana < hero.power.cost:
            raise IllegalAction("Not enough mana for hero power")

        # Validate targeting by hero.power.targeting
        targ = hero.power.targeting
        needs_target = targ in ("any_character", "enemy_minion", "friendly_minion",
                                "friendly_character", "enemy_character")
        runtime_target: Optional[int] = None  # int => minionId or playerId

        if needs_target:
            # We accept either (target_minion) or (target_player)
            if target_minion is not None:
                loc = self.find_minion(target_minion)
                if not loc:
                    raise IllegalAction("Target minion not found")
                # scope checking
                tpid, _, _ = loc
                if targ == "enemy_minion" and tpid == pid:
                    raise IllegalAction("Must target enemy minion")
                if targ == "friendly_minion" and tpid != pid:
                    raise IllegalAction("Must target friendly minion")
                runtime_target = target_minion
            elif target_player in (0, 1):
                if targ == "enemy_minion" or targ == "friendly_minion":
                    raise IllegalAction("This power requires a minion target")
                if targ == "friendly_character" and target_player != pid:
                    raise IllegalAction("Must target friendly character")
                if targ in ("enemy_character",) and target_player == pid:
                    raise IllegalAction("Must target enemy character")
                runtime_target = target_player
            else:
                raise IllegalAction("Hero power needs a target")
        else:
            # If the power declares "enemy_face", UI passes none; effect spec can infer POV
            if targ == "enemy_face":
                runtime_target = None  # effect spec resolves using owner POV
            else:
                runtime_target = None

        # Pay + mark used + log
        p.mana -= hero.power.cost
        p.hero_power_used_this_turn = True
        ev: List[Event] = [Event("HeroPowerUsed", {"player": pid, "hero": hero.id})]

        # Build a lightweight "source" carrying owner + display name
        kw = {"type": "SPELL"} if getattr(hero.power, "counts_as_spell", False) else {}
        src = SimpleNamespace(owner=pid, name=hero.power.name, **kw)  # NEW

        # Compile & run effects (on demand)
        impl = _compile_effects_for_heroes(hero.power.effects_spec, self.cards_db)
        if isinstance(runtime_target, int):
            if target_minion is not None:
                tagged = {"minion": runtime_target}
            elif target_player in (0, 1):
                tagged = {"player": runtime_target}
            else:
                tagged = None
        else:
            tagged = None
        ev += impl(self, src, tagged)

        self.history += ev
        return ev

    def hero_can_attack(self, pid:int) -> bool:
        p = self.players[pid]
        return (
            pid == self.active_player
            and p.weapon is not None
            and p.weapon.attack > 0
            and not p.hero_has_attacked_this_turn
            and not p.hero_frozen
        )

    def hero_legal_targets(self, pid:int) -> Tuple[set, bool]:
        """Return (enemy_minion_ids, face_ok). Taunt gates face."""
        opp = self.other(pid)
        if not self.hero_can_attack(pid):
            return set(), False
        taunts = [m for m in self.players[opp].board if m.taunt and m.is_alive()]
        if taunts:
            return {m.id for m in taunts}, False
        return {m.id for m in self.players[opp].board if m.is_alive()}, True

    def hero_attack(self, pid:int, *, target_player: Optional[int]=None, target_minion: Optional[int]=None) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")
        if not self.hero_can_attack(pid):
            raise IllegalAction("Hero cannot attack")

        p   = self.players[pid]
        opp = self.other(pid)
        w   = p.weapon
        if w is None or w.attack <= 0:
            raise IllegalAction("No usable weapon")

        # Taunt / legality
        allowed_mins, face_ok = self.hero_legal_targets(pid)

        ev: List[Event] = []

        # ----- vs MINION -----
        if target_minion is not None:
            loc = self.find_minion(target_minion)
            if not loc:
                raise IllegalAction("Target minion not found")
            tpid, _, tgt = loc
            if tpid != opp:
                raise IllegalAction("Must target enemy")
            if target_minion not in allowed_mins:
                raise IllegalAction("Illegal target (Taunt)")

            # announce
            ev.append(Event("HeroAttack", {"player": pid, "target": tgt.id}))

            # Defender secrets first
            ev += self._trigger_secrets(opp, "minion_attacked")

            # Fire weapon triggers before damage
            ev += self._run_weapon_triggers(pid, "hero_attacks", {
                "target_minion": (tgt.id if target_minion is not None else None),
                "target_player": (self.other(pid) if target_player is not None else None)
            })

            # capture minion's attack BEFORE dealing damage (simultaneous combat)
            retaliate = max(0, tgt.attack)

            ret_to_minion = self._damage_minion(tgt, w.attack, source=w.name)
            ev += ret_to_minion

            if retaliate > 0:
                ret_to_hero = self.deal_damage_to_player(pid, retaliate, source=tgt.name)
                ev += ret_to_hero
                # If hero actually took damage, emit target minion's self_deals_damage
                if any(e.kind == "PlayerDamaged" and e.payload.get("player") == pid and e.payload.get("amount", 0) > 0 for e in ret_to_hero):
                    ev += self._run_minion_triggers(tgt, "self_deals_damage", {"player": pid})

            # spend durability
            ev += self.lose_weapon_durability(pid, 1, source="HeroAttack")

            p.hero_has_attacked_this_turn = True
            self.history += ev
            return ev

        # ----- vs FACE -----
        if target_player is not None:
            if target_player != opp:
                raise IllegalAction("Must target enemy face")
            if not face_ok:
                raise IllegalAction("Taunt blocks attacking face")

            ev.append(Event("HeroAttack", {"player": pid, "target": f"player:{opp}"}))

            # Defender secrets first
            ev += self._trigger_secrets(opp, "hero_attacked")

            # >>> RECHECK hero can still attack (weapon removed, atk 0, or hero died)
            if not self.hero_can_attack(pid):
                self.history += ev
                return ev

            # Fire weapon triggers before damage
            ev += self._run_weapon_triggers(pid, "hero_attacks", {
                "target_minion": None,
                "target_player": opp
            })

            ev += self.deal_damage_to_player(opp, w.attack, source=w.name)
            ev += self.lose_weapon_durability(pid, 1, source="HeroAttack")

            p.hero_has_attacked_this_turn = True
            self.history += ev
            return ev

        raise IllegalAction("Hero attack needs a target")

    def _trigger_secrets(self, victim_pid: int, trigger: str, context: Optional[Dict[str, Any]] = None) -> List[Event]:
        p = self.players[victim_pid]
        if not p.active_secrets:
            return []
        fired = [s for s in p.active_secrets if s.get("trigger") == trigger]
        if not fired:
            return []
        ev: List[Event] = []
        for s in fired:
            # 1) reveal
            ev.append(Event("SecretRevealed", {"player": victim_pid, "card": s["card_id"], "name": s["name"]}))
            # 2) run the secret's effect (now with context)
            src = SimpleNamespace(owner=victim_pid, name=s["name"])
            ev += s["runner"](self, src, context or None)
            # 3) consume
            p.active_secrets.remove(s)
            self.players[victim_pid].graveyard.append(s["card_id"])
            # 4) notify friendly weapon triggers (unchanged)
            ev += self._run_weapon_triggers(victim_pid, "friendly_secret_revealed", {"secret": s["card_id"]})
        return ev


    def _fire_friendly_spell_cast(self, pid: int) -> List[Event]:
        """
        After a player casts any *spell card*, fire 'friendly_spell_cast' triggers
        on that player's board. We pass the minion itself as the runtime target
        so JSON like {effect:add_attack, target:self} works with _fx_add_attack.
        """
        ev: List[Event] = []
        me = self.players[pid]
        for m in list(me.board):
            if not m.is_alive() or m.silenced:
                continue
            # run compiled trigger runners from triggers_map
            ev += self._run_minion_triggers(m, "friendly_spell_cast", {"minion": m.id})
        return ev

    def _fire_end_of_turn(self, owner: int) -> List[Event]:
        ev: List[Event] = []
        for m in list(self.players[owner].board):
            if not m.is_alive() or m.silenced:
                continue
            ev += self._run_minion_triggers(m, "end_of_your_turn", None)
        return ev

    def play_card(self, pid:int, hand_index:int, target_player:Optional[int]=None, target_minion:Optional[int]=None, insert_at: Optional[int] = None,) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")

        p = self.players[pid]

        if hand_index < 0 or hand_index >= len(p.hand):
            raise IllegalAction("Bad hand index")

        cid = p.hand[hand_index]
        card = self.cards_db[cid]

        # --- Secret duplicate check (must happen BEFORE paying mana or popping the card) ---
        if card.type == "SECRET" or ("Secret" in getattr(card, "keywords", [])):
            if any(s.get("card_id") == card.id for s in self.players[pid].active_secrets):
                raise IllegalAction("You already have that Secret active.")

        # Only block MINION plays when board is full
        if card.type == "MINION" and len(p.board) >= 7:
            raise IllegalAction("Board full")

        eff_cost = self.get_effective_cost(pid, cid)

        if p.mana < eff_cost:
            raise IllegalAction("Not enough mana")

        p.mana -= eff_cost
        p.hand.pop(hand_index)
        ev: List[Event] = [Event("CardPlayed", {"player": pid, "card": cid, "name": card.name})]

        if card.type == "MINION":
            if len(p.board) >= 7:
                raise IllegalAction("Board full")
            m = Minion(
                id=self.next_minion_id, owner=pid, name=card.name,
                attack=card.attack, health=card.health, max_health=card.health,
                taunt=("Taunt" in card.keywords),
                charge=("Charge" in card.keywords),
                rush=("Rush" in card.keywords),
                divine_shield = ("Divine Shield" in card.keywords),
                summoned_this_turn=True,
                cost=card.cost,
                rarity=card.rarity,
                card_id=card.id,
                base_attack=card.attack,
                base_health=card.health,
                base_text=card.text or "",
                base_keywords=list(card.keywords),
                aura_spec=card.aura_spec,
                aura_active=False,
                spell_damage=getattr(card, "spell_damage", 0),
                enrage_spec=getattr(card, "enrage_spec", None),
                enrage_active=False,
                minion_type=getattr(card, "minion_type", "None"),
                base_minion_type=getattr(card, "minion_type", "None"),
                triggers_map=dict(getattr(card, "triggers_map", {})),
                cost_aura_spec=getattr(card, "cost_aura_spec", None),
                auras=list(getattr(card, "auras", [])),
                cant_attack = ("Can't Attack" in card.keywords) or ("Cant Attack" in card.keywords),
            )
            self.next_minion_id += 1

            # --- place at requested index if provided ---
            if insert_at is None:
                p.board.append(m)
            else:
                # clamp to legal (n+1) slots
                idx = max(0, min(int(insert_at), len(p.board)))
                p.board.insert(idx, m)

            ev.append(Event("MinionSummoned", {"player": pid, "minion": m.id, "name": m.name}))

            # if the minion provides an aura, enable it now
            ev += self._enable_aura(m)
            # and let existing friendly auras affect this newcomer
            #ev += self._apply_existing_auras_to(m)

            # Recompute all adjacent auras for this side so old neighbors lose stale buffs
            ev += self._refresh_stat_auras(pid)

            ev += self._handle_friendly_summon(pid, m.id)
            
            # --- after summon/auras/summon-triggers, before this minion's battlecry
            ev += self._trigger_secrets(self.other(pid), "enemy_minion_played", {"minion": m.id})

            # --- after you insert the minion and add MinionSummoned + auras ---
            if card.battlecry:
                need = (self.cards_db.get("_TARGETING", {}).get(card.id, "none") or "none").lower()

                # If a target was provided, resolve immediately (unchanged behavior)
                if need != "none" and (target_minion is None and target_player not in (0, 1)):
                    # No target yet → DEFER it and return an event so the UI can ask the user
                    self.pending_battlecry = {
                        "pid": pid,
                        "card_id": card.id,
                        "minion_id": m.id,
                        "need": need,
                        "fn": card.battlecry,   # compiled effect
                    }
                    ev.append(Event("BattlecryPending", {
                        "player": pid, "minion": m.id, "card": card.id, "need": need
                    }))
                else:
                    # Resolve now (existing flow)
                    if need != "none":
                        if target_minion is not None:
                            tagged = {"minion": target_minion}
                        elif target_player in (0, 1):
                            tagged = {"player": target_player}
                        else:
                            tagged = None
                    else:
                        tagged = None

                    self.current_battlecry_minion_id = m.id
                    self.current_battlecry_owner = pid

                    try:
                        ev += card.battlecry(self, card, tagged)
                    finally:
                        self.current_battlecry_minion_id = None
                        self.current_battlecry_owner = None
        elif card.type == "SPELL":
            ev += self._fire_friendly_spell_cast(pid)

            # Let opponent secrets (e.g., Counterspell) react to the cast and possibly cancel it
            self._spell_countered = False
            ev += self._trigger_secrets(self.other(pid), "enemy_spell_cast", {"card": cid, "name": card.name})
            if self._spell_countered:
                # Spell fizzles: no on_cast effects, still goes to graveyard
                ev.append(Event("SpellCountered", {"player": pid, "card": cid, "name": card.name}))
                self.players[pid].graveyard.append(card.id)
                self.history += ev
                return ev

            # Not countered → resolve normally
            if card.on_cast:
                tagged = None
                if target_minion is not None:
                    tagged = {"minion": target_minion}
                elif target_player in (0, 1):
                    tagged = {"player": target_player}

                ev += card.on_cast(self, card, tagged)
            self.players[pid].graveyard.append(card.id)
        elif card.type == "WEAPON":
            old = p.weapon
            if old is not None:
                ev.append(Event("WeaponBroken", {"player": pid, "name": old.name}))
            p.weapon = Weapon(name=card.name, attack=card.attack,
                              durability=card.health, card_id=card.id,
                              triggers_map=dict(getattr(card, "triggers_map", {})),
            )
            ev.append(Event("WeaponEquipped", {
                "player": pid, "name": card.name,
                "attack": card.attack, "durability": card.health
            }))

            # If the weapon card ALSO defines effects (battlecry/on_cast), run them too
            if card.battlecry:
                ev += card.battlecry(self, card, None)
            if card.on_cast:
                ev += card.on_cast(self, card, None)
        elif card.type == "SECRET":
            # no duplicate of same secret for that player
            if any(s["card_id"] == card.id for s in p.active_secrets):
                raise IllegalAction("You already have that Secret active")
            
            # === Secrets are SPELL-LIKE on cast ===
            # 1) Friendly "cast a spell" triggers (e.g., Antonidas)
            ev += self._fire_friendly_spell_cast(pid)

            # 2) Enemy secrets may counter spells (Counterspell)
            self._spell_countered = False
            ev += self._trigger_secrets(self.other(pid), "enemy_spell_cast", {"card": cid, "name": card.name})
            if self._spell_countered:
                # Fizzles like a spell: effects don't arm; card still goes to graveyard
                ev.append(Event("SpellCountered", {"player": pid, "card": cid, "name": card.name}))
                self.players[pid].graveyard.append(card.id)
                self.history += ev
                return ev
            
            # 3) Not countered → arm the secret (reveal effects are NOT “spells”)
            trig = getattr(card, "secret_trigger", None)
            run  = getattr(card, "secret_runner", None)
            if not trig or not callable(run):
                raise IllegalAction("Malformed Secret")
            p.active_secrets.append({
                "card_id": card.id,
                "name": card.name,
                "trigger": trig,
                "runner": run,
            })
            ev.append(Event("SecretPlayed", {"player": pid}))  # no name: hidden information
            # (stays armed; not in graveyard yet)
        else:
            raise IllegalAction("Unknown card type")
        self.history += ev
        return ev

    def _thaw_owner(self, pid: int) -> List[Event]:
        ev: List[Event] = []
        p = self.players[pid]
        if p.hero_frozen:
            p.hero_frozen = False
            ev.append(Event("Thaw", {"target_type": "player", "player": pid}))
        for m in list(p.board):
            if getattr(m, "frozen", False):
                m.frozen = False
                ev.append(Event("Thaw", {"target_type": "minion", "player": pid, "minion": m.id}))
        return ev

    def resolve_pending_battlecry(self, pid:int,
                              target_player:Optional[int]=None,
                              target_minion:Optional[int]=None) -> List[Event]:
        if self.pending_battlecry is None:
            raise IllegalAction("No pending battlecry")
        pb = self.pending_battlecry
        if pid != self.active_player or pid != pb["pid"]:
            raise IllegalAction("Not your pending battlecry")

        loc = self.find_minion(pb["minion_id"])
        if not loc:
            self.pending_battlecry = None
            return []

        need = pb["need"]
        owner_scope, tribe = _parse_minion_targeting(need)

        tagged = None
        if target_minion is not None:
            loc2 = self.find_minion(target_minion)
            if not loc2:
                raise IllegalAction("Target minion not found")
            tpid, _, tgtm = loc2

            # If the spec is character-wide, reject minion targets
            char_scopes = ("any_character","friendly_character","enemy_character")
            if need in char_scopes:
                raise IllegalAction("This battlecry requires a character (face) target")

            # Owner scope gate (friendly/enemy/any)
            if not _minion_owner_matches(pid, tpid, owner_scope):
                raise IllegalAction("Wrong side for this target")

            # Tribe gate (if a tribe is requested)
            if tribe is not None and not _has_tribe(tgtm, tribe):
                raise IllegalAction("Target does not match required tribe")

            # If no tribe was requested, still ensure it's a minion-scope card
            if tribe is None and not any(need.startswith(x) for x in ("friendly_minion","enemy_minion","any_minion","friendly_tribe","enemy_tribe","any_tribe")):
                raise IllegalAction("This battlecry doesn't accept a minion target")

            tagged = {"minion": target_minion}

        elif target_player in (0, 1):
            # Any *_tribe or *_minion targeting cannot accept a face
            if any(need.startswith(x) for x in ("friendly_minion","enemy_minion","any_minion","friendly_tribe","enemy_tribe","any_tribe")):
                raise IllegalAction("This battlecry requires a minion target")
            if need == "friendly_character" and target_player != pid:
                raise IllegalAction("Must target friendly character")
            if need == "enemy_character" and target_player == pid:
                raise IllegalAction("Must target enemy character")
            tagged = {"player": target_player}
        else:
            raise IllegalAction("Battlecry needs a target")

        card_obj = self.cards_db[pb["card_id"]]
        fn = pb["fn"]
        self.pending_battlecry = None
        self.current_battlecry_minion_id = pb["minion_id"]
        self.current_battlecry_owner = pid
        try:
            ev = fn(self, card_obj, tagged)
        finally:
            self.current_battlecry_minion_id = None
            self.current_battlecry_owner = None
        self.history += ev
        return ev

    def equip_weapon(self, pid: int, name: str, attack: int, durability: int,
                 *, card_id: str = "", triggers_map: Optional[Dict[str, List[Callable]]] = None) -> List[Event]:
        p = self.players[pid]
        ev: List[Event] = []
        if p.weapon is not None:
            old = p.weapon
            p.weapon = None
            ev.append(Event("WeaponDestroyed", {"player": pid, "name": old.name, "reason": "Replaced"}))
        p.weapon = Weapon(
            name=name, attack=attack, durability=durability,
            card_id=card_id, triggers_map=dict(triggers_map or {})
        )
        ev.append(Event("WeaponEquipped", {"player": pid, "name": name, "attack": attack, "durability": durability}))
        self.history += ev
        return ev

    def destroy_weapon(self, pid: int, reason: str = "Broken") -> List[Event]:
        """Break the current weapon, if any. Emits logs."""
        p = self.players[pid]
        if p.weapon is None:
            return []
        w = p.weapon
        p.weapon = None
        ev = [Event("WeaponDestroyed", {"player": pid, "name": w.name, "reason": reason})]
        self.history += ev
        return ev

    def lose_weapon_durability(self, pid: int, amount: int = 1, source: str = "HeroAttack") -> List[Event]:
        """Lose durability, log the change, auto-break at 0."""
        p = self.players[pid]
        if p.weapon is None or amount <= 0:
            return []
        before = p.weapon.durability
        p.weapon.durability = max(0, p.weapon.durability - amount)
        after = p.weapon.durability
        ev: List[Event] = [Event("WeaponDurabilityChanged", {
            "player": pid, "name": p.weapon.name, "from": before, "to": after, "source": source
        })]
        # Break at 0 (log destruction)
        if p.weapon.durability == 0:
            # Destroy emits its own WeaponDestroyed log
            ev += self.destroy_weapon(pid, reason="DurabilityZero")
        self.history += ev
        return ev

    def _handle_friendly_summon(self, owner: int, summoned_minion_id: int) -> List[Event]:
        """
        Fires 'friendly_summon' triggers for OWNER (including the minion just summoned).
        Each trigger contains precompiled effect runners (no targets; they decide).
        """
        ev: List[Event] = []
        # Copy list to be safe if effects summon/kill minions
        for m in list(self.players[owner].board):
            if not m.is_alive() or m.silenced:
                continue

            if m.id == summoned_minion_id:
                # Do not let a minion trigger from its own summon.
                continue

            runs = m.triggers_map.get("friendly_summon", [])
            if not runs:
                continue

            # Provide a small source object: owner + name
            src = SimpleNamespace(owner=owner, name=m.name, id=m.id)  # NEW

            for run in runs:
                # Effects may generate damage events, deaths, etc.
                ev += run(self, src, {"minion": summoned_minion_id})
        # Log a synthetic event if you want (optional)
        return ev

    def _run_weapon_triggers(self, pid: int, trigger_name: str, context: Optional[Dict[str, Any]] = None) -> List[Event]:
        p = self.players[pid]
        if not p.weapon:
            return []
        fns = p.weapon.triggers_map.get(trigger_name, [])
        if not fns:
            return []
        src = SimpleNamespace(owner=pid, name=p.weapon.name)  # NEW
        ev: List[Event] = []
        for fn in fns:
            ev += fn(self, src, context)
        return ev

    def _fire_minion_healed(self, healed_minion_owner: int, minion_id: int, amount: int, source: str) -> List[Event]:
        """
        Notify ALL minions on BOTH sides that some minion was healed.
        Context includes the healed minion id, how much, and the source name.
        """
        ev: List[Event] = []
        for pid in (0, 1):
            for m in list(self.players[pid].board):
                if m.silenced:
                    continue
                runs = m.triggers_map.get("minion_healed", [])
                if not runs:
                    continue
                src = SimpleNamespace(owner=m.owner, name=m.name, id=m.id)
                ctx = {"minion": minion_id, "amount": amount, "source": source, "owner": healed_minion_owner}
                for run in runs:
                    ev += run(self, src, ctx)
        return ev

    def _fire_friendly_minion_damaged(self, owner: int, damaged_minion_id: int, amount: int, source: str) -> List[Event]:
        """
        Notify all minions on OWNER's board (including the damaged one) that a friendly
        minion just took real damage. Context includes minion id, amount, and source name.
        """
        ev: List[Event] = []
        for m in list(self.players[owner].board):
            if m.silenced:
                continue
            runs = m.triggers_map.get("friendly_minion_damaged", [])
            if not runs:
                continue
            src = SimpleNamespace(owner=m.owner, name=m.name, id=m.id)
            for run in runs:
                ev += run(self, src, {"minion": damaged_minion_id, "amount": amount, "source": source})
        return ev


    def attack(self, pid:int, attacker_id:int, target_player:Optional[int]=None, target_minion:Optional[int]=None) -> List[Event]:
        if pid != self.active_player:
            raise IllegalAction("Not your turn")
        loc = self.find_minion(attacker_id)
        if not loc:
            raise IllegalAction("Attacker not found")
        apid, _, att = loc
        if apid != pid:
            raise IllegalAction("You don't control that minion")
        if getattr(att, "cant_attack", False):
            raise IllegalAction("This minion can't attack")
        if att.has_attacked_this_turn or not att.is_alive():
            raise IllegalAction("Minion cannot attack")
        if att.attack <= 0:
            raise IllegalAction("Minion has 0 attack")
        if getattr(att, "frozen", False):
            raise IllegalAction("Minion is frozen")   # NEW

        opp = self.other(pid)
        taunts = self.get_taunts(opp)

        # ----- Attack MINION -----
        if target_minion is not None:
            tloc = self.find_minion(target_minion)
            if not tloc:
                raise IllegalAction("Target minion not found")
            tpid, _, tgt = tloc
            if tpid != opp:
                raise IllegalAction("Must target enemy")
            if taunts and not tgt.taunt:
                raise IllegalAction("Must attack Taunt first")

            # Legality vs MINION
            can_vs_minion = (not att.summoned_this_turn) or att.charge or att.rush
            if not can_vs_minion:
                raise IllegalAction("This minion can't attack another minion yet")

            # SIMULTANEOUS DAMAGE
            att.has_attacked_this_turn = True
            ev: List[Event] = [Event("Attack", {"attacker": att.id, "target": tgt.id})]

            # SECRETS: defender 'opp' minion is being attacked
            ev += self._trigger_secrets(opp, "minion_attacked")

            a_dmg = att.attack
            t_dmg = tgt.attack

            # --- attacker deals damage to target ---
            ret1 = self._damage_minion(tgt, a_dmg, source=att.name)
            ev += ret1
            # If damage actually landed (not absorbed by Divine Shield), fire the trigger
            if any(e.kind == "MinionDamaged" and e.payload.get("minion") == tgt.id and e.payload.get("amount", 0) > 0 for e in ret1):
                ev += self._run_minion_triggers(att, "self_deals_damage", {"minion": tgt.id})

            # --- defender deals damage back to attacker ---
            ret2 = self._damage_minion(att, t_dmg, source=tgt.name)
            ev += ret2
            if any(e.kind == "MinionDamaged" and e.payload.get("minion") == att.id and e.payload.get("amount", 0) > 0 for e in ret2):
                ev += self._run_minion_triggers(tgt, "self_deals_damage", {"minion": att.id})

            self.history += ev
            return ev

        # ----- Attack FACE -----
        if taunts:
            raise IllegalAction("Taunt blocks attacking face")
        can_vs_face = (not att.summoned_this_turn) or att.charge
        if not can_vs_face:
            raise IllegalAction("This minion can't attack the enemy hero yet")

        att.has_attacked_this_turn = True
        ev = [Event("Attack", {"attacker": att.id, "target": f"player:{opp}"})]

        # SECRETS: defender 'opp' hero is being attacked
        ev += self._trigger_secrets(opp, "hero_attacked")

        # >>> RECHECK attacker still present & alive (secret may have killed/bounced it)
        loc_after = self.find_minion(att.id)
        if (not loc_after) or (not loc_after[2].is_alive()):
            # Attack fizzles; do NOT deal face damage
            self.history += ev
            return ev

        ret_face = self.deal_damage_to_player(opp, att.attack, source=att.name)
        ev += ret_face
        # Only if real damage got through armor
        if any(e.kind == "PlayerDamaged" and e.payload.get("player") == opp and e.payload.get("amount", 0) > 0 for e in ret_face):
            ev += self._run_minion_triggers(att, "self_deals_damage", {"player": opp})

        self.history += ev
        return ev
    
    def _refresh_stat_auras(self, owner: int) -> List[Event]:
        """Re-evaluate all *stats* auras (legacy aura_spec or auras[kind=stats]) for OWNER."""
        ev: List[Event] = []
        for src in list(self.players[owner].board):
            if not src.is_alive() or src.silenced:
                continue

            # Needs refresh if the source has any stats aura (regardless of scope)
            has_legacy_stats = (
                getattr(src, "aura_spec", None)
                and str(src.aura_spec.get("scope", "")).lower() in (
                    "adjacent_friendly_minions", "other_friendly_minions"
                )
            )
            has_list_stats = any(
                str(a.get("kind", "")).lower() == "stats" and
                str(a.get("scope", "")).lower() in ("adjacent_friendly_minions", "other_friendly_minions")
                for a in getattr(src, "auras", [])
            )
            if has_legacy_stats or has_list_stats:
                ev += self._disable_aura(src)
                ev += self._enable_aura(src)
        return ev

    def _summon_from_card_spec(self, owner, card_spec, count):
        ev = []
        for _ in range(count):
            if len(self.players[owner].board) >= 7:
                break
                
            kws = card_spec.get("keywords", []) or []

            m = Minion(
                id=self.next_minion_id,
                owner=owner,
                name=card_spec.get("name", "Token"),
                attack=int(card_spec.get("attack", 0)),
                health=int(card_spec.get("health", 1)),
                max_health=int(card_spec.get("health", 1)),
                taunt=("Taunt" in kws),
                divine_shield = ("Divine Shield" in kws),
                charge=("Charge" in kws),
                rush=("Rush" in kws),
                exhausted=not ("Charge" in kws or "Rush" in kws),
                cost=int(card_spec.get("cost", 0)),
                rarity=str(card_spec.get("rarity", "Common")),
                card_id=card_spec.get("id", ""),
                base_attack=int(card_spec.get("attack", 0)),
                base_health=int(card_spec.get("health", 1)),
                base_text=str(card_spec.get("text", "")),
                base_keywords=list(kws),
                aura_spec=card_spec.get("aura"),
                aura_active=False,
                spell_damage=int(card_spec.get("spell_damage", 0)),
                enrage_spec=card_spec.get("enrage"),
                enrage_active=False,
                minion_type=str(card_spec.get("minion_type", "None")),
                base_minion_type=str(card_spec.get("minion_type", "None")),
                triggers_map=dict(card_spec.get("triggers_map", {})),
                cost_aura_spec=card_spec.get("cost_aura"),
                auras=list(card_spec.get("auras", [])),
                cant_attack = ("Can't Attack" in kws) or ("Cant Attack" in kws)
            )
            self.next_minion_id += 1
            self.players[owner].board.append(m)
            ev.append(Event("MinionSummoned", {"player": owner, "minion": m.id, "name": m.name}))

            # NEW: enable the token's own aura (if any), then apply existing friendly auras to it
            ev += self._enable_aura(m)
            #ev += g._apply_existing_auras_to(m)
            ev += self._handle_friendly_summon(owner, m.id)
            ev += self._refresh_stat_auras(owner)
        return ev

# ---------------------- Small helpers (DRY only, no behavior change) ----------------------

def _resolve_owner_list(owner_param, g:'Game', source_owner:int) -> List[int]:
    """Map an owner param to a list of pids (used by summon, pools, etc.)."""
    if isinstance(owner_param, int):
        return [0 if owner_param == 0 else 1]
    s = str(owner_param).lower()
    if s in ("player", "friendly", "ally", "self"):
        return [source_owner]
    if s in ("enemy", "opponent", "foe"):
        return [g.other(source_owner)]
    if s in ("both", "each", "mirror"):
        return [source_owner, g.other(source_owner)]
    if s in ("active", "current"):
        return [g.active_player]
    if s in ("inactive", "other_active"):
        return [g.other(g.active_player)]
    return [source_owner]

def _resolve_owner_single(owner_param, g:'Game', source_owner:int, *, default_to_enemy:bool=False) -> int:
    """Map an owner param to a single pid (used by destroy_weapon, etc.)."""
    if isinstance(owner_param, int):
        return 0 if owner_param == 0 else 1
    s = str(owner_param).lower()
    if s in ("enemy", "opponent", "foe"):
        return g.other(source_owner)
    if s in ("friendly", "ally", "self", "player"):
        return source_owner
    if s == "active":
        return g.active_player
    if s == "inactive":
        return g.other(g.active_player)
    return g.other(source_owner) if default_to_enemy else source_owner

def _is_spell_source(source_obj) -> bool:
    """True iff effects should get Spell Damage bonus."""
    return getattr(source_obj, "type", None) == "SPELL"

def _with_spell_bonus(base_amount:int, g:'Game', owner:int, source_obj) -> int:
    """base + (spell damage if applicable)."""
    return base_amount + (g.get_spell_damage(owner) if _is_spell_source(source_obj) else 0)

def hero_name(h) -> str:
    if isinstance(h, str):
        return h.capitalize()
    if hasattr(h, "name"):
        return h.name
    return str(h)

# ---------------------- Target helpers ----------------------

def _minion_dead_or_gone(g: 'Game', minion_id: int) -> bool:
    # still on board?
    loc = g.find_minion(minion_id)
    if loc:
        return not loc[2].is_alive()  # should always be alive on board, but keep for safety
    # not on board — check both graveyards
    for pid in (0, 1):
        if any(dm.id == minion_id for dm in g.players[pid].dead_minions):
            return True
    # not in graveyard either (e.g., bounced/returned to hand/removed) — treat as "gone"
    return True

def _resolve_tagged_target(g, target):
    """
    Accepts either:
      - {"minion": <minion_id>}
      - {"player": 0|1}
      - legacy int (0|1 => player; else try minion id)
    Returns: ("minion", Minion) | ("player", pid) | (None, None)
    """
    # New tagged dict form
    if isinstance(target, dict):
        if "minion" in target:
            loc = g.find_minion(target["minion"])
            return ("minion", loc[2]) if loc else (None, None)
        if "player" in target and target["player"] in (0, 1):
            return ("player", target["player"])
        return (None, None)

    # Back-compat: raw int
    if isinstance(target, int):
        if target in (0, 1):
            return ("player", target)
        loc = g.find_minion(target)
        if loc:
            return ("minion", loc[2])
    return (None, None)

def _apply_adjacent_buff(g, owner_pid: int, summoned_minion_id: int, *, attack=0, health=0, taunt=False):
    loc = g.find_minion(summoned_minion_id)
    if not loc:
        return []
    pid, idx, _self = loc
    if pid != owner_pid:
        return []

    board = g.players[pid].board
    events = []

    def buff_minion(m):
        if attack or health:
            m.attack += int(attack)
            m.max_health += int(health)
            m.health += int(health)
            events.append(Event("Buff", {
                "minion": m.id,
                "attack_delta": int(attack),
                "health_delta": int(health)
            }))
            # keep enrage correct if you use it
            events.extend(g._update_enrage(m))
        if taunt and not getattr(m, "taunt", False):
            m.taunt = True
            events.append(Event("BuffKeyword", {"minion": m.id, "keyword": "Taunt"}))

    if idx - 1 >= 0 and board[idx - 1].is_alive():
        buff_minion(board[idx - 1])
    if idx + 1 < len(board) and board[idx + 1].is_alive():
        buff_minion(board[idx + 1])

    return events

def _has_tribe(m: 'Minion', tribe: str) -> bool:
    """Return True if minion counts as the given tribe. 'All' counts as every tribe."""
    if not tribe or tribe.lower() == "none":
        return True
    mt = (getattr(m, "minion_type", "None") or "None").lower()
    if mt == "all":
        return True
    return mt == tribe.lower()

def _is_spell_like_card(cobj) -> bool:
    """Cards that should count as 'spells' for cost & 'cast a spell' triggers."""
    t = str(getattr(cobj, "type", "")).upper()
    return t in ("SPELL", "SECRET")

def _parse_minion_targeting(spec: str):
    """
    Returns (owner_scope, tribe) where:
      owner_scope ∈ {"friendly", "enemy", "any"} (default "any")
      tribe is a lowercase string or None
    Supported:
      "friendly_minion", "enemy_minion", "any_minion"
      "friendly_tribe:beast", "enemy_tribe:mech", "any_tribe:dragon", ...
      Legacy shortcuts also work: "friendly_beast", "enemy_beast", "any_beast"
    """
    s = (spec or "none").lower().strip()

    # Legacy shortcuts -> normalize to tribe pattern
    legacy = ("beast","mech","demon","dragon","murloc","pirate","totem",
              "elemental","naga","undead","all")
    for t in legacy:
        if s == f"friendly_{t}": return ("friendly", t)
        if s == f"enemy_{t}":    return ("enemy", t)
        if s == f"any_{t}":      return ("any", t)

    if s.endswith("_minion"):
        if s.startswith("friendly_"): return ("friendly", None)
        if s.startswith("enemy_"):    return ("enemy", None)
        if s.startswith("any_"):      return ("any", None)

    # Pattern *_tribe:<name>
    if "_tribe:" in s:
        side, tribe = s.split("_tribe:", 1)
        side = side.replace("target_", "")
        if side not in ("friendly","enemy","any"): side = "any"
        return (side, tribe.strip().lower() or None)

    # Fallback: no tribe/any side
    return ("any", None)

def _minion_owner_matches(source_pid: int, target_pid: int, scope: str) -> bool:
    if scope == "friendly": return target_pid == source_pid
    if scope == "enemy":    return target_pid != source_pid
    return True  # "any"

# ---- Effect factories ----

def _fx_replace_hero(params):
    """
    Replace the source owner's hero. Also sets BOTH current and maximum hero health.
    Removes the summoning minion if this effect was run from a battlecry.
    JSON params:
      {
        "hero_id": "WARLOCK_JARAXXUS",
        "hero_name": "Lord Jaraxxus",
        "set_health_to": 15,
        "power": { ... }
      }
    """
    hero_id   = str(params.get("hero_id", "HERO")).upper()
    hero_name = params.get("hero_name", "New Hero")
    set_to    = int(params.get("set_health_to", 30))
    pwr_spec  = params.get("power", {}) or {}

    def _mk_power(spec):
        return HeroPower(
            name=spec.get("name", "Hero Power"),
            text=spec.get("text", ""),
            cost=int(spec.get("cost", 2)),
            targeting=str(spec.get("targeting", "none")).lower(),
            effects_spec=list(spec.get("effects", [])),
            counts_as_spell=bool(spec.get("counts_as_spell", False)),
        )

    def run(g, source_obj, target):
        pid = getattr(source_obj, "owner", g.active_player)
        p   = g.players[pid]

        # 1) Replace hero + set max & current health (armor unchanged)
        new_power = _mk_power(pwr_spec)
        p.hero = Hero(id=hero_id, name=hero_name, power=new_power)

        before_h  = p.health
        before_mh = p.max_health
        p.max_health = max(1, set_to)
        p.health     = max(0, min(p.max_health, set_to))

        ev = [
            Event("HeroReplaced", {"player": pid, "hero": hero_id, "name": hero_name}),
            Event("PlayerMaxHealthSet", {"player": pid, "from": before_mh, "to": p.max_health}),
            Event("HeroHealthSet", {"player": pid, "from": before_h, "to": p.health})
        ]

        # 2) If this came from a battlecry, remove the summoning minion
        mid = getattr(g, "current_battlecry_minion_id", None)
        if mid is not None:
            loc = g.find_minion(mid)
            if loc:
                _, _, mm = loc
                mm.deathrattle = None
                ev += g.destroy_minion(mm, reason="HeroReplaced")

        return ev

    return run

def _fx_shadowflame(params):
    """
    Destroy a *friendly* tagged minion, then deal damage equal to its current Attack
    to all enemy minions. (No Spell Damage scaling.)
    """
    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)
        name  = getattr(source_obj, "name", "Shadowflame")

        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []
        if obj.owner != owner:  # must be friendly
            return []

        amount = max(0, obj.attack)  # capture *before* destroy
        ev: list[Event] = []

        # Destroy the chosen minion (deathrattle should trigger as normal)
        ev += g.destroy_minion(obj, reason="Shadowflame")

        # Deal its attack to all enemy minions (no spell dmg bonus)
        opp = g.other(owner)
        for m in list(g.players[opp].board):
            if m.is_alive():
                ev += g.deal_damage_to_minion(m, amount, source=name)

        g.history += ev
        return ev
    return run

def _fx_counterspell(params):
    """
    Counter the just-cast enemy spell by setting a flag on the Game.
    The spell is considered cast (so friendly 'cast a spell' triggers already fired),
    but its effects will not resolve.
    """
    def run(g, source_obj, context):
        g._spell_countered = True
        return []
    return run

def _fx_mirror_played_minion(params):
    """
    Summon a copy of the just-played enemy minion for the source owner.
    Expects context {"minion": <id>} from _trigger_secrets(..., context=...).
    """
    def run(g, source_obj, context):
        mid = (context or {}).get("minion")
        if not mid:
            return []
        loc = g.find_minion(mid)
        if not loc:
            return []
        _, _, enemy_minion = loc

        # Build a spec from the original card (so it's a proper summon, no Battlecry)
        cid = getattr(enemy_minion, "card_id", "")
        raw_map = g.cards_db.get("_RAW", {})
        raw = dict(raw_map.get(cid, {}))
        if not raw or raw.get("type") != "MINION":
            return []

        spec = {
            "id": raw.get("id", cid),
            "name": raw.get("name", enemy_minion.name),
            "type": "MINION",
            "cost": raw.get("cost", enemy_minion.cost),
            "attack": raw.get("attack", enemy_minion.base_attack or enemy_minion.attack),
            "health": raw.get("health", enemy_minion.base_health or enemy_minion.health),
            "rarity": raw.get("rarity", "Common"),
            "keywords": list(raw.get("keywords", [])),
            "minion_type": raw.get("minion_type", enemy_minion.base_minion_type or "None"),
            "text": raw.get("text", ""),
            "spell_damage": raw.get("spell_damage", 0),
            "enrage": raw.get("enrage"),
            "aura": raw.get("aura"),
            "auras": list(raw.get("auras", [])),
            "cost_aura": raw.get("cost_aura"),
            "triggers_map": {},  # tokens summoned shouldn't inherit runtime trigger callables
        }
        # Summon the copy for the secret owner (source_obj.owner)
        return g._summon_from_card_spec(getattr(source_obj, "owner", g.active_player), spec, 1)
    return run

def _fx_freeze(params):
    """
    Supports:
      - Tagged target (minion or player): target={"minion": id} | {"player": pid}
      - AOE minion scopes via params["target"]:
          "enemy_minions", "friendly_minions", "all_minions"
      - Character scopes via params["target"] (NEW):
          "enemy_character", "friendly_character", "any_character",
          "enemy_face"/"enemy_hero", "friendly_face"/"friendly_hero"
    Notes:
      - Freezing a hero ignores Armor completely (Armor only affects damage).
    """
    scope = str(params.get("target", "") or "").lower()

    def _freeze_minion(m: Minion, ev: list[Event]):
        if m.is_alive() and not m.frozen:
            m.frozen = True
            ev.append(Event("Frozen", {
                "target_type": "minion",
                "minion": m.id,
                "owner": m.owner
            }))

    def _freeze_hero(g: 'Game', pid: int, ev: list[Event]):
        p = g.players[pid]
        if not p.hero_frozen:
            p.hero_frozen = True
            ev.append(Event("Frozen", {"target_type": "player", "player": pid}))

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)
        ev: List[Event] = []

        # ----- 1) AOE minion scopes -----
        if scope in ("enemy_minions", "friendly_minions", "all_minions"):
            sides = (
                [g.other(owner)] if scope == "enemy_minions"
                else [owner] if scope == "friendly_minions"
                else [owner, g.other(owner)]
            )
            for pid in sides:
                for m in list(g.players[pid].board):
                    _freeze_minion(m, ev)
            return ev

        # ----- 2) Character scopes (NEW) -----
        if scope in ("enemy_character", "enemy_face", "enemy_hero"):
            _freeze_hero(g, g.other(owner), ev); return ev
        if scope in ("friendly_character", "friendly_face", "friendly_hero"):
            _freeze_hero(g, owner, ev); return ev
        if scope in ("any_character", "character", "any_face", "any_hero"):
            # Default to enemy hero if not tagged
            _freeze_hero(g, g.other(owner), ev); return ev

        # ----- 3) Tagged targets (backward compatible) -----
        kind, obj = _resolve_tagged_target(g, target)
        if kind == "minion" and obj is not None:
            _freeze_minion(obj, ev)
            return ev
        if kind == "player":
            _freeze_hero(g, obj, ev)
            return ev

        # No valid target → safe no-op.
        return ev

    return run

def _fx_weapon_durability_delta(params):
    delta = int(params.get("amount", 0))
    def run(g, source_obj, target):
        pid = getattr(source_obj, "owner", g.active_player)
        p = g.players[pid]
        if not p.weapon or delta == 0:
            return []
        if delta < 0:
            # Use existing path so 0 auto-breaks & logs consistently
            return g.lose_weapon_durability(pid, -delta, source="WeaponTrigger")
        before = p.weapon.durability
        p.weapon.durability = before + delta
        ev = [Event("WeaponDurabilityChanged", {
            "player": pid, "name": p.weapon.name, "from": before, "to": p.weapon.durability, "source": "WeaponTrigger"
        })]
        g.history += ev
        return ev
    return run

def _fx_if_control_tribe(params, json_db_tokens):
    """
    If the source owner controls at least one friendly minion of 'tribe',
    run 'then' effects; otherwise run optional 'else' effects.
    """
    tribe = str(params.get("tribe", "")).lower().strip()
    then_spec = params.get("then", []) or []
    else_spec = params.get("else", []) or []
    then_fn = _compile_effects(then_spec, json_db_tokens)
    else_fn = _compile_effects(else_spec, json_db_tokens)

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)
        has = any(
            m.is_alive() and _has_tribe(m, tribe)
            for m in g.players[owner].board
        ) if tribe else False
        return then_fn(g, source_obj, target) if has else else_fn(g, source_obj, target)
    return run

def _fx_if_summoned_tribe(params, json_db_tokens):
    """Run nested 'then' effects only if the current target minion is of the given tribe."""
    tribe = str(params.get("tribe", "")).lower().strip()
    then_spec = params.get("then", []) or []
    then_fn = _compile_effects(then_spec, json_db_tokens)

    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)  # expect ("minion", Minion)
        if kind != "minion" or not obj:
            return []
        if not tribe or _has_tribe(obj, tribe):
            return then_fn(g, source_obj, target)
        return []
    return run

def _fx_summon_from_pool(params, json_db_tokens):
    """
    params:
      pool: [token_id, token_id, ...]   # choose 1 at random (or 'count' times with replacement)
      count: int (default 1)
      owner: same semantics as _fx_summon (player/enemy/both/active/inactive/0/1)
    """
    pool = list(params.get("pool", []))
    count = int(params.get("count", 1))
    owner_param = params.get("owner", "player")

    def run(g, source_obj, target):
        if not pool:
            return []
        source_owner = getattr(source_obj, "owner", g.active_player)
        owners = _resolve_owner_list(owner_param, g, source_owner)  # NEW
        evs = []
        for ow in owners:
            for _ in range(count):
                token_id = g.rng.choice(pool)
                raw = json_db_tokens[token_id]
                spec = dict(raw); spec.setdefault("id", token_id)
                evs += g._summon_from_card_spec(ow, spec, 1)
        return evs

    return run

def _fx_equip_weapon(params, json_db_tokens):
    token_id = params.get("card_id")
    inline_a = params.get("attack")
    inline_d = params.get("durability")
    inline_name = params.get("name", "Weapon")

    def run(g, source_obj, target):
        pid = getattr(source_obj, "owner", g.active_player)
        card_id = ""
        trig_map = {}
        if token_id:
            spec = dict(json_db_tokens.get(token_id, {}))
            if not spec and token_id in g.cards_db:
                c = g.cards_db[token_id]
                spec = {
                    "id": c.id, "name": c.name, "type": getattr(c, "type", "WEAPON"),
                    "attack": getattr(c, "attack", 0), "durability": getattr(c, "health", inline_d or 0),
                }
                trig_map = dict(getattr(c, "triggers_map", {}))  # NEW
            name = spec.get("name", inline_name)
            atk  = int(spec.get("attack", inline_a or 0))
            dur  = int(spec.get("durability", inline_d or 0))
            card_id = spec.get("id", "")
        else:
            name, atk, dur = inline_name, int(inline_a or 0), int(inline_d or 0)

        return g.equip_weapon(pid, name, atk, dur, card_id=card_id, triggers_map=trig_map)  # NEW
    return run

def _fx_destroy_weapon(params):
    """
    Destroy a weapon. Owner resolution:
      - "enemy" (default), "opponent"
      - "friendly", "ally", "self", "player"
      - "active", "inactive"
      - or an absolute pid: 0 / 1
    """
    owner_param = params.get("owner", "enemy")

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)
        victim = _resolve_owner_single(owner_param, g, owner, default_to_enemy=True)  # NEW
        return g.destroy_weapon(victim, reason="Effect")
    return run

def _fx_gain_armor(params):
    amt = int(params.get("amount", 0))
    t_spec = params.get("target")  # optional: "self"/"friendly_face"/"enemy_face"

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)

        # Resolve player to receive armor
        if isinstance(target, int):
            pid = target
        else:
            pid = owner
            if t_spec:
                s = str(t_spec).lower()
                if s in ("self", "self_face", "friendly", "friendly_face", "ally_face"):
                    pid = owner
                elif s in ("enemy", "enemy_face", "opponent", "opponent_face"):
                    pid = g.other(owner)

        p = g.players[pid]
        p.armor += amt
        return [Event("ArmorGained", {"player": pid, "amount": amt})]
    return run

def _fx_add_keyword(params):
    raw = str(params["keyword"]).strip().lower()

    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []

        m = obj
        # normalize pretty label for the log
        if raw in ("taunt",):
            m.taunt = True
            pretty = "Taunt"
        elif raw in ("charge",):
            m.charge = True
            pretty = "Charge"
        elif raw in ("rush",):
            m.rush = True
            pretty = "Rush"
        elif raw in ("divine_shield", "divineshield", "divine shield"):
            m.divine_shield = True
            pretty = "Divine Shield"
        else:
            return []

        return [Event("BuffKeyword", {"minion": m.id, "keyword": pretty})]
    return run

def _fx_deal_damage(params):
    n = int(params["amount"])
    t_spec = params.get("target")

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)
        dmg   = _with_spell_bonus(n, g, owner, source_obj)  # NEW

        ev = []

        # 1) Tagged target wins
        kind, obj = _resolve_tagged_target(g, target)
        if kind == "minion" and obj is not None:
            ev.append(Event("SpellHit", {"source": name, "target_type": "minion", "minion": obj.id, "player": obj.owner}))
            ev += g.deal_damage_to_minion(obj, dmg, source=name)
            g.history += ev
            return ev
        if kind == "player":
            pid = obj
            ev.append(Event("SpellHit", {"source": name, "target_type": "player", "player": pid}))
            ev += g.deal_damage_to_player(pid, dmg, source=name)
            g.history += ev
            return ev

        # 2) Param-based hero targets
        if t_spec:
            s = str(t_spec).lower()
            if s in ("enemy_face","opponent_face","enemy_hero","opponent_hero"):
                pid = g.other(owner)
                ev.append(Event("SpellHit", {"source": name, "target_type": "player", "player": pid}))
                ev += g.deal_damage_to_player(pid, dmg, source=name); g.history += ev; return ev
            if s in ("friendly_face","ally_face","self_face","friendly_hero","self_hero"):
                pid = owner
                ev.append(Event("SpellHit", {"source": name, "target_type": "player", "player": pid}))
                ev += g.deal_damage_to_player(pid, dmg, source=name); g.history += ev; return ev

        # 3) Fallback: enemy face
        pid = g.other(owner)
        ev.append(Event("SpellHit", {"source": name, "target_type": "player", "player": pid}))
        ev += g.deal_damage_to_player(pid, dmg, source=name)
        g.history += ev
        return ev
    return run

def _fx_deal_damage_equal_armor(params):
    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)

        dmg = max(0, g.players[owner].armor)  # no Spell Damage bonus

        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []

        ev = []
        ev.append(Event("SpellHit", {
            "source": name, "target_type": "minion",
            "minion": obj.id, "player": obj.owner
        }))
        ev += g.deal_damage_to_minion(obj, dmg, source=name)
        g.history += ev
        return ev
    return run

def _fx_heal(params):
    n = int(params["amount"])
    t_spec = params.get("target")  # optional: "friendly_face" / "enemy_face"
    def run(g, source_obj, target):
        name = getattr(source_obj, "name", "Effect")
        # 1) If a tagged target was provided (minion or player), use it.
        kind, obj = _resolve_tagged_target(g, target)
        if kind == "minion":
            ev = []
            before = obj.health
            obj.health = min(obj.max_health, obj.health + n)
            healed = obj.health - before
            if healed > 0:
                ev.append(Event("MinionHealed", {
                    "minion": obj.id,
                    "amount": healed,
                    "source": name
                }))
                ev += g._fire_minion_healed(obj.owner, obj.id, healed, name)

            ev += g._update_enrage(obj)
            return ev
        if kind == "player":
            p = g.players[obj]
            before = p.health
            p.health = min(p.max_health, p.health + n)
            return [Event("PlayerHealed", {"player": obj, "amount": p.health - before, "source": name})]

        # 2) Param-based hero targets (useful for triggers like Truesilver)
        if t_spec:
            owner = getattr(source_obj, "owner", g.active_player)
            if str(t_spec).lower() in ("friendly_face", "ally_face", "self_face"):
                pid = owner
            elif str(t_spec).lower() in ("enemy_face", "opponent_face"):
                pid = g.other(owner)
            else:
                return []
            p = g.players[pid]
            before = p.health
            p.health = min(p.max_health, p.health + n)
            return [Event("PlayerHealed", {"player": pid, "amount": p.health - before, "source": name})]

        return []
    return run

def _fx_adjacent_buff(params):
    a = int(params.get("attack", 0))
    h = int(params.get("health", 0))
    give_taunt = bool(params.get("taunt", False))

    def run(g, source_obj, target):
        # Use the context set by play_card()/resolve_pending_battlecry
        mid = getattr(g, "current_battlecry_minion_id", None)
        owner = getattr(g, "current_battlecry_owner", getattr(source_obj, "owner", g.active_player))
        if mid is None:
            return []  # safety
        return _apply_adjacent_buff(g, owner, mid, attack=a, health=h, taunt=give_taunt)
    return run

def _fx_discover_equal_remaining_mana(params):
    """
    Discover (auto-pick for now) a card whose cost equals the player's
    remaining mana crystals. Adds the chosen card to hand (or burns if full).

    JSON usage (e.g. in battlecry):
      { "effect": "discover_equal_remaining_mana" }
    """
    def run(g, source_obj, target):
        pid = g.active_player
        p = g.players[pid]
        remaining = max(0, p.mana)

        # pool: real collectible cards with exactly that cost
        def is_real_card(cid, cobj):
            if cid.startswith("_"):
                return False
            t = getattr(cobj, "type", None)
            return t in ("MINION", "SPELL")  # include other types if you have them

        pool = [cid for cid, c in g.cards_db.items()
                if isinstance(c, Card) and is_real_card(cid, c) and c.cost == remaining]

        if not pool:
            return []  # nothing to discover

        # up to 3 options, then auto-pick 1 (deterministic via g.rng)
        options = g.rng.sample(pool, min(3, len(pool)))
        choice = g.rng.choice(options)

        ev = []
        if len(p.hand) < 10:
            p.hand.append(choice)
            ev.append(Event("CardDiscovered", {
                "player": pid, "card": choice, "options": options, "source": "Discover"
            }))
        else:
            p.graveyard.append(choice)
            ev.append(Event("CardBurned", {"player": pid, "card": choice}))

        return ev
    return run

def _fx_draw(params):
    count = int(params.get("count", 1))
    who   = params.get("owner")  # optional: "source_owner", "target_owner", "opponent", "active", "inactive", 0/1

    def run(g, source_obj, target):
        # try to infer a pid from the tagged target (if any)
        def _pid_from_target():
            kind, obj = _resolve_tagged_target(g, target)
            if kind == "player" and obj in (0, 1):
                return obj
            if kind == "minion" and obj is not None:
                return obj.owner
            return None

        src_owner = getattr(source_obj, "owner", g.active_player)
        pid = None

        # resolve 'who' without introducing any new utility funcs beyond this file
        if isinstance(who, int) and who in (0, 1):
            pid = who
        elif isinstance(who, str):
            s = who.lower()
            if s in ("source_owner", "self", "controller", "player", "friendly"):
                pid = src_owner
            elif s in ("target_owner", "target", "target_controller"):
                pid = _pid_from_target()
            elif s in ("opponent", "enemy"):
                pid = g.other(src_owner)
            elif s in ("active", "active_player", "current"):
                pid = g.active_player
            elif s in ("inactive", "other_active"):
                pid = g.other(g.active_player)

        # default: if we have a tagged target use its owner, else the source's owner
        if pid is None:
            pid = _pid_from_target() or src_owner

        return g.players[pid].draw(g, count)

    return run

def _fx_gain_temp_mana(params):
    amt = int(params.get("amount", 1))
    def run(g, source_obj, target):
        p = g.players[g.active_player]
        p.mana = min(p.mana + amt, p.max_mana + amt)
        return [Event("GainMana", {"player": g.active_player, "temp": amt, "mana_after": p.mana})]
    return run

def _fx_random_pings(params):
    base_count = int(params["count"])

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)

        # NEW: Spell Damage increases the *number* of pings, not the damage per ping
        extra = g.get_spell_damage(owner) if _is_spell_source(source_obj) else 0
        total = max(0, base_count + extra)
        per_hit = 1  # each missile still deals 1

        opp = g.other(owner)
        ev = []
        for _ in range(total):
            pool = [("player", opp)] + [
                ("minion", m.id) for m in g.players[opp].board if m.is_alive()
            ]
            tgt_kind, tgt_val = g.rng.choice(pool)
            if tgt_kind == "player":
                ev.append(Event("SpellHit", {"source": name, "target_type": "player", "player": opp}))
                ev += g.deal_damage_to_player(opp, per_hit, source=name)
            else:
                loc = g.find_minion(tgt_val)
                if loc:
                    _, _, mm = loc
                    ev.append(Event("SpellHit", {"source": name, "target_type": "minion", "minion": mm.id, "player": mm.owner}))
                    ev += g.deal_damage_to_minion(mm, per_hit, source=name)
        g.history += ev
        return ev
    return run


# ---------- Random target helpers ----------

def _build_random_target_pool(g:'Game', owner:int, scope:str, *, only_injured:bool=False):
    """
    Returns a list of ("player", pid) and ("minion", mid) pairs according to scope.
    Supported scopes (case-insensitive):
      - "enemy_characters"  (default for damage)
      - "friendly_characters"
      - "all_characters"
      - "enemy_minions"
      - "friendly_minions"
      - "all_minions"
      - "enemy_face" / "friendly_face"
    When only_injured=True, players/minions that are at full health are excluded.
    """
    s = (scope or "").lower().strip()
    opp = g.other(owner)

    def _maybe_add_player(pid, out):
        if only_injured:
            p = g.players[pid]
            if p.health >= p.max_health:
                return
        out.append(("player", pid))

    def _maybe_add_minions(pid, out):
        for m in list(g.players[pid].board):
            if not m.is_alive():
                continue
            if only_injured and m.health >= m.max_health:
                continue
            out.append(("minion", m.id))

    pool = []

    if s in ("", "enemy_characters", "enemy_character"):
        _maybe_add_player(opp, pool)
        _maybe_add_minions(opp, pool)
        return pool

    if s in ("friendly_characters","friendly_character"):
        _maybe_add_player(owner, pool)
        _maybe_add_minions(owner, pool)
        return pool

    if s in ("all_characters","both_characters","all"):
        _maybe_add_player(owner, pool)
        _maybe_add_player(opp, pool)
        _maybe_add_minions(owner, pool)
        _maybe_add_minions(opp, pool)
        return pool

    if s in ("enemy_minions","enemies","enemy"):
        _maybe_add_minions(opp, pool); return pool
    if s in ("friendly_minions","friendlies","friendly"):
        _maybe_add_minions(owner, pool); return pool
    if s in ("all_minions","both_minions"):
        _maybe_add_minions(owner, pool); _maybe_add_minions(opp, pool); return pool

    if s in ("enemy_face","enemy_hero","opponent_face"):
        _maybe_add_player(opp, pool); return pool
    if s in ("friendly_face","friendly_hero","self_face"):
        _maybe_add_player(owner, pool); return pool

    # Fallback to enemy characters
    _maybe_add_player(opp, pool)
    _maybe_add_minions(opp, pool)
    return pool

def _fx_random_enemy_damage(params):
    """
    Deal N damage to a single random target chosen from a scope.
    JSON:
      { "effect":"random_enemy_damage", "amount":3, "target":"enemy_characters" }
    target (optional): see _build_random_target_pool docs. Default: "enemy_characters".
    Spell Damage applies to the damage amount (not the selection).
    """
    n = int(params.get("amount", 1))
    scope = str(params.get("target", "enemy_characters"))

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)
        dmg   = _with_spell_bonus(n, g, owner, source_obj)

        pool = _build_random_target_pool(g, owner, scope, only_injured=False)
        if not pool:
            return []

        kind, val = g.rng.choice(pool)
        ev: List[Event] = []
        if kind == "player":
            pid = val
            ev.append(Event("SpellHit", {"source": name, "target_type": "player", "player": pid}))
            ev += g.deal_damage_to_player(pid, dmg, source=name)
        else:
            loc = g.find_minion(val)
            if loc:
                _, _, mm = loc
                ev.append(Event("SpellHit", {"source": name, "target_type": "minion", "minion": mm.id, "player": mm.owner}))
                ev += g.deal_damage_to_minion(mm, dmg, source=name)
        g.history += ev
        return ev
    return run

def _fx_random_heal(params):
    """
    Restore N Health to a single random *injured* target from a scope.
    JSON:
      { "effect":"random_heal", "amount":2, "target":"friendly_characters" }
    target: same values as damage variant. Default: "friendly_characters".
    Notes:
      - Only selects injured characters/minions (otherwise does nothing).
      - Fires MinionHealed/PlayerHealed events. If your engine has
        g._fire_minion_healed(owner, minion_id, amount, source) it will be called.
    """
    n = int(params.get("amount", 1))
    scope = str(params.get("target", "friendly_characters"))

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)

        pool = _build_random_target_pool(g, owner, scope, only_injured=True)
        if not pool:
            return []

        kind, val = g.rng.choice(pool)
        ev: List[Event] = []

        if kind == "player":
            pid = val
            p = g.players[pid]
            before = p.health
            p.health = min(p.max_health, p.health + n)
            healed = p.health - before
            if healed > 0:
                ev.append(Event("PlayerHealed", {"player": pid, "amount": healed, "source": name}))
            return ev

        # minion
        loc = g.find_minion(val)
        if not loc:
            return []
        _, _, m = loc
        before = m.health
        m.health = min(m.max_health, m.health + n)
        healed = m.health - before
        if healed > 0:
            ev.append(Event("MinionHealed", {"minion": m.id, "amount": healed, "source": name}))
            # If you added the global broadcaster, notify it (safe if missing)
            if hasattr(g, "_fire_minion_healed"):
                ev += g._fire_minion_healed(m.owner, m.id, healed, name)
            ev += g._update_enrage(m)
        return ev
    return run


def _fx_random_add_stat(params):
    """
    Give +attack/+health to ONE random minion from a scope.
    JSON:
      {
        "effect": "random_add_stat",
        "attack": 0,
        "health": 3,
        "target": "friendly_minions",   # "enemy_minions" | "all_minions"
        "exclude_self": false           # if true, won't select the source minion
      }
    Notes:
      - Health buff increases both max_health and current health (like typical +Health buffs).
      - Minion-only (characters/heroes are ignored even if passed via target).
    """
    a = int(params.get("attack", 0))
    h = int(params.get("health", 0))
    scope = str(params.get("target", "friendly_minions"))
    exclude_self = bool(params.get("exclude_self", False))

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)
        self_id = getattr(source_obj, "id", None)

        # Build pool and keep only live minions
        pairs = _build_random_target_pool(g, owner, scope, only_injured=False)
        mids = []
        for kind, val in pairs:
            if kind != "minion":
                continue
            loc = g.find_minion(val)
            if not loc:
                continue
            _, _, mm = loc
            if not mm.is_alive():
                continue
            if exclude_self and self_id is not None and mm.id == self_id:
                continue
            mids.append(mm)

        if not mids or (a == 0 and h == 0):
            return []

        m = g.rng.choice(mids)
        before_a = m.attack
        before_h = m.health
        # Apply stat buffs (permanent)
        if a:
            m.attack = max(0, m.attack + a)
        if h:
            m.max_health = max(1, m.max_health + h)
            m.health = m.health + h  # lift current by same delta

        ev = [Event("Buff", {
            "minion": m.id,
            "attack_delta": m.attack - before_a,
            "health_delta": m.health - before_h
        })]
        ev += g._update_enrage(m)
        return ev

    return run


def _fx_aoe_damage(params):
    """
    Deal N damage to:
      - default: enemy hero + enemy minions (backward compatible)
      - target: "enemy" | "friendly" | "all" (aka both, all_characters)
    """
    n = int(params["amount"])
    scope = str(params.get("target", "enemy")).lower()

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)
        dmg   = _with_spell_bonus(n, g, owner, source_obj)

        # which sides to hit?
        if scope in ("all", "both", "all_characters"):
            sides = [owner, g.other(owner)]
        elif scope in ("friendly", "ally", "self"):
            sides = [owner]
        else:  # "enemy" | "opponent" (default)
            sides = [g.other(owner)]

        ev = []
        for pid in sides:
            # hit hero
            ev.append(Event("SpellHit", {"source": name, "target_type": "player", "player": pid, "aoe": True}))
            ev += g.deal_damage_to_player(pid, dmg, source=name)

            # snapshot the board so deaths during iteration don't skip or double-hit
            for m in list(g.players[pid].board):
                if not m.is_alive():
                    continue
                ev.append(Event("SpellHit", {"source": name, "target_type": "minion",
                                             "minion": m.id, "name": m.name, "aoe": True}))
                ev += g.deal_damage_to_minion(m, dmg, source=name)
        return ev
    return run

def _fx_aoe_damage_minions(params):
    n = int(params["amount"])
    scope = str(params.get("target", "enemy")).lower()

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)
        dmg   = _with_spell_bonus(n, g, owner, source_obj)

        if scope in ("all", "both", "all_minions"):
            sides = [owner, g.other(owner)]
        elif scope in ("friendly", "ally", "self", "friendly_minions"):
            sides = [owner]
        else:  # "enemy", "enemies", "opponent", "enemy_minions"
            sides = [g.other(owner)]

        ev = []
        for pid in sides:
            for m in list(g.players[pid].board):
                if m.is_alive():
                    ev += g.deal_damage_to_minion(m, dmg, source=name)
        return ev
    return run

def _fx_aoe_heal(params):
    """
    Restore N Health to:
      - default: friendly hero + friendly minions (matches typical heal AOE default)
      - target: "friendly" | "enemy" | "all" (aka both, all_characters)
    Produces PlayerHealed/MinionHealed events (with amount actually healed), and
    updates Enrage on affected minions.
    """
    n = int(params["amount"])
    scope = str(params.get("target", "friendly")).lower()

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)

        if scope in ("all", "both", "all_characters"):
            sides = [owner, g.other(owner)]
        elif scope in ("friendly", "ally", "self", "friendly_characters"):
            sides = [owner]
        else:  # "enemy", "opponent"
            sides = [g.other(owner)]

        ev: list[Event] = []
        for pid in sides:
            # --- heal hero
            p = g.players[pid]
            if n > 0 and p.health < p.max_health:
                before = p.health
                p.health = min(p.max_health, p.health + n)
                healed = p.health - before
                if healed > 0:
                    ev.append(Event("PlayerHealed", {
                        "player": pid, "amount": healed, "source": name, "aoe": True
                    }))

            # --- heal minions (snapshot board)
            for m in list(g.players[pid].board):
                if not m.is_alive():
                    continue
                if n > 0 and m.health < m.max_health:
                    before = m.health
                    m.health = min(m.max_health, m.health + n)
                    healed = m.health - before
                    if healed > 0:
                        ev.append(Event("MinionHealed", {
                            "minion": m.id, "amount": healed, "source": name, "aoe": True
                        }))
                        ev += g._fire_minion_healed(m.owner, m.id, healed, name)
                        ev += g._update_enrage(m)
        return ev

    return run

def _fx_aoe_heal_minions(params):
    """
    Restore N Health to minions only.
      - default scope: friendly minions
      - target: "friendly_minions" | "enemy_minions" | "all_minions"
                Also accepts "friendly"/"enemy"/"all" for convenience.
    """
    n = int(params["amount"])
    scope = str(params.get("target", "friendly_minions")).lower()

    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Effect")
        owner = getattr(source_obj, "owner", g.active_player)

        if scope in ("all", "both", "all_minions"):
            sides = [owner, g.other(owner)]
        elif scope in ("friendly", "ally", "self", "friendly_minions"):
            sides = [owner]
        else:  # "enemy", "enemies", "opponent", "enemy_minions"
            sides = [g.other(owner)]

        ev: list[Event] = []
        for pid in sides:
            for m in list(g.players[pid].board):
                if not m.is_alive():
                    continue
                if n > 0 and m.health < m.max_health:
                    before = m.health
                    m.health = min(m.max_health, m.health + n)
                    healed = m.health - before
                    if healed > 0:
                        ev.append(Event("MinionHealed", {
                            "minion": m.id, "amount": healed, "source": name, "aoe": True
                        }))
                        ev += g._fire_minion_healed(m.owner, m.id, healed, name)
                        ev += g._update_enrage(m)
        return ev

    return run

def _fx_add_attack(params):
    n = int(params["amount"])
    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion":
            return []
        obj.attack += n
        return [Event("Buff", {"minion": obj.id, "attack_delta": n})]
    return run

def _fx_multiply_attack(params):
    """
    Multiply a minion's current Attack by a factor.
    JSON:
      { "effect": "multiply_attack", "factor": 2 }
    """
    factor = float(params.get("factor", 2))

    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []
        before = obj.attack
        # multiply and clamp to >= 0, keep as int
        new_val = max(0, int(round(before * factor)))
        obj.attack = new_val
        return [Event("Buff", {
            "minion": obj.id,
            "attack_delta": new_val - before,
            "health_delta": 0
        })]
    return run

def _fx_multiply_health(params):
    """
    Multiply a minion's Health pool.
    - Multiplies max_health by 'factor' (rounded to int, min 1).
    - Increases current health by the same delta to keep damage amount constant.
    JSON:
      { "effect": "multiply_health", "factor": 2 }
    """
    factor = float(params.get("factor", 2))

    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []

        before_max = obj.max_health
        before_hp  = obj.health

        # compute new max; clamp to at least 1; keep integers
        new_max = max(1, int(round(before_max * factor)))
        delta_max = new_max - before_max

        if delta_max == 0:
            return []

        obj.max_health = new_max
        # increase current health by the same delta, clamped to new max
        before = obj.health
        obj.health = max(0, min(new_max, obj.health + delta_max))

        ev = [Event("Buff", {
            "minion": obj.id,
            "attack_delta": 0,
            "health_delta": obj.health - before
        })]
        ev += g._update_enrage(obj)
        return ev

    return run


def _fx_add_stats(params):
    a = int(params.get("attack", 0))
    h = int(params.get("health", 0))
    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion":
            return []
        m = obj
        m.attack += a
        m.max_health += h
        m.health += h
        return [Event("Buff", {"minion": m.id, "attack_delta": a, "health_delta": h})]
    return run

def _fx_silence(params):
    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion":
            return []
        m = obj
        m.silenced = True
        ev = []
        ev += g._disable_aura(m)     # remove active aura first
        ev += g._update_enrage(m)
        m.taunt = m.charge = m.rush = m.divine_shield = False
        m.temp_stats.clear()
        m.triggers_map.clear()
        m.deathrattle = None
        m.cant_attack = False
        m.health = m.health if m.health <= m.base_health else m.base_health
        m.attack = m.base_attack
        m.max_health = m.base_health
        
        
        ev.append(Event("Silenced", {"minion": m.id}))
        
        return ev
    return run

def _fx_summon(params, json_db_tokens):
    """
    params:
      card_id: str (token id)
      count: int (default 1)
      owner: "player" | "enemy" | "both" | 0 | 1 | "active" | "inactive" (optional)
             - "player"   => the caster's side
             - "enemy"    => the opponent of the caster
             - "both"     => summon for both sides (mirror)
             - 0 or 1     => absolute player index
             - "active"   => g.active_player
             - "inactive" => the other of g.active_player
    """
    token_id = params["card_id"]
    count = int(params.get("count", 1))
    owner_param = params.get("owner", "player")  # default friendly to the caster

    def run(g, source_obj, target):
        source_owner = getattr(source_obj, "owner", g.active_player)
        owners = _resolve_owner_list(owner_param, g, source_owner)  # NEW

        raw = json_db_tokens[token_id]
        spec = dict(raw)
        spec.setdefault("id", token_id)
        evs = []
        for ow in owners:
            evs += g._summon_from_card_spec(ow, spec, count)
        return evs

    return run

def _fx_temp_modify(params):
    # Any subset is fine
    a  = int(params.get("attack", 0))
    h  = int(params.get("health", 0))
    mh = int(params.get("max_health", 0))
    add_kw = [k for k in params.get("add_keywords", [])]
    rem_kw = [k for k in params.get("remove_keywords", [])]

    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []
        caster = getattr(source_obj, "owner", g.active_player)
        return g._apply_temp_to_minion(obj, caster_pid=caster,
                                       attack=a, health=h, max_health=mh,
                                       add_keywords=add_kw, remove_keywords=rem_kw)
    return run

def _fx_temp_cost(params):
    """
    JSON:
      { "effect":"temp_cost", "delta":-1, "floor":0, "scope":"friendly:spell|friendly:type:MINION|friendly:tribe:beast|spells" }
    """
    delta = int(params.get("delta", 0))
    floor = int(params.get("floor", 0))
    scope = str(params.get("scope", "spells")).lower()

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)
        g.players[owner].temp_cost_mods.append({
            "scope": scope, "delta": delta, "floor": floor,
            "expires_pid": owner, "expires_when": "end_of_turn"
        })
        return [Event("TempRuleAdded", {"player": owner, "kind": "cost", "delta": delta, "scope": scope})]
    return run

def _fx_transform(params, json_db_tokens):
    """
    Transform the tagged MINION into the given token_id *in place*:
      - keeps the same id, owner, and board position
      - does NOT trigger death or deathrattle
      - clears temporary buffs/debuffs, silence, and freeze (typical transform semantics)
      - resets stats/keywords to the token's base
      - re-enables any auras from the new form and refreshes adjacency
    JSON:
      { "effect": "transform", "card_id": "<TOKEN_ID>" }
    """
    token_id = params["card_id"]

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []

        loc = g.find_minion(obj.id)
        if not loc:
            return []
        pid, _, m = loc

        prev_m = copy.deepcopy(m)
        # Load token spec
        raw = dict(json_db_tokens.get(token_id, {}))
        if not raw:
            return []

        
        # Before morphing, disable any aura the current minion provides
        ev: list[Event] = []
        ev += g._remove_all_stat_auras(pid)
        #ev += g._disable_aura(m)

        # --- Reset runtime flags that transforms typically clear
        m.silenced = False
        m.frozen = False
        m.temp_stats.clear()
        m.temp_keywords.clear()
        m.deathrattle = None  # (tokens may add their own via triggers_map/auras later)

        # Preserve attack usage/exhaustion state for the turn (no extra attacks granted)
        # Keep: m.exhausted, m.has_attacked_this_turn, m.summoned_this_turn

        
        # --- Apply token identity & base stats/keywords
        m.name            = raw.get("name", "Token")
        m.card_id         = raw.get("id", token_id)

        base_atk          = int(raw.get("attack", 0))
        base_hp           = int(raw.get("health", 1))
        m.base_attack     = base_atk
        m.base_health     = base_hp
        m.attack          = max(0, base_atk)
        m.max_health      = max(1, base_hp)
        m.health          = m.max_health  # transforms reset damage

        m.cost            = int(raw.get("cost", 0))
        m.rarity          = str(raw.get("rarity", "Common"))
        m.base_text       = str(raw.get("text", ""))

        kws               = list(raw.get("keywords", []) or [])
        m.base_keywords   = list(kws)
        # Recompute keyword booleans from base
        m.taunt           = ("Taunt" in kws)
        m.charge          = ("Charge" in kws)
        m.rush            = ("Rush" in kws)
        m.divine_shield   = ("Divine Shield" in kws)
        m.cant_attack     = ("Can't Attack" in kws) or ("Cant Attack" in kws)

        # Types / spell damage / enrage / auras / triggers
        m.minion_type       = str(raw.get("minion_type", "None"))
        m.base_minion_type  = str(raw.get("minion_type", "None"))
        m.spell_damage      = int(raw.get("spell_damage", 0))

        m.enrage_spec       = raw.get("enrage")
        m.enrage_active     = False

        m.aura_spec         = raw.get("aura")
        m.auras             = list(raw.get("auras", []))
        m.cost_aura_spec    = raw.get("cost_aura")

        # Note: json token specs don't contain compiled callables; default to empty.
        # If you later want token deathrattles from your main cards.json, you could
        # attach them here via a helper similar to _POST_SUMMON_HOOK.
        m.triggers_map      = dict(raw.get("triggers_map", {}))

        # Re-enable any auras the *new* form provides, and refresh adjacency on this side
        #ev += g._enable_aura(m)
        #ev += g._refresh_stat_auras(pid)
        ev += g._apply_all_stat_auras(pid)
        # Keep Enrage accurate after stat reset
        ev += g._update_enrage(m)

        # Recompute attack readiness flag from current exhaustion/charge
        m.can_attack = m.charge or (not m.exhausted)

        # UX event: transformed (no death/summon emitted)
        ev.append(Event("MinionTransformed", {
            "player": owner,
            "old_name": prev_m.name,
            "new_name": m.name,
        }))

        g.history += ev
        return ev

    return run


def _fx_if_target_survived_then(params, json_db_tokens):
    """
    Run 'then' effects if the tagged target was a MINION and is still alive on the board
    after prior effects resolved.
    """
    then_spec = params.get("then", []) or []
    then_fn = _compile_effects(then_spec, json_db_tokens)

    def run(g, source_obj, target):
        # We expect the spell to have been cast with a tagged minion target:
        #   target == {"minion": <id>}
        if not isinstance(target, dict) or "minion" not in target:
            return []
        mid = target["minion"]

        # If it's still on board and alive => survived
        loc = g.find_minion(mid)
        if loc:
            _, _, m = loc
            if m.is_alive():
                return then_fn(g, source_obj, target)

        # If it’s gone from board, we consider it dead (or bounced); no draw.
        return []
    return run

def _fx_if_target_died_then(params, json_db_tokens):
    """
    After prior effects, if the originally-tagged minion target died (or left play),
    run 'then' effects.
    """
    then_spec = params.get("then", []) or []
    then_fn = _compile_effects(then_spec, json_db_tokens)

    def run(g, source_obj, target):
        # We expect the spell to have been cast with a tagged minion target:
        #   target == {"minion": <id>}
        mid = None
        if isinstance(target, dict) and "minion" in target:
            mid = target["minion"]
        elif isinstance(target, int):
            # legacy int-minion id targeting supported
            mid = target

        if mid is None:
            return []

        if _minion_dead_or_gone(g, mid):
            return then_fn(g, source_obj, target)
        return []
    return run

def _fx_discard_random(params):
    """
    Discard N random cards from the caster's hand.
    JSON:
      { "effect":"discard_random", "count": 2 }
    """
    count = int(params.get("count", 1))

    def run(g, source_obj, target):
        owner = getattr(source_obj, "owner", g.active_player)
        p = g.players[owner]
        n = min(count, len(p.hand))
        ev: List[Event] = []
        # choose n distinct random indices
        if n <= 0:
            return ev
        # pick indices, then remove by descending index so positions stay valid
        idxs = list(range(len(p.hand)))
        picks = g.rng.sample(idxs, n)
        picks.sort(reverse=True)
        for i in picks:
            cid = p.hand.pop(i)
            p.graveyard.append(cid)
            cname = cid
            if cid in g.cards_db:
                try:
                    cname = getattr(g.cards_db[cid], "name", cid)
                except Exception:
                    pass
            ev.append(Event("CardDiscarded", {
                "player": owner,
                "card": cid,        # keep id for consumers
                "name": cname       # add human-readable name
            }))
            
        return ev

    return run

def _fx_set_attack(params):
    n = int(params.get("amount", 1))
    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []
        m = obj
        before = m.attack
        m.attack = n
        return [Event("Buff", {"minion": m.id, "attack_delta": m.attack - before, "health_delta": 0})]
    return run

def _fx_set_health(params):
    """
    Set a minion's health to a fixed value and also set max_health to that value.
    JSON:
      { "effect": "set_health", "amount": 1, "target": "any_minion" }
    """
    n = int(params.get("amount", 1))

    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []
        before = obj.health
        # clamp to [0, max_health] and set max_health to match (behavior unchanged; doc updated)
        obj.health = n
        obj.max_health = n
        ev = []
        # Use a Buff event so your UI log shows a change (+/-)
        ev.append(Event("MinionSet", {
            "minion": obj.id,
            "attack_delta": 0,
            "health_delta": obj.health - before
        }))
        # If it somehow hits 0, kill it
        if obj.health <= 0:
            ev += g.destroy_minion(obj, reason="SetHealthZero")
        else:
            ev += g._update_enrage(obj)
        return ev
    return run

def _fx_if_summoned_has_keyword(params, json_db_tokens):
    """
    If the most recently summoned minion (from trigger context) has the given keyword
    in its *base* keywords (from the card), run 'then' effects.
    Used by Crowd Favorite to detect Battlecry minions.
    """
    want = str(params.get("keyword", "")).strip().lower()
    then_spec = params.get("then", []) or []
    then_fn = _compile_effects(then_spec, json_db_tokens)

    def run(g, source_obj, context):
        mid = (context or {}).get("minion")
        if not mid:
            return []
        loc = g.find_minion(mid)
        if not loc:
            return []  # died or bounced; nothing to do
        _, _, summoned = loc
        
        base_kws = [k.lower() for k in getattr(summoned, "base_keywords", [])]
        #print(context)
        if want and want in base_kws:
            return then_fn(g, source_obj, context)
        return []
    return run

def _fx_add_self_stats(params):
    a = int(params.get("attack", 0))
    h = int(params.get("health", 0))
    def run(g, source_obj, context):
        
        # We’ll find the source minion by id (see step 3)
        sid = getattr(source_obj, "id", None)
        if sid is None:
            return []
        loc = g.find_minion(sid)
        
        if not loc:
            return []
        _, _, me = loc
        me.attack += a
        me.max_health += h
        me.health += h
        ev = [Event("Buff", {"minion": me.id, "attack_delta": a, "health_delta": h})]
        ev += g._update_enrage(me)
        return ev
    return run

def _fx_execute(params):
    def run(g, source_obj, target):
        name  = getattr(source_obj, "name", "Execute")
        owner = getattr(source_obj, "owner", g.active_player)

        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []

        # Must be enemy and damaged (current HP < max HP)
        if obj.owner == owner or obj.health >= obj.max_health:
            # Soft-fail: do nothing (keeps play flow safe)
            return []

        ev = []
        ev.append(Event("SpellHit", {
            "source": name, "target_type": "minion",
            "minion": obj.id, "player": obj.owner
        }))
        ev += g.destroy_minion(obj, reason="Execute")
        g.history += ev
        return ev
    return run

def _fx_brawl(params):
    """
    Destroy all minions except one random survivor (both sides).
    - Uses destroy_minion so Divine Shield won’t save anything.
    - No targeting; works from on_cast.
    """
    def run(g, source_obj, target):
        # snapshot alive minions on both boards
        pool = [m for m in list(g.players[0].board) if m.is_alive()]
        pool += [m for m in list(g.players[1].board) if m.is_alive()]

        if len(pool) <= 1:
            return []  # nothing to do

        survivor = g.rng.choice(pool)
        ev = [Event("BrawlSurvivor", {
            "minion": survivor.id, "player": survivor.owner, "name": survivor.name
        })]

        # destroy everyone except the survivor
        for m in pool:
            if m is survivor or not m.is_alive():
                continue
            ev += g.destroy_minion(m, reason="Brawl")
        return ev
    return run

def _fx_add_card_to_hand(params):
    card_id = str(params.get("card_id", "")).strip()
    count   = int(params.get("count", 1))
    who     = params.get("owner", "friendly")  # defaults to source owner

    def run(g, source_obj, target):
        if not card_id or card_id not in g.cards_db:
            return []
        src_owner = getattr(source_obj, "owner", g.active_player)

        # resolve recipient pid
        if isinstance(who, int) and who in (0, 1):
            pid = who
        else:
            s = str(who).lower()
            if s in ("friendly", "self", "owner", "player", "controller"):
                pid = src_owner
            elif s in ("enemy", "opponent", "foe"):
                pid = g.other(src_owner)
            elif s in ("active", "current"):
                pid = g.active_player
            elif s in ("inactive", "other_active"):
                pid = g.other(g.active_player)
            else:
                pid = src_owner

        ev = []
        for _ in range(max(0, count)):
            if len(g.players[pid].hand) < 10:
                g.players[pid].hand.append(card_id)
                ev.append(Event("CardCreated", {"player": pid, "card": card_id}))
            else:
                g.players[pid].graveyard.append(card_id)
                ev.append(Event("CardBurned", {"player": pid, "card": card_id}))
        return ev

    return run

def _fx_if_target_attack_at_most(params, json_db_tokens):
    """
    Run 'then' effects only if the tagged MINION target's current Attack <= amount.
    JSON:
      {
        "effect": "if_target_attack_at_most",
        "amount": 3,
        "then": [ ... ]
      }
    """
    need = int(params.get("amount", 0))
    then_spec = params.get("then", []) or []
    then_fn = _compile_effects(then_spec, json_db_tokens)

    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []
        if obj.attack <= need:
            return then_fn(g, source_obj, target)
        return []
    return run


def _fx_if_target_attack_at_least(params, json_db_tokens):
    """
    Run 'then' effects only if the tagged MINION target's current Attack >= amount.
    JSON:
      {
        "effect": "if_target_attack_at_least",
        "amount": 7,
        "then": [ ... ]
      }
    """
    need = int(params.get("amount", 0))
    then_spec = params.get("then", []) or []
    then_fn = _compile_effects(then_spec, json_db_tokens)

    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []
        if obj.attack >= need:
            return then_fn(g, source_obj, target)
        return []
    return run

def _fx_destroy(params):
    """
    Destroy the tagged minion outright.
    Optional: {"reason": "BigGameHunter"} for log clarity.
    """
    reason = str(params.get("reason", "Effect"))
    def run(g, source_obj, target):
        kind, obj = _resolve_tagged_target(g, target)
        if kind != "minion" or obj is None:
            return []
        return g.destroy_minion(obj, reason=reason)
    return run

def _fx_copy_self_as_target_minion(params):
    """
    Faceless Manipulator:
    On battlecry, the just-summoned minion (self) becomes a copy of the tagged minion's
    *current* state (stats/keywords/silence/spell damage/minion type/aura specs/etc.).
    Keeps same id/owner. Re-enables copied auras and refreshes adjacency for the side.
    """
    def run(g, source_obj, target):
        # Find the self minion created by play_card (battlecry context)
        sid = getattr(g, "current_battlecry_minion_id", None)
        if sid is None:
            return []
        loc_self = g.find_minion(sid)
        if not loc_self:
            return []
        _, _, me = loc_self

        kind, tgt = _resolve_tagged_target(g, target)
        if kind != "minion" or tgt is None:
            return []

        ev: list[Event] = []
        # Drop any active aura from current self before morphing
        ev += g._disable_aura(me)

        # Copy live state from target (current stats + relevant flags)
        me.name           = tgt.name
        me.card_id        = tgt.card_id
        me.attack         = max(0, tgt.attack)
        me.max_health     = max(1, tgt.max_health)
        me.health         = max(0, min(me.max_health, tgt.health))

        me.taunt          = bool(tgt.taunt)
        me.divine_shield  = bool(tgt.divine_shield)
        me.charge         = bool(tgt.charge)
        me.rush           = bool(tgt.rush)
        me.frozen         = bool(tgt.frozen)          # copies current freeze state
        me.silenced       = bool(tgt.silenced)
        me.cant_attack    = bool(tgt.cant_attack)

        me.spell_damage   = int(getattr(tgt, "spell_damage", 0))
        me.minion_type    = getattr(tgt, "minion_type", "None")
        me.base_minion_type = getattr(tgt, "base_minion_type", me.minion_type)

        # Copy base/card identity traits (affects silences, reveals, etc.)
        me.cost           = int(getattr(tgt, "cost", 0))
        me.rarity         = getattr(tgt, "rarity", "")
        me.base_attack    = int(getattr(tgt, "base_attack", me.attack))
        me.base_health    = int(getattr(tgt, "base_health", me.max_health))
        me.base_text      = getattr(tgt, "base_text", "")
        me.base_keywords  = list(getattr(tgt, "base_keywords", []))

        # Copy auras / triggers / enrage
        me.aura_spec      = getattr(tgt, "aura_spec", None)
        me.auras          = list(getattr(tgt, "auras", []))
        me.cost_aura_spec = getattr(tgt, "cost_aura_spec", None)
        me.triggers_map   = dict(getattr(tgt, "triggers_map", {}))
        me.enrage_spec    = getattr(tgt, "enrage_spec", None)
        me.enrage_active  = bool(getattr(tgt, "enrage_active", False))

        # Clear temporary stacks from the old self (those shouldn’t carry over)
        me.temp_stats.clear()
        me.temp_keywords.clear()

        # Re-enable any copied aura(s) and refresh adjacency on our side
        ev += g._enable_aura(me)
        ev += g._refresh_stat_auras(me.owner)

        # Recompute enrage / attack-ready flag
        ev += g._update_enrage(me)
        me.can_attack = me.charge or (not me.exhausted)

        # Log a friendly event for UX
        ev.append(Event("MinionTransformed", {
            "minion": me.id,
            "name": me.name,
            "reason": "FacelessManipulator",
            "copied_from": tgt.id
        }))
        g.history += ev
        return ev
    return run

def _fx_add_self_health_from_hand(params):
    """
    Add +1 Health (and Max Health) to THIS minion for each card in its owner's hand.
    Used by Twilight Drake.
    JSON:
      { "effect": "add_self_health_from_hand" }
    """
    def run(g, source_obj, context):
        # Find the minion that just resolved its battlecry
        sid = getattr(g, "current_battlecry_minion_id", None) or getattr(source_obj, "id", None)
        owner = getattr(g, "current_battlecry_owner", getattr(source_obj, "owner", g.active_player))
        if sid is None:
            return []
        loc = g.find_minion(sid)
        if not loc:
            return []
        _, _, me = loc

        # Count current cards in hand (Twilight Drake does NOT count itself)
        amount = len(g.players[owner].hand)
        if amount <= 0:
            return []
        
        before = me.health
        me.max_health += amount
        me.health += amount

        ev = [Event("Buff", {"minion": me.id, "attack_delta": 0, "health_delta": me.health - before})]
        ev += g._update_enrage(me)
        return ev
    return run

# Registry maps effect name -> factory
def _effect_factory(name, params, json_tokens):
    table = {
        "deal_damage":                      _fx_deal_damage,
        "heal":                             _fx_heal,
        "draw":                             _fx_draw,
        "gain_temp_mana":                   _fx_gain_temp_mana,
        "aoe_damage":                       _fx_aoe_damage,
        "aoe_damage_minions":               _fx_aoe_damage_minions,
        "aoe_heal":                         _fx_aoe_heal,
        "aoe_heal_minions":                 _fx_aoe_heal_minions,
        "add_keyword":                      _fx_add_keyword,
        "add_attack":                       _fx_add_attack,
        "add_stats":                        _fx_add_stats,
        "add_self_stats":                   _fx_add_self_stats,
        "random_add_stat":                  _fx_random_add_stat,
        "silence":                          _fx_silence,
        "freeze":                           _fx_freeze,
        "summon":                           lambda p: _fx_summon(p, json_tokens),
        "summon_from_pool":                 lambda p: _fx_summon_from_pool(p, json_tokens),
        "transform":                        lambda p: _fx_transform(p, json_tokens),
        "equip_weapon":                     lambda p: _fx_equip_weapon(p, json_tokens),
        "if_summoned_tribe":                lambda p: _fx_if_summoned_tribe(p, json_tokens),
        "if_control_tribe":                 lambda p: _fx_if_control_tribe(p, json_tokens),
        "if_target_died_then":              lambda p: _fx_if_target_died_then(p, json_tokens),
        "if_target_survived_then":          lambda p: _fx_if_target_survived_then(p, json_tokens),
        "if_summoned_has_keyword":          lambda p: _fx_if_summoned_has_keyword(p, json_tokens),
        "if_target_attack_at_least":        lambda p: _fx_if_target_attack_at_least(p, json_tokens),
        "if_target_attack_at_most":         lambda p: _fx_if_target_attack_at_most(p, json_tokens),
        "destroy_weapon":                   _fx_destroy_weapon,
        "gain_armor":                       _fx_gain_armor,
        "adjacent_buff":                    _fx_adjacent_buff,
        "set_health":                       _fx_set_health,
        "set_attack":                       _fx_set_attack,
        "multiply_attack":                  _fx_multiply_attack,
        "multiply_health":                  _fx_multiply_health,
        "weapon_durability_delta":          _fx_weapon_durability_delta,
        "discover_equal_remaining_mana":    _fx_discover_equal_remaining_mana,
        "temp_modify":                      _fx_temp_modify,
        "temp_cost":                        _fx_temp_cost,
        "discard_random":                   _fx_discard_random,
        "random_pings":                     _fx_random_pings,
        "random_enemy_damage":              _fx_random_enemy_damage,
        "random_heal":                      _fx_random_heal,
        "deal_damage_equal_armor":          _fx_deal_damage_equal_armor,
        "execute":                          _fx_execute,
        "brawl":                            _fx_brawl,
        "add_card_to_hand":                 _fx_add_card_to_hand,
        "mirror_played_minion":             _fx_mirror_played_minion,
        "counterspell":                     _fx_counterspell,
        "shadowflame":                      _fx_shadowflame,
        "destroy":                          _fx_destroy,
        "copy_self_as_target_minion":       _fx_copy_self_as_target_minion,
        "add_self_health_from_hand":        _fx_add_self_health_from_hand,
        "replace_hero":                     _fx_replace_hero,
        
    }
    if name not in table:
        raise ValueError(f"Unknown effect: {name}")
    fn_or_factory = table[name]
    return fn_or_factory(params)

def _compile_effects_for_heroes(effects_spec, cards_db):
    tokens = cards_db.get("_TOKENS", {})
    return _compile_effects(effects_spec, tokens)

def _compile_effects(effects_spec, json_tokens):
    """
    Compile a list of effect specs into a single runner:
      runner(game, source_obj, target) -> List[Event]
    Each spec is a dict with at least {"effect": "<name>", ...}.
    """
    fns = []
    for eff in effects_spec or []:
        if not isinstance(eff, dict):
            continue
        name = eff.get("effect")
        if not name:
            continue
        params = dict(eff)
        params.pop("effect", None)
        fn = _effect_factory(name, params, json_tokens)  # returns runner(g, src, target)
        fns.append(fn)

    def run(g, source_obj, target):
        ev: List[Event] = []
        for fn in fns:
            ev += fn(g, source_obj, target)
        return ev

    return run

# ------------ Loaders ----------------

def load_heros_from_json(path: str) -> Dict[str, Hero]:
    """
    heroes.json format (flexible, but this is recommended):
    {
      "heroes": [
        {
          "id": "MAGE",
          "name": "Mage",
          "power": {
            "name": "Fireblast",
            "text": "Deal 1 damage.",
            "cost": 2,
            "targeting": "any_character",
            "effects": [
              {"effect":"deal_damage","amount":1}
            ]
          }
        },
        ...
      ]
    }
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    db: Dict[str, Hero] = {}
    for h in raw.get("heroes", []):
        pid  = str(h.get("id", "")).upper()
        name = h.get("name") or pid.capitalize()
        pwr  = h.get("power", {}) or {}
        hp = HeroPower(
            name=pwr.get("name", "Hero Power"),
            text=pwr.get("text", ""),
            cost=int(pwr.get("cost", 2)),
            targeting=str(pwr.get("targeting", "none")).lower(),
            effects_spec=list(pwr.get("effects", [])),
            counts_as_spell=bool(pwr.get("counts_as_spell", False)),
        )
        db[pid] = Hero(id=pid, name=name, power=hp)
    return db

def load_cards_from_json(path: str) -> Dict[str, Card]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tokens = data.get("tokens", {})
    db: Dict[str, Card] = {}
    targeting: Dict[str, str] = {}
    deathrattles_map: Dict[str, Any] = {}

    raw_cards: Dict[str, dict] = {}

    for raw in data["cards"]:
        cid   = raw["id"]
        name  = raw["name"]
        typ   = raw["type"]
        cost  = int(raw["cost"])
        text  = raw.get("text", "")
        atk   = int(raw.get("attack", 0))
        hp    = int(raw.get("health", 0))
        kwords= list(raw.get("keywords", []))
        rarity = (raw.get("rarity") or "Common")
        aura_spec = raw.get("aura")  # dict or None
        spell_dmg = int(raw.get("spell_damage", 0))
        enrage_spec = raw.get("enrage")  # dict or None
        mtype = str(raw.get("minion_type", "None"))
        secret_spec = raw.get("secret")
        cost_aura = raw.get("cost_aura")  # dict or None
        auras_list = list(raw.get("auras", [])) # NEW: list of generic auras

        triggers_map: Dict[str, List[Callable]] = {}
        for tr in raw.get("triggers", []) or []:
            on = str(tr.get("on","")).lower().strip()
            effs = tr.get("effects", []) or []
            if on:
                triggers_map.setdefault(on, []).append(_compile_effects(effs, tokens))

        bc = oc = None
        if "battlecry" in raw:
            bc = _compile_effects(raw["battlecry"], tokens)
        if "on_cast" in raw:
            oc = _compile_effects(raw["on_cast"], tokens)
        if "deathrattle" in raw:
            deathrattles_map[cid] = raw["deathrattle"]  # keep spec for hook attachment

        card = Card(
            id=cid, name=name, cost=cost, type=typ, attack=atk, health=hp,
            keywords=kwords, battlecry=bc, on_cast=oc, rarity=rarity,
            aura_spec=aura_spec,
            spell_damage=spell_dmg,
            minion_type=mtype,
            triggers_map=triggers_map,
            cost_aura_spec=cost_aura, auras=auras_list
        )

        setattr(card, "enrage_spec", enrage_spec)
        # if your Card has a text field:
        try:
            setattr(card, "text", text)
        except Exception:
            pass

        # compile secret (if present)
        if secret_spec:
            trig = str(secret_spec.get("trigger","")).lower()
            effs = secret_spec.get("effects", []) or []
            setattr(card, "secret_trigger", trig)
            setattr(card, "secret_runner", _compile_effects(effs, tokens))

        db[cid] = card
        targeting[cid] = raw.get("targeting", "none")
        raw_cards[cid] = dict(raw)

    # Provide post-summon hook that attaches JSON deathrattles
    def _post_summon(g: Game, m: Minion):
        # find the card id by name (cheap, but fine for prototype)
        for cid, c in db.items():
            if c.name == m.name and cid in deathrattles_map:
                dr = _compile_effects(deathrattles_map[cid], tokens)
                def _dr(g2: Game, m2: Minion, _dr_inner=dr, _nm=m.name):
                    return _dr_inner(g2, m2, None)
                m.deathrattle = _dr
                break

    db["_TOKENS"] = tokens  # expose raw token specs for other compilers (heroes)
    db["_POST_SUMMON_HOOK"] = _post_summon
    db["_TARGETING"] = targeting  # (optional) UI can use this to highlight targets'
    db["_RAW"]        = raw_cards
    return db

def _is_real_card(db, cid: str) -> bool:
    return (cid in db) and (not cid.startswith("_")) and hasattr(db[cid], "type")

def _is_legendary(db, cid: str) -> bool:
    try:
        return str(getattr(db[cid], "rarity", "")).upper() == "LEGENDARY"
    except Exception:
        return False

def _expand_counts_to_list(counts: Dict[str, int]) -> List[str]:
    lst: List[str] = []
    for cid, n in counts.items():
        lst.extend([cid] * int(n))
    return lst

def _validate_deck_list(db, deck_list: List[str]) -> Tuple[bool, List[str]]:
    """
    Enforces:
      - exactly 30 cards
      - up to 2 copies non-legendary
      - up to 1 copy legendary
      - all card ids exist in db
    Returns (ok, errors[])
    """
    errors: List[str] = []
    if len(deck_list) != 30:
        errors.append(f"Deck must have exactly 30 cards (got {len(deck_list)}).")

    # Existence + counts
    counts: Dict[str, int] = {}
    for cid in deck_list:
        if not _is_real_card(db, cid):
            errors.append(f"Unknown card id: {cid}")
        counts[cid] = counts.get(cid, 0) + 1

    for cid, n in counts.items():
        if _is_legendary(db, cid):
            if n > 1:
                errors.append(f"Legendary '{cid}' appears {n} times (max 1).")
        else:
            if n > 2:
                errors.append(f"'{cid}' appears {n} times (max 2).")

    return (len(errors) == 0), errors

def load_decks_from_json(path: str, cards_db) -> Dict[str, Dict[str, object]]:
    """
    Loads and validates decks. Returns:
      {
        deck_name: {
          "list": [<30 card ids>],
          "hero": <optional hero id or None>,
          "errors": []   # present only if invalid
        },
        ...
      }
    Invalid decks are included with an 'errors' key so you can surface issues in UI/log.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, object]] = {}

    for entry in raw.get("decks", []):
        name = str(entry.get("name", "")).strip() or f"Deck_{len(out)+1}"
        hero_hint = entry.get("hero")
        if "cards" in entry:
            deck_list = _expand_counts_to_list(entry["cards"])
        elif "list" in entry:
            deck_list = list(entry["list"])
        else:
            deck_list = []

        ok, errs = _validate_deck_list(cards_db, deck_list)
        if ok:
            out[name] = {"list": deck_list[:30], "hero": hero_hint}
        else:
            out[name] = {"list": deck_list, "hero": hero_hint, "errors": errs}
    return out

def choose_loaded_deck(decks: Dict[str, Dict[str, object]],
                       preferred_name: str | None) -> Tuple[List[str], str | None]:
    """
    Picks a valid deck by name (if provided) else the first valid one.
    Returns (deck_list, hero_hint) or ([], None) if none valid.
    """
    # prefer by name
    if preferred_name and preferred_name in decks:
        d = decks[preferred_name]
        if "errors" not in d:
            return list(d["list"]), (d.get("hero") or None)
    # otherwise first valid
    for d in decks.values():
        if "errors" not in d:
            return list(d["list"]), (d.get("hero") or None)
    return [], None
