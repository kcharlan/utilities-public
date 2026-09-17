from __future__ import annotations

import random
import subprocess
from pathlib import Path

import pytest

import video_compiler
from video_compiler import (
    MediaInfo,
    Segment,
    build_filter_graph,
    probe_media,
    process_video,
    sample_start_times,
)


@pytest.mark.parametrize(
    ("num_samples", "expected"),
    [
        (0, [0.0]),
        (1, [0.0]),
        (3, [0.0, 3.0, 6.0]),
    ],
)
def test_even_sampling_preserves_legacy_endpoint_matrix(
    num_samples: int, expected: list[float]
) -> None:
    assert sample_start_times(10.0, 2.0, 2.0, num_samples, "even") == expected


def test_even_sampling_repeats_zero_when_no_start_range_remains() -> None:
    assert sample_start_times(4.0, 3.0, 2.0, 4, "even") == [0.0] * 4


def test_even_sampling_includes_exact_floating_point_endpoints() -> None:
    starts = sample_start_times(0.1, 0.0, 0.0, 12, "even")

    assert starts[0] == 0.0
    assert starts[-1] == 0.1


def test_random_sampling_preserves_zero_and_empty_asymmetry() -> None:
    assert sample_start_times(10.0, 2.0, 2.0, 0, "random") == []
    assert sample_start_times(4.0, 3.0, 2.0, 4, "random") == []


def test_random_sampling_uses_sorted_nonrepeating_thousand_point_grid() -> None:
    starts = sample_start_times(
        10.0,
        2.0,
        2.0,
        1_500,
        "random",
        random.Random(1729),
    )

    assert len(starts) == 1_000
    assert starts == sorted(starts)
    assert len(set(starts)) == 1_000
    assert starts[0] == 0.0
    assert starts[-1] == 6.0


def test_random_sampling_is_repeatable_with_injected_rng() -> None:
    first = sample_start_times(
        20.0, 4.0, 2.0, 5, "random", random.Random(42)
    )
    second = sample_start_times(
        20.0, 4.0, 2.0, 5, "random", random.Random(42)
    )

    assert first == second
    assert first == sorted(first)
    assert len(set(first)) == 5


def test_sampling_rejects_unknown_method() -> None:
    with pytest.raises(ValueError, match="even.*random"):
        sample_start_times(10.0, 2.0, 2.0, 2, "middle")


def test_probe_media_reads_duration_and_audio_presence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "synthetic.mp4"
    source.write_bytes(b"synthetic")
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"format":{"duration":"12.5"},"streams":'
        '[{"codec_type":"video"},{"codec_type":"audio"}]}',
        stderr="",
    )
    calls: list[tuple[list[str], dict[str, object]]] = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return completed

    monkeypatch.setattr(video_compiler.subprocess, "run", run)

    assert probe_media(source) == MediaInfo(duration=12.5, has_audio=True)
    assert calls == [
        (
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(source),
            ],
            {
                "capture_output": True,
                "text": True,
                "check": False,
                "shell": False,
            },
        )
    ]


@pytest.mark.parametrize(
    ("completed", "message"),
    [
        (
            subprocess.CompletedProcess([], 1, stdout="", stderr="bad container"),
            "bad container",
        ),
        (
            subprocess.CompletedProcess([], 0, stdout="not-json", stderr=""),
            "invalid JSON",
        ),
        (
            subprocess.CompletedProcess(
                [], 0, stdout='{"format":{"duration":"nan"},"streams":[]}', stderr=""
            ),
            "finite positive duration",
        ),
    ],
)
def test_probe_media_reports_unreadable_or_invalid_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completed: subprocess.CompletedProcess[str],
    message: str,
) -> None:
    source = tmp_path / "broken.mp4"
    monkeypatch.setattr(video_compiler.subprocess, "run", lambda *a, **k: completed)

    with pytest.raises(video_compiler.MediaProcessingError, match=message):
        probe_media(source)


def test_probe_media_reports_missing_ffprobe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(video_compiler.subprocess, "run", missing)

    with pytest.raises(video_compiler.MediaProcessingError, match="ffprobe.*PATH"):
        probe_media(tmp_path / "source.mp4")


