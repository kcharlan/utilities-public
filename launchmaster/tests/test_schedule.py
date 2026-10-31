"""
Tests for schedule humanizer logic.

These tests don't need a running server — they verify the backend's
schedule humanizer function against known plist schedule patterns.

Run:  pytest tests/test_schedule.py -v
"""

class TestScheduleHumanizer:
    """Verify schedule_human strings are correct for known job patterns."""

    def test_calendar_interval_has_human_string(self, api_jobs_no_apple):
        """Jobs with StartCalendarInterval should have a readable schedule."""
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

    def test_start_interval_has_human_string(self, api_jobs_no_apple):
        """Jobs with StartInterval should show 'Every N minutes/hours'."""
        job = next(j for j in api_jobs_no_apple if j["label"] == "com.example.synthetic-interval")
        assert job["start_interval"] == 300
        assert job["schedule_human"] == "Every 5 minutes"
        for job in api_jobs_no_apple:
            if job.get("start_interval"):
                assert "every" in job["schedule_human"].lower() or "interval" in job["schedule_human"].lower(), (
                    f"Job {job['label']} has StartInterval={job['start_interval']} "
                    f"but schedule_human='{job['schedule_human']}'"
                )

    def test_keep_alive_has_human_string(self, api_jobs_no_apple):
        """Jobs with KeepAlive should mention it."""
        job = next(j for j in api_jobs_no_apple if j["label"] == "com.example.synthetic-running")
        assert job["keep_alive"] is True
        assert job["schedule_human"] == "Always running (KeepAlive)"
        for job in api_jobs_no_apple:
            if job.get("keep_alive"):
                assert "alive" in job["schedule_human"].lower() or "always" in job["schedule_human"].lower(), (
                    f"Job {job['label']} has KeepAlive but schedule_human='{job['schedule_human']}'"
                )

    def test_watch_paths_has_human_string(self, api_jobs_no_apple):
        """Jobs with WatchPaths should mention watching."""
        job = next(j for j in api_jobs_no_apple if j["label"] == "com.example.synthetic-watch")
        assert job["watch_paths"] == ["/synthetic/input"]
        assert job["schedule_human"] == "Watching: /synthetic/input"
        for job in api_jobs_no_apple:
            if job.get("watch_paths"):
                assert "watch" in job["schedule_human"].lower(), (
                    f"Job {job['label']} has WatchPaths but schedule_human='{job['schedule_human']}'"
                )

    def test_no_schedule_shows_manual_or_load(self, api_jobs_no_apple):
        """Jobs with no schedule config should show 'Manual' or 'Run at load'."""
        job = next(j for j in api_jobs_no_apple if j["label"] == "com.example.synthetic-idle")
        assert job["schedule_human"] == "Manual"
        for job in api_jobs_no_apple:
            has_schedule = (
                job.get("start_interval")
                or job.get("start_calendar_interval")
                or job.get("watch_paths")
                or job.get("keep_alive")
            )
            if not has_schedule and job.get("plist_path"):
                acceptable = {"manual", "run at load", "unknown"}
                assert any(
                    a in job["schedule_human"].lower() for a in acceptable
                ), (
                    f"Job {job['label']} has no schedule but "
                    f"schedule_human='{job['schedule_human']}'"
                )
