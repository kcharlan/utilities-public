# Anduril 2 Step Calculator and Solver

`anduril_steps.py` is a dependency-free command-line helper for exploring
stepped brightness ramps on the 1–150 level scale used by Anduril 2.

It has two modes:

1. **Calculator:** Given a floor, ceiling, and step count, print the levels
   produced by the script's spacing model.
2. **Solver:** Given a floor and a desired level at a particular step, search
   for ceiling and step-count combinations which produce that result.

## Requirements

- Python 3.10 or newer
- No third-party packages

The examples below assume the current directory is `anduril_steps/`. The script
is tracked as executable, so it can be run directly:

```bash
./anduril_steps.py --help
```

It can also be invoked through a compatible Python interpreter:

```bash
python3 anduril_steps.py --help
```

## Interactive use

Run the script without arguments:

```bash
./anduril_steps.py
```

The menu selects calculator or solver mode and prompts for the required values.
Interactive calculator inputs are limited to levels 1–150 and 1–50 steps. It
also prompts for the level at which output labels switch from `REG` to `FET`;
the default is 65.

## Command-line use

### Calculator

Supply all three calculator values for non-interactive output:

```bash
./anduril_steps.py \
  --calc \
  --floor 1 \
  --ceiling 130 \
  --steps 7
```

Use levels from 1 through 150, an ascending range (`floor <= ceiling`), and
1–50 steps. The command-line parser does not enforce these limits. If any of
the three values is omitted, calculator mode falls back to the interactive
prompts instead of combining flags with prompted values.

In non-interactive calculator output, levels below 65 are labeled `REG` and
levels at or above 65 are labeled `FET`.

### Solver

For example, search for configurations where step 3 is level 65, using five
steps as the preferred count:

```bash
./anduril_steps.py \
  --solve \
  --floor 1 \
  --target-step 3 \
  --target-level 65 \
  --steps 5
```

Here, `--steps` is the preferred total step count rather than a fixed value.
The solver searches that value plus and minus two, never searches fewer than
two total steps, and ignores counts smaller than `--target-step`. For each
eligible count, it tests every ceiling from the floor through 150 and prints
all exact matches. Use a floor from 1 through 150, a target level from that
floor through 150, a preferred count from 2 through 50, and a positive target
step no greater than 50. The command-line parser does not enforce these limits.
Missing solver arguments are requested interactively.

Supplying `--target-step` or `--target-level` without `--solve` also selects
solver mode. Supplying floor, ceiling, or step arguments without an explicit
mode selects calculator mode.

## Output labels

- **Floor:** Lowest level in the calculated ramp.
- **Ceiling:** Highest level in the calculated ramp.
- **Steps:** Number of calculated positions, including the endpoints.
- **REG / FET:** Labels based only on the script's threshold. They do not
  inspect the flashlight or determine its driver topology.

The point where a driver changes from regulated output to FET or another
channel is hardware- and firmware-specific. Treat the default threshold of 65
as a display aid, not a universal Anduril boundary.

## Calculation model and firmware compatibility

For two or more steps, the script computes each raw level with linear spacing:

```text
raw_level = floor + step_index * (ceiling - floor) / (number_of_steps - 1)
```

It then rounds halves upward with `floor(raw_level + 0.5)`, clamps the result
to 1–150, forces the first and last values to the requested endpoints, and
ensures the sequence does not decrease. Rounding can produce duplicate levels.
With one requested step, the script returns the ceiling.

This is the model implemented by this utility; it is not an exact emulator of
every Anduril 2 build. In particular, the
[current upstream ramp code](https://github.com/ToyKeeper/anduril/blob/trunk/ui/anduril/ramp-mode.c)
uses integer division when generating multi-step levels and uses the midpoint
of floor and ceiling for a one-step ramp. Firmware versions and flashlight
configurations can also vary. Verify important results against the source or
behavior of the firmware installed on the target light.
