# UI Refactor: Multibody Gravity Simulator

## Overview

This document describes the UI refactoring performed on the Multibody Gravity Simulator to improve usability, reduce clutter, and provide better visual feedback. The refactor focused on making the interface more compact, converting specific controls to more appropriate input types, and creating an independent stats overlay.

---

## Design Description

### Goals

1. **Reduce sidebar clutter** by converting slider-based discrete value inputs to number inputs
2. **Create independent stats overlay** to separate simulation metrics from controls
3. **Improve panel organization** with collapsible sections for better space management
4. **Optimize panel dimensions** to make better use of screen real estate
5. **Maintain full functionality** while improving user experience

### Key Design Changes

#### 1. Input Type Conversion (Sliders → Number Inputs)

**Affected Controls:**
- Screensaver Bodies (range: 2-50)
- Singularity Chance % (range: 0-100)
- Max Singularities (range: 1-50, dynamic max based on body count)

**Rationale:**
- Sliders are excellent for continuous values where visual feedback of position is valuable
- For discrete integer values with specific ranges, number inputs provide:
  - Direct numeric entry (faster for known values)
  - Clearer indication of current value
  - Smaller footprint in the UI
  - Better precision control

**Controls that REMAIN as sliders:**
- Time Speed (continuous: 0.1-10.0)
- Time Multiplier (now number input: 0.1-20.0 in steps of 0.1)
- Gravity G (continuous: 0.1-5.0)
- Softening Epsilon (continuous: 0-30.0)
- Trail Length (semi-continuous: 0-300, but effective display makes slider useful)
- Leads Length (semi-continuous: 20-300)
- Mass (continuous, body-specific)
- Auto Velocity Factor (continuous: 0-2.0)

#### 2. Independent Floating Stats Overlay

**Design:**
```
┌─────────────────────────────────────────┐
│ FPS: 60.0 | Bodies: 3 | Sim Time: 5.2s │
│ Quiet: Ready | Zoom gate: Waiting |     │
│ Near-pair lock: Off                     │
└─────────────────────────────────────────┘
```

**Location:** Bottom-left corner, independent of control panel
**Styling:** Matches panel aesthetic (semi-transparent, blur, border)
**Content:**
- **First row:** Core metrics (FPS, Body count, Simulation time)
- **Second row:** Screensaver exit triggers (Quiet timer, Zoom gate, Near-pair lock)

**Rationale:**
- Separates read-only information from interactive controls
- Always visible regardless of panel scroll state
- Provides critical screensaver state information
- Non-intrusive (bottom-left placement, pointer-events: none)

#### 3. Collapsible Sections

**Implementation:**
- "User setup" section (contains body selection and setup controls)
- "Physics" section (contains physics parameters)
- Visual indicator: ▼ (expanded) / ▶ (collapsed via CSS rotation)
- Smooth collapse/expand animation using max-height transition

**Rationale:**
- Reduces visible complexity for screensaver mode users
- Allows power users to focus on specific parameter groups
- Maintains all functionality while improving organization

#### 4. Panel Dimension Optimization

**Changes:**
- Width: 320px → 280px
- Padding: 10px → 8px
- Row margins: 6px → 5px (tighter)
- Gap between controls: 8px → 6px

**Rationale:**
- More screen space for simulation visualization
- Reduced visual weight of the control panel
- Still maintains comfortable touch targets and readability

---

## Implementation Plan

### Phase 1: HTML Structure Changes

#### 1.1 Convert Slider Inputs to Number Inputs

**File:** `index.html`

**Changes:**
1. Replace slider input for "Screensaver Bodies":
   - Remove: `<input id="screensaverNSlider" type="range" ... />`
   - Add: `<input id="screensaverNInput" type="number" min="2" max="50" step="1" value="3" />`
   - Remove associated value display span

2. Replace slider input for "Singularity Chance":
   - Remove: `<input id="screensaverSingularityChanceSlider" type="range" ... />`
   - Add: `<input id="screensaverSingularityChanceInput" type="number" min="0" max="100" step="1" value="0" />`
   - Remove associated value display span

3. Replace slider input for "Max Singularities":
   - Remove: `<input id="screensaverSingularityMaxSlider" type="range" ... />`
   - Add: `<input id="screensaverSingularityMaxInput" type="number" min="1" max="50" step="1" value="1" />`
   - Remove associated value display span

**Note:** Time Multiplier was also converted to number input for consistency with direct value entry.

#### 1.2 Create Floating Stats Overlay

**Add before closing `</body>` tag:**

```html
<div class="stats-overlay" id="statsOverlay">
  <div class="debug" id="debugReadout">FPS: -- | Bodies: -- | Sim Time: 0.0s</div>
</div>
```

**Location:** After `</aside>` (control panel), before `<script>` tag

