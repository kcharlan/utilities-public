import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.testkit import ASGISyncClient, load_launcher


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tax2"


def _client(monkeypatch, tmp_path):
    module = load_launcher(SCRIPT_PATH)
    return ASGISyncClient(module.app)


def test_states_endpoint_lists_ga_and_pa_with_qif(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.get("/api/states")

    assert response.status_code == 200
    states = {state["code"]: state for state in response.json()["states"]}
    assert states["GA"]["display_name"] == "Georgia"
    assert states["GA"]["years"] == [2025, 2026]
    assert states["GA"]["qif"]["state_transfer"] == "[GA State Income Taxes]"
    assert states["PA"]["display_name"] == "Pennsylvania"
    assert states["PA"]["years"] == [2026]
    assert states["PA"]["qif"]["state_transfer"] == "[PA State Income Taxes]"


def test_compute_single_ga_matches_golden(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/compute",
        json={
            "monthly_earned": 0,
            "monthly_unearned": 5000,
            "filing_status": "single",
            "year": 2026,
            "mode": "rules",
            "states": [{"code": "GA", "allocation_pct": 100}],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["federal_monthly"] == 418.33
    assert data["states"][0]["monthly"] == 203.6
    assert data["total_monthly"] == 621.93


def test_compute_ga_pa_both_100_are_independent(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/compute",
        json={
            "monthly_earned": 0,
            "monthly_unearned": 5000,
            "filing_status": "single",
            "year": 2026,
            "mode": "rules",
            "states": [
                {"code": "GA", "allocation_pct": 100},
                {"code": "PA", "allocation_pct": 100},
            ],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    states = {state["code"]: state for state in data["states"]}
    assert states["GA"]["monthly"] == 203.6
    assert states["PA"]["monthly"] == 153.5
    assert data["total_monthly"] == 775.43


def test_compute_pa_half_allocation_uses_half_income(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/compute",
        json={
            "monthly_earned": 0,
            "monthly_unearned": 5000,
            "filing_status": "single",
            "year": 2026,
            "mode": "rules",
            "states": [
                {"code": "GA", "allocation_pct": 100},
                {"code": "PA", "allocation_pct": 50},
            ],
        },
    )

    assert response.status_code == 200, response.text
    states = {state["code"]: state for state in response.json()["states"]}
    assert states["PA"]["monthly"] == 76.75


def test_compute_validates_states(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    payload = {
        "monthly_earned": 0,
        "monthly_unearned": 5000,
        "filing_status": "single",
        "year": 2026,
        "mode": "rules",
        "states": [],
    }

    assert client.post("/api/compute", json=payload).status_code == 422

    payload["states"] = [{"code": "XX", "allocation_pct": 100}]
    assert client.post("/api/compute", json=payload).status_code == 422

    payload["states"] = [{"code": "GA", "allocation_pct": 101}]
    assert client.post("/api/compute", json=payload).status_code == 422


def test_export_qif_multistate_request(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/export/qif",
        json={
            "tx_date": "2026-09-15",
            "federal_tax": 100,
            "payee": "Estimated Taxes Withholding",
            "federal_expense": "Tax:Federal",
            "federal_transfer": "[Federal]",
            "states": [
                {
                    "code": "GA",
                    "amount": 20,
                    "expense": "Tax:GA",
                    "transfer": "[GA]",
                },
                {
                    "code": "PA",
                    "amount": 30,
                    "expense": "Tax:PA",
                    "transfer": "[PA]",
                },
            ],
        },
    )

    assert response.status_code == 200, response.text
    text = response.text
    assert text.startswith("!Type:Bank\n")
    assert text.count("MEstimated Federal taxes - 09/15/2026") == 2
    assert "MEstimated GA State taxes - 09/15/2026" in text
    assert "MEstimated PA State taxes - 09/15/2026" in text