def test_build_filter_graph_orders_and_resets_every_audio_video_leg() -> None:
    graph, maps = build_filter_graph(
        [Segment(1.25, 2.5), Segment(8.0, 3.0)], has_audio=True
    )

    assert graph == (
        "[0:v]trim=start=1.25:duration=2.5,setpts=PTS-STARTPTS[v0];"
        "[0:a]atrim=start=1.25:duration=2.5,asetpts=PTS-STARTPTS[a0];"
        "[0:v]trim=start=8:duration=3,setpts=PTS-STARTPTS[v1];"
        "[0:a]atrim=start=8:duration=3,asetpts=PTS-STARTPTS[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    assert maps == ["[v]", "[a]"]


def test_build_filter_graph_video_only_has_no_audio_legs() -> None:
    graph, maps = build_filter_graph([Segment(0.0, 1.0)], has_audio=False)

    assert graph == (
        "[0:v]trim=start=0:duration=1,setpts=PTS-STARTPTS[v0];"
        "[v0]concat=n=1:v=1:a=0[v]"
    )
    assert maps == ["[v]"]


def test_segment_construction_clamps_tail_and_appends_it_last() -> None:
    assert video_compiler.build_segments(5.0, 10.0, 2.0, 3, "even") == [
        Segment(0.0, 5.0)
    ]


def test_segment_construction_keeps_full_sample_after_legacy_eligibility_check() -> None:
    segments = video_compiler.build_segments(10.0, 3.0, 4.0, 2, "even")

    assert segments == [
        Segment(0.0, 4.0),
        Segment(3.0, 4.0),
        Segment(7.0, 3.0),
    ]


@pytest.mark.parametrize("method", ["even", "random"])
def test_segment_construction_appends_tail_last_for_all_modes(method: str) -> None:
    segments = video_compiler.build_segments(
        10.0, 2.0, 1.0, 2, method, random.Random(19)
    )

    assert segments[-1] == Segment(8.0, 2.0)


def test_failed_render_preserves_existing_final_and_removes_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "result.mp4"
    output.write_bytes(b"existing-final")
    monkeypatch.setattr(
        video_compiler, "probe_media", lambda path: MediaInfo(10.0, True)
    )
    monkeypatch.setattr(
        video_compiler.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "render failed"),
    )

    assert not process_video(source, output, 1, 2.0, 2.0, "even")
    assert output.read_bytes() == b"existing-final"
    assert list(tmp_path.glob("*.partial*.mp4")) == []
    assert "render failed" in capsys.readouterr().out


def test_successful_render_atomically_replaces_final_with_unique_mp4_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "result.mp4"
    output.write_bytes(b"old")
    temporary_paths: list[Path] = []
    commands: list[list[str]] = []
    monkeypatch.setattr(
        video_compiler, "probe_media", lambda path: MediaInfo(10.0, False)
    )

    def render(command, **kwargs):
        assert kwargs["shell"] is False
        commands.append(command)
        temporary = Path(command[-1])
        temporary_paths.append(temporary)
        assert temporary.parent == output.parent
        assert temporary.name.endswith(".mp4")
        temporary.write_bytes(b"new")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(video_compiler.subprocess, "run", render)

    assert process_video(source, output, 1, 2.0, 2.0, "even")
    assert process_video(source, output, 1, 2.0, 2.0, "even")
    assert output.read_bytes() == b"new"
    assert temporary_paths[0] != temporary_paths[1]
    assert list(tmp_path.glob("*.partial*.mp4")) == []
    assert commands[0].count("-map") == 1
    assert "[v]" in commands[0]
    assert "[a]" not in commands[0]
    assert commands[0][commands[0].index("-c:v") + 1] == "h264_videotoolbox"
    assert "-c:a" not in commands[0]


def test_batch_continues_after_file_failure_and_worker_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    valid = tmp_path / "valid.mp4"
    invalid = tmp_path / "invalid.mp4"
    exploding = tmp_path / "exploding.mp4"
    inputs = [str(valid), str(invalid), str(exploding)]

    class FakeFuture:
        def __init__(self, result=None, error: Exception | None = None):
            self._result = result
            self._error = error

        def result(self):
            if self._error is not None:
                raise self._error
            return self._result

    class FakeExecutor:
        def __init__(self, max_workers=None):
            assert max_workers == 2

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, function, *args):
            source = Path(args[0])
            if source == exploding:
                return FakeFuture(error=RuntimeError("pool boom"))
            if source == invalid:
                return FakeFuture(result=False)
            Path(args[1]).write_bytes(b"valid-output")
            return FakeFuture(result=True)

    monkeypatch.setattr(video_compiler.glob, "glob", lambda pattern: inputs)
    monkeypatch.setattr(video_compiler, "ProcessPoolExecutor", FakeExecutor)
    monkeypatch.setattr(video_compiler, "as_completed", lambda futures: list(futures))

    status = video_compiler.main(
        [
            "--input",
            "*.mp4",
            "--output_dir",
            str(tmp_path / "output"),
            "--max_workers",
            "2",
        ]
    )

    assert status == 0
    assert (tmp_path / "output/valid_compilation.mp4").read_bytes() == b"valid-output"
    output = capsys.readouterr().out
    assert f"failed: {invalid}" in output
    assert f"Failed to process {exploding}: unexpected worker error: pool boom" in output
    assert f"failed: {exploding}" in output
    assert "Processing videos: 3/3" in output


def test_missing_matches_preserve_zero_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(video_compiler.glob, "glob", lambda pattern: [])

    assert video_compiler.main(
        ["--input", "missing-*.mp4", "--output_dir", str(tmp_path)]
    ) == 0
    assert capsys.readouterr().out == "No matching files found.\n"


def test_equal_basenames_keep_documented_final_path_collision(
    tmp_path: Path,
) -> None:
    args = video_compiler.argparse.Namespace(
        output_dir=tmp_path,
        samples=1,
        sample_length=2.0,
        tail_length=3.0,
        sampling="even",
        verbose=False,
    )

    first = video_compiler.batch_args("one/shared.mp4", args)
    second = video_compiler.batch_args("two/shared.mp4", args)

    assert first[1] == second[1] == tmp_path / "shared_compilation.mp4"