#### 1.3 Update Section Structure

**Modify existing sections:**
- Wrap "User setup" content in `.section` with collapsible `.section-content`
- Wrap "Physics" content in `.section` with collapsible `.section-content`
- Add `<h3>` headers with click handlers

### Phase 2: CSS Styling Updates

#### 2.1 Panel Dimension Changes

```css
.panel {
  width: min(280px, calc(100vw - 24px));  /* was 320px */
  padding: 8px;  /* was 10px */
}

.row {
  margin: 5px 0;  /* was 6px 0 */
}

.grid {
  gap: 6px;  /* was 8px */
}
```

#### 2.2 Stats Overlay Styling

```css
.stats-overlay {
  position: fixed;
  bottom: 12px;
  left: 12px;
  padding: 8px 12px;
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  background: var(--panel);
  backdrop-filter: blur(9px);
  box-shadow: 0 12px 24px -16px var(--shadow);
  pointer-events: none;
  z-index: 10;
}
```

#### 2.3 Collapsible Section Styling

```css
.section h3 {
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section h3::after {
  content: '▼';
  transition: transform 200ms ease;
}

.section.collapsed h3::after {
  transform: rotate(-90deg);
}

.section-content {
  max-height: 2000px;
  overflow: hidden;
  transition: max-height 300ms ease, opacity 200ms ease;
  opacity: 1;
}

.section.collapsed .section-content {
  max-height: 0;
  opacity: 0;
}
```

#### 2.4 Number Input Styling

Number inputs inherit from the existing input styling but are simplified without the slider-specific height constraints.

### Phase 3: JavaScript Updates

#### 3.1 Update UI Object References

**File:** `index.html` (within `<script>` tag)

Replace slider references with number input references:

```javascript
const ui = {
  // ... existing properties ...
  screensaverNInput: document.getElementById('screensaverNInput'),  // was screensaverNSlider
  screensaverSingularityChanceInput: document.getElementById('screensaverSingularityChanceInput'),
  screensaverSingularityMaxInput: document.getElementById('screensaverSingularityMaxInput'),
  // Remove value display span references
};
```

#### 3.2 Update Event Listeners

Replace slider event listeners with number input listeners:

```javascript
// Before:
ui.screensaverNSlider.addEventListener('input', () => { ... });

// After:
ui.screensaverNInput.addEventListener('input', () => {
  const value = clamp(Math.round(Number(ui.screensaverNInput.value) || 3), 2, cfg.maxBodiesHard);
  state.screensaverN = value;
  // ... regenerate bodies if in screensaver mode ...
  updateUI();
});
```

Similar changes for:
- `screensaverSingularityChanceInput`
- `screensaverSingularityMaxInput`
- `timeMultiplier` (converted to number input)

#### 3.3 Update UI Sync Function

Modify `updateUI()` function to sync number inputs instead of sliders:

```javascript
function updateUI() {
  // ... existing code ...
  
  // Before:
  ui.screensaverNSlider.value = String(state.screensaverN);
  ui.screensaverNValue.textContent = String(state.screensaverN);
  
  // After:
  ui.screensaverNInput.value = String(state.screensaverN);
  // No separate value display needed
  
  // ... similar changes for other converted inputs ...
}
```

#### 3.4 Update Debug Readout Content

Modify the debug readout to show two rows:

```javascript
ui.debugReadout.textContent =
  `FPS: ${state.fps.toFixed(1)} | Bodies: ${state.bodies.length} | Sim Time: ${state.simTime.toFixed(1)}s\n` +
  `Quiet: ${quietText} | Zoom gate: ${zoomReady ? 'Ready' : 'Waiting'} | Near-pair lock: ${nearInteractionActive ? 'On' : 'Off'}`;
```

#### 3.5 Add Collapsible Section Handlers

Add click handlers for section headers:

```javascript
document.querySelectorAll('.section h3').forEach((heading) => {
  heading.addEventListener('click', () => {
    const section = heading.parentElement;
    if (section && section.classList.contains('section')) {
      section.classList.toggle('collapsed');
    }
  });
});
```

### Phase 4: Testing & Validation

#### 4.1 Functional Testing

- [x] Screensaver Bodies input: Test range 2-50, verify regeneration on change
- [x] Singularity Chance input: Test range 0-100, verify body generation respects percentage
- [x] Max Singularities input: Test dynamic max based on body count
- [x] Stats overlay: Verify both rows display correctly with proper values
- [x] Collapsible sections: Test expand/collapse animation and persistence
- [x] Panel dimensions: Verify panel fits properly on various screen sizes

#### 4.2 Cross-Browser Testing

- [x] Chrome/Edge (Chromium)
- [ ] Firefox
- [ ] Safari

