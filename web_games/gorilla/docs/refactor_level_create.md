# Gorilla.BAS Level Generation Refactoring Plan

## Executive Summary

This document outlines a comprehensive refactoring plan to replace the current guess-and-check level generation system with a deterministic, constraint-based approach. The new system will eliminate validation failures, increase map diversity, and produce consistent, playable levels on the first attempt.

**Key Benefits:**
- **Zero validation failures** - levels are built to satisfy constraints from the start
- **100% success rate** - no fallback to emergency layouts
- **Increased diversity** - wider variety of valid configurations
- **Better performance** - no retry loops or expensive post-validation
- **More maintainable** - clear separation of concerns and explicit constraints

---

## Current System Analysis

### How It Works Now

The current level generation follows this pattern:

1. **Generate Random Buildings** (`generateBuildings`)
   - Creates buildings with random widths (140-220) and heights (180-620)
   - Buildings are placed left-to-right until screen is filled
   - No consideration for playability during generation

2. **Place Gorillas** (`placeGorillas`)
   - Selects buildings in left/right zones for gorilla placement
   - Applies post-hoc fixes:
     - `enforceMidObstacle` - raises middle building to block direct shots
     - `applyGorillaClearanceCaps` - lowers neighbors to prevent "hugging"
     - Checks variation from previous round

3. **Validate Level** (`validateLevel`, `attemptGorillaPlacement`)
   - Runs expensive trajectory simulations to verify both gorillas can hit each other
   - Checks for direct line of sight (fails if present)
   - Validates shot angles/velocities are "reasonable"
   - Checks robustness (±1° angle, ±2% velocity tolerance)
   - Verifies 5px clearance on trajectories

4. **Retry Loop** (up to 14 attempts + 8 simple mode retries)
   - If validation fails, generate completely new buildings and retry
   - After 14 failures, tries "simple mode" (caps all buildings at 35% of screen height)
   - If all attempts fail, falls back to hardcoded emergency layout or last known good

### Critical Problems

1. **High Failure Rate**
   - Up to 22 generation attempts per round (14 normal + 8 simple)
   - Frequently falls back to emergency layout
   - Console shows validation failures on most rounds

2. **Expensive Validation**
   - Full physics simulation for every candidate level
   - Tests 4 directional shots (shooter→target, target→shooter, with variations)
   - Brute-force search through angle/velocity space (88 angles × 50 velocities = 4,400+ simulations)
   - Robustness checks add 4 more simulations per candidate shot

3. **Poor Map Diversity**
   - Emergency fallback layout gets reused frequently
   - Last-known-good layout persists across multiple rounds
   - Failed levels are completely discarded (wasted work)
   - Simple mode caps restrict creativity

4. **Post-Hoc Fixes Create New Problems**
   - `enforceMidObstacle` can make center building too tall, blocking reasonable shots
   - `applyGorillaClearanceCaps` can create artificial "valleys" in the skyline
   - Fixes don't guarantee validity - still need full validation
   - Order of fixes matters (fragile)

5. **Unpredictable Behavior**
   - Random generation means same settings produce vastly different difficulty
   - No control over shot difficulty or trajectory requirements
   - Variation checks can fail even when level is playable

---

## New Approach: Constraint-Based Generation

### Core Philosophy

**Instead of "generate and validate," we "design and construct."**

The new system works backwards from requirements:
1. Determine the desired gorilla positions and trajectory characteristics
2. Calculate the required obstacle configuration
3. Generate buildings that fulfill these constraints
4. Fill remaining space with appropriate decoration

### Key Design Principles

1. **Constraint Satisfaction** - Build levels that meet requirements by construction, not validation
2. **Separation of Concerns** - Gorilla placement, obstacles, and decoration are independent phases
3. **Explicit Design Parameters** - Clear control over difficulty, shot types, and aesthetics
4. **Deterministic Core** - Randomness only for variety, not for correctness
5. **Progressive Enhancement** - Start with minimal valid level, add complexity safely

---

## New Architecture Overview

### High-Level Flow

