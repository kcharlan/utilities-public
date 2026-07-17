## Agent Implementation Brief: Single-File N-Body Gravity Simulator (Web App)

### Objective

Create a single-page, single-file (`index.html`) web app that simulates 2D Newtonian gravity for **N bodies (N ≥ 2)** with a polished “screensaver” mode and a user-configurable setup mode. The simulation should be visually smooth, numerically stable, and easy to control.

The app must run with no build step and no external dependencies required.

---

## 1) Deliverable and Tech Constraints

### Output

- Produce **one file only**: `index.html`
- Must run by opening the file directly or via any static server.
- All JS and CSS must be embedded in the HTML.

### Language / Structure

- Use modern ES modules in `<script type="module">`.
- Write code in a TypeScript style. Since browsers do not execute TS directly in a single file, implement in:
  - JavaScript with strong JSDoc typedefs, OR
  - “already-compiled” JS output that follows TS-designed structure.
- Use Canvas 2D for rendering.
- CSS: lightweight custom CSS (Tailwind not required; do not rely on CDNs).

---

## 2) Core Features

### Two Modes

1) **Screensaver Mode (default on load)**
   
   - Defaults to **N = 3**.
   - Randomly generates masses, positions, and velocities (stable-ish).
   - Runs automatically with camera auto-pan/auto-zoom.
   - Ends and restarts automatically when bodies have left a defined “final boundary” or other termination conditions.

2) **User Setup Mode**
   
   - While paused/setup, the user can place bodies, set mass, and set velocity vectors.
   - User can either:
     - manually set velocities, or
     - enable a checkbox to auto-assign velocities on Start (“lazy mode”).
   - User presses Start to run the simulation.
   - Pause and reset controls must work.

---

## 3) Physics Model (Locked Decisions)

### Gravity

- Newtonian gravity in 2D with softening.
- Default constants:
  - `G = 1.0`
  - `epsilon = 8` (softening)

Acceleration for body \(i\) due to \(j\):

- \( \vec{a_i} += G \cdot m_j \cdot \frac{\vec{r_{ji}}}{(|r_{ji}|^2 + \epsilon^2)^{3/2}} \)

### Integrator (must use)

- **Leapfrog (Kick-Drift-Kick)** with a fixed physics timestep.
- Fixed step defaults:
  - `dt = 1 / 120`
  - Use accumulator to step multiple times per frame.
  - `maxSubsteps = 10` per animation frame (avoid spiral-of-death).

### Collisions (must use merge)

When two bodies overlap:

- Collision condition: `distance < (r1 + r2) * collisionFactor`
  - default `collisionFactor = 1.0`
- Merge into one body, conserving:
  - mass: `m = m1 + m2`
  - position: center of mass  
    `pos = (m1*p1 + m2*p2) / (m1+m2)`
  - velocity: momentum conservation  
    `vel = (m1*v1 + m2*v2) / (m1+m2)`

#### Radius from mass (locked)

- `radius = radiusScale * sqrt(mass)`
- Tune `radiusScale` so default masses are visible and not enormous.

#### Color blending on merge (locked)

- Store colors as RGB.
- On merge, mass-weight blend per channel:
  - `rgb = (m1*rgb1 + m2*rgb2) / (m1+m2)`
- This should produce intuitive mixing (red + blue → purple).

---

## 4) Rendering and Camera

### Canvas

- Full-window canvas with UI panel overlay or reserved space.
- Bodies drawn as filled circles.
- Optional: outline or subtle glow for visibility.
- Render order: trails (if enabled) then bodies.

### Trails (locked default behavior)

- Screensaver mode: trails ON by default.
- Trail length default: `trailLength = 60` points (configurable 0..300).
- Fade trail alpha with age.

### Camera (locked behavior)

Implement a camera transform with pan and zoom:

- Determine bounding box (or bounding circle) of all bodies each frame.
- Camera targets:
  - `targetCenter = boundsCenter`
  - `targetZoom` chosen so bounds fit viewport with padding
- Smoothing:
  - `cameraLerp = 0.12`
- Padding:
  - `cameraPaddingFactor = 1.3`

Mode specifics:

- Screensaver: auto camera always ON.
- User mode:
  - Setup/paused: camera fixed by default (optional “Auto camera” toggle).
  - Running: auto camera ON by default.

---

## 5) Screensaver Mode Details (Phase 1)

### Random generation (must be stable-ish)

Defaults:

- `N = 3`
- `massMin = 50`
- `massMax = 300`
- Random positions within a radius:
  - `initialPositionRadius = 200` (tune)
- Generate orbit-ish velocities:
  1) Compute `comPos` of initial positions.
  2) For each body:
     - `r = pos - comPos`
     - tangential unit vector `t = normalize(perp(r))`
     - speed estimate:
       - `v = sqrt(G * M_total / (|r| + r0)) * velFactor`
       - defaults: `r0 = 30`, `velFactor = 0.9`
     - `vel = t * v` plus small noise (optional).
  3) Remove net drift:
     - `comVel = sum(m*v)/M_total`
     - subtract from each body velocity.

