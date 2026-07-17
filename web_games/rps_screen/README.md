# Rock Paper Scissors Simulator

A "screen saver" style simulation where Rock, Paper, and Scissors battle for dominance.

## Features
-   **Physics Engine**: Elastic collisions, wall bouncing, and momentum.
-   **Game Logic**: Standard RPS rules (Rock > Scissors > Paper > Rock). Winners convert losers.
-   **Auto-Restart**: Infinite loop mode – the simulation automatically restarts after a winner is declared. Restart delay scales inversely with speed.
-   **Fair Start**: Guaranteed inclusive distribution (min 15% per type) spawned in balanced quadrants to prevent clustering/early wipes.
-   **Customization**:
    -   **Count**: Adjust population size (2-200).
    -   **Speed**: Real-time speed adjustment.
    -   **Size**: Logarithmic scaling for icons.
    -   **Theme**: Light/Dark/System support.
-   **Advanced Physics**:
    -   **Pass Thru**: Reduce chaos by allowing same-type items to pass through each other (Default: On).
    -   **Saving Throws**: Losers have a chance (0-100%) to "reverse" the outcome and convert the winner instead.
-   **Stats & Tracking**:
    -   **Dynamic Leaderboard**: "Wins" display automatically sorts by win count and breaks ties alphabetically.
    -   **Kill Counters**: Each item displays a counter showing how many opponents it has converted. Note: Counters reset if an item is converted.
    -   **MVP Highlight**: At the end of each round, the item(s) with the highest conversion count are highlighted with a gold glow effect.
    -   **Visual Feedback**:
        -   Items that successfully perform a "Saving Throw" appear with inverted colors.
        -   Counters use high-contrast text pathing for readability.

## Project Layout
- `index.html`: Page structure and controls.
- `script.js`: Game engine, physics, collision, balancing logic, and rendering.
- `style.css`: Styling with Light/Dark/System theme support via CSS custom properties.
- `rock.png`, `paper.png`, `scissors.png`: Item sprites.

## Fairness & Simulation Mechanics
The simulation employs several layers of logic to ensure games are fair, dynamic, and fun to watch.

### 1. Fair Start Mechanics (Population & Distribution)
At the beginning of every round, we ensure no team starts with an unfair advantage.
*   **Guaranteed Representation**: The system enforces a minimum population of 15% per type. This prevents RNG from spawning a game with 1 Rock vs 50 Paper.
*   **Quadrant Spawning**: To preventing immediate team-wipes, units are spawned using a round-robin quadrant system.
    *   *Example*: Rock #1 spawns Top-Left, Rock #2 Top-Right... while Paper #1 starts Top-Right. This spatial padding gives teams a moment to breathe before chaos ensues.

### 2. Dynamic Balancing (The Handicap)
During the game, it's common for one type to snowball uncontrollably. To prevent boring, instant-win scenarios, we monitor the **Win Ratios** (active counts) of the teams.

**The Mechanism**:
If a team becomes too dominant, a "Handicap" is applied. While handicapped, that team **cannot convert new members**. If they win a fight, the loser is randomized to a neutral type instead of being recruited. This stalls the leader's growth.

When the handicap is active, there is a banner displayed in red text with the message "Handicap: <Type>". When the handicap is inactive or released (deactivated), the banner is removed.

**Trigger Logic (Activation)**:
The handicap does not become eligible for activation until 35 or more round wins have been recorded. Once that threshold is met, this mechanism becomes available.

The handicap activates when the dominant team exceeds the weakest team by a margin calculated as the **greater** of:
*   **Ratio**: 1.5x the weakest team's count.
*   **Distance**: The weakest team's count + 8.

`Threshold = Math.max(MinCount * 1.5, MinCount + 8)`

**Release Logic (De-activation)**:
The handicap releases when the playing field levels out, defined as when the dominant team drops to within the **greater** of:
*   **Ratio**: 1.2x the weakest team's count.
*   **Distance**: The weakest team's count + 5.

`StopThreshold = Math.max(MinCount * 1.2, MinCount + 5)`

### 3. Session Timer
The timer tracks your total viewing session. It persists across auto-restarts and only resets when you manually intervene (Restart/Reload).

## Running
Simply open `index.html` in your browser.
```bash
open index.html
```
No build steps or dependencies required.
