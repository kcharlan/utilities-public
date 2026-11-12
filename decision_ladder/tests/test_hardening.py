from datetime import datetime, timezone
from helpers import feed, system


def test_output_mode_and_payload_escaping(dl):
    data = feed(systems=[system(name="Synthetic </script><img src=x>")])
    home = dl.runtime_home()
    dl.save_snapshot(home, {"feed": data, "sha256": "synthetic"}, datetime(2026, 1, 1, tzinfo=timezone.utc))
    output = home / "decision_ladder.html"
    dl.build_page(home, output)
    assert output.stat().st_mode & 0o777 == 0o600
    assert "Synthetic </script><img src=x>" not in output.read_text()
