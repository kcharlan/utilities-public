# Telltale visual design

Status: draft for review (2026-10-27). This covers how Telltale looks and reads.
Behavior, data sources and the collector are covered in the design spec, which
is still to be written.

## Subject, audience, job

- **Subject.** A live health monitor for the AI coding services Kevin uses all
  day. It starts with Codex on OpenAI models. OpenRouter and Claude come later
  as plugins.
- **Audience.** One person, a heavy agent user, glancing at it between tasks.
- **Job.** Answer two questions at a glance: "Is something off?" and "Is it
  them or me?" (provider trouble, or a heavy workload of my own).

A *telltale* is a warning lamp on a vehicle's instrument cluster. Telltale
borrows two ideas from cockpits and dashboards:

- **Dark cockpit.** When everything is normal, nothing is lit. Light means
  "look here".
- **ISO 2575 lamp colors.** Red means act now. Amber means caution. Green
  means a system is on. Blue is information, the way the high-beam lamp is.
  Telltale's blue means "faster than usual". Speedups are deviations too.

## Color

Core surfaces (dashboard window, dark by default):

| Name | Hex | Use |
|---|---|---|
| Cluster | `#151B21` | Window background: the smoked face of a gauge cluster |
| Housing | `#262F37` | Unlit lamps, plot frames, separators |
| Readout | `#E9EDF0` | Primary numbers and text |
| Dim | `#8D99A3` | Labels, the "usual" values, axes |

Lamp colors (only ever mean one thing):

| Lamp | Hex | Meaning |
|---|---|---|
| Red | `#E5484D` | Failures, collector down, a severe slowdown |
| Amber | `#F0A800` | Slower than usual, heavy workload, provider incident |
| Blue | `#4C8DFF` | Faster than usual (possible shallower output) |
| Green | `#3DB879` | Collector running. Shown only in the collector view, never as "all good" |

A light-appearance counterpart keeps the lamp hues. It uses Housing
`#D9DEE2`, Cluster `#F6F7F8` and Readout `#141A1F`, and darkens Amber to
`#B87A00` for contrast.

The menu-bar panel uses the system material and follows the system
appearance. Lamp colors are its only custom colors.

## Type

- **SF Pro** (system) for all interface text and controls, in sentence case.
  The panel matches Brew Version: 13 pt body, 11 pt secondary.
- **Barlow Semi Condensed** (SIL OFL, bundled) for instrument readouts: big
  numerals, lamp captions, axis numbers. It always uses tabular figures. Barlow
  descends from road-sign and DIN lettering, so it reads like a cluster readout
  without being monospace.

Scale (pt): 11 / 13 / 15 / 20 / 34. Weights are Regular and Medium only.
Readout numerals take the 34 and 20 steps, and their "usual" values sit beside
them at 15, in Dim.

## Layout

### Menu-bar glyph

A template glyph for a lamp lens (a rounded rectangle with a filament line).
While healthy it's a plain template image, unlit, like the rest of the bar.
When a lamp lights, a 7 pt dot in the most severe lamp color appears on it.
This uses the same drawing approach as Brew Version's `StatusIcon` (mug plus
dot).

### Panel (340 pt wide, native)

```
┌─────────────────────────────────────────┐
│ Telltale                 Checked 12:40 ⟳│
│ ▢ Speed ▢ Errors ▢ Link ▢ OpenAI ▢ Load │   lamp strip: unlit = Housing
├─────────────────────────────────────────┤
│ ▲ Sol is 26% slower than usual          │   alert list, newest severe first
│   for prompts this size. Since 08:10.   │   (empty: "Nothing to report.")
│ ▲ 3 of your last 10 prompts were over   │
│   300k tokens. A fresh session would    │
│   speed things up.                      │
├─────────────────────────────────────────┤
│ Sol     31 tok/s  usual 42   ▁▂▃▅▃▂▁    │   one row per active model
│ Terra   70 tok/s  usual 74   ▃▃▄▃▃▃▃    │
├─────────────────────────────────────────┤
│ ● Collector running, every 5 min        │
│                         Open dashboard  │
└─────────────────────────────────────────┘
```