```
1. Design Phase
   ├─ Select gorilla zones (left/right regions)
   ├─ Determine horizontal separation (dx)
   ├─ Determine height difference (dy)
   └─ Calculate required trajectory characteristics

2. Constraint Resolution
   ├─ Calculate minimum obstacle configuration
   ├─ Determine clearance zones around gorillas
   └─ Establish valid shot corridors

3. Building Construction
   ├─ Create gorilla platforms (left/right buildings)
   ├─ Create obstacle buildings (center blockers)
   ├─ Fill gaps with supporting buildings
   └─ Apply aesthetic variation within constraints

4. Verification (optional/debug only)
   └─ Assert that constructed level meets design parameters
```

### Core Data Structures

```javascript
// Level Design Specification
const LevelSpec = {
  // Gorilla placement
  leftZone: { xMin, xMax },
  rightZone: { xMin, xMax },
  leftHeight: number,
  rightHeight: number,
  heightDifference: number,
  horizontalSeparation: number,
  
  // Trajectory requirements
  minObstacleHeight: number,
  shotCorridor: { minAngle, maxAngle, minVelocity, maxVelocity },
  clearanceZones: [{ x, width, maxHeight }, ...],
  
  // Aesthetic parameters
  variance: number,
  simpleMode: boolean,
  previousPlacement: { left, right, delta }
};

// Building Construction Plan
const BuildingPlan = {
  zones: [
    { type: 'gorilla-left', x, width, height, fixed: true },
    { type: 'obstacle', x, width, minHeight, maxHeight },
    { type: 'filler', x, width, minHeight, maxHeight },
    { type: 'gorilla-right', x, width, height, fixed: true }
  ]
};
```

---

## Detailed Implementation Plan

### Phase 1: Establish Foundation (Low Risk)

Create new functions alongside existing code without breaking anything.

#### Step 1.1: Create LevelSpec Builder

**File:** `index.html` (add after line 1369, before `regenerateRound`)

**Action:** Create `createLevelSpec` function

```javascript
function createLevelSpec(variance, previousPlacement, simpleMode) {
  // Define gorilla zones (similar to current findLeft/findRight logic)
  const edgeMargin = 220;
  const zoneBand = 320;
  
  const leftZone = {
    xMin: edgeMargin,
    xMax: edgeMargin + zoneBand
  };
  
  const rightZone = {
    xMin: world.width - edgeMargin - zoneBand,
    xMax: world.width - edgeMargin
  };
  
  // Determine gorilla positions
  const leftX = leftZone.xMin + Math.random() * (leftZone.xMax - leftZone.xMin);
  const rightX = rightZone.xMin + Math.random() * (rightZone.xMax - rightZone.xMin);
  
  // Calculate heights with variation checking
  const baseHeight = 280;
  let leftHeight = clamp(
    baseHeight * (1 + rand(-variance, variance)) + rand(60, 220),
    MIN_BUILDING_HEIGHT,
    simpleMode ? world.height * 0.35 : MAX_BUILDING_HEIGHT
  );
  let rightHeight = clamp(
    baseHeight * (1 + rand(-variance, variance)) + rand(60, 220),
    MIN_BUILDING_HEIGHT,
    simpleMode ? world.height * 0.35 : MAX_BUILDING_HEIGHT
  );
  
  // Ensure variation from previous round
  if (previousPlacement) {
    leftHeight = ensureHeightVariation(leftHeight, previousPlacement.left.height);
    rightHeight = ensureHeightVariation(rightHeight, previousPlacement.right.height);
  }
  
  const dx = Math.abs(rightX - leftX);
  const dy = Math.abs(leftHeight - rightHeight);
  
  // Calculate required obstacle height
  const tallerHeight = Math.max(leftHeight, rightHeight);
  const span = Math.floor((rightX - leftX) / 180); // Approximate building count
  const spanBoost = clamp((span - 5) * (simpleMode ? 6 : 8), 0, simpleMode ? 42 : 64);
  const minObstacleHeight = tallerHeight + 
    (simpleMode ? SIMPLE_MID_OBSTACLE_EXTRA : MID_OBSTACLE_EXTRA) + 
    spanBoost;
  
  // Calculate clearance zones
  const clearanceZones = [
    {
      x: leftX - 200,
      width: 400,
      maxHeight: leftHeight + GORILLA_NEIGHBOR_CAP,
      priority: 'high'
    },
    {
      x: rightX - 200,
      width: 400,
      maxHeight: rightHeight + GORILLA_NEIGHBOR_CAP,
      priority: 'high'
    }
  ];
  
  return {
    leftZone,
    rightZone,
    leftX,
    rightX,
    leftHeight,
    rightHeight,
    horizontalSeparation: dx,
    heightDifference: dy,
    minObstacleHeight: clamp(
      minObstacleHeight,
      simpleMode ? SIMPLE_MID_OBSTACLE_MIN : MID_OBSTACLE_MIN,
      simpleMode ? SIMPLE_MID_OBSTACLE_MAX : MAX_BUILDING_HEIGHT
    ),
    clearanceZones,
    variance,
    simpleMode
  };
}

function ensureHeightVariation(proposedHeight, previousHeight) {
  if (!previousHeight) return proposedHeight;
  
  const baseline = Math.max(previousHeight, MIN_BUILDING_HEIGHT);
  const change = Math.abs(proposedHeight - previousHeight) / baseline;
  
  if (change >= 0.2) return proposedHeight;
  
  // Force variation
  const scale = Math.random() < 0.5 ? 0.75 : 1.25;
  return clamp(
    proposedHeight * scale,
    MIN_BUILDING_HEIGHT,
    MAX_BUILDING_HEIGHT
  );
}
```

