# MLS Tracker User Guide

A walkthrough for tracking MLS playoff races, analyzing scenarios, and understanding clinch/elimination math with MLS Tracker.

---

## 1. Getting Started

### Launch

```bash
# Default launch (opens browser automatically)
./mls_tracker

# Custom port
./mls_tracker --port 9000

# Suppress auto-open browser
./mls_tracker --no-browser
```

MLS Tracker starts a local web server and opens your browser to `http://127.0.0.1:8501`.

### First-Time Setup

On first run, the script creates a private virtual environment at `~/.mls_tracker_venv` and installs its dependencies (FastAPI, uvicorn, httpx). This happens once — subsequent launches start instantly.

**Requirements:** Python 3.8+ and an internet connection (data is fetched live from the ESPN API; CDN resources for React, Tailwind, and fonts).

### Data Source

All standings and team metadata come from the ESPN public API:
- **Standings:** `https://site.api.espn.com/apis/v2/sports/soccer/usa.1/standings?season={year}`
- **Teams:** `https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/teams`

Data is cached server-side for **5 minutes**. Use the refresh button to force a fresh fetch.

---

## 2. The Interface

### Settings Bar

A sticky bar across the top of the page with backdrop blur. It contains all controls:

| Control | Description |
|---------|-------------|
| **Live indicator** | Green pulsing dot confirming data connection |
| **Conference** | Dropdown: Eastern or Western |
| **Team** | Dropdown: all teams in the selected conference (sorted alphabetically) |
| **Season** | Dropdown: current year and previous 2 years |
| **Line** | Number input (1–15): the playoff cutoff position to analyze against (default: 9) |
| **Refresh** | Invalidates the 5-minute cache and re-fetches live data (icon spins while loading) |
| **Dark mode** | Sun/moon toggle — auto-detects system preference on first visit, persists to localStorage |

### Team Header

A full-width hero section with:
- **Dynamic gradient background** using the selected team's primary and secondary colors
- **Team logo** (80x80px, centered)
- **Team name** in large display type
- **Season and conference** badge
- **Conference rank** badge (visible on desktop)

---

## 3. Status Banner

Below the header, a banner immediately communicates the team's playoff status. There are four possible states:

| Status | Color | Icon | Meaning |
|--------|-------|------|---------|
| **Playoffs Clinched** | Green | Trophy | The team's points exceed the cutoff team's maximum possible points — playoffs are guaranteed |
| **In The Hunt** | Team color | Zap | The team controls its own destiny — results on the pitch determine playoff fate |
| **Need Help From Other Results** | Orange | AlertTriangle | The team cannot clinch on its own — the cutoff team's results also matter |
| **Mathematically Eliminated** | Red | XCircle | Even winning all remaining games cannot overtake the cutoff position |

### Need Help Details

When a team needs help, the banner shows a dynamic message explaining what the cutoff team must do (e.g., "Team X must earn no more than Y points in Z games").

---

## 4. Key Metrics

Four stat cards appear below the status banner in a 2x2 grid (mobile) or 4-column row (desktop):

| Card | Value | Sub-text |
|------|-------|----------|
| **Current Points** | Team's current point total | Games remaining |
| **Points to Safety** | Gap between team and projected cutoff | Projected cutoff value |
| **Min Wins Needed** | Fewest wins required to make playoffs | "Achievable" or "Not possible with games left" |
| **PPG Required** | Points per game needed from remaining matches | Current PPG for comparison |

Each card has a top accent bar in the team's primary color and a sequential fade-in animation.

---

## 5. Conference Standings

A full standings table for the selected conference.

### Columns

| Column | Description |
|--------|-------------|
| **#** | Position/rank |
| **Team** | Team name with logo and abbreviation (abbreviation hidden on mobile) |
| **GP** | Games played |
| **W** | Wins |
| **L** | Losses |
| **T** | Ties |
| **PTS** | Points (bold) |
| **GD** | Goal differential (green if positive, red if negative, gray if zero) |
| **PPG** | Points per game |

