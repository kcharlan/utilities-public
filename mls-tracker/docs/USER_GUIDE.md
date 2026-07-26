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

MLS Tracker starts a local web server bound to `127.0.0.1` and opens the corresponding browser URL. The default is `http://127.0.0.1:8501`; `--port` changes it.

### First-Time Setup

Install [uv](https://docs.astral.sh/uv/) first (`brew install uv`). The launcher declares Python 3.12+ and its runtime dependencies (FastAPI, uvicorn, and requests) in a PEP 723 header. On first launch, uv resolves them into its shared cache; later launches reuse that cache.

**Requirements:** uv and an internet connection. The backend fetches data from ESPN, while the browser loads React, Babel, Tailwind CSS, Lucide Icons, and Google Fonts from CDNs.

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
| **Live indicator** | Green pulsing marker identifying the live-data view; fetch failures are reported separately in the error banner |
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
| **Playoffs Clinched** | Green | Trophy | The team's current points exceed the selected cutoff team's maximum possible points |
| **In The Hunt** | Team color | Zap | None of the other three conditions in this cutoff-team model applies |
| **Need Help From Other Results** | Orange | AlertTriangle | The team's maximum possible points are below the cutoff team's projected total |
| **Mathematically Eliminated** | Red | XCircle | The team's maximum possible points are below the cutoff team's current points |

### Need Help Details

When a team needs help, the banner shows a dynamic message explaining what the cutoff team must do (e.g., "Team X must earn no more than Y points in Z games").

These labels compare the selected team only with the team currently at the chosen cutoff position. The model assumes a 34-game season and does not simulate other teams, remaining fixtures, or MLS tiebreakers. Treat it as an exploratory projection, not an official league determination.

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

Uses wins only (with all other remaining matches counted as losses) to get one point above the cutoff team's projected total. Shows:
- **Wins** / **Ties** / **Losses** / **Final Points**
- "Not Possible" badge if the scenario is unachievable with remaining games

### Easiest Path

Maximizes ties while finding a combination that gets one point above the cutoff team's projected total. Shows the same breakdown.

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
- A client-side timestamp labeled **Last Refresh**

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

If something goes wrong (network issue, ESPN API down), a red banner appears beneath the settings bar with:
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
| **In The Hunt** | None of the other three cutoff-team conditions applies |

The cutoff projection is `cutoff current points + (cutoff games remaining × cutoff current PPG)`. Scenario cards target the next whole point above that projection. The model does not apply MLS tiebreakers or account for movement by teams other than the current cutoff occupant.

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
