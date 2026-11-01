#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd -P)"
scratch_dir="$(mktemp -d "${TMPDIR:-/tmp}/health-timezone.XXXXXX")"
trap 'rm -r -- "$scratch_dir"' EXIT
cd "$scratch_dir"
cat > export.xml <<'XML'
<HealthData>
<Workout workoutActivityType="SYNTHETIC" sourceName="SYNTHETIC_A" startDate="2001-04-01 01:59:00 -0500" endDate="2001-04-01 03:02:00 -0400" duration="3"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_A" value="1" startDate="2001-04-01 01:59:00 -0500" endDate="2001-04-01 03:00:00 -0400"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_B" value="1" startDate="2001-04-01 01:59:00 -0500" endDate="2001-04-01 03:00:00 -0400"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_A" value="1" startDate="2001-04-01 03:00:00 -0400" endDate="2001-04-01 03:01:00 -0400"/>
<Record type="HKQuantityTypeIdentifierStepCount" sourceName="SYNTHETIC_A" value="42" startDate="2001-04-01 03:00:30 -0400"/>
<Record type="HKQuantityTypeIdentifierStepCount" sourceName="SYNTHETIC_B" value="42" startDate="2001-04-01 02:00:30 -0500"/>
<Record type="HKQuantityTypeIdentifierStepCount" sourceName="SYNTHETIC_A" value="42" startDate="2001-04-01 03:00:30 -0400"/>
</HealthData>
XML
UV_PYTHON_DOWNLOADS=never "$project_dir/extract_workout_stats.py"
UV_PYTHON_DOWNLOADS=never "$project_dir/exercise_bouts.py"
awk -F, 'NR==2 {if ($4 != 2 || $10 != 84 || $13 != "Workout") exit 1; found=1} END {if (!found || NR != 2) exit 1}' exercise_bouts.csv
awk -F, 'NR==2 {if ($11 != 84) exit 1; found=1} END {if (!found) exit 1}' workout_summary.csv
cat > workout_summary.csv <<'CSV'
id,type,start,end
0,SYNTHETIC_LOCAL,2001-04-01 03:00:00,2001-04-01 03:03:00
CSV
TZ=America/New_York UV_PYTHON_DOWNLOADS=never "$project_dir/exercise_bouts.py"
awk -F, 'NR==2 {if ($13 != "Workout" || $14 != "SYNTHETIC_LOCAL") exit 1; found=1} END {if (!found) exit 1}' exercise_bouts.csv
