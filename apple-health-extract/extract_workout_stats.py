import xml.etree.ElementTree as ET
import pandas as pd
from tqdm import tqdm

XML_PATH = "export.xml"

# Types of interest
HEART_RATE_TYPE = "HKQuantityTypeIdentifierHeartRate"
STEP_TYPE = "HKQuantityTypeIdentifierStepCount"
DISTANCE_TYPE = "HKQuantityTypeIdentifierDistanceWalkingRunning"
CALORIES_TYPE = "HKQuantityTypeIdentifierActiveEnergyBurned"

# First: Load all workout windows
print("Parsing workouts...")
workouts = []
for event, elem in ET.iterparse(XML_PATH, events=("start",)):
    if elem.tag == "Workout":
        workouts.append({
            "id": len(workouts),
            "type": elem.attrib.get("workoutActivityType"),
            "start": pd.to_datetime(elem.attrib.get("startDate")[:19]),
            "end": pd.to_datetime(elem.attrib.get("endDate")[:19]),
            "duration_min": float(elem.attrib.get("duration", "0")),
            "device": elem.attrib.get("sourceName"),
        })
    elem.clear()
workouts_df = pd.DataFrame(workouts)
print(f"Found {len(workouts)} workouts.")

# Pre-scan: Only parse records in relevant window for speed
print("Parsing health records (heart rate, steps, calories, distance)...")
records = []
for event, elem in tqdm(ET.iterparse(XML_PATH, events=("start",)), total=5_000_000):
    if elem.tag == "Record" and elem.attrib.get("type") in [
        HEART_RATE_TYPE, STEP_TYPE, DISTANCE_TYPE, CALORIES_TYPE
    ]:
        start = pd.to_datetime(elem.attrib.get("startDate")[:19])
        value = float(elem.attrib.get("value", "0"))
        records.append({
            "type": elem.attrib.get("type"),
            "start": start,
            "value": value
        })
    elem.clear()
print(f"Loaded {len(records)} health records.")

records_df = pd.DataFrame(records)

# Create summary and detail output lists
summary_rows = []
hr_detail_rows = []

print("Aggregating stats for each workout...")
for idx, workout in tqdm(workouts_df.iterrows(), total=workouts_df.shape[0]):
    w_start, w_end = workout["start"], workout["end"]

    # Find heart rate samples
    hr = records_df[
        (records_df["type"] == HEART_RATE_TYPE) &
        (records_df["start"] >= w_start) &
        (records_df["start"] <= w_end)
    ]
    steps = records_df[
        (records_df["type"] == STEP_TYPE) &
        (records_df["start"] >= w_start) &
        (records_df["start"] <= w_end)
    ]
    dist = records_df[
        (records_df["type"] == DISTANCE_TYPE) &
        (records_df["start"] >= w_start) &
        (records_df["start"] <= w_end)
    ]
    cal = records_df[
        (records_df["type"] == CALORIES_TYPE) &
        (records_df["start"] >= w_start) &
        (records_df["start"] <= w_end)
    ]

    # Save detailed HR samples for this workout
    for _, row in hr.iterrows():
        hr_detail_rows.append({
            "workout_id": workout["id"],
            "workout_start": w_start,
            "workout_type": workout["type"],
            "timestamp": row["start"],
            "heart_rate_bpm": row["value"]
        })

    summary_rows.append({
        "id": workout["id"],
        "type": workout["type"],
        "start": w_start,
        "end": w_end,
        "duration_min": workout["duration_min"],
        "device": workout["device"],
        "hr_samples": len(hr),
        "hr_avg": hr["value"].mean() if not hr.empty else None,
        "hr_min": hr["value"].min() if not hr.empty else None,
        "hr_max": hr["value"].max() if not hr.empty else None,
        "steps_total": steps["value"].sum() if not steps.empty else None,
        "distance_km": dist["value"].sum() / 1000 if not dist.empty else None,
        "calories_kcal": cal["value"].sum() if not cal.empty else None,
    })

# Save outputs
summary_df = pd.DataFrame(summary_rows)
hr_detail_df = pd.DataFrame(hr_detail_rows)

summary_df.to_csv("workout_summary.csv", index=False)
hr_detail_df.to_csv("workout_heart_rate_detail.csv", index=False)

print("Saved: workout_summary.csv (summary per workout)")
print("Saved: workout_heart_rate_detail.csv (detailed heart rate data per workout)")
print("All done!")
