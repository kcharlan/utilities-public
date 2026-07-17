/**
 * Rock Paper Scissors Simulator
 */

// --- Configuration & State ---
const CONFIG = {
    count: 20,
    speedMultiplier: 5,
    scaleLevel: 4,      // 1-10
    baseSize: 24,       // Size at level 1
    iconSize: 96,       // Calculated: baseSize * scaleLevel
    collisionRadius: 48, // Calculated: iconSize / 2
    passThru: true,
    saveChance: 0,
    startTime: 0 // For timer
};

const BALANCING = {
    active: false,
    handicapType: null, // The type being capped
    targetRatio: 0.33,  // Cap to 33%
    minGames: 35,
    triggerRatio: 1.5,
    minCount: 8,
    stopRatio: 1.2,
    stopDiff: 5
};

const TYPES = {
    ROCK: 0,
    PAPER: 1,
    SCISSORS: 2
};
// Rules: Key beats Value
const RULES = {
    [TYPES.ROCK]: TYPES.SCISSORS,
    [TYPES.SCISSORS]: TYPES.PAPER,
    [TYPES.PAPER]: TYPES.ROCK
};

const ASSETS = {
    [TYPES.ROCK]: { src: 'rock.png', img: null },
    [TYPES.PAPER]: { src: 'paper.png', img: null },
    [TYPES.SCISSORS]: { src: 'scissors.png', img: null },
};

let canvas, ctx;
let items = [];
let animationId;
let isRunning = false;
let width, height;

// --- Elements ---
const restartBtn = document.getElementById('restartBtn');
const countInput = document.getElementById('countInput');
const speedInput = document.getElementById('speedInput');
const speedValue = document.getElementById('speedValue');
const sizeRange = document.getElementById('sizeRange');
const sizeInput = document.getElementById('sizeInput');
const themeSelect = document.getElementById('themeSelect');
const passThruCheck = document.getElementById('passThruCheck');
const saveInput = document.getElementById('saveInput');
const timerEl = document.getElementById('timer');
const handicapEl = document.getElementById('handicapIndicator');
const stats = {
    rock: document.getElementById('rockCount'),
    paper: document.getElementById('paperCount'),
    scissors: document.getElementById('scissorsCount')
};
const winList = document.getElementById('winsList');
const winStats = {
    [TYPES.ROCK]: document.getElementById('rockWins'),
    [TYPES.PAPER]: document.getElementById('paperWins'),
    [TYPES.SCISSORS]: document.getElementById('scissorsWins')
};

// --- Win State ---
let winCounts = {
    [TYPES.ROCK]: 0,
    [TYPES.PAPER]: 0,
    [TYPES.SCISSORS]: 0
};
let restartTimeoutId = null;

// --- Initialization ---
async function init() {
    canvas = document.getElementById('simCanvas');
    ctx = canvas.getContext('2d');

    // --- Check System Theme ---
    applyTheme(themeSelect.value);

    // --- Event Listeners (Attach FIRST so they always work) ---
    window.addEventListener('resize', resizeCanvas);
    restartBtn.addEventListener('click', () => startSimulation(true));

    countInput.addEventListener('change', () => {
        let val = parseInt(countInput.value);
        if (val < 2) val = 2;
        if (val > 200) val = 200;
        countInput.value = val;
        CONFIG.count = val;
    });

    speedInput.addEventListener('input', () => {
        CONFIG.speedMultiplier = parseInt(speedInput.value);
        speedValue.textContent = CONFIG.speedMultiplier;
        updateSpeed();
    });

    // Size Inputs
    const handleSizeChange = (val) => {
        let v = parseInt(val);
        if (v < 1) v = 1;
        if (v > 10) v = 10;
        CONFIG.scaleLevel = v;
        sizeRange.value = v;
        sizeInput.value = v;
        updateSize();
    };

    sizeRange.addEventListener('input', (e) => handleSizeChange(e.target.value));
    sizeInput.addEventListener('change', (e) => handleSizeChange(e.target.value));

    themeSelect.addEventListener('change', (e) => applyTheme(e.target.value));

    passThruCheck.addEventListener('change', () => {
        CONFIG.passThru = passThruCheck.checked;
    });

    saveInput.addEventListener('change', () => {
        let val = parseInt(saveInput.value);
        if (val < 0) val = 0;
        if (val > 100) val = 100;
        saveInput.value = val;
        CONFIG.saveChance = val;
    });

    // --- Load Images ---
    // Note: Local file security restrictions prevent pixel manipulation (getImageData)
    // without a web server. We try-catch to gracefully fallback if it fails.
    try {
        await Promise.all(Object.values(ASSETS).map(asset => {
            return new Promise((resolve, reject) => {
                const img = new Image();
                img.src = asset.src;
                img.onload = () => {
                    asset.img = img;
                    resolve();
                };
                img.onerror = (e) => {
                    console.error("Failed to load image:", asset.src, e);
                    resolve();
                };
            });
        }));
    } catch (e) {
        console.error("Image loading error", e);
    }

    // Initial Setup
    resizeCanvas();
    startSimulation(true);
}

