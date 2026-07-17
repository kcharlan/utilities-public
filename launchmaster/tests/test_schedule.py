"""
Tests for schedule humanizer logic.

These tests don't need a running server — they verify the backend's
schedule humanizer function against known plist schedule patterns.

Run:  pytest tests/test_schedule.py -v
"""

import json
import urllib.request

import pytest


class TestScheduleHumanizer:
    """Verify schedule_human strings are correct for known job patterns."""

    def test_calendar_interval_has_human_string(self, api_jobs_no_apple):
        """Jobs with StartCalendarInterval should have a readable schedule."""
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
        for job in api_jobs_no_apple:
            if job.get("start_interval"):
                assert "every" in job["schedule_human"].lower() or "interval" in job["schedule_human"].lower(), (
                    f"Job {job['label']} has StartInterval={job['start_interval']} "
                    f"but schedule_human='{job['schedule_human']}'"
                )

    def test_keep_alive_has_human_string(self, api_jobs_no_apple):
        """Jobs with KeepAlive should mention it."""
        for job in api_jobs_no_apple:
            if job.get("keep_alive"):
                assert "alive" in job["schedule_human"].lower() or "always" in job["schedule_human"].lower(), (
                    f"Job {job['label']} has KeepAlive but schedule_human='{job['schedule_human']}'"
                )

    def test_watch_paths_has_human_string(self, api_jobs_no_apple):
        """Jobs with WatchPaths should mention watching."""
        for job in api_jobs_no_apple:
            if job.get("watch_paths"):
                assert "watch" in job["schedule_human"].lower(), (
                    f"Job {job['label']} has WatchPaths but schedule_human='{job['schedule_human']}'"
                )

    def test_no_schedule_shows_manual_or_load(self, api_jobs_no_apple):
        """Jobs with no schedule config should show 'Manual' or 'Run at load'."""
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
