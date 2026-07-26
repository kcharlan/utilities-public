# Gorilla.BAS Reimagined — Delivered Product Reference

This document records the product behavior and design boundaries represented by the current single-file implementation. It is a reference, not an implementation plan or backlog.

## 1. Product Summary
**Project Name:** Gorilla.BAS Web (Reimagined)
**Format:** Single-file HTML application (no external assets or build steps).
**Tech Stack:** HTML5 Canvas, CSS3, Vanilla JavaScript (ES6+).

**Concept:**
A modern, feature-rich artillery game inspired by QBasic Gorilla.BAS but significantly evolved. While it pays homage to the original concept of two gorillas throwing exploding bananas, the implementation features fluid canvas-based rendering, particle physics, a modern UI, simultaneous "Counterfire" turns, and an arcade progression mode. It is not a direct port but a spiritual successor designed for modern browsers.

## 2. Core Gameplay
### 2.1 Mechanics
- **Artillery Combat:** Players control a gorilla on a procedurally generated skyline.
- **Trajectory:** Projectiles (bananas) are affected by gravity and wind. The simulation continues even when projectiles leave the visible viewport, allowing for high-arcing "mortar" shots.
- **Turn Systems:**
  - **Classic:** Sequential turns (Player 1 -> Player 2).
  - **Counterfire:** Simultaneous turn planning. Both players lock in their angle/velocity, and shots are launched together in a volley.
- **Collision:**
  - **Buildings:** Projectiles explode on impact and are removed. Terrain is not deformed.
  - **Gorillas:** A banana overlapping a gorilla's rectangular hitbox records a kill and ends the round after the volley resolves. There is no splash-damage mechanic.
- **Scoring:** Points are awarded for kills. "Aces" are tracked (first-shot hits).

### 2.2 Game Modes
1.  **Classic Mode:** Standard 1v1 (AI or Human). Infinite rounds.
2.  **Arcade Mode:** Survival challenge. Player 1 starts with 5 lives. Goal is to survive as many rounds as possible against the AI. Difficulty setting is locked in at the first firing.
3.  **Demo Mode:** AI vs AI auto-play. Pressing `Escape` returns to the last manually selected mode.

### 2.3 AI
- **Behavior:** The AI calculates trajectories based on the target's position, wind, and gravity.
- **Difficulty Levels:**
  - **Easy:** High variance/error in aiming.
  - **Medium:** Moderate precision.
  - **Hard:** High precision, often "locking in" after 1-2 ranging shots.
- **Implementation:** The AI simulates possible angle/velocity pairs to find a solution, then schedules a difficulty-dependent number of deliberately offset ranging shots before using the calculated shot.

## 3. UI & UX
### 3.1 Heads-Up Display (HUD)
- Sticky header containing:
  - Game Title.
  - Wind Indicator (Arrow + Value).
  - Scoreboard (P1 vs P2).
  - Lives Counter (visible in Arcade mode).
  - Turn Indicator / Status Message.
  - Settings Toggle.

### 3.2 Controls
- **Input Methods:**
  - Numeric inputs for Angle (0-180°) and Velocity (5-100).
  - Range sliders synced with numeric inputs for intuitive adjustment.
- **Action Buttons:** "Throw" (per player), "New Round", "Reset Scores".
- **Keyboard Shortcuts:** `Enter` to throw, `R` to restart round.

### 3.3 Settings Sidebar
A collapsible sidebar allows configuration of:
- **Game Mode:** Classic, Demo, Arcade.
- **Opponent:** Vs AI, Local 2-Player.
- **Counterfire:** Toggle simultaneous turns.
- **AI Difficulty:** Easy, Medium, Hard.
- **Physics Modifiers:** Gravity (Low/Normal/High), Wind (Off/Low/High).
- **Environment:** Skyline Variance (Low/Normal/High).
- **Audio:** Mute Toggle.

### 3.4 Feedback Systems
- **Visuals:**
  - Canvas-based rendering with gradients for sky and buildings.
  - Particle effects for explosions.
  - Procedurally drawn gorillas and bananas (no external images).
- **Audio:** Synthesized sound effects (Web Audio API) for throws, explosions, and impacts.
- **Stats:** Session-only kills, aces, and kills-by-shot-count are viewable in a modal. They are not persisted across page reloads.

## 4. Technical Architecture
### 4.1 Single-File Constraint
- All code, styles, and data must reside in `index.html`.
- No external CSS, JS, or image files.
- Sprites are drawn programmatically via Canvas API.

### 4.2 State Management
- **Global State:** Centralized `state` object tracking scores, round status, buildings, and projectiles.
- **Settings:** A separate in-memory `settings` object tracks the current options. Preferences are not persisted.
- **Game Loop:** `requestAnimationFrame` driving a fixed time-step physics simulation for stability.

### 4.3 Physics Engine
- **Integration:** Euler integration for projectile motion.
- **Collision Detection:** AABB (Axis-Aligned Bounding Box) for buildings and gorillas.
- **Simulation:** Projectiles are simulated in logical world space and may travel beyond the visible canvas until they hit a termination bound or the flight timeout.

## 5. Delivered Scope Boundaries
- Building impacts do not deform terrain.
- Multiplayer is local only; there is no network protocol or server component.
- The responsive layout supports smaller viewports, but there are no dedicated touch gestures.