function updateSpeed() {
    items.forEach(item => {
        const currentSpeed = Math.sqrt(item.vx * item.vx + item.vy * item.vy);
        if (currentSpeed === 0) return;
        // We want base speed ~ 1-2 pixels/frame * multiplier?
        // Let's say max speed is multiplier * 0.5
        const targetSpeed = (CONFIG.speedMultiplier * 0.5) + 0.5; // Ensure non-zero
        const scale = targetSpeed / currentSpeed;
        item.vx *= scale;
        item.vy *= scale;
    });
}

function updateSize() {
    // Target: Level 10 should be 6x base size.
    // Formula: base * (1 + log10(scale) * 5)
    // Level 1: 1 + 0 = 1x (24px)
    // Level 10: 1 + 1*5 = 6x (144px)
    CONFIG.iconSize = CONFIG.baseSize * (1 + Math.log10(CONFIG.scaleLevel) * 5);
    CONFIG.collisionRadius = CONFIG.iconSize / 2;

    // Update existing items
    items.forEach(item => {
        item.radius = CONFIG.collisionRadius;
    });
    // Re-check bounds immediately in case they grew into a wall
    resizeCanvas();
}

function resizeCanvas() {
    width = canvas.parentElement.clientWidth;
    height = canvas.parentElement.clientHeight;
    // Handle High DPI
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    // Bounds check immediately to prevent items stuck outside
    if (items.length > 0) {
        items.forEach(item => {
            item.x = Math.min(Math.max(item.x, CONFIG.collisionRadius), width - CONFIG.collisionRadius);
            item.y = Math.min(Math.max(item.y, CONFIG.collisionRadius), height - CONFIG.collisionRadius);
        });
    }
}

function applyTheme(theme) {
    document.body.classList.remove('light-theme', 'dark-theme');
    if (theme === 'light') document.body.classList.add('light-theme');
    if (theme === 'dark') document.body.classList.add('dark-theme');
}

// --- Game Logic ---

class Item {
    constructor(type, bounds) {
        this.radius = CONFIG.collisionRadius;
        this.type = type;
        this.inverted = false; // For visual effect on "Saved" items
        this.conversionCount = 0; // "Kill Count"

        // Use provided bounds or default to full screen (with radius padding)
        const minX = (bounds?.minX ?? 0) + this.radius;
        const maxX = (bounds?.maxX ?? width) - this.radius;
        const minY = (bounds?.minY ?? 0) + this.radius;
        const maxY = (bounds?.maxY ?? height) - this.radius;

        // Random Position within bounds
        this.x = Math.random() * (maxX - minX) + minX;
        this.y = Math.random() * (maxY - minY) + minY;

        // Safety clamp just in case bounds were too tight
        this.x = Math.min(Math.max(this.x, this.radius), width - this.radius);
        this.y = Math.min(Math.max(this.y, this.radius), height - this.radius);

        // Random Direction
        const angle = Math.random() * Math.PI * 2;
        const speed = (CONFIG.speedMultiplier * 0.5) + 0.5;
        this.vx = Math.cos(angle) * speed;
        this.vy = Math.sin(angle) * speed;

        // Cooldown to prevent double-processing collisions
        this.cooldown = 0;
    }

    draw() {
        // Apply filter if inverted
        if (this.inverted) {
            ctx.filter = 'invert(1) hue-rotate(180deg)'; // Invert + shift hue for distinct look
        }

        const img = ASSETS[this.type].img;
        const size = CONFIG.iconSize;

        if (img) {
            // Draw centered
            ctx.drawImage(img, this.x - size / 2, this.y - size / 2, size, size);
        } else {
            // Fallback
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
            ctx.fillStyle = this.getColor();
            ctx.fill();
        }

        // Reset filter
        if (this.inverted) {
            ctx.filter = 'none';
        }

        // Draw Conversion Count
        ctx.fillStyle = '#000';
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 3;
        ctx.font = `bold ${Math.max(12, size * 0.4)}px sans-serif`; // Scale with size
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        const text = this.conversionCount.toString();
        ctx.strokeText(text, this.x, this.y);
        ctx.fillText(text, this.x, this.y);
    }