**Why this is safe:**
- No existing code calls these functions yet
- Can be tested in isolation
- No state modifications

**Testing:** Add temporary button to call `createLevelSpec` and log output to console.

---

#### Step 1.2: Create Building Zone Planner

**File:** `index.html` (add after `createLevelSpec`)

**Action:** Create `planBuildingZones` function

```javascript
function planBuildingZones(spec) {
  const zones = [];
  let currentX = 0;
  
  // Phase 1: Create gorilla platforms and obstacle
  const leftBuildingWidth = rand(140, 220);
  const rightBuildingWidth = rand(140, 220);
  
  // Determine building positions
  const leftBuildingX = spec.leftX - leftBuildingWidth / 2;
  const rightBuildingX = spec.rightX - rightBuildingWidth / 2;
  const midX = (spec.leftX + spec.rightX) / 2;
  const obstacleBuildingX = midX - rand(60, 110);
  const obstacleBuildingWidth = rand(140, 220);
  
  // Create ordered zones (left to right)
  const keyBuildings = [
    {
      type: 'gorilla-platform',
      side: 'left',
      x: leftBuildingX,
      width: leftBuildingWidth,
      height: spec.leftHeight,
      fixed: true,
      gorillaX: spec.leftX
    },
    {
      type: 'obstacle',
      x: obstacleBuildingX,
      width: obstacleBuildingWidth,
      minHeight: spec.minObstacleHeight,
      maxHeight: spec.simpleMode ? SIMPLE_MID_OBSTACLE_MAX : MAX_BUILDING_HEIGHT,
      fixed: false
    },
    {
      type: 'gorilla-platform',
      side: 'right',
      x: rightBuildingX,
      width: rightBuildingWidth,
      height: spec.rightHeight,
      fixed: true,
      gorillaX: spec.rightX
    }
  ].sort((a, b) => a.x - b.x);
  
  // Phase 2: Fill gaps with filler buildings
  const allZones = [];
  
  // Fill from 0 to first key building
  allZones.push(...createFillerZones(0, keyBuildings[0].x, spec));
  
  // Add first key building
  allZones.push(keyBuildings[0]);
  
  // Fill between key buildings
  for (let i = 1; i < keyBuildings.length; i++) {
    const prevEnd = keyBuildings[i - 1].x + keyBuildings[i - 1].width;
    const nextStart = keyBuildings[i].x;
    allZones.push(...createFillerZones(prevEnd, nextStart, spec));
    allZones.push(keyBuildings[i]);
  }
  
  // Fill from last key building to world edge
  const lastBuilding = keyBuildings[keyBuildings.length - 1];
  allZones.push(...createFillerZones(lastBuilding.x + lastBuilding.width, world.width, spec));
  
  return allZones;
}

function createFillerZones(startX, endX, spec) {
  const zones = [];
  let x = startX;
  
  while (x < endX) {
    const width = rand(140, 220);
    if (x + width > endX) {
      // Last building in this gap - adjust to fit
      const remainingWidth = endX - x;
      if (remainingWidth >= 80) {
        zones.push(createFillerZone(x, remainingWidth, spec));
      }
      break;
    }
    
    zones.push(createFillerZone(x, width, spec));
    x += width + rand(-12, 14);
  }
  
  return zones;
}

function createFillerZone(x, width, spec) {
  // Determine height constraints based on clearance zones
  let maxHeight = spec.simpleMode ? world.height * 0.35 : MAX_BUILDING_HEIGHT;
  let minHeight = MIN_BUILDING_HEIGHT;
  
  for (const clearance of spec.clearanceZones) {
    if (x + width > clearance.x && x < clearance.x + clearance.width) {
      // This filler overlaps a clearance zone
      if (clearance.priority === 'high') {
        maxHeight = Math.min(maxHeight, clearance.maxHeight);
      }
    }
  }
  
  return {
    type: 'filler',
    x,
    width,
    minHeight,
    maxHeight,
    fixed: false
  };
}
```