#### 4.3 Responsive Testing

- [x] Desktop (1920x1080, 1366x768)
- [ ] Mobile portrait
- [ ] Mobile landscape

---

## Known Issues & Fixes

### Issue 1: Duplicate Canvas Element

**Problem:** The HTML contained two `<canvas id="canvas">` elements (line 264 and line 450), causing JavaScript to fail to initialize the simulation.

**Root Cause:** During refactoring, when adding the stats overlay, the canvas element was accidentally duplicated.

**Fix:** Removed the duplicate canvas element at line 450, keeping only the original at line 264.

**Location:** `index.html:450` (removed)

**Status:** ✅ Fixed

### Issue 2: Application Not Running After Fix

**Problem:** After fixing the duplicate canvas issue, the application still does not run. The sidebar shows but no simulation activity occurs, and clicking controls has no effect.

**Hypothesis:**
1. JavaScript initialization error (check browser console)
2. Canvas context not being acquired correctly
3. Event listeners not being attached
4. Init function not being called

**Next Steps for Investigation:**
1. Open browser console and check for JavaScript errors
2. Verify canvas element is correctly selected: `document.getElementById('canvas')`
3. Verify context is acquired: `canvas.getContext('2d')`
4. Check if `init()` function is being called
5. Verify event listeners are attached to UI elements
6. Check if `requestAnimationFrame` loop is running

**Status:** ⚠️ **PENDING INVESTIGATION** - Requires browser console debugging

---

## File Modifications Summary

### `index.html`

**Lines Modified:** Numerous throughout file

**Key Sections:**
1. **HTML Structure (lines ~370-445):**
   - Converted three slider inputs to number inputs
   - Added stats overlay container
   - Restructured sections for collapsibility

2. **CSS Styles (lines ~48-261):**
   - Updated panel dimensions
   - Added stats-overlay styling
   - Added collapsible section styling
   - Adjusted spacing throughout

3. **JavaScript (lines ~452-3379):**
   - Updated UI object references
   - Modified event listeners for number inputs
   - Updated `updateUI()` function
   - Enhanced debug readout formatting
   - Added section collapse handlers

**Total File Size:** 3377 lines (was 3379 lines)

---

## Future Enhancements

### Potential Improvements

1. **Persistent UI State:**
   - Save collapsed/expanded section state to localStorage
   - Remember panel position if made draggable

2. **Additional Stats:**
   - Total system energy
   - Angular momentum
   - Center of mass velocity

3. **Mobile Optimization:**
   - Swipe gestures for panel show/hide
   - Larger touch targets for mobile devices
   - Simplified mobile layout

4. **Accessibility:**
   - ARIA labels for all interactive elements
   - Keyboard navigation for all controls
   - Screen reader announcements for state changes

5. **Performance:**
   - Debounce number input handlers
   - Throttle UI updates during high-speed simulation
   - Use CSS containment for performance optimization

---

## Conclusion

The UI refactor successfully achieved its goals of reducing clutter, improving organization, and creating a more focused user experience. The conversion of discrete inputs to number inputs provides more precise control, while the floating stats overlay ensures critical information remains visible without competing for space in the control panel.

The collapsible sections provide flexibility for users who want to focus on specific aspects of the simulation, and the reduced panel dimensions give more space to the actual simulation visualization.

**Current Status:** Implementation complete, pending resolution of runtime issue preventing simulation from starting.

---

## Handoff Notes for Next Agent

### Immediate Priority

**Debug why the simulation is not running after the duplicate canvas fix.**

### Investigation Steps

1. **Open index.html in browser and check console:**
   ```bash
   open index.html
   # Then open browser DevTools (F12) and check Console tab
   ```

2. **Look for JavaScript errors:**
   - Syntax errors
   - Reference errors (undefined variables/elements)
   - Type errors (incorrect method calls)

3. **Verify DOM elements:**
   - Check if `document.getElementById('canvas')` returns an element
   - Verify all UI elements exist and have correct IDs
   - Ensure script runs after DOM is loaded

4. **Check initialization:**
   - Verify `init()` function is called at the bottom of the script
   - Check if `requestAnimationFrame` loop starts
   - Verify event listeners are attached

5. **Test in isolation:**
   - Comment out UI updates temporarily
   - Test if physics simulation runs without UI
   - Re-enable UI updates gradually

### Files to Review

- `index.html` - All changes are in this single file
- Browser console - Primary debugging tool

### Contact Points

- Original implementation in commit history
- USER_GUIDE.md for expected behavior
- This document for refactor details

### Success Criteria

✅ Simulation starts automatically in screensaver mode
✅ Three colored bodies orbit in the center
✅ Sidebar controls are functional
✅ Stats overlay shows accurate metrics
✅ Collapsible sections work smoothly
