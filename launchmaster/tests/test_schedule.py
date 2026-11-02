"""Exercise calendar descriptions through the synthetic API server."""


def test_calendar_interval_has_human_string(api_jobs_no_apple):
    job = next(j for j in api_jobs_no_apple if j["label"] == "com.example.synthetic-calendar")
    assert job["start_calendar_interval"] == {"Weekday": 1, "Hour": 9, "Minute": 30}
    assert job["schedule_human"] == "Mon at 9:30 AM"
    for job in api_jobs_no_apple:
        if job.get("start_calendar_interval"):
            assert job["schedule_human"], (
                f"Job {job['label']} has StartCalendarInterval but empty schedule_human"
            )
            assert job["schedule_human"] != "Manual", (
                f"Job {job['label']} has StartCalendarInterval but schedule_human='Manual'"
            )