    getColor() {
        switch (this.type) {
            case TYPES.ROCK: return '#888';
            case TYPES.PAPER: return '#eee';
            case TYPES.SCISSORS: return '#f00';
        }
    }

    move() {
        this.x += this.vx;
        this.y += this.vy;

        // Wall Bouncing
        if (this.x - this.radius < 0) {
            this.x = this.radius;
            this.vx *= -1;
        } else if (this.x + this.radius > width) {
            this.x = width - this.radius;
            this.vx *= -1;
        }

        if (this.y - this.radius < 0) {
            this.y = this.radius;
            this.vy *= -1;
        } else if (this.y + this.radius > height) {
            this.y = height - this.radius;
            this.vy *= -1;
        }

        if (this.cooldown > 0) this.cooldown--;
    }
}

function startSimulation(resetWins = false) {
    if (restartTimeoutId) {
        clearTimeout(restartTimeoutId);
        restartTimeoutId = null;
    }

    isRunning = true;

    // Only reset start time if manually resetting or if it's the first run
    if (resetWins || CONFIG.startTime === 0) {
        CONFIG.startTime = Date.now();
    }

    items = [];
    CONFIG.count = parseInt(countInput.value);
    CONFIG.speedMultiplier = parseInt(speedInput.value);

    // Reset Wins if requested (Manual Restart)
    if (resetWins) {
        winCounts[TYPES.ROCK] = 0;
        winCounts[TYPES.PAPER] = 0;
        winCounts[TYPES.SCISSORS] = 0;
        updateWinUI();
    }

    // Distribution Logic: Min 15% per type
    const minPerType = Math.floor(CONFIG.count * 0.15);
    const typesPool = [];

    // Add minimums
    for (let i = 0; i < minPerType; i++) {
        typesPool.push(TYPES.ROCK);
        typesPool.push(TYPES.PAPER);
        typesPool.push(TYPES.SCISSORS);
    }

    // Fill remainder randomly
    while (typesPool.length < CONFIG.count) {
        typesPool.push(Math.floor(Math.random() * 3));
    }

    // Shuffle pool (Fisher-Yates)
    for (let i = typesPool.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [typesPool[i], typesPool[j]] = [typesPool[j], typesPool[i]];
    }

    // Quadrant Definition (TL, TR, BL, BR)
    const midX = width / 2;
    const midY = height / 2;
    const quadrants = [
        { minX: 0, maxX: midX, minY: 0, maxY: midY },       // TL
        { minX: midX, maxX: width, minY: 0, maxY: midY },   // TR
        { minX: 0, maxX: midX, minY: midY, maxY: height },  // BL
        { minX: midX, maxX: width, minY: midY, maxY: height } // BR
    ];

    // Track items per type to offset their starting quadrant
    // This ensures Rock 1 goes to Q1, Rock 2 to Q2... 
    // AND Paper 1 goes to Q2, Paper 2 to Q3... prevents type clumping in one quadrant.
    const typeDistribution = {
        [TYPES.ROCK]: 0,
        [TYPES.PAPER]: 1, // Offset start
        [TYPES.SCISSORS]: 2 // Offset start
    };

    for (let i = 0; i < CONFIG.count; i++) {
        const type = typesPool[i];

        // Pick quadrant round-robin style for this type
        const quadIndex = (typeDistribution[type]++) % 4;
        const bounds = quadrants[quadIndex];

        items.push(new Item(type, bounds));
    }

    if (animationId) cancelAnimationFrame(animationId);
    loop();
}

function loop() {
    if (!isRunning) return;

    ctx.clearRect(0, 0, width, height);

    // Move & Wall Collisions
    items.forEach(item => {
        item.move();
    });

    // Object Collisions
    // Naive O(N^2) check. Given N <= 200, this is negligible logic time (40k checks max).
    for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
            checkCollision(items[i], items[j]);
        }
    }

    // Draw
    items.forEach(item => item.draw());

    // Stats & End Condition
    // Stats & End Condition
    updateStats();
    updateTimer();

    animationId = requestAnimationFrame(loop);
}

function updateTimer() {
    if (!isRunning) return;
    const elapsed = Math.floor((Date.now() - CONFIG.startTime) / 1000);
    const m = Math.floor(elapsed / 60).toString().padStart(2, '0');
    const s = (elapsed % 60).toString().padStart(2, '0');
    timerEl.textContent = `Time: ${m}:${s}`;
}

