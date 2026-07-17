from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path


_STANDARD_TERMINAL_NOTIFIER_PATHS = (
    Path("/opt/homebrew/bin/terminal-notifier"),
    Path("/usr/local/bin/terminal-notifier"),
)


def send_notification(
    *,
    title: str,
    message: str,
    report_path: Path | None,
    open_target: str,
    terminal_notifier_path: Path | None = None,
    sound_name: str | None = None,
    runtime_home: Path | None = None,
) -> None:
    del runtime_home
    logger = logging.getLogger("model_sentinel")
    if sys.platform != "darwin":
        return
    target_path = _notification_target_path(report_path=report_path, open_target=open_target)
    terminal_notifier = _resolve_terminal_notifier(configured_path=terminal_notifier_path)
    if terminal_notifier is not None:
        _send_terminal_notifier(
            executable=str(terminal_notifier),
            title=title,
            message=message,
            target_path=target_path,
            sound_name=sound_name,
        )
        logger.info("Sent notification via terminal-notifier: %s", terminal_notifier)
        return
    if report_path is not None:
        message = _with_report_path(
            message=message,
            report_path=report_path,
            open_target=open_target,
            click_to_open_supported=False,
        )
        logger.warning(
            "terminal-notifier was not found; falling back to AppleScript notification without click-to-open support"
        )
    _send_plain_notification(title=title, message=message, sound_name=sound_name)


def _send_plain_notification(*, title: str, message: str, sound_name: str | None) -> None:
    escaped_title = title.replace('"', '\\"')
    escaped_message = message.replace('"', '\\"')
    script = f'display notification "{escaped_message}" with title "{escaped_title}"'
    if sound_name:
        escaped_sound_name = sound_name.replace('"', '\\"')
        script += f' sound name "{escaped_sound_name}"'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


def _send_terminal_notifier(
    *,
    executable: str,
    title: str,
    message: str,
    target_path: Path | None,
    sound_name: str | None,
) -> None:
    command = [
        executable,
        "-title",
        title,
        "-message",
        message,
    ]
    if target_path is not None:
        command.extend(["-open", target_path.resolve().as_uri()])
    if sound_name:
        command.extend(["-sound", sound_name])
    subprocess.run(command, check=False, capture_output=True)


def _notification_target_path(*, report_path: Path | None, open_target: str) -> Path | None:
    if report_path is None:
        return None
    if open_target == "file":
        return report_path
    if open_target == "folder":
        return report_path.parent
    return None


def _with_report_path(
    *,
    message: str,
    report_path: Path,
    open_target: str,
    click_to_open_supported: bool,
) -> str:
    target = report_path if open_target == "file" else report_path.parent
    if click_to_open_supported:
        suffix = f" Path: {target}"
    else:
        suffix = f" Click-to-open unavailable; open manually: {target}"
    combined = f"{message}{suffix}"
    if len(combined) <= 240:
        return combined
    return message


def _resolve_terminal_notifier(*, configured_path: Path | None) -> Path | None:
    candidates: list[Path] = []
    if configured_path is not None:
        candidates.append(configured_path)
    discovered = shutil.which("terminal-notifier")
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend(_STANDARD_TERMINAL_NOTIFIER_PATHS)

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file() and resolved.exists() and _is_executable(resolved):
            return resolved
    return None


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)
