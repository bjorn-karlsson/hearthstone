from engine import Game, make_db, apply_post_summon_hooks, IllegalAction

STARTER_DECK = [
    "SHIELD_BEARER","LEPER_GNOME","RIVER_CROCOLISK","RUSHER","KOBOLD_PING",
    "WOLFRIDER","CHILLWIND_YETI","FIREBALL_LITE","ARCANE_MISSILES_LITE",
    "BOULDERFIST_OGRE"
]*3  # 30 cards

def name_of(db, cid): return db[cid].name

def print_state(g: Game):
    p = g.players
    ap = g.active_player
    print("="*70)
    print(f"Turn {g.turn} | Active: P{ap} | Mana {p[ap].mana}/{p[ap].max_mana}")
    for pid in (0,1):
        hand_names = [name_of(g.cards_db, cid) for cid in p[pid].hand]
        board_str = []
        for m in p[pid].board:
            flags = []
            if getattr(m, "taunt", False): flags.append("T")
            if getattr(m, "charge", False): flags.append("C")
            if getattr(m, "rush", False): flags.append("R")
            if getattr(m, "summoned_this_turn", False): flags.append("S")
            board_str.append(f"{m.id}:{m.name}({m.attack}/{m.health})[{''.join(flags)}]")
        print(f"P{pid}: {p[pid].health} HP | Hand[{len(hand_names)}]: {hand_names}")
        print(f"     Board[{len(board_str)}]: {board_str}")
    print("="*70)

def show_help():
    print("""Commands:
  help                        show this help
  state                       re-print current state
  hand                        list your hand with indices
  board                       list both boards with minion IDs
  end                         end your turn
  play <idx>                  play card from your HAND index (0-based)
  play <idx> face             play a targeted card at enemy hero
  play <idx> m <minion_id>    play a targeted card at a MINION id
  atk <attacker_id> face      attack enemy hero
  atk <attacker_id> m <id>    attack an enemy minion
Notes:
- Taunt blocks attacking face.
- Rush can attack MINIONS on the summon turn, never face; Charge can attack anything.
- The Coin (if in hand) gives +1 temporary mana immediately when played.
""")

def list_hand(g: Game):
    ap = g.active_player
    hand = g.players[ap].hand
    print("Hand:")
    for i, cid in enumerate(hand):
        c = g.cards_db[cid]
        extras = []
        if c.type == "MINION":
            extras.append(f"{c.attack}/{c.health}")
            if "Taunt" in c.keywords: extras.append("Taunt")
            if "Charge" in c.keywords: extras.append("Charge")
            if "Rush" in c.keywords: extras.append("Rush")
        print(f"  [{i}] {c.name} (cost {c.cost}, {c.type}{' ' + ' '.join(extras) if extras else ''})")

def apply_and_print(g: Game, evs):
    apply_post_summon_hooks(g, evs)
    for e in evs:
        if e.kind in ("CardPlayed","MinionSummoned","Attack","PlayerDamaged","MinionDamaged",
                      "MinionDied","PlayerDefeated","TurnStart","TurnEnd","GainMana"):
            print(f"EVENT: {e.kind} -> {e.payload}")

def parse_target(tokens, g: Game):
    """Returns (target_player, target_minion) based on tokens after command."""
    if not tokens:
        return (None, None)
    if tokens[0].lower() == "face":
        return (1 - g.active_player, None)
    if tokens[0].lower() == "m":
        if len(tokens) < 2:
            raise ValueError("Missing minion id after 'm'")
        try:
            mid = int(tokens[1])
        except ValueError:
            raise ValueError("Minion id must be an integer")
        return (None, mid)
    raise ValueError("Unknown target. Use 'face' or 'm <id>'")

def interactive(seed=1337):
    db = make_db()
    g = Game(db, STARTER_DECK.copy(), STARTER_DECK.copy(), seed=seed)
    apply_and_print(g, g.start_game())
    show_help()
    print_state(g)

    while True:
        # check defeat
        for pid in (0,1):
            if g.players[pid].health <= 0:
                print(f"Game over! P{1-pid} wins.")
                return

        cmd = input(f"P{g.active_player}> ").strip()
        if not cmd: 
            continue
        parts = cmd.split()
        op = parts[0].lower()

        try:
            if op in ("q","quit","exit"):
                print("Bye!")
                return
            elif op == "help":
                show_help()
            elif op == "state":
                print_state(g)
            elif op == "hand":
                list_hand(g)
            elif op == "board":
                print_state(g)
            elif op == "end":
                apply_and_print(g, g.end_turn(g.active_player))
                print_state(g)
            elif op == "play":
                if len(parts) < 2:
                    print("Usage: play <hand_index> [face | m <minion_id>]")
                    continue
                idx = int(parts[1])
                t_player, t_minion = (None, None)
                if len(parts) > 2:
                    t_player, t_minion = parse_target(parts[2:], g)
                ev = g.play_card(g.active_player, idx, target_player=t_player, target_minion=t_minion)
                apply_and_print(g, ev)
                print_state(g)
            elif op in ("atk","attack"):
                if len(parts) < 3:
                    print("Usage: atk <attacker_id> face | m <minion_id>")
                    continue
                attacker = int(parts[1])
                t_player, t_minion = parse_target(parts[2:], g)
                ev = g.attack(g.active_player, attacker_id=attacker, target_player=t_player, target_minion=t_minion)
                apply_and_print(g, ev)
                print_state(g)
            else:
                print("Unknown command. Type 'help' for a list of commands.")
        except IllegalAction as e:
            print(f"IllegalAction: {e}")
        except Exception as e:
            print(f"Error: {e}")

def run_demo(seed=1337):
    """Keep your original scripted demo in case you want auto-play for testing."""
    db = make_db()
    g = Game(db, STARTER_DECK.copy(), STARTER_DECK.copy(), seed=seed)
    apply_and_print(g, g.start_game())
    print_state(g)
    # (no scripted actions; switch to interactive to actually play)

if __name__ == "__main__":
    interactive()
