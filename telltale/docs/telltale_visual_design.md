# Telltale visual design

This covers how Telltale looks and reads. Behavior, data sources and the collector
are covered in the [design spec](telltale_design_spec.md) and [Claude provider design](telltale_claude_design.md).

## Subject, audience, job

- **Subject.** A live health monitor for the AI coding services Kevin uses all
  day. It watches Codex and Claude Code. OpenRouter is a possible later plugin.
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
When a new lamp condition lights, a 7 pt dot in the most severe new color appears
on it. When all lit conditions are acknowledged, a 1.5 pt ring takes the most
severe lit color. With no lit lamps the lens stays plain.
This uses the same drawing approach as Brew Version's `StatusIcon` (mug plus
dot).

### Panel (340 pt wide, native)

```
┌─────────────────────────────────────────┐
│ Telltale                 Checked 12:40 ⟳│
│ ▢ Speed ▢ Errors ▢ Link ▢ OpenAI ▢ Load │   lamp strip: unlit = Housing
├─────────────────────────────────────────┤
│ ▲ Sol has been up to 26% slower than    │   alert list, newest severe first
│   usual for prompts this size since     │   (empty: "Nothing to report.")
│   08:10.                                │
│ ▲ 3 of your last 10 prompts were over   │
│   300k tokens. A fresh session would    │
│   speed things up.                      │
├─────────────────────────────────────────┤
│ Sol     31 tok/s  usual 42   ▁▂▃▅▃▂▁    │   one row per active model
│ Terra   70 tok/s  usual 74   ▃▃▄▃▃▃▃    │
├─────────────────────────────────────────┤
│ ● Collector running, every 5 min        │
│ Telltale 0.3.1          Open dashboard  │
└─────────────────────────────────────────┘
```

Everything is left aligned. The alert list is the panel's main content and
follows the cockpit crew-alerting pattern: one message per condition, new rows
first, then acknowledged rows; each group is ordered by severity and recency.
Model row numbers use the current stored speed evaluation point. They are dashes
when it is stale or has no matched responses; thin matched data can show numbers
with a note, and learning notes remain visible while the baseline is learning.
Acknowledged rows use a hollow diamond and secondary text, and remain until
the condition clears.

The panel bottom row shows the version at left and its build number in help.

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
below. Unconfigured providers appear dimmed, as "Not set up". The sidebar foot shows the version with its build number in help.

### Collector view

The lamp idea, applied to the background job. It has four lamps, each lit
green when true and red when it should be true but isn't:

- Installed
- Loaded
- Last run succeeded
- On schedule

Below them: the interval, the last and next run, Run now, Turn off and
Turn on, and the recent log lines.

### Notification banners

A banner is the system's, so its only color is what the title text can carry, and
its body often names the outcome last. The title therefore says what happened
first, so a glance tells an alert from a clear:

| Banner | Title | Example |
|---|---|---|
| Alert (new, catch-up, escalated) | The lit lamp's color, then the rule | 🔴 Collector health |
| Cleared | A plain check and "Cleared:", then the rule | ✓ Cleared: Collector health |

Lamp glyphs follow the lamp's severity: 🔴 red, 🟠 amber, 🔵 blue. A clear is a
lamp going out, so it has no color: green would break the dark cockpit and the
rule that green means only "collector is on". The two also differ in shape and
wording, so the difference doesn't rest on color. Event and rule titles in the
app stay plain; only the banner carries the glyph.

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

Open speed alerts state the worst deviation since onset, using the latest event as a fallback for an unusable value. Fired events and notifications retain their own wording.

- Name conditions the way the user sees them: "Sol has been up to 26% slower than usual",
  not "throughput index 0.74".
- Every alert says what to do when there's something to do: "A fresh session
  would speed things up." "Turn on the collector to keep watching."
- Baseline reset is labeled **Accept as usual**. Its confirmation says
  "Sol's usual speed is now 24% lower than before."
- Sample values in mockups and tests are synthetic.
