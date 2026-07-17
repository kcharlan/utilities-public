import xml.etree.ElementTree as ET
import pandas as pd
from datetime import timedelta
import csv
from tqdm import tqdm

# -------- CONFIGURATION --------
XML_PATH = "export.xml"
WORKOUT_CSV = "workout_summary.csv"
OUTPUT_CSV = "exercise_bouts.csv"

# Types of interest
HEART_RATE_TYPE = "HKQuantityTypeIdentifierHeartRate"
STEP_TYPE = "HKQuantityTypeIdentifierStepCount"
DISTANCE_TYPE = "HKQuantityTypeIdentifierDistanceWalkingRunning"
CALORIES_TYPE = "HKQuantityTypeIdentifierActiveEnergyBurned"
EXERCISE_TYPE = "HKQuantityTypeIdentifierAppleExerciseTime"

# --------- PARSE XML ---------
print("Counting lines in export.xml for progress bar...")
with open(XML_PATH, "r", encoding="utf-8", errors="ignore") as f:
    num_lines = sum(1 for _ in f)

print("Parsing export.xml for exercise, heart rate, steps, calories, distance...")
exercise_rows, heart_rate_rows, step_rows, distance_rows, calories_rows = [], [], [], [], []

with open(XML_PATH, "r", encoding="utf-8", errors="ignore") as file:
    for event, elem in tqdm(ET.iterparse(file, events=("start",)), total=num_lines, desc="Parsing XML"):
        t = elem.attrib.get("type")
        if elem.tag == "Record":
            if t == EXERCISE_TYPE:
                exercise_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "endDate": elem.attrib.get("endDate"),
                    "value": float(elem.attrib.get("value", "0")),
                    "unit": elem.attrib.get("unit"),
                    "sourceName": elem.attrib.get("sourceName"),
                    "sourceVersion": elem.attrib.get("sourceVersion"),
                    "device": elem.attrib.get("device")
                })
            elif t == HEART_RATE_TYPE:
                heart_rate_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "value": float(elem.attrib.get("value", "0"))
                })
            elif t == STEP_TYPE:
                step_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "value": float(elem.attrib.get("value", "0"))
                })
            elif t == DISTANCE_TYPE:
                distance_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "value": float(elem.attrib.get("value", "0"))
                })
            elif t == CALORIES_TYPE:
                calories_rows.append({
                    "startDate": elem.attrib.get("startDate"),
                    "value": float(elem.attrib.get("value", "0"))
                })
        elem.clear()

exercise_df = pd.DataFrame(exercise_rows)
heart_rate_df = pd.DataFrame(heart_rate_rows)
step_df = pd.DataFrame(step_rows)
distance_df = pd.DataFrame(distance_rows)
calories_df = pd.DataFrame(calories_rows)

if exercise_df.empty:
    raise ValueError("No Apple Exercise Time records found!")

exercise_df["start_dt"] = pd.to_datetime(exercise_df["startDate"])
exercise_df["end_dt"] = pd.to_datetime(exercise_df["endDate"])
exercise_df = exercise_df.sort_values("start_dt").reset_index(drop=True)

# --------- GROUP INTO BOUTS ---------
print("Grouping exercise minutes into bouts...")
bouts = []
current_bout = None

for idx, row in exercise_df.iterrows():
    this_start = row['start_dt']
    this_end = row['end_dt']
    if current_bout is None:
        current_bout = {
            "start_dt": this_start,
            "end_dt": this_end,
            "rows": [row],
        }
    else:
        last_end_dt = pd.to_datetime(current_bout["rows"][-1]["endDate"])
        if (this_start - last_end_dt) <= timedelta(seconds=90):
            current_bout["end_dt"] = this_end
            current_bout["rows"].append(row)
        else:
            bouts.append(current_bout)
            current_bout = {
                "start_dt": this_start,
                "end_dt": this_end,
                "rows": [row],
            }
if current_bout:
    bouts.append(current_bout)

# --------- BUILD BOUTS DATAFRAME W/ INTERVALS ---------
bouts_df = pd.DataFrame([{
    "bout_id": i,
    "bout_start": b['start_dt'],
    "bout_end": b['end_dt'],
    "duration_min": len(b['rows']),
    "sourceName": b['rows'][0]['sourceName'],
    "device": b['rows'][0]['device'],
    "first_min_start": b['rows'][0]['startDate'],
    "last_min_end": b['rows'][-1]['endDate'],
} for i, b in enumerate(bouts)])
bouts_df['interval'] = pd.IntervalIndex.from_arrays(bouts_df['bout_start'], bouts_df['bout_end'], closed='both')

# --------- FAST ASSIGNMENT OF METRIC RECORDS TO BOUTS ---------
def assign_metric(records_df, bouts_df, agg='mean'):
    if records_df.empty:
        return pd.Series([None] * len(bouts_df), index=bouts_df.index)
    record_times = pd.to_datetime(records_df['startDate'])
    # bug - idx = bouts_df['interval'].get_indexer(record_times)
    interval_index = pd.IntervalIndex(bouts_df['interval'])
    idx = interval_index.get_indexer(record_times)
    records_df = records_df.assign(bout_id=idx)
    # Only keep records that fall into a valid bout
    valid_records = records_df[records_df['bout_id'] != -1]
    # Group by bout and aggregate
    if agg == 'mean':
        result = valid_records.groupby('bout_id')['value'].mean()
    elif agg == 'sum':
        result = valid_records.groupby('bout_id')['value'].sum()
    else:
        raise ValueError("agg must be 'mean' or 'sum'")
    return bouts_df.index.map(result)  # preserve index order

print("Assigning metrics to bouts quickly...")
bouts_df['avg_heart_rate'] = assign_metric(heart_rate_df, bouts_df, 'mean')
bouts_df['steps'] = assign_metric(step_df, bouts_df, 'sum')
bouts_df['calories'] = assign_metric(calories_df, bouts_df, 'sum')
bouts_df['distance_km'] = assign_metric(distance_df, bouts_df, 'sum')

# --------- LABEL EACH BOUT ---------
print("Loading workout time windows...")
workouts_df = pd.read_csv(WORKOUT_CSV)
workouts_df["start_dt"] = pd.to_datetime(workouts_df["start"]).dt.tz_localize("US/Eastern")
workouts_df["end_dt"] = pd.to_datetime(workouts_df["end"]).dt.tz_localize("US/Eastern")

def label_bout(bout_start, bout_end):
    for _, w in workouts_df.iterrows():
        if (bout_start < w["end_dt"]) and (bout_end > w["start_dt"]):
            return ("Workout", w["type"])
    return ("Incidental", None)

print("Labelling bouts as Workout or Incidental...")
labels = [label_bout(bout_start, bout_end) for bout_start, bout_end in tqdm(zip(bouts_df['bout_start'], bouts_df['bout_end']), total=len(bouts_df))]
bouts_df['type'] = [x[0] for x in labels]
bouts_df['workout_type'] = [x[1] for x in labels]

# --------- FINAL CLEANUP AND EXPORT ---------
bouts_df.drop(columns=['interval'], inplace=True)
print(f"Exporting {len(bouts_df)} bouts to {OUTPUT_CSV}...")
bouts_df.to_csv(OUTPUT_CSV, index=False)
print("Done! Your exercise bouts with metrics are ready for analysis.")
