"""
Integration tests for launchmaster REST API.

These tests run against a real launchmaster server and verify
that API responses match the actual macOS launchd system state.

Run:  pytest tests/test_api.py -v
"""

import json
import os
import urllib.request
import urllib.error

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Health endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    def test_health_returns_ok(self, server_url):
        resp = urllib.request.urlopen(f"{server_url}/api/health")
        data = json.loads(resp.read().decode())
        assert data["status"] == "ok"
        assert "version" in data
        assert "job_count" in data
        assert isinstance(data["job_count"], int)
        assert data["job_count"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Job listing
# ═══════════════════════════════════════════════════════════════════════════════

class TestJobListing:
    def test_jobs_returns_list(self, server_url):
        resp = urllib.request.urlopen(f"{server_url}/api/jobs")
        data = json.loads(resp.read().decode())
        assert isinstance(data, list)
        assert len(data) > 0

    def test_jobs_include_apple_true(self, server_url):
        resp = urllib.request.urlopen(f"{server_url}/api/jobs?include_apple=true")
        data = json.loads(resp.read().decode())
        apple_jobs = [j for j in data if j.get("is_apple")]
        assert len(apple_jobs) > 0, "Expected Apple jobs when include_apple=true"

    def test_jobs_include_apple_false(self, server_url):
        resp = urllib.request.urlopen(f"{server_url}/api/jobs?include_apple=false")
        data = json.loads(resp.read().decode())
        apple_jobs = [j for j in data if j.get("is_apple")]
        assert len(apple_jobs) == 0, "Expected no Apple jobs when include_apple=false"

    def test_job_has_required_fields(self, api_jobs_no_apple):
        """Every job must have the fields the SPA expects."""
        required_fields = {
            "label", "domain", "loaded", "enabled", "status",
            "pid", "last_exit", "is_apple",
        }
        for job in api_jobs_no_apple:
            missing = required_fields - set(job.keys())
            assert not missing, f"Job {job.get('label', '?')} missing fields: {missing}"

    def test_status_values_are_valid(self, api_jobs_no_apple):
        valid_statuses = {"running", "idle", "failed", "disabled", "unloaded"}
        for job in api_jobs_no_apple:
            assert job["status"] in valid_statuses, (
                f"Job {job['label']} has invalid status: {job['status']}"
            )

    def test_enabled_is_boolean(self, api_jobs_no_apple):
        for job in api_jobs_no_apple:
            assert isinstance(job["enabled"], bool), (
                f"Job {job['label']} enabled is {type(job['enabled'])}, expected bool"
            )

    def test_loaded_is_boolean(self, api_jobs_no_apple):
        for job in api_jobs_no_apple:
            assert isinstance(job["loaded"], bool), (
                f"Job {job['label']} loaded is {type(job['loaded'])}, expected bool"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Regression: enabled/disabled detection
# (Catches the bug where all jobs showed as "Disabled" because
#  the backend used plist "Disabled" key without checking launchctl state,
#  and never set the "enabled" field at all.)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnabledDisabledRegression:
    """Regression tests for the enabled/disabled detection bug.

    The original bug:
    - Backend only checked the plist Disabled key (rarely set)
    - Backend never set an "enabled" field on job dicts
    - Frontend checked job.enabled (always undefined → falsy → showed "Disabled")
    - The "loaded" detection had a pop-then-check bug that always returned False

    These tests verify enabled/disabled state matches the real launchctl state.
    """

    def test_enabled_field_exists_on_all_jobs(self, api_jobs_no_apple):
        """Every job must have an explicit 'enabled' boolean field."""
        for job in api_jobs_no_apple:
            assert "enabled" in job, (
                f"Job {job['label']} missing 'enabled' field — "
                "regression: backend must set enabled explicitly"
            )

    def test_enabled_matches_launchctl_print_disabled(
        self, api_jobs_no_apple, disabled_labels
    ):
        """Jobs reported as disabled by launchctl must show enabled=False in API."""
        for job in api_jobs_no_apple:
            label = job["label"]
            if label in disabled_labels:
                assert not job["enabled"], (
                    f"Job {label} is disabled in launchctl but API says enabled=True"
                )

    def test_enabled_jobs_not_in_disabled_list(
        self, api_jobs_no_apple, disabled_labels
    ):
        """Jobs NOT in launchctl's disabled list should show enabled=True
        (unless the plist itself has Disabled=true)."""
        for job in api_jobs_no_apple:
            label = job["label"]
            if label not in disabled_labels and not job.get("disabled", False):
                assert job["enabled"], (
                    f"Job {label} is NOT disabled in launchctl but API says enabled=False — "
                    "regression: enabled detection must check launchctl print-disabled"
                )

    def test_loaded_jobs_appear_in_launchctl_list(
        self, api_jobs_no_apple, launchctl_state
    ):
        """Jobs marked loaded=True must appear in launchctl list output."""
        for job in api_jobs_no_apple:
            if job["loaded"]:
                assert job["label"] in launchctl_state, (
                    f"Job {job['label']} is loaded=True but not in launchctl list — "
                    "regression: loaded detection must not use pop-then-check pattern"
                )

    def test_disabled_status_only_for_truly_disabled(
        self, api_jobs_no_apple, disabled_labels
    ):
        """Only jobs that are genuinely disabled should have status='disabled'."""
        for job in api_jobs_no_apple:
            if job["status"] == "disabled":
                is_truly_disabled = (
                    job["label"] in disabled_labels
                    or job.get("disabled", False)
                )
                assert is_truly_disabled, (
                    f"Job {job['label']} has status='disabled' but is not actually disabled"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# PID and exit code accuracy
# ═══════════════════════════════════════════════════════════════════════════════

class TestPidAndExitCode:
    def test_running_jobs_have_pids(self, api_jobs_no_apple):
        for job in api_jobs_no_apple:
            if job["status"] == "running":
                assert job["pid"] is not None and job["pid"] > 0, (
                    f"Running job {job['label']} has no PID"
                )

    def test_pids_match_launchctl(self, api_jobs_no_apple, launchctl_state):
        """API PIDs must match launchctl list PIDs."""
        for job in api_jobs_no_apple:
            label = job["label"]
            if label in launchctl_state:
                real = launchctl_state[label]
                assert job["pid"] == real["pid"], (
                    f"Job {label}: API pid={job['pid']}, launchctl pid={real['pid']}"
                )

    def test_exit_codes_match_launchctl(self, api_jobs_no_apple, launchctl_state):
        """API exit codes must match launchctl list exit codes."""
        for job in api_jobs_no_apple:
            label = job["label"]
            if label in launchctl_state:
                real = launchctl_state[label]
                assert job["last_exit"] == real["last_exit"], (
                    f"Job {label}: API exit={job['last_exit']}, "
                    f"launchctl exit={real['last_exit']}"
                )

    def test_failed_jobs_have_nonzero_exit(self, api_jobs_no_apple):
        for job in api_jobs_no_apple:
            if job["status"] == "failed":
                assert job["last_exit"] is not None and job["last_exit"] != 0, (
                    f"Failed job {job['label']} has exit code {job['last_exit']}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# Plist path validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlistPaths:
    def test_plist_paths_exist_on_disk(self, api_jobs_no_apple):
        """Jobs with a plist_path should point to a real file."""
        for job in api_jobs_no_apple:
            path = job.get("plist_path")
            if path:
                assert os.path.isfile(path), (
                    f"Job {job['label']}: plist_path does not exist: {path}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# Settings endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettings:
    def test_get_settings(self, server_url):
        resp = urllib.request.urlopen(f"{server_url}/api/settings")
        data = json.loads(resp.read().decode())
        assert "poll_interval" in data
        assert "dark_mode" in data

    def test_put_settings(self, server_url):
        new_settings = {"poll_interval": 10}
        req = urllib.request.Request(
            f"{server_url}/api/settings",
            data=json.dumps(new_settings).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read().decode())
        assert data.get("success") is True

        # Verify the setting was actually saved
        get_resp = urllib.request.urlopen(f"{server_url}/api/settings")
        saved = json.loads(get_resp.read().decode())
        assert saved.get("poll_interval") == 10

        # Reset
        reset = {"poll_interval": 5}
        req2 = urllib.request.Request(
            f"{server_url}/api/settings",
            data=json.dumps(reset).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        urllib.request.urlopen(req2)


# ═══════════════════════════════════════════════════════════════════════════════
# Backups endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackups:
    def test_list_backups(self, server_url):
        resp = urllib.request.urlopen(f"{server_url}/api/backups")
        data = json.loads(resp.read().decode())
        assert isinstance(data, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Logs endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogs:
    def test_logs_stdout_returns_data_or_error(self, server_url, api_jobs_no_apple):
        """Logs endpoint should return lines list or graceful error."""
        # Find a job with a stdout path
        job = next(
            (j for j in api_jobs_no_apple if j.get("stdout_path")),
            None,
        )
        if job is None:
            pytest.skip("No jobs with stdout_path found")

        label = urllib.parse.quote(job["label"], safe="")
        resp = urllib.request.urlopen(
            f"{server_url}/api/jobs/{label}/logs/stdout"
        )
        data = json.loads(resp.read().decode())
        assert isinstance(data, (list, dict)), f"Unexpected log response type: {type(data)}"
