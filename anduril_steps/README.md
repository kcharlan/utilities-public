# Anduril 2 Step Calculator & Solver

**Anduril Steps** is a utility for flashlight enthusiasts using the **Anduril 2** user interface. It helps configure the "Stepped Ramp" mode by calculating the specific brightness levels (1-150) assigned to each step.

It features two modes:
1.  **Calculator:** You provide the Floor, Ceiling, and Number of Steps; it tells you the brightness level of each step.
2.  **Solver (Reverse Lookup):** You tell it a specific goal (e.g., "I want Step 3 to be exactly Level 64"), and it calculates which Floor/Ceiling settings will achieve that.

## Prerequisites
*   Python 3 installed (`python3 --version`).
*   No external dependencies required.

## Installation
Make the script executable (optional) or run via python:
```bash
chmod +x anduril_steps.py
```

## Usage

### 1. Interactive Mode
Simply run the script without arguments to see a menu:
```bash
./anduril_steps.py
```
Follow the on-screen prompts to select a mode and enter values.

### 2. Command Line Arguments
You can use flags for quick calculations or scripting.

#### Calculator Mode
Calculate levels for a specific configuration.
```bash
# Syntax: --calc --floor [1-150] --ceiling [1-150] --steps [1-150]
./anduril_steps.py --calc --floor 1 --ceiling 130 --steps 7
```

#### Solver Mode
Find the settings required to hit a specific target.
*   **Scenario:** You want a middle mode (Step 3 of 5) to be exactly Level 65 (often the max regulated level before the FET kicks in on some drivers).
```bash
# Syntax: --solve --floor [N] --target-step [N] --target-level [N] --steps [Approx N]
./anduril_steps.py --solve --floor 1 --target-step 3 --target-level 65 --steps 5
```
*   **Output:** The script will check step counts around your target (e.g., 4, 5, 6 steps) and list every Ceiling value that results in your desired level.

## Terminology
*   **Floor:** The lowest brightness level (1-150).
*   **Ceiling:** The highest brightness level (1-150).
*   **Steps:** How many distinct levels exist between Floor and Ceiling.
*   **FET:** Field Effect Transistor. On many enthusiast lights (like Emisar/Noctigon), levels above ~65 activate the FET for direct-drive power. The script highlights these levels so you know which steps are regulated (efficient) vs. unregulated (powerful but hot).

## Math Details
Anduril 2 uses linear spacing for steps.
```python
step_size = (ceiling - floor) / (num_steps - 1)
level = floor + (step_index * step_size)
```
The result is rounded to the nearest integer. The **Solver** accounts for this rounding to find exact matches.
