"""Fresh synthetic inputs and the release executable's public interface only."""
import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path

SESSION = "synthetic-session-standalone"
REQUEST = "Invent a synthetic violet kite"

class DataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "colophon-data":
            self.active = True
            self.count += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

def extract_payload(html):
    parser = DataParser()
    parser.feed(html)
    if parser.count != 1:
        raise ValueError("expected exactly one colophon-data script")
    value = json.loads("".join(parser.parts))
    if not isinstance(value, dict):
        raise ValueError("payload must be an object")
    return value

class NativeRun:
    def __init__(self, root):
        self.root = root
        self.home = root / "home"
        self.codex = root / "codex"
        self.runtime = root / "runtime"
        self.home.mkdir()
        self.codex.mkdir()
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), COLOPHON_HOME=str(self.runtime),
                        TMPDIR=str(root), COLOPHON_PRICING_URL="http://127.0.0.1:9/catalog.json")
        self.binary = Path(os.environ["COLOPHON_BIN"])
        if not self.binary.is_absolute() or not self.binary.is_file():
            raise ValueError("COLOPHON_BIN must name an absolute existing release executable")

    @property
    def page(self):
        return self.runtime / "colophon.html"

    def invoke(self, *args):
        return subprocess.run([str(self.binary), *args], env=self.env, text=True,
                              capture_output=True, timeout=45)

    def build(self, *args, offline=True):
        return self.invoke("--codex-home", str(self.codex), "--no-open",
                           *(["--offline"] if offline else []), *args)

    def payload(self, path=None):
        return extract_payload((path or self.page).read_text())

    def session(self):
        directory = self.codex / "sessions" / "2026" / "01" / "02"
        directory.mkdir(parents=True)
        path = directory / "rollout-synthetic.jsonl"
        def row(kind, payload, second):
            return {"type": kind, "timestamp": f"2026-01-02T12:00:{second:02d}Z", "payload": payload}
        rows = [
            row("session_meta", {"id": SESSION, "cwd": "/synthetic/kite", "source": "cli", "thread_name": "Synthetic violet kite"}, 0),
            row("turn_context", {"model": "gpt-5", "turn_id": "synthetic-turn"}, 1),
            row("event_msg", {"type": "task_started", "turn_id": "synthetic-turn"}, 1),
            row("event_msg", {"type": "user_message", "message": REQUEST}, 2),
            row("event_msg", {"type": "token_count", "turn_id": "synthetic-turn", "info": {"model": "gpt-5", "last_token_usage": {"input_tokens": 120, "cached_input_tokens": 20, "output_tokens": 30, "reasoning_output_tokens": 5, "total_tokens": 150}, "total_token_usage": {"input_tokens": 120, "cached_input_tokens": 20, "output_tokens": 30, "reasoning_output_tokens": 5, "total_tokens": 150}}}, 3),
            row("event_msg", {"type": "agent_message", "phase": "final_answer", "message": "Synthetic kite complete"}, 4),
            row("event_msg", {"type": "task_complete", "turn_id": "synthetic-turn"}, 5),
        ]
        path.write_text("".join(json.dumps(value) + "\n" for value in rows))
        return path
