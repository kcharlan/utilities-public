# Rock Paper Scissors Simulator

A screensaver-style browser simulation where Rock, Paper, and Scissors battle
for dominance. When different types collide, the winner normally converts the
loser according to the standard rules: Rock beats Scissors, Scissors beats
Paper, and Paper beats Rock.

## Features

- **Physics:** Equal-mass elastic collisions, wall bouncing, and adjustable
  movement speed.
- **Auto-restart:** After one type takes over the field, the next round starts
  automatically. The delay is `10000 / speed` milliseconds.
- **Fair starts:** Each type receives `floor(count * 0.15)` guaranteed entries;
  remaining entries are random. Entries of each type rotate through offset
  quadrants to reduce starting clusters. At very small counts, representation
  of all three types cannot be guaranteed.
- **Controls:**
  - **Count:** Set the population from 2 to 200. A new count takes effect on
    the next manual or automatic restart.
  - **Speed:** Adjust movement speed immediately from 1 to 20.
  - **Size:** Adjust icon and collision size immediately on a logarithmic scale
    from 1 to 10.
  - **Theme:** Follow the system color scheme or force light or dark mode.
  - **Pass Thru:** Let same-type items pass through one another (enabled by
    default).
  - **Save %:** Give a loser a 0–100% chance to reverse the result and convert
    the winner.
- **Stats and feedback:**
  - Current populations and elapsed session time.
  - A cumulative round-wins leaderboard, sorted by wins and then
    alphabetically.
  - A per-item conversion counter, reset whenever that item is converted.
  - Inverted colors on an item converted by a successful saving throw.
  - A gold MVP glow at round end when one to three items share the highest
    nonzero conversion count.

## Project layout

- `index.html`: Page structure and controls.
- `script.js`: Game engine, physics, collision, balancing logic, and rendering.
- `style.css`: Layout and light/dark/system theme styling.
- `rock.png`, `paper.png`, `scissors.png`: Item sprites.

## Simulation mechanics

### Round initialization

At the start of each round, the simulator builds a shuffled type pool. It adds
`floor(count * 0.15)` entries for each type, fills the remainder randomly, and
spreads each type through the four quadrants with a different starting offset.

### Round-win handicap

The handicap compares **cumulative round-win totals**, not the current
populations within a round. It is not evaluated until at least 35 rounds have
finished, and it can activate only after every type has won at least once.

The leading type becomes handicapped when its win total is greater than:

- 1.5 times the lowest win total, or
- the lowest win total plus 8,

whichever is greater:

```text
activation threshold = max(lowest wins * 1.5, lowest wins + 8)
```

While active, the handicap follows whichever type currently has the most round
wins. When that type wins a collision and already occupies at least 33% of the
current field, the loser is assigned one of the other two types instead of
joining the winner. The red `Handicap: TYPE` indicator shows the affected type.

The handicap is released when the leading win total is no greater than:

```text
release threshold = max(lowest wins * 1.2, lowest wins + 5)
```

### Session timer and restarts

The timer spans automatic round restarts. Clicking **Restart** starts a new
session by clearing the timer and round-win totals, then rebuilding the field
from the current controls. Reloading the page also starts a new session.

## Running

Open `index.html` in a browser:

```bash
open web_games/rps_screen/index.html
```

No build steps or dependencies required.
