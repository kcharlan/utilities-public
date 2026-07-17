# Multibody Gravity Lab - User Guide

This guide is for people using the simulator (not maintaining code). It starts with a quickstart and reference, then goes deep on both modes.

## Quickstart

From repo root:

```bash
cd web_games/multibody_sim
open index.html
```

In the app:

1. Pick a mode (`Screensaver` or `User setup`).
2. Use `Start/Pause` to run or stop simulation time.
3. Use `Reset` to regenerate (screensaver) or restore your saved setup (user mode).
4. Tune `Time speed` and `Time multiplier` for simulation rate.
5. Use `Trails` and `Leads` for visual history/forecast.

Quick first run:

1. Leave mode on `Screensaver`.
2. Leave `Screensaver bodies` at the default `5` (or adjust as desired).
3. Set `Time multiplier` to `8`.
4. Watch interactions; it will auto-restart at end of cycle.

---

## Quick Reference

## Main Controls

| Control | Available In | What It Does |
|---|---|---|
| `Start/Pause` | Both | Starts or pauses simulation time |
| `Reset` | Both | Screensaver: new random system. User setup: restore baseline setup |
| `Save` | Both | Screensaver: save current cycle starting state to JSON. User setup: save setup to JSON |
| `Time speed` | Both | Multiplies simulation time rate (slider) |
| `Time multiplier` | Both | Additional simulation time multiplier (number input) |
| `Gravity (G)` | Both | Strength of attraction |
| `Softening (epsilon)` | Both | Reduces extreme close-range acceleration |
| `Trails` + `Trail length` | Both | Past-path rendering |
| `Leads` + `Leads length` | Both | Predicted future path rendering |
| `Show object numbers` | Both | Toggle on-canvas body id labels on/off |
| `Screensaver bodies` | Screensaver | Number of generated bodies |
| `Singularity chance (%)` | Screensaver | Probability each generated body is a singularity |
| `Max singularities` | Screensaver | Caps singularities per generated screensaver cycle (enabled when chance > 0) |
| `Clear` | User setup | Wipe current setup completely |
| `Auto velocities` | User setup | Auto-assign velocities to current bodies |
| `Auto-assign velocities on Start` | User setup | Recompute velocities automatically when `Start` is pressed |
| `Auto velocity factor` | User setup | Scales speed used by auto-generated velocities |
| `Auto camera while paused` | User setup | Keeps camera auto-framing active while paused |
| `Camera subject` | Both | `Auto`: default camera logic. `Full`: always frame all bodies. `Follow`: lock to one body. |
| `Follow ID` + `◀/▶` | Both (when `Camera subject = Follow`) | Jump directly to an id or step previous/next across all remaining bodies |
| `Singularity` (selected body) | User setup (paused) | Toggles selected body between regular and singularity behavior |
| `Load` | User setup | Load setup from JSON file |

## Stats Overlay

The floating bottom-left readout is always visible and separate from controls:

- Row 1: `FPS`, active `Bodies`, `Sim Time`.
- Row 2: screensaver exit gates (`Quiet`, `Zoom gate`, `Near-pair lock`).

The floating bottom-right `Camera Subject` panel controls camera targeting:

- `Auto`: existing mode-aware auto camera behavior.
- `Full`: frames all current bodies (does not narrow to near-pair focus).
- `Follow`: follows a selected body id and uses the same near-pair-style framing envelope.
- `Follow ID` supports direct numeric entry plus `◀/▶` stepping through all current bodies (sorted by id).
- If the followed object merges, follow automatically transfers to the merged successor body, which keeps the dominant original object's number (highest effective mass, then tie-breakers).
- If the followed object is removed with no successor, camera subject falls back to `Auto`.
- Keyboard shortcuts (global override): `[` previous followed body, `]` next followed body, `\` return to `Auto`.

UI sections (`User setup`, `Selected body`, `Physics`) are collapsible by clicking section headers.

## Mouse + Keyboard Shortcuts (User setup mode)

These actions work only in `User setup` while paused unless noted.

| Action | Input |
|---|---|
| Create a body | Left click empty canvas |
| Select body | Left click body |
| Move body | Left drag body |
| Set velocity | Middle-button drag on body |
| Resize mass | Right drag on body |
| Change mass quickly | Mouse wheel over body |
| Delete selected body | `Delete` or `Backspace` |

Notes:

- Velocity arrows start at the body edge (not center).
- Body ids are rendered directly on each object for faster camera/object selection.
- In user setup, newly created body numbers track current canvas count (`count + 1`); deleting all bodies resets the next created body to `1`.
- If your cursor is inside the body while setting velocity, velocity can resolve to zero.
- Delete key does not remove a body while your cursor focus is inside a text/number input.

---

## Mode Deep Dive: Screensaver

`Screensaver` auto-generates systems and runs continuously.

What to expect:

- Bodies spawn with random mass/position/color.
- Velocities are auto-generated (with special low-body logic for 3-4 body cases to improve interaction likelihood).
- Camera auto-tracks bodies.
- Simulation restarts automatically at cycle end.

End/restart behavior:

1. If one body remains, simulator waits 2 seconds of real time, then resets.
2. Otherwise, restart requires all three gates:
   - quiet timer elapsed,
   - near-pair lock is off,
   - zoom boundary condition is reached.

Useful tuning for viewing:

- Increase `Time multiplier` for faster evolution.
- Lower `epsilon` for stronger close-pass deflection/capture.
- Increase `Screensaver bodies` for more chaotic behavior.
- Turn on `Trails` and `Leads` to see trajectory history and forecast.

Saving interesting screensaver scenarios:

- Use `Save` in Screensaver mode at any time during a cycle.
- The saved JSON stores that cycle's starting state (not the current in-run merged state).
- Switch to `User setup`, then use `Load` to import and edit the saved scenario.

---

## Mode Deep Dive: User Setup

`User setup` is for manual scene creation, editing, and repeatable experiments.

## Typical Workflow

1. Switch mode to `User setup`.
2. (Optional) Press `Load` and choose `multibody-test-1.json`, `multibody-test-2.json`, or `multibody-test-3.json` to start from an included sample setup.
3. Place bodies by left-clicking canvas (or edit bodies from the loaded sample).
4. Set mass and velocity per selected body.
5. Press `Start` to run.
6. Press `Reset` to return to your saved baseline.
7. Use `Save` to export scene to JSON; `Load` to import.

## Building and Editing Bodies

Create/select/move:

- Left click empty space: create new body (default mass).
- Left click body: select it.
- Left drag selected body: reposition it.

Mass controls:

- `Mass` slider in panel for selected body.
- Right-drag on a body to resize mass continuously.
- Mouse wheel over a body for fast adjustments.

Velocity controls:

- Drag velocity with middle-drag.
- Fine-tune with panel fields:
  - `Velocity X`
  - `Velocity Y`
- `Velocity (drag x10)` readout shows current selected-body velocity while editing.
- Press `Enter` in a velocity field to commit and leave edit focus.

Body type controls:

- `Singularity` checkbox in `Selected body` toggles singularity physics/visuals for the selected body.
- This toggle is editable while paused.

Delete controls:

- `Delete selected` button in panel.
- `Delete`/`Backspace` keyboard shortcut.

## Run, Reset, and Clear (Important Differences)

- `Start`: begins simulation.
- `Reset`: restores your baseline setup snapshot (positions, velocities, bodies, colors, etc.).
- `Clear`: removes everything from the board and clears baseline.

When baseline is captured:

- Baseline is captured on `Start`.
- Baseline is also restored/created during `Load`.

## Auto Velocity Features (User mode)

- `Auto-assign velocities on Start`:
  - If enabled, pressing `Start` computes velocities before run.
- `Auto velocity factor`:
  - Scales auto-generated speed.
- `Auto velocities` button:
  - Applies velocity assignment immediately to current bodies.

## Camera Behavior in User Mode

- While running, camera auto-follows bodies.
- In paused user mode, `Auto camera while paused` controls whether camera reframes while you edit.
- `Reset` also snaps camera to include bodies and velocity arrows with padding.
- `Camera subject` overrides this when set to `Full` or `Follow`; those modes stay active in both running and paused states.

## Save and Load (JSON)

`Save` writes a JSON file containing:

- bodies (position, velocity, mass, color, ids),
- baseline reset snapshot,
- selected body id,
- sidebar settings (time controls, physics settings, trails/leads settings, user mode toggles, camera subject settings).

`Load` restores that JSON into user mode and updates camera/UI accordingly.

Included sample files for testing and learning:

- `multibody-test-1.json`
- `multibody-test-2.json`
- `multibody-test-3.json`

These are ready-made User setup mode states you can load to:

- see what a valid start state looks like,
- run a scenario immediately to observe interactions,
- tweak masses/velocities/settings and learn how controls affect behavior.

Save behavior:

- Browser may show a save dialog (File System Access API).
- If not available, file is downloaded automatically using a generated filename.

Quick try flow with included samples:

1. Switch to `User setup`.
2. Click `Load` and choose `multibody-test-1.json`, `multibody-test-2.json`, or `multibody-test-3.json` from this project folder.
3. Press `Start` to see baseline behavior.
4. Pause, then modify bodies (move, mass, velocity) and toggle `Trails`/`Leads`.
5. Press `Reset` to return to the loaded baseline and compare results.

## Good Practices for Better Results

- Start with 2-5 bodies when hand-tuning.
- Use lower speeds than expected; high speed often escapes interaction.
- Reduce `epsilon` for stronger close encounters.
- Use `Leads` when tuning velocities; use `Trails` to understand what happened.
- Save setups you like before experimenting further.

## Troubleshooting

- "Delete key does nothing":
  - click on canvas/body first; ensure focus is not inside an input field.
- "Velocity drag seems weak or weird":
  - start drag outside the body edge; use panel velocity fields for precise edits.
- "Reset says no saved setup yet":
  - press `Start` once (captures baseline), or load a saved JSON.