function analyzeBalance() {
    const totalGames = winCounts[TYPES.ROCK] + winCounts[TYPES.PAPER] + winCounts[TYPES.SCISSORS];
    if (totalGames < BALANCING.minGames) return;

    const counts = [
        { type: TYPES.ROCK, val: winCounts[TYPES.ROCK] },
        { type: TYPES.PAPER, val: winCounts[TYPES.PAPER] },
        { type: TYPES.SCISSORS, val: winCounts[TYPES.SCISSORS] }
    ];
    counts.sort((a, b) => b.val - a.val);
    const max = counts[0];
    const min = counts[2];

    // Check Trigger
    if (!BALANCING.active) {
        // Threshold: Larger of (Min * 1.5) OR (Min + 8)
        const threshold = Math.max(min.val * BALANCING.triggerRatio, min.val + BALANCING.minCount);

        if (min.val > 0 && max.val > threshold) {
            console.log(`Balancing Triggered: Capping ${Object.keys(TYPES).find(k => TYPES[k] === max.type)}`);
            BALANCING.active = true;
            BALANCING.handicapType = max.type;
        }
    } else {
        // Check Stop
        // Stop Threshold: Larger of (Min * 1.2) OR (Min + 5)
        const stopThreshold = Math.max(min.val * BALANCING.stopRatio, min.val + BALANCING.stopDiff);

        if (min.val > 0 && max.val <= stopThreshold) {
            console.log("Balancing Disabled: Ratios restored.");
            BALANCING.active = false;
            BALANCING.handicapType = null;
        }
        // If the current handicap type is no longer the winner, switch it? 
        if (max.type !== BALANCING.handicapType) {
            BALANCING.handicapType = max.type;
        }
    }

    // Update Indicator UI
    if (BALANCING.active && BALANCING.handicapType !== null) {
        const typeName = Object.keys(TYPES).find(k => TYPES[k] === BALANCING.handicapType);
        handicapEl.textContent = `Handicap: ${typeName}`;
        handicapEl.style.display = 'inline';
    } else {
        handicapEl.style.display = 'none';
    }
}

function checkCollision(p1, p2) {
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < p1.radius + p2.radius) {

        // Pass Thru Check
        if (p1.type === p2.type && CONFIG.passThru) {
            return; // Ignore collision
        }

        // Collision Detected

        // 1. Resolve Overlap (push apart)
        const overlap = (p1.radius + p2.radius - dist) / 2;
        const nx = dx / dist; // Normal X
        const ny = dy / dist; // Normal Y

        p1.x -= nx * overlap;
        p1.y -= ny * overlap;
        p2.x += nx * overlap;
        p2.y += ny * overlap;

        // 2. Resolve Velocity (Elastic Collision)
        // Normal component of velocities
        const v1n = p1.vx * nx + p1.vy * ny;
        const v2n = p2.vx * nx + p2.vy * ny;

        // Tangent component (unchanged)
        const tx = -ny;
        const ty = nx;
        const v1t = p1.vx * tx + p1.vy * ty;
        const v2t = p2.vx * tx + p2.vy * ty;

        // New normal velocities (swap for equal mass elastic)
        const v1nFinal = v2n;
        const v2nFinal = v1n;

        // Convert back to x,y
        p1.vx = v1nFinal * nx + v1t * tx;
        p1.vy = v1nFinal * ny + v1t * ty;
        p2.vx = v2nFinal * nx + v2t * tx;
        p2.vy = v2nFinal * ny + v2t * ty;

        // 3. Apply Game Rules & Saving Fhrow
        if (p1.type !== p2.type) {
            let winner = null;
            let loser = null;

            if (RULES[p1.type] === p2.type) {
                winner = p1;
                loser = p2;
            } else if (RULES[p2.type] === p1.type) {
                winner = p2;
                loser = p1;
            }

            if (winner && loser) {
                // Check Saving Throw
                const roll = Math.floor(Math.random() * 100) + 1; // 1-100
                if (CONFIG.saveChance && roll <= CONFIG.saveChance) {
                    // SAVED! Winner becomes Loser's type (Reversal)
                    winner.type = loser.type;
                    winner.inverted = true; // Visual marker
                    winner.conversionCount = 0; // Reset count on conversion
                    loser.conversionCount++; // Loser technically "converted" the winner
                } else {
                    // Normal conversion logic

                    // Check Balancing Cap
                    // If Winner is the Handicap Type AND they are already over the cap...
                    let allowed = true;
                    if (BALANCING.active && winner.type === BALANCING.handicapType) {
                        const typeCount = items.filter(i => i.type === winner.type).length;
                        if (typeCount >= items.length * BALANCING.targetRatio) {
                            allowed = false;
                        }
                    }

                    if (allowed) {
                        loser.type = winner.type;
                        loser.inverted = false; // Reset if it was inverted
                        loser.conversionCount = 0; // Reset count on conversion
                        winner.conversionCount++; // Winner converted someone
                    } else {
                        // Cap Hit! Loser becomes Random NON-Winner type
                        const possibleTypes = Object.values(TYPES).filter(t => t !== winner.type);
                        const newType = possibleTypes[Math.floor(Math.random() * possibleTypes.length)];
                        loser.type = newType;
                        loser.inverted = false;
                        loser.conversionCount = 0;
                        // Winner gets a point for removing a threat, even if not recruiting? 
                        // Let's count it to keep mechanics consistent (winner won).
                        winner.conversionCount++;
                    }
                }
            }
        }
    }
}