**Why this is safe:**
- Purely functional - returns a plan without modifying state
- Can be tested independently with different specs
- Zones can be inspected/validated before building construction

**Testing:** Call `planBuildingZones` with a spec and verify zones cover entire world width with no overlaps.

---

#### Step 1.3: Create Building Constructor

**File:** `index.html` (add after `planBuildingZones`)

**Action:** Create `constructBuildings` function

```javascript
function constructBuildings(zones, spec) {
  const buildings = [];
  const gorillaMetadata = { left: null, right: null };
  
  for (const zone of zones) {
    const building = {
      x: zone.x,
      width: zone.width,
      height: 0,
      color: `hsl(${rand(200, 230)}, ${rand(28, 46)}%, ${rand(25, 40)}%)`,
      windows: []
    };
    
    // Assign height based on zone type
    if (zone.type === 'gorilla-platform') {
      building.height = zone.height;
      
      // Store gorilla metadata
      const gorillaData = {
        x: zone.gorillaX,
        y: world.groundY - zone.height,
        buildingIndex: buildings.length,
        facing: zone.side === 'left' ? 1 : -1
      };
      gorillaMetadata[zone.side] = gorillaData;
      
    } else if (zone.type === 'obstacle') {
      // Pick height in allowed range
      const heightRange = zone.maxHeight - zone.minHeight;
      building.height = zone.minHeight + Math.random() * Math.min(heightRange, 100);
      building.height = clamp(building.height, zone.minHeight, zone.maxHeight);
      
    } else if (zone.type === 'filler') {
      // Generate height with variance, respecting constraints
      const baseHeight = 280;
      let height = clamp(
        baseHeight * (1 + rand(-spec.variance, spec.variance)) + rand(60, 220),
        zone.minHeight,
        zone.maxHeight
      );
      building.height = height;
    }
    
    buildings.push(building);
  }
  
  return {
    buildings,
    gorillas: [gorillaMetadata.left, gorillaMetadata.right]
  };
}
```

**Why this is safe:**
- Takes a plan and constructs actual buildings
- No randomness in gorilla positions (determined by plan)
- Respects all constraints from zones
- Returns data without modifying global state

**Testing:** Construct buildings from a plan and verify:
- All heights respect min/max constraints
- Gorilla buildings are at correct positions
- No gaps or overlaps

---

### Phase 2: Integration (Medium Risk)

Connect new system to existing code with feature flag.

#### Step 2.1: Create New Generation Entry Point

**File:** `index.html` (add after `constructBuildings`)

**Action:** Create `generateLevelConstraintBased` function

```javascript
function generateLevelConstraintBased(variance, previousPlacement, simpleMode) {
  // Create specification
  const spec = createLevelSpec(variance, previousPlacement, simpleMode);
  
  // Plan zones
  const zones = planBuildingZones(spec);
  
  // Construct buildings
  const { buildings, gorillas } = constructBuildings(zones, spec);
  
  // Add windows
  buildings.forEach(b => {
    b.windows = buildWindowsForBuilding(b);
  });
  
  // Calculate placement data
  const leftBuilding = buildings[gorillas[0].buildingIndex];
  const rightBuilding = buildings[gorillas[1].buildingIndex];
  
  const result = {
    gorillas,
    delta: {
      dx: spec.horizontalSeparation,
      dy: spec.heightDifference
    },
    variationSatisfied: true, // Always true by construction
    leftPlacement: {
      x: gorillas[0].x,
      y: gorillas[0].y,
      height: leftBuilding.height
    },
    rightPlacement: {
      x: gorillas[1].x,
      y: gorillas[1].y,
      height: rightBuilding.height
    }
  };
  
  return {
    ok: true,
    buildings,
    result,
    reason: 'constraint-based-generation'
  };
}
```