Everything is left aligned. The alert list is the panel's main content and
follows the cockpit crew-alerting pattern: one message per condition, ordered
by severity, removed when the condition clears.

### Dashboard window (resizable, about 1100 × 760)

```
┌───────────────┬──────────────────────────────────────────────────┐
│ Codex         │  Speed  Errors  Link  OpenAI  Load  Collector    │ big lamp strip
│   Sol         ├──────────────────────────────────────────────────┤
│   Terra       │  Alerts (same messages as the panel)             │
│ OpenRouter    ├──────────────────────────────────────────────────┤
│   Not set up  │  Speed against usual        6h  24h  7d  14d     │
│ Claude        │  diverging dots around 1.0, incident bands,      │
│   Not set up  │  failure markers, "usual" line                   │
│               ├────────────────────────┬─────────────────────────┤
│               │  Prompt sizes          │  Workload               │
│ Collector     │  histogram: now vs     │  responses/h, turns,    │
│ Settings      │  usual (overlaid)      │  sessions, cache hits,  │
│               │                        │  reasoning share        │
│               ├────────────────────────┴─────────────────────────┤
│               │  Events: failures, retries, disconnects,         │
│               │  incidents, baseline changes                     │
└───────────────┴──────────────────────────────────────────────────┘
```

The sidebar lists providers, each as a plugin, with Collector and Settings
below. Unconfigured providers appear dimmed, as "Not set up".

### Collector view

The lamp idea, applied to the background job. It has four lamps, each lit
green when true and red when it should be true but isn't:

- Installed
- Loaded
- Last run succeeded
- On schedule

Below them: the interval, the last and next run, Run now, Turn off and
Turn on, and the recent log lines.

## Principles

1. **Dark cockpit.** Healthy means quiet. Color appears only for a
   deviation, and the absence of lit lamps is the all-clear. No green "OK"
   badges.
2. **Usual sits beside now.** Every live number shows its baseline next to it,
   and the eye reads the gap.
3. **Them or me.** A speed alert always says whether prompt size explains it.
   The workload view sits next to the speed chart, not on another tab.
4. **Both directions.** Faster than usual lights the blue lamp, and gets the
   same attention as slower.
5. **Native first.** The panel is a well-behaved Mac panel. The dashboard
   carries the identity. The lamps are the one bold element.

## Review against the brief (what changed and why)

- **Revised: card grid of KPIs.** My first sketch of the dashboard was a row
  of stat cards (big number, label, sparkline). That's the generic look for
  any monitoring page. I replaced it with the lamp strip and alert list, which
  come from the subject (telltales and cockpit alerting).
- **Revised: monospace readouts.** I first reached for SF Mono, which is the
  default "data" face. Barlow Semi Condensed is grounded in road and
  instrument lettering, and its tabular figures keep columns aligned.
- **Revised: the meaning of green.** A green "healthy" dot is the default
  status idiom, and it would fight the dark-cockpit principle. Green now
  means only "collector is on", as on a vehicle cluster.
- **Kept: dark background.** Kevin prefers dark, high-contrast instrument
  styling for data tools. Cluster `#151B21` is chosen to match a smoked gauge
  face, not as a neutral near-black. A light counterpart is specified.
- **Kept: native panel.** It matches Brew Version and Anker Charge Monitor,
  and Brew Version's macOS 27 status-item handling is required anyway.

## Copy rules

- Name conditions the way the user sees them: "Sol is 26% slower than usual",
  not "throughput index 0.74".
- Every alert says what to do when there's something to do: "A fresh session
  would speed things up." "Turn on the collector to keep watching."
- Baseline reset is labeled **Accept as usual**. Its confirmation says
  "Sol's usual speed is now 24% lower than before."
- Sample values in mockups and tests are synthetic.
