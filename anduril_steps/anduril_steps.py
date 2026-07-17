#!/usr/bin/env python3
"""
Anduril 2 stepped-ramp helper for the "1..150" brightness scale.
Includes a solver to find settings for a specific target step/level.
"""

from __future__ import annotations

import math
import argparse
import sys

MAX_LEVEL = 150


def prompt_int(name: str, lo: int, hi: int, default: int | None = None) -> int:
    prompt_str = f"{name} ({lo}-{hi})"
    if default is not None:
        prompt_str += f" [default {default}]"
    prompt_str += ": "
    
    while True:
        s = input(prompt_str).strip()
        if not s and default is not None:
            return default
            
        try:
            v = int(s)
        except ValueError:
            print("  Please enter an integer.")
            continue
        if not (lo <= v <= hi):
            print(f"  Out of range. Must be {lo}..{hi}.")
            continue
        return v


def compute_steps(floor: int, ceiling: int, n_steps: int) -> list[int]:
    if n_steps == 1:
        return [ceiling]

    step = (ceiling - floor) / (n_steps - 1)
    levels: list[int] = []
    for i in range(n_steps):
        raw = floor + i * step
        lvl = int(math.floor(raw + 0.5))  # round-half-up
        lvl = max(1, min(MAX_LEVEL, lvl))
        levels.append(lvl)

    # Ensure monotonic nondecreasing and endpoints match.
    levels[0] = floor
    levels[-1] = ceiling
    for i in range(1, len(levels)):
        if levels[i] < levels[i - 1]:
            levels[i] = levels[i - 1]

    return levels


def print_steps(levels: list[int], fet_threshold: int = 65):
    # Find first step that reaches FET region
    first_fet_idx = None
    for idx, lvl in enumerate(levels, start=1):
        if lvl >= fet_threshold:
            first_fet_idx = idx
            break

    print("-" * 40)
    for idx, lvl in enumerate(levels, start=1):
        region = "FET" if lvl >= fet_threshold else "REG"
        marker = " <-- FET starts here" if idx == first_fet_idx else ""
        print(f"Step {idx:>2}: {lvl:>3}  [{region}]{marker}")
    
    uniq = len(set(levels))
    if uniq != len(levels):
        print("\nNote: Duplicate steps detected due to rounding.")
    print("-" * 40)


def run_calculator():
    print("\n--- Standard Calculator ---")
    floor = prompt_int("Floor", 1, MAX_LEVEL)
    ceiling = prompt_int("Ceiling", 1, MAX_LEVEL)
    if ceiling < floor:
        print("Ceiling is below floor; swapping them.")
        floor, ceiling = ceiling, floor

    n_steps = prompt_int("Number of steps", 1, 50)
    
    fet_input = input("FET start threshold (default 65): ").strip()
    fet_start = int(fet_input) if fet_input.isdigit() else 65

    levels = compute_steps(floor, ceiling, n_steps)
    
    print(f"\nConfiguration: Floor={floor}, Ceiling={ceiling}, Steps={n_steps}")
    print_steps(levels, fet_start)


def run_solver(floor=None, target_step=None, target_level=None, approx_steps=None):
    print("\n--- Configuration Solver ---")
    
    # Collect inputs if not provided via args
    if floor is None:
        floor = prompt_int("Required Floor", 1, MAX_LEVEL, default=1)
    if approx_steps is None:
        approx_steps = prompt_int("Desired Total Steps", 2, 50, default=5)
    if target_step is None:
        target_step = prompt_int(f"Target Step Index (1-{approx_steps})", 1, 50, default=int(approx_steps/2)+1)
    if target_level is None:
        target_level = prompt_int("Target Level Value", floor, MAX_LEVEL, default=65)

    print(f"\nSearching for configurations where Step {target_step} is Level {target_level}...")
    print(f"Fixed Floor: {floor}")
    
    # Range of steps to check: User's guess +/- 2
    step_counts_to_check = range(max(2, approx_steps - 2), approx_steps + 3)
    
    found_any = False
    
    for n in step_counts_to_check:
        if n < target_step:
            continue
            
        current_matches = []
        # Iterate all possible ceilings
        for c in range(floor, MAX_LEVEL + 1):
            lvl_calc = compute_steps(floor, c, n)
            
            # Check the target step (index is target_step - 1)
            actual_val = lvl_calc[target_step - 1]
            
            if actual_val == target_level:
                current_matches.append(c)
        
        if current_matches:
            found_any = True
            prefix = ">>> PREFERRED COUNT" if n == approx_steps else "Alternative"
            print(f"\n{prefix}: {n} Total Steps")
            
            # Compress output if many contiguous ceilings work (e.g., 120, 121, 122)
            if len(current_matches) > 0:
                # Basic display
                for c in current_matches:
                    full_levels = compute_steps(floor, c, n)
                    # Create a string representation of levels
                    lvl_str = ", ".join(str(x) for x in full_levels)
                    print(f"  Ceiling {c:<3} -> Steps: [{lvl_str}]")

    if not found_any:
        print("\nNo exact matches found for these constraints.")
        print("Try widening the search range or slightly adjusting the Target Level.")


def main():
    parser = argparse.ArgumentParser(description="Anduril 2 Step Calculator & Solver")
    parser.add_argument("--solve", action="store_true", help="Run in solver mode")
    parser.add_argument("--calc", action="store_true", help="Run in calculator mode")
    parser.add_argument("--floor", type=int, help="Floor level (1-150)")
    parser.add_argument("--ceiling", type=int, help="Ceiling level (1-150)")
    parser.add_argument("--steps", type=int, help="Total number of steps")
    parser.add_argument("--target-step", type=int, help="Which step number to target (Solver only)")
    parser.add_argument("--target-level", type=int, help="What level the target step should be (Solver only)")
    
    args = parser.parse_args()

    # Determine mode logic
    mode = None
    if args.solve:
        mode = "solve"
    elif args.calc:
        mode = "calc"
    elif args.target_step or args.target_level:
        # Implicit solver mode if solver-specific args are present
        mode = "solve"

    # Interactive Menu if no args
    if mode is None:
        if len(sys.argv) > 1 and (args.floor or args.ceiling or args.steps):
            # If standard args provided but no explicit mode, assume calc
            mode = "calc"
        else:
            print("Anduril 2 Step Tool")
            print("1. Calculate Steps (Standard)")
            print("2. Solve for Configuration (Target a specific level)")
            choice = input("Select mode (1/2) [default 1]: ").strip()
            if choice == "2":
                mode = "solve"
            else:
                mode = "calc"

    if mode == "solve":
        run_solver(
            floor=args.floor,
            target_step=args.target_step,
            target_level=args.target_level,
            approx_steps=args.steps
        )
    else:
        # Calculator Mode
        if args.floor and args.ceiling and args.steps:
            # Non-interactive One-shot
            lvl = compute_steps(args.floor, args.ceiling, args.steps)
            print(f"Floor={args.floor}, Ceiling={args.ceiling}, Steps={args.steps}")
            print_steps(lvl)
        else:
            run_calculator()


if __name__ == "__main__":
    main()