**Why this is safe:**
- Returns same data structure as `attemptGorillaPlacement`
- Can be swapped in with minimal changes
- Self-contained with clear boundaries

---

#### Step 2.2: Add Feature Flag

**File:** `index.html` (add after constants around line 836)

**Action:** Add feature flag constant

```javascript
const USE_CONSTRAINT_BASED_GENERATION = false; // Set to true to enable new system
```

---

#### Step 2.3: Modify Regeneration Function

**File:** `index.html` (modify `regenerateRound` around line 1386)

**Action:** Add conditional to use new system

**Find this code:**
```javascript
const placementAttempt = attemptGorillaPlacement(variance, roundGravity, roundWind);
```

**Replace with:**
```javascript
let placementAttempt;
if (USE_CONSTRAINT_BASED_GENERATION) {
  placementAttempt = generateLevelConstraintBased(variance, lastPlacement, false);
  
  // Optional: validate for debugging
  if (placementAttempt.ok) {
    const isValid = validateLevel(
      placementAttempt.buildings,
      placementAttempt.result.gorillas[0],
      placementAttempt.result.gorillas[1],
      roundGravity,
      roundWind
    );
    if (!isValid) {
      console.error('[DEBUG] Constraint-based generation produced invalid level!');
      // Fall back to old system
      placementAttempt = attemptGorillaPlacement(variance, roundGravity, roundWind);
    } else {
      console.log('[DEBUG] Constraint-based generation validated successfully');
    }
  }
} else {
  placementAttempt = attemptGorillaPlacement(variance, roundGravity, roundWind);
}
```

**Why this is safe:**
- Default is OFF - no behavior change
- Old system still available as fallback
- Can validate new system against old validation
- Easy to toggle for testing

---

### Phase 3: Testing and Refinement (Medium Risk)

Validate new system and tune parameters.

#### Step 3.1: Enable and Test

**Action:** Set `USE_CONSTRAINT_BASED_GENERATION = true`

**Testing checklist:**
1. Play 50+ rounds across all difficulty settings
2. Monitor console for validation failures
3. Check that no emergency layouts are used
4. Verify map diversity (no repeated layouts)
5. Test all wind conditions (none, low, medium, high)
6. Test all gravity settings
7. Test all variance levels (low, normal, high, chaos)
8. Test simple mode scenarios

**Expected results:**
- Zero validation failures
- Zero fallbacks to emergency layout
- First-attempt success every time
- High visual diversity in skylines

---

#### Step 3.2: Debug Common Issues

**Potential Issue 1:** Obstacle too tall, blocks all shots

**Symptom:** Validation fails with "no reasonable shots found"

**Fix:** Adjust `minObstacleHeight` calculation in `createLevelSpec`:
```javascript
// Reduce obstacle boost for wide spans
const spanBoost = clamp((span - 5) * (simpleMode ? 4 : 6), 0, simpleMode ? 30 : 50);
```

---

**Potential Issue 2:** Gorillas too close to screen edges

**Symptom:** Shots fly off-screen or feel cramped

**Fix:** Widen gorilla zones in `createLevelSpec`:
```javascript
const edgeMargin = 250; // Increased from 220
const zoneBand = 350;   // Increased from 320
```

---

**Potential Issue 3:** Clearance zones too restrictive

**Symptom:** Buildings around gorillas all look similar/flat

**Fix:** Soften clearance in `createFillerZone`:
```javascript
if (clearance.priority === 'high') {
  maxHeight = Math.min(maxHeight, clearance.maxHeight + rand(0, 40));
}
```

---

**Potential Issue 4:** Filler buildings don't match variance setting

**Symptom:** High variance looks same as low variance

