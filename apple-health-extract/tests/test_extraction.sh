#!/bin/bash
set -euo pipefail
project_dir="${1:-$(cd "$(dirname "$0")/.." && pwd -P)}"
case "$project_dir" in /*) ;; *) echo 'Project directory must be absolute' >&2; exit 2;; esac
scratch_dir="$(mktemp -d "${TMPDIR:-/tmp}/apple-health-extraction-test.XXXXXX")"
trap 'rm -r -- "${scratch_dir:?}"' EXIT
cd "$scratch_dir"
cat > export.xml <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
<Workout workoutActivityType="INVENTED_WORKOUT" sourceName="SYNTHETIC_DEVICE" startDate="2001-01-01 10:00:00 -0500" endDate="2001-01-01 10:10:00 -0500" duration="10"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_SOURCE" sourceVersion="0" device="SYNTHETIC_DEVICE" unit="min" value="1" startDate="2001-01-01 10:01:00 -0500" endDate="2001-01-01 10:02:00 -0500"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_SOURCE" sourceVersion="0" device="SYNTHETIC_DEVICE" unit="min" value="1" startDate="2001-01-01 11:01:00 -0500" endDate="2001-01-01 11:02:00 -0500"/>
<Record type="HKQuantityTypeIdentifierHeartRate" value="100" startDate="2001-01-01 10:01:30 -0500"/>
<Record type="HKQuantityTypeIdentifierHeartRate" value="120" startDate="2001-01-01 11:01:30 -0500"/>
<Record type="HKQuantityTypeIdentifierStepCount" value="42" startDate="2001-01-01 10:01:30 -0500"/>
<Record type="HKQuantityTypeIdentifierStepCount" value="24" startDate="2001-01-01 11:01:30 -0500"/>
<Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" unit="km" value="1" startDate="2001-01-01 10:01:30 -0500"/>
<Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" unit="mi" value="1" startDate="2001-01-01 11:01:30 -0500"/>
<Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" unit="m" value="500" startDate="2001-01-01 11:01:40 -0500"/>
<Record type="HKQuantityTypeIdentifierActiveEnergyBurned" value="7" startDate="2001-01-01 10:01:30 -0500"/>
<Record type="HKQuantityTypeIdentifierActiveEnergyBurned" value="3" startDate="2001-01-01 11:01:30 -0500"/>
</HealthData>
XML
UV_PYTHON_DOWNLOADS=never "$project_dir/extract_workout_stats.py"
if ! UV_PYTHON_DOWNLOADS=never "$project_dir/exercise_bouts.py" 2> bouts.stderr; then
    cat bouts.stderr >&2
    exit 1
fi
if grep -q 'Warning' bouts.stderr; then
    cat bouts.stderr >&2
    exit 1
fi
cat > expected-summary.csv <<'CSV'
id,type,start,end,duration_min,device,hr_samples,hr_avg,hr_min,hr_max,steps_total,distance_km,calories_kcal
0,INVENTED_WORKOUT,2001-01-01 15:00:00+00:00,2001-01-01 15:10:00+00:00,10.0,SYNTHETIC_DEVICE,1,100.0,100.0,100.0,42.0,1.0,7.0
CSV
cat > expected-detail.csv <<'CSV'
workout_id,workout_start,workout_type,timestamp,heart_rate_bpm
0,2001-01-01 15:00:00+00:00,INVENTED_WORKOUT,2001-01-01 15:01:30+00:00,100.0
CSV
cat > expected-bouts.csv <<'CSV'
bout_id,bout_start,bout_end,duration_min,sourceName,device,first_min_start,last_min_end,avg_heart_rate,steps,calories,distance_km,type,workout_type
0,2001-01-01 15:01:00+00:00,2001-01-01 15:02:00+00:00,1,SYNTHETIC_SOURCE,SYNTHETIC_DEVICE,2001-01-01 10:01:00 -0500,2001-01-01 10:02:00 -0500,100.0,42.0,7.0,1.0,Workout,INVENTED_WORKOUT
1,2001-01-01 16:01:00+00:00,2001-01-01 16:02:00+00:00,1,SYNTHETIC_SOURCE,SYNTHETIC_DEVICE,2001-01-01 11:01:00 -0500,2001-01-01 11:02:00 -0500,120.0,24.0,3.0,2.109344,Incidental,
CSV
# Both parsers reject unknown and missing distance units, even in a workout window.
cp export.xml valid.xml
for replacement in 'unit="furlong"' ''; do
    sed "s/unit=\"km\"/$replacement/" valid.xml > export.xml
    for script in extract_workout_stats.py exercise_bouts.py; do
        if UV_PYTHON_DOWNLOADS=never "$project_dir/$script" > invalid.stdout 2> invalid.stderr; then
            echo "$script accepted an unsupported distance unit: $replacement" >&2
            exit 1
        fi
        if ! grep -q 'Unsupported distance unit' invalid.stderr; then
            cat invalid.stderr >&2
            exit 1
        fi
    done
done
diff -u expected-summary.csv workout_summary.csv
diff -u expected-detail.csv workout_heart_rate_detail.csv
diff -u expected-bouts.csv exercise_bouts.csv

mkdir "$scratch_dir/no-metrics"
cd "$scratch_dir/no-metrics"
cat > export.xml <<'XML'
<HealthData>
<Workout workoutActivityType="INVENTED_WORKOUT" sourceName="SYNTHETIC_DEVICE" startDate="2001-01-01 10:00:00 -0500" endDate="2001-01-01 10:10:00 -0500" duration="10"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_SOURCE" device="SYNTHETIC_DEVICE" unit="min" value="1" startDate="2001-01-01 10:01:00 -0500" endDate="2001-01-01 10:02:00 -0500"/>
</HealthData>
XML
UV_PYTHON_DOWNLOADS=never "$project_dir/extract_workout_stats.py"
UV_PYTHON_DOWNLOADS=never "$project_dir/exercise_bouts.py"
cat > expected-summary.csv <<'CSV'
id,type,start,end,duration_min,device,hr_samples,hr_avg,hr_min,hr_max,steps_total,distance_km,calories_kcal
0,INVENTED_WORKOUT,2001-01-01 15:00:00+00:00,2001-01-01 15:10:00+00:00,10.0,SYNTHETIC_DEVICE,0,,,,,,
CSV
diff -u expected-summary.csv workout_summary.csv

mkdir "$scratch_dir/no-workouts"
cd "$scratch_dir/no-workouts"
cat > export.xml <<'XML'
<HealthData>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_SOURCE" device="SYNTHETIC_DEVICE" unit="min" value="1" startDate="2001-01-01 10:01:00 -0500" endDate="2001-01-01 10:02:00 -0500"/>
<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="SYNTHETIC_SOURCE" value="100" startDate="2001-01-01 10:01:30 -0500"/>
</HealthData>
XML
UV_PYTHON_DOWNLOADS=never "$project_dir/extract_workout_stats.py"
UV_PYTHON_DOWNLOADS=never "$project_dir/exercise_bouts.py"
printf '%s\n' 'id,type,start,end,duration_min,device,hr_samples,hr_avg,hr_min,hr_max,steps_total,distance_km,calories_kcal' > expected-summary.csv
printf '%s\n' 'workout_id,workout_start,workout_type,timestamp,heart_rate_bpm' > expected-detail.csv
diff -u expected-summary.csv workout_summary.csv
diff -u expected-detail.csv workout_heart_rate_detail.csv
awk -F, 'NR==2 {if ($13 != "Incidental" || $14 != "") exit 1; found=1} END {if (!found || NR != 2) exit 1}' exercise_bouts.csv

mkdir "$scratch_dir/bout-boundary"
cd "$scratch_dir/bout-boundary"
cat > export.xml <<'XML'
<HealthData>
<Workout workoutActivityType="INVENTED_WORKOUT" sourceName="SYNTHETIC_DEVICE" startDate="2001-01-02 10:00:00 -0500" endDate="2001-01-02 10:10:00 -0500" duration="10"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_SOURCE" device="SYNTHETIC_DEVICE" unit="min" value="1" startDate="2001-01-01 10:00:00 -0500" endDate="2001-01-01 10:01:00 -0500"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_SOURCE" device="SYNTHETIC_DEVICE" unit="min" value="1" startDate="2001-01-01 10:02:30 -0500" endDate="2001-01-01 10:03:30 -0500"/>
<Record type="HKQuantityTypeIdentifierAppleExerciseTime" sourceName="SYNTHETIC_SOURCE" device="SYNTHETIC_DEVICE" unit="min" value="1" startDate="2001-01-01 10:05:01 -0500" endDate="2001-01-01 10:06:01 -0500"/>
</HealthData>
XML
UV_PYTHON_DOWNLOADS=never "$project_dir/extract_workout_stats.py"
UV_PYTHON_DOWNLOADS=never "$project_dir/exercise_bouts.py"
awk -F, '
    NR==2 {if ($1 != 0 || $2 != "2001-01-01 15:00:00+00:00" || $3 != "2001-01-01 15:03:30+00:00" || $4 != 2) exit 1}
    NR==3 {if ($1 != 1 || $2 != "2001-01-01 15:05:01+00:00" || $3 != "2001-01-01 15:06:01+00:00" || $4 != 1) exit 1}
    END {if (NR != 3) exit 1}
' exercise_bouts.csv
printf 'apple-health-extract extraction tests: PASS\n'