### Termination and restart (locked)

Define two concepts:

- Camera view (what user sees)
- Final boundary (restart condition)

Procedure:

- During first `settleTime = 3` sim seconds, track `maxExtent` (max distance of any body from the system center or max of bounds).
- Final boundary radius:
  - `finalBoundary = maxExtent * boundaryMultiplier`
  - `boundaryMultiplier = 4`

Restart when any condition true:

- All bodies are outside `finalBoundary`, OR
- `bodies.length <= 1`, OR
- `simTime >= 90` seconds (failsafe), OR
- Any NaN/Infinity detected (hard reset)

On restart:

- Generate a new random system and start immediately.

---

## 6) User Setup Mode Details (Phase 2)

### Setup interactions (must be intuitive and reliable)

When simulation is paused (setup state):

- **Add body**: left-click empty space → create body at world position.
- **Select body**: left-click body.
- **Move body**: left-drag selected body.
- **Change mass**:
  - mouse wheel while hovering a body adjusts mass (and radius updates)
  - also show a mass slider/input in the sidebar for selected body
- **Set velocity vector** (manual):
  - middle-drag from body sets velocity (arrow direction and length)
  - right-drag from body adjusts mass/size
- **Delete body**:
  - Delete key removes selected body
  - also provide a “Delete” button in UI

### Velocity “lazy mode” (must implement)

UI elements:

- Checkbox: `Auto-assign velocities on Start` (default ON or OFF, choose one; recommended ON to help beginners)
- Slider: `Auto velocity factor` range 0..2, default 0.9
- Button: `Auto-assign velocities now`

Algorithm (same as screensaver):

- tangential orbit-ish velocities around COM, then subtract COM velocity.

### Starting and running

- “Start” begins the simulation.
- “Pause” stops simulation and returns to editable state.
- “Reset/Clear” clears all bodies and returns to setup.

Validation:

- Start should be disabled (or show warning) if `N < 2`.

---

## 7) UI Requirements

### Layout

- A control panel on left or top (agent choose), responsive.
- Must include:

Global:

- Mode toggle: Screensaver / User setup
- Start / Pause
- Reset (screensaver resets random system; user mode clears or resets to setup)
- Time speed slider: range 0.1x to 10x, default 1x
- Body count stepper (for screensaver): 2..25 (hard cap 50)

Physics controls:

- Gravity `G`: 0.1..5 (default 1)
- Softening `epsilon`: 0..30 (default 8)
- Trails toggle + trail length slider

User mode extras:

- Auto-assign velocities checkbox
- Auto velocity factor slider
- Selected body editor:
  - mass slider/input
  - velocity readout (vx, vy)
  - delete button

Debug readouts (simple text):

- FPS
- current body count
- sim time

---

## 8) Data Structures (Guidance)

Use objects like:

- `Body`:
  
  - `id`
  - `pos {x,y}`
  - `vel {x,y}`
  - `mass`
  - `radius`
  - `color {r,g,b}`
  - `trail: {x,y}[]`

- `SimState`:
  
  - `bodies: Body[]`
  - `mode: 'screensaver' | 'user'`
  - `running: boolean`
  - `G, epsilon, dt`
  - `timeSpeed`
  - `simTime`
  - `camera`
  - config values

- `Camera`:
  
  - `center, zoom`
  - `targetCenter, targetZoom`

---

## 9) Performance and Safety Requirements

- O(N^2) gravity calculation.
- Clamp UI N to 25 by default, hard cap 50.
- If `N` is high, auto reduce trail length or disable trails to maintain FPS.

Safety checks (must):

- If any body state becomes NaN/Infinity: stop and reset (screensaver: auto restart; user mode: pause and show warning).

---

## 10) Acceptance Criteria (What “Done” Means)

### Phase 1 (Screensaver)

- Loads into screensaver mode and starts immediately.
- Shows 3 bodies with stable-ish motion and trails.
- Camera keeps bodies in view, smoothly zooming/panning.
- Merge events happen and merged body color blends as specified.
- When bodies leave boundary (or timeout), it restarts automatically.

### Phase 2 (User Mode)

- User can add, move, resize (mass), delete bodies in setup.
- User can set velocity vectors manually.
- Auto-assign velocities checkbox/button works.
- Start/Pause/Reset work predictably.
- Simulation remains stable; merges behave correctly.

---

## Implementation Notes (Important)

- The deliverable must be a single HTML file.
- Do not use external libraries.
- Keep the code organized within the script via modules or sections (physics, rendering, UI, input, utilities).
- Favor correctness and stability over fancy visuals.

If anything conflicts (for example, camera vs UI layout), preserve simulation correctness and controls first.