**Fix:** Increase variance multiplier in `constructBuildings`:
```javascript
const varianceMultiplier = spec.simpleMode ? 0.5 : 1.2;
let height = clamp(
  baseHeight * (1 + rand(-spec.variance * varianceMultiplier, spec.variance * varianceMultiplier)) + rand(60, 220),
  zone.minHeight,
  zone.maxHeight
);
```

---

### Phase 4: Cleanup (Low Risk)

Remove old system once new one is proven.

#### Step 4.1: Remove Old Functions

**Action:** Once `USE_CONSTRAINT_BASED_GENERATION` has been `true` for extended testing (recommend 1-2 weeks of play), remove these functions:

- `attemptGorillaPlacement` (lines 1767-1837)
- `enforceMidObstacle` (lines 1839-1852) - no longer needed
- `applyGorillaClearanceCaps` (lines 1578-1596) - baked into zones
- `applyHeightVariation` (lines 1598-1605) - replaced by `ensureHeightVariation`
- `shiftRightPlacement` (lines 1607-1614) - no longer needed

**Why this is safe:**
- Functions are no longer called
- Old system logic is dead code
- Removing reduces maintenance burden

**Keep these functions** (still useful):
- `buildDeterministicEmergencyLayout` - useful for testing/debugging
- `validateLevel` - useful for assertions and debugging
- `findValidationShot` - useful for AI hint system
- `hasDirectLineOfSight` - useful for assertions

---

#### Step 4.2: Remove Feature Flag

**File:** `index.html` (modify `regenerateRound`)

**Action:** Simplify to always use new system

**Remove:**
```javascript
const USE_CONSTRAINT_BASED_GENERATION = false;
```

**Replace this:**
```javascript
let placementAttempt;
if (USE_CONSTRAINT_BASED_GENERATION) {
  // ... new system ...
} else {
  placementAttempt = attemptGorillaPlacement(variance, roundGravity, roundWind);
}
```

**With:**
```javascript
const placementAttempt = generateLevelConstraintBased(variance, lastPlacement, false);
```

---

#### Step 4.3: Simplify Error Handling

**File:** `index.html` (modify `regenerateRound` around line 1390)

**Current code:**
```javascript
if (placementAttempt.ok) {
  layout = {
    buildings: placementAttempt.buildings,
    result: placementAttempt.result
  };
  shouldPersistKnownGood = true;
} else if (lastKnownGoodLayout) {
  console.warn(`Generation failed (${placementAttempt.reason}). Reusing last known-good layout.`);
  layout = cloneLayout(lastKnownGoodLayout);
} else {
  console.warn(`Generation failed (${placementAttempt.reason}). Using deterministic emergency layout.`);
  // ... emergency layout code ...
}
```

**Simplified (since new system never fails):**
```javascript
// Constraint-based generation always succeeds
layout = {
  buildings: placementAttempt.buildings,
  result: placementAttempt.result
};
lastKnownGoodLayout = cloneLayout(layout);
```

---

### Phase 5: Enhancement (Optional)

Add features that are now easy with new architecture.

#### Step 5.1: Add Shot Difficulty Control

**Goal:** Let users choose whether they want "easy," "medium," or "hard" shots required

**Implementation:**

1. Add setting to `settings` object:
```javascript
const settings = {
  // ... existing settings ...
  shotDifficulty: 'medium' // 'easy', 'medium', 'hard'
};
```

2. Modify `createLevelSpec` to adjust obstacle height based on difficulty:
```javascript
function createLevelSpec(variance, previousPlacement, simpleMode) {
  // ... existing code ...
  
  // Adjust obstacle based on shot difficulty
  let obstacleMultiplier = 1.0;
  if (settings.shotDifficulty === 'easy') {
    obstacleMultiplier = 0.7; // Lower obstacles = easier shots
  } else if (settings.shotDifficulty === 'hard') {
    obstacleMultiplier = 1.3; // Higher obstacles = harder shots
  }
  
  const minObstacleHeight = clamp(
    (tallerHeight + (simpleMode ? SIMPLE_MID_OBSTACLE_EXTRA : MID_OBSTACLE_EXTRA) + spanBoost) * obstacleMultiplier,
    simpleMode ? SIMPLE_MID_OBSTACLE_MIN : MID_OBSTACLE_MIN,
    simpleMode ? SIMPLE_MID_OBSTACLE_MAX : MAX_BUILDING_HEIGHT
  );
  
  // ... rest of function ...
}
```