function updateStats() {
    let counts = { [TYPES.ROCK]: 0, [TYPES.PAPER]: 0, [TYPES.SCISSORS]: 0 };
    items.forEach(item => counts[item.type]++);

    stats.rock.textContent = `Rock: ${counts[TYPES.ROCK]}`;
    stats.paper.textContent = `Paper: ${counts[TYPES.PAPER]}`;
    stats.scissors.textContent = `Scissors: ${counts[TYPES.SCISSORS]}`;

    // End Condition
    const activeTypes = Object.values(counts).filter(c => c > 0).length;
    if (activeTypes === 1 && items.length > 0) {
        // Game Over - Stop Simulation
        isRunning = false;

        const winnerType = items[0].type;

        // Increment Win
        winCounts[winnerType]++;
        analyzeBalance();
        updateWinUI();

        // Draw one last frame to show final state clearly
        ctx.clearRect(0, 0, width, height);
        items.forEach(item => item.draw());

        // Overlay?
        ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
        ctx.fillRect(0, 0, width, height);

        // Highlight MVPs (Highest Conversion Count)
        const maxKills = Math.max(...items.map(i => i.conversionCount));
        if (maxKills > 0) {
            const mvps = items.filter(i => i.conversionCount === maxKills);
            if (mvps.length <= 3) {
                mvps.forEach(mvp => {
                    ctx.save();
                    // Gold outer glow
                    ctx.shadowColor = '#FFD700';
                    ctx.shadowBlur = 30;
                    // Redraw item on top of overlay
                    mvp.draw();
                    ctx.restore();
                });
            }
        }

        ctx.fillStyle = '#fff';
        ctx.font = 'bold 48px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        let winnerText = "DRAW";
        if (winnerType === TYPES.ROCK) winnerText = "ROCK WINS!";
        if (winnerType === TYPES.PAPER) winnerText = "PAPER WINS!";
        if (winnerType === TYPES.SCISSORS) winnerText = "SCISSORS WINS!";

        ctx.fillText(winnerText, width / 2, height / 2);

        // Auto-Restart
        // Scale delay with speed: Speed 5 = 2000ms. Inverse relationship.
        // Delay = 10000 / Speed
        const delay = 10000 / CONFIG.speedMultiplier;

        restartTimeoutId = setTimeout(() => {
            startSimulation(false); // don't reset wins
        }, delay);
    }
}

function updateWinUI() {
    // Update Text
    winStats[TYPES.ROCK].textContent = `Rock: ${winCounts[TYPES.ROCK]}`;
    winStats[TYPES.PAPER].textContent = `Paper: ${winCounts[TYPES.PAPER]}`;
    winStats[TYPES.SCISSORS].textContent = `Scissors: ${winCounts[TYPES.SCISSORS]}`;

    // Sorting
    const sortedStats = [
        { type: TYPES.ROCK, count: winCounts[TYPES.ROCK], el: winStats[TYPES.ROCK] },
        { type: TYPES.PAPER, count: winCounts[TYPES.PAPER], el: winStats[TYPES.PAPER] },
        { type: TYPES.SCISSORS, count: winCounts[TYPES.SCISSORS], el: winStats[TYPES.SCISSORS] }
    ];

    sortedStats.sort((a, b) => {
        if (b.count !== a.count) return b.count - a.count; // High to Low
        // Alphabetical tie-break
        const names = { [TYPES.ROCK]: "Rock", [TYPES.PAPER]: "Paper", [TYPES.SCISSORS]: "Scissors" };
        return names[a.type].localeCompare(names[b.type]);
    });

    // Re-append in order (this moves them in DOM)
    sortedStats.forEach(item => winList.appendChild(item.el));
}

// Start
init();