### Visual Indicators

| Indicator | Meaning |
|-----------|---------|
| **Highlighted row** | The currently selected team — tinted background with a vertical accent bar next to the team name |
| **Dashed line** | The playoff cutoff line — drawn below the cutoff position with a legend: "Playoff cutoff line (position X)" |
| **Row hover** | Light tint on hover for visual feedback |

---

## 6. Playoff Scenarios

Two side-by-side cards (stacked on mobile) break down the paths to the playoffs:

### Worst Case

Minimizes ties and maximizes wins needed. Shows:
- **Wins** / **Ties** / **Losses** / **Final Points**
- "Not Possible" badge if the scenario is unachievable with remaining games

### Easiest Path

Maximizes ties and minimizes wins needed. Shows the same breakdown — this is the path requiring the fewest outright wins.

Each card has a colored header bar (team secondary color for Worst Case, team primary for Easiest Path) with an icon (Flame / Route).

---

## 7. Competition Card

Below the scenarios, a card shows details about the team currently sitting at the playoff cutoff position:

| Field | Description |
|-------|-------------|
| **Team logo & name** | The cutoff team with its position badge (e.g., "#9") |
| **Points** | Current point total |
| **Projected** | Final points if current PPG continues |
| **PPG** | Points per game |
| **Games Left** | Remaining matches |

This gives context for how hard it will be to overtake (or stay ahead of) the cutoff.

---

## 8. Technical Details Footer

A collapsible section at the bottom (starts collapsed). Click to expand and see:

- **Data source:** ESPN MLS API
- **Standings and teams API URLs**
- **Cache TTL:** 5 minutes
- **Clinch logic formula:** `target_pts > cutoff_max_possible`
- **Last refresh timestamp**

---

## 9. Dark Mode

Click the sun/moon icon in the settings bar to toggle.

- **Auto-detection:** On first visit, MLS Tracker follows your OS preference (`prefers-color-scheme: dark`)
- **Persistence:** Saved to localStorage as `mls-dark-mode`
- **Team colors:** Dynamic team branding stays vivid in both modes — surface colors invert but accent colors remain consistent
- **Smooth transition:** 0.3s animation on background and text color changes

---

## 10. Loading and Error States

### Loading

On initial load, a skeleton UI appears with shimmer animations — a large block for the header, a bar for the settings, four cards for metrics, and a table placeholder. This indicates data is being fetched from ESPN.

### Refresh

While refreshing, the refresh button icon spins and the button is disabled.

### Errors

If something goes wrong (network issue, ESPN API down), a red banner appears below the header with:
- An error icon and message
- A **Retry** button to attempt the fetch again

A React error boundary also catches UI crashes and shows a full-page error overlay with a reload button.

---

## 11. Quick Reference

### CLI Flags

```
./mls_tracker [--port PORT] [--no-browser]
```

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--port` | `-p` | 8501 | Server port |
| `--no-browser` | — | off | Don't open browser automatically |

### Clinch / Elimination Logic

| Status | Condition |
|--------|-----------|
| **Clinched** | Team's current points > cutoff team's maximum possible points |
| **Eliminated** | Team's maximum possible points < cutoff team's current points |
| **Need Help** | Team's maximum possible points < cutoff team's projected points |
| **In The Hunt** | None of the above — team controls its own fate |

### Color Legend

**Status Colors:**

| Status | Color |
|--------|-------|
| Clinched | Green |
| In The Hunt | Team primary color |
| Need Help | Orange |
| Eliminated | Red |

**Standings:**

| Element | Color | Meaning |
|---------|-------|---------|
| Green GD | Green | Positive goal differential |
| Red GD | Red | Negative goal differential |
| Dashed line | Team primary | Playoff cutoff position |
| Highlighted row | Team primary (translucent) | Currently selected team |

**Typography:**

| Font | Usage |
|------|-------|
| **Oswald** | Headers, labels, badges, uppercase titles |
| **Source Sans 3** | Body text, data rows, descriptions |