3. Add UI control in settings panel

**Benefits:**
- Players can tune challenge to their skill
- AI difficulty can be matched with shot difficulty
- Enables "puzzle mode" with very specific shot requirements

---

#### Step 5.2: Add Level Presets

**Goal:** Create handcrafted level templates that guarantee interesting scenarios

**Implementation:**

1. Define preset specifications:
```javascript
const LEVEL_PRESETS = {
  'canyon': {
    leftHeight: 450,
    rightHeight: 460,
    minObstacleHeight: 250,
    horizontalSeparation: 1200,
    description: 'Deep valley between gorillas'
  },
  'mountain': {
    leftHeight: 220,
    rightHeight: 210,
    minObstacleHeight: 650,
    horizontalSeparation: 900,
    description: 'Tall mountain in center'
  },
  'asymmetric': {
    leftHeight: 600,
    rightHeight: 250,
    minObstacleHeight: 450,
    horizontalSeparation: 1100,
    description: 'Extreme height difference'
  }
};
```

2. Modify `createLevelSpec` to accept preset:
```javascript
function createLevelSpec(variance, previousPlacement, simpleMode, preset = null) {
  if (preset) {
    // Use preset values instead of random
    return buildSpecFromPreset(preset, variance);
  }
  // ... existing random generation ...
}
```

3. Add "Daily Challenge" mode that uses same preset for all players on a given day

**Benefits:**
- Enables competitive play (everyone gets same level)
- Guarantees interesting scenarios
- Useful for tutorials/training

---

#### Step 5.3: Add Visual Themes

**Goal:** Generate buildings with cohesive visual themes (modern, retro, industrial, etc.)

**Implementation:**

1. Define color palettes:
```javascript
const BUILDING_THEMES = {
  'retro': {
    hueRange: [200, 230],
    satRange: [28, 46],
    lightRange: [25, 40]
  },
  'modern': {
    hueRange: [0, 360],
    satRange: [5, 15],
    lightRange: [15, 25]
  },
  'neon': {
    hueRange: [280, 320],
    satRange: [70, 90],
    lightRange: [35, 55]
  }
};
```

2. Apply theme in `constructBuildings`:
```javascript
const theme = BUILDING_THEMES[settings.theme || 'retro'];
building.color = `hsl(${rand(theme.hueRange[0], theme.hueRange[1])}, ${rand(theme.satRange[0], theme.satRange[1])}%, ${rand(theme.lightRange[0], theme.lightRange[1])}%)`;
```

**Benefits:**
- Increased visual variety
- Better aesthetics
- Players can customize experience

---

## Risk Mitigation

### Rollback Plan

If new system has critical bugs after Phase 3:

1. Set `USE_CONSTRAINT_BASED_GENERATION = false`
2. Old system resumes immediately
3. No data loss or state corruption
4. Debug new system offline

### Testing Strategy

**Before each phase:**
1. Create backup branch
2. Test on local copy first
3. Verify in multiple browsers
4. Check performance (no frame drops)

**During Phase 3:**
1. Monitor console for errors
2. Track success rate metrics
3. Collect player feedback
4. Compare performance to baseline

### Performance Considerations

**New system should be faster because:**
- No retry loops (1 attempt vs up to 22)
- No expensive validation (no trajectory simulation)
- No brute-force shot finding

**Measure:**
- Time per level generation (should be <5ms vs 50-200ms)
- Frame rate during generation (should be stable 60fps)
- Memory usage (should be similar)

---

## Success Criteria

The refactor is considered successful when:

1. **Zero validation failures** over 1000 generated levels
2. **Zero emergency fallbacks** over 1000 generated levels
3. **100% first-attempt success** rate
4. **High diversity**: No two consecutive levels look "too similar" (visual inspection)
5. **Performance**: Level generation completes in <10ms average
6. **Playability**: All levels have reasonable shot solutions (no "impossible" shots)
7. **Stability**: No crashes or errors over extended play sessions
8. **Variation respected**: Consecutive levels differ by at least 20% in dx and dy

---

## Timeline Estimate

**Phase 1 (Foundation):** 3-4 hours
- Writing new functions
- Unit testing each function
- Code review

