"""
Integration tests for launchmaster REST API.

These tests run against launchmaster with synthetic launchd inputs and verify
that API responses match those inputs.

Run:  pytest tests/test_api.py -v
"""

import json
import os
import urllib.request
import urllib.error

import pytest


def test_synthetic_server_denies_native_mutations(server_url):
    request = urllib.request.Request(
        f"{server_url}/api/jobs/com.example.synthetic-idle/stop", headers={"Origin": server_url}, method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 403


def test_synthetic_server_lists_only_fixture_jobs(api_jobs):
    assert {job["label"] for job in api_jobs} == {
        "com.example.synthetic-idle", "com.example.synthetic-failed",
        "com.example.synthetic-disabled", "com.apple.example-synthetic",
        "com.example.synthetic-calendar", "com.example.synthetic-interval",
        "com.example.synthetic-running", "com.example.synthetic-watch",
    }


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


# ═══════════════════════════════════════════════════════════════════════════════
# PID and exit code accuracy
# ═══════════════════════════════════════════════════════════════════════════════

class TestPidAndExitCode:
    def test_running_jobs_have_pids(self, api_jobs_no_apple):
        running = next(j for j in api_jobs_no_apple if j["label"] == "com.example.synthetic-running")
        assert running["status"] == "running"
        assert running["pid"] == 424242
        for job in api_jobs_no_apple:
            if job["status"] == "running":
                assert job["pid"] is not None and job["pid"] > 0, (
                    f"Running job {job['label']} has no PID"
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
# Export endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestExport:
    def test_get_export_for_unknown_job_returns_404(self, server_url):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(
                f"{server_url}/api/jobs/com.example.does-not-exist/export"
            )
        assert exc_info.value.code == 404


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
            headers={"Content-Type": "application/json", "Origin": server_url},
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
            headers={"Content-Type": "application/json", "Origin": server_url},
            method="PUT",
        )
        urllib.request.urlopen(req2)


# ═══════════════════════════════════════════════════════════════════════════════
# Logs endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogs:
    def test_logs_stdout_returns_synthetic_line(self, server_url):
        label = "com.example.synthetic-idle"
        resp = urllib.request.urlopen(f"{server_url}/api/jobs/{label}/logs/stdout")
        data = json.loads(resp.read().decode())
        assert "Synthetic log line" in data["lines"]