**Phase 2 (Integration):** 2-3 hours
- Adding feature flag
- Wiring up new system
- Initial testing

**Phase 3 (Testing):** 4-6 hours
- Extensive gameplay testing
- Bug fixing and tuning
- Parameter adjustment

**Phase 4 (Cleanup):** 1-2 hours
- Removing old code
- Simplifying logic
- Documentation updates

**Phase 5 (Enhancement):** 2-4 hours per feature (optional)
- Shot difficulty control
- Level presets
- Visual themes

**Total (Core Refactor):** 10-15 hours
**Total (With Enhancements):** 16-27 hours

---

## Conclusion

This refactoring transforms the level generation from a probabilistic, failure-prone process to a deterministic, reliable system. By building levels that satisfy constraints from the start rather than validating random generations, we eliminate failure cases, improve performance, and enable new features that were difficult or impossible before.

The phased approach ensures we can test thoroughly at each step, roll back if needed, and maintain the existing system until the new one is proven. The result will be a more maintainable, extensible, and reliable game with better player experience.

---

## Appendix A: Function Reference

### New Functions (Core)

- `createLevelSpec(variance, previousPlacement, simpleMode)` - Creates level design specification
- `ensureHeightVariation(proposedHeight, previousHeight)` - Enforces variation between rounds
- `planBuildingZones(spec)` - Plans building zones from specification
- `createFillerZones(startX, endX, spec)` - Creates filler zones for gaps
- `createFillerZone(x, width, spec)` - Creates single filler zone with constraints
- `constructBuildings(zones, spec)` - Constructs actual buildings from zones
- `generateLevelConstraintBased(variance, previousPlacement, simpleMode)` - Main entry point

### Modified Functions

- `regenerateRound` - Calls new system instead of old

### Deprecated Functions (Remove in Phase 4)

- `attemptGorillaPlacement`
- `enforceMidObstacle`
- `applyGorillaClearanceCaps`
- `applyHeightVariation`
- `shiftRightPlacement`

### Preserved Functions (Still Useful)

- `generateBuildings` - Can be removed but harmless to keep
- `buildWindowsForBuilding` - Still needed for window decoration
- `placeGorillas` - Can be removed once deprecated
- `validateLevel` - Keep for debugging/assertions
- `findValidationShot` - Keep for AI and hints
- `hasDirectLineOfSight` - Keep for assertions/debugging
- `buildDeterministicEmergencyLayout` - Keep as ultimate fallback for debugging

---

## Appendix B: Constants Reference

### Existing Constants (Used by New System)

```javascript
world.width = 2200
world.height = 1200
world.groundY = 1100

MIN_BUILDING_HEIGHT = 180
MAX_BUILDING_HEIGHT = 780
MID_OBSTACLE_EXTRA = 96
MID_OBSTACLE_MIN = 240
SIMPLE_MID_OBSTACLE_EXTRA = 64
SIMPLE_MID_OBSTACLE_MIN = 230
SIMPLE_MID_OBSTACLE_MAX = 430
GORILLA_NEIGHBOR_CAP = 110
GORILLA_SECOND_NEIGHBOR_CAP = 160
```

### New Constants (Optional)

```javascript
GORILLA_EDGE_MARGIN = 220  // Extracted from placeGorillas
GORILLA_ZONE_BAND = 320    // Extracted from placeGorillas
MIN_BUILDING_WIDTH = 140   // Extracted from generateBuildings
MAX_BUILDING_WIDTH = 220   // Extracted from generateBuildings
BUILDING_GAP_MIN = -12     // Extracted from generateBuildings
BUILDING_GAP_MAX = 14      // Extracted from generateBuildings
```

---

## Appendix C: Data Flow Diagram

```
Input: variance, previousPlacement, simpleMode
   ↓
createLevelSpec
   ↓
LevelSpec (design parameters)
   ↓
planBuildingZones
   ↓
BuildingZones[] (spatial plan)
   ↓
constructBuildings
   ↓
{ buildings[], gorillas[] } (actual level)
   ↓
Output: { ok: true, buildings, result, reason }
```

**Key insight:** Each stage is purely functional - takes input, returns output, no side effects. This makes testing, debugging, and maintenance much easier than the current imperative, stateful approach.
