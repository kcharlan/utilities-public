from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from textwrap import dedent

import pytest

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.pack_loader import load_pack_manifest
from cognitive_switchyard.parsers import (
    parse_resolution_json,
    parse_staged_task_plan,
    parse_task_plan,
)
from cognitive_switchyard.planning_runtime import (
    prepare_session_for_execution,
    run_planning_phase,
    run_resolution_phase,
)
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _write_script(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(contents).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def _write_pack(
    tmp_path: Path,
    *,
    name: str,
    planning_enabled: bool = False,
    planning_max_instances: int = 1,
    resolution_executor: str = "passthrough",
    resolve_script_body: str | None = None,
    execute_script_body: str = """
    #!/usr/bin/env python3
    raise SystemExit(0)
    """,
) -> Path:
    pack_root = tmp_path / name
    scripts_dir = pack_root / "scripts"
    prompts_dir = pack_root / "prompts"
    scripts_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)

    manifest_lines = [
        f"name: {name}",
        "description: Planning runtime test pack.",
        "version: 1.2.3",
        "",
        "phases:",
    ]
    if planning_enabled:
        (prompts_dir / "planner.md").write_text("planner prompt\n", encoding="utf-8")
        manifest_lines.extend(
            [
                "  planning:",
                "    enabled: true",
                "    executor: agent",
                "    model: test-planner",
                "    prompt: prompts/planner.md",
                f"    max_instances: {planning_max_instances}",
            ]
        )
    if resolution_executor == "agent":
        (prompts_dir / "resolver.md").write_text("resolver prompt\n", encoding="utf-8")
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: agent",
                "    model: test-resolver",
                "    prompt: prompts/resolver.md",
            ]
        )
    elif resolution_executor == "script":
        _write_script(scripts_dir / "resolve", resolve_script_body or "")
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: script",
                "    script: scripts/resolve",
            ]
        )
    else:
        manifest_lines.extend(
            [
                "  resolution:",
                "    enabled: true",
                "    executor: passthrough",
            ]
        )
    _write_script(scripts_dir / "execute", execute_script_body)
    manifest_lines.extend(
        [
            "  execution:",
            "    enabled: true",
            "    executor: shell",
            "    command: scripts/execute",
        ]
    )
    (pack_root / "pack.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return pack_root


def _write_intake(path: Path, name: str, contents: str) -> Path:
    target = path / name
    target.write_text(dedent(contents).lstrip(), encoding="utf-8")
    return target


def _staged_plan_text(
    task_id: str,
    *,
    depends_on: str = "none",
    full_test_after: str = "no",
    body_extra: str = "",
) -> str:
    return dedent(
        f"""
        ---
        PLAN_ID: {task_id}
        PRIORITY: normal
        ESTIMATED_SCOPE: src/{task_id}.py
        DEPENDS_ON: {depends_on}
        FULL_TEST_AFTER: {full_test_after}
        ---

        # Plan: Task {task_id}

        Implement task {task_id}.
        {body_extra}
        """
    ).lstrip()


def _write_staging_plan(session_root: Path, task_id: str, *, depends_on: str = "none") -> Path:
    path = session_root / "staging" / f"{task_id}.plan.md"
    path.write_text(_staged_plan_text(task_id, depends_on=depends_on), encoding="utf-8")
    return path


def test_planner_claims_oldest_intake_item_and_writes_staged_plan(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-plan-oldest",
        name="Packet 08 planning oldest",
        pack="planning-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="planning-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_first.md", "# First intake\n")
    _write_intake(session_paths.intake, "002_second.md", "# Second intake\n")

    seen: list[str] = []

    def planner_agent(*, intake_path: Path, **_: object) -> str:
        seen.append(intake_path.name)
        task_id = intake_path.name.split("_", 1)[0]
        return _staged_plan_text(task_id)

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert seen == ["001_first.md", "002_second.md"]
    assert result.staged_task_ids == ("001", "002")
    assert result.review_task_ids == ()
    assert sorted(path.name for path in session_paths.staging.glob("*.plan.md")) == [
        "001.plan.md",
        "002.plan.md",
    ]
    assert not any(session_paths.claimed.iterdir())
    assert sorted(p.name for p in session_paths.intake.iterdir()) == ["NEXT_SEQUENCE"]


def test_planner_output_with_questions_goes_to_review_and_halts_before_resolution(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-review-halt",
        name="Packet 08 review halt",
        pack="review-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="review-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "010_review.md", "# Needs review\n")

    def planner_agent(**_: object) -> str:
        return _staged_plan_text(
            "010",
            body_extra="""

            ## Questions for Review

            1. Which branch should this target?
            """,
        )

    result = prepare_session_for_execution(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.review_task_ids == ("010",)
    assert result.ready_task_ids == ()
    assert result.resolution_conflicts == ()
    assert (session_paths.review / "010.plan.md").is_file()
    assert not session_paths.resolution.exists()
    assert not any(session_paths.ready.iterdir())
    assert store.list_ready_tasks(session.id) == ()


def test_mixed_review_and_staged_plans_proceeds_with_staged_plans_through_resolution(
    tmp_path: Path,
) -> None:
    """When some plans go to review and others are staged, resolution and
    execution should proceed with the staged plans.  Review items stay parked."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-mixed-review",
        name="Mixed review and staged",
        pack="mixed-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="mixed-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_review.md", "# Needs review\n")
    _write_intake(session_paths.intake, "002_ready.md", "# Good to go\n")

    def planner_agent(*, intake_path: Path, **_: object) -> str:
        task_id = intake_path.name.split("_", 1)[0]
        if "review" in intake_path.name:
            return _staged_plan_text(
                task_id,
                body_extra="""
            ## Questions for Review

            1. Why?
            """,
            )
        return _staged_plan_text(task_id)

    result = prepare_session_for_execution(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    # Review items are reported but don't block ready tasks
    assert result.review_task_ids == ("001",)
    assert result.ready_task_ids == ("002",)
    assert result.resolution_conflicts == ()

    # 001 is in review/, 002 made it to ready/
    assert (session_paths.review / "001.plan.md").is_file()
    assert (session_paths.ready / "002.plan.md").is_file()
    assert store.list_ready_tasks(session.id) == (store.get_task(session.id, "002"),)


def test_planning_disabled_session_promotes_valid_intake_plan_files_to_staging(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-no-planner",
        name="Packet 08 planning disabled",
        pack="no-planner-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="no-planner-pack", planning_enabled=False)
    session_paths = runtime_paths.session_paths(session.id)
    intake_plan = session_paths.intake / "021.plan.md"
    intake_plan.write_text(_staged_plan_text("021"), encoding="utf-8")

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.staged_task_ids == ("021",)
    assert result.review_task_ids == ()
    assert not intake_plan.exists()
    staged_path = session_paths.staging / "021.plan.md"
    assert staged_path.is_file()
    assert parse_staged_task_plan(
        staged_path.read_text(encoding="utf-8"),
        source=staged_path,
    ).task_id == "021"


def test_planning_enabled_session_uses_effective_planner_count_up_to_pack_max_instances(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-11d-planner-count",
        name="Packet 11D planner count",
        pack="planning-pack",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps({"planner_count": 4}),
    )
    pack_root = _write_pack(
        tmp_path,
        name="planning-pack",
        planning_enabled=True,
        planning_max_instances=2,
    )
    session_paths = runtime_paths.session_paths(session.id)
    for index in range(1, 5):
        _write_intake(session_paths.intake, f"{index:03d}_task.md", f"# Intake {index}\n")

    lock = threading.Lock()
    current = 0
    max_seen = 0

    def planner_agent(*, intake_path: Path, **_: object) -> str:
        nonlocal current, max_seen
        with lock:
            current += 1
            max_seen = max(max_seen, current)
        try:
            time.sleep(0.05)
            return _staged_plan_text(intake_path.name.split("_", 1)[0])
        finally:
            with lock:
                current -= 1

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.staged_task_ids == ("001", "002", "003", "004")
    assert result.review_task_ids == ()
    assert max_seen == 2


def test_parallel_planning_sends_failed_item_to_review_and_continues(tmp_path: Path) -> None:
    """A planner exception sends that item to review; other items still get planned."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-11d-planner-failure",
        name="Packet 11D planner failure",
        pack="planning-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(
        tmp_path,
        name="planning-pack",
        planning_enabled=True,
        planning_max_instances=2,
    )
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_fail.md", "# Fail\n")
    _write_intake(session_paths.intake, "002_wait.md", "# Wait\n")
    _write_intake(session_paths.intake, "003_tail.md", "# Tail\n")

    slow_started = threading.Event()

    def planner_agent(*, intake_path: Path, **_: object) -> str:
        if intake_path.name == "001_fail.md":
            slow_started.wait(timeout=5)
            raise RuntimeError("planner exploded")
        slow_started.set()
        time.sleep(0.2)
        return _staged_plan_text(intake_path.name.split("_", 1)[0])

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        effective_planner_count=2,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert slow_started.is_set()
    assert not any(session_paths.claimed.iterdir())
    # Failed item goes to review, not back to intake.
    assert not any(session_paths.intake.glob("001_fail.md"))
    # Successful items are staged; failed item is in review.
    assert sorted(result.staged_task_ids) == ["002", "003"]
    assert sorted(result.review_task_ids) == ["001"]
    assert sorted(path.name for path in session_paths.staging.iterdir()) == ["002.plan.md", "003.plan.md"]
    assert sorted(path.name for path in session_paths.review.iterdir()) == ["001.plan.md"]
    # Review file contains the error detail.
    review_text = (session_paths.review / "001.plan.md").read_text()
    assert "planner exploded" in review_text
    assert "Questions for Review" in review_text


def test_passthrough_resolution_writes_resolution_json_and_moves_plans_to_ready(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-passthrough",
        name="Packet 08 passthrough",
        pack="passthrough-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="passthrough-pack", resolution_executor="passthrough")
    session_paths = runtime_paths.session_paths(session.id)
    _write_staging_plan(session_paths.root, "031")
    _write_staging_plan(session_paths.root, "032", depends_on="031")

    result = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    resolution = parse_resolution_json(
        session_paths.resolution.read_text(encoding="utf-8"),
        source=session_paths.resolution,
    )
    assert result.ready_task_ids == ("031", "032")
    assert result.conflicts == ()
    assert [task.task_id for task in resolution.tasks] == ["031", "032"]
    assert resolution.tasks[0].anti_affinity == ()
    assert resolution.tasks[0].exec_order == 1
    assert resolution.tasks[1].depends_on == ("031",)
    assert resolution.tasks[1].exec_order == 2
    ready_text = (session_paths.ready / "032.plan.md").read_text(encoding="utf-8")
    assert "ANTI_AFFINITY: none" in ready_text
    assert "EXEC_ORDER: 2" in ready_text
    assert [task.task_id for task in store.list_ready_tasks(session.id)] == ["031", "032"]


def test_resolution_rerun_with_conflicts_advances_valid_tasks_and_reviews_broken(
    tmp_path: Path,
) -> None:
    """Conflicted tasks go to review; valid tasks still advance to ready."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-08-rerun-conflict",
        name="Packet 08 rerun conflict",
        pack="rerun-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="rerun-pack", resolution_executor="passthrough")
    session_paths = runtime_paths.session_paths(session.id)
    _write_staging_plan(session_paths.root, "035")

    first = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert first.ready_task_ids == ("035",)
    assert [task.task_id for task in store.list_ready_tasks(session.id)] == ["035"]

    _write_staging_plan(session_paths.root, "036", depends_on="999")

    second = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    # Valid task 035 advances; broken task 036 goes to review, not staging.
    assert second.ready_task_ids == ("035",)
    assert second.conflicts == ("unknown dependency 999 referenced by 036",)
    assert not any(session_paths.staging.glob("*.plan.md"))
    assert sorted(path.name for path in session_paths.ready.glob("*.plan.md")) == [
        "035.plan.md",
    ]
    assert sorted(path.name for path in session_paths.review.glob("*.plan.md")) == [
        "036.plan.md",
    ]
    assert [task.task_id for task in store.list_ready_tasks(session.id)] == ["035"]


@pytest.mark.parametrize("mode", ["script", "agent"])
def test_script_or_agent_resolution_rewrites_plan_headers_and_registers_ready_tasks(
    tmp_path: Path,
    mode: str,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id=f"session-08-{mode}",
        name=f"Packet 08 {mode}",
        pack=f"{mode}-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    if mode == "script":
        pack_root = _write_pack(
            tmp_path,
            name="script-pack",
            resolution_executor="script",
            resolve_script_body="""
            #!/usr/bin/env python3
            import json
            import sys
            from pathlib import Path

            session_root = Path(sys.argv[1])
            resolution_path = session_root / "resolution.json"
            resolution_path.write_text(json.dumps({
                "resolved_at": "2026-03-09T11:00:00Z",
                "tasks": [
                    {
                        "task_id": "041",
                        "depends_on": [],
                        "anti_affinity": ["042"],
                        "exec_order": 5,
                    },
                    {
                        "task_id": "042",
                        "depends_on": ["041"],
                        "anti_affinity": [],
                        "exec_order": 6,
                    },
                ],
                "groups": [],
                "conflicts": [],
                "notes": "script resolution"
            }) + "\\n", encoding="utf-8")
            """,
        )
        resolver_agent = None
    else:
        pack_root = _write_pack(tmp_path, name="agent-pack", resolution_executor="agent")

        def resolver_agent(*, model: str, prompt_path: Path, session_root: Path, **_: object) -> str:
            assert model == "test-resolver"
            assert prompt_path.name == "resolver.md"
            assert session_root == tmp_path
            return dedent(
                """
                {
                  "resolved_at": "2026-03-09T11:00:00Z",
                  "tasks": [
                    {
                      "task_id": "041",
                      "depends_on": [],
                      "anti_affinity": ["042"],
                      "exec_order": 5
                    },
                    {
                      "task_id": "042",
                      "depends_on": ["041"],
                      "anti_affinity": [],
                      "exec_order": 6
                    }
                  ],
                  "groups": [],
                  "conflicts": [],
                  "notes": "agent resolution"
                }
                """
            ).strip()

    session_paths = runtime_paths.session_paths(session.id)
    _write_staging_plan(session_paths.root, "041")
    _write_staging_plan(session_paths.root, "042")

    resolution_env = {"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)} if mode == "agent" else None
    result = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        resolver_agent=resolver_agent,
        env=resolution_env,
    )

    assert result.ready_task_ids == ("041", "042")
    ready_plan = parse_task_plan(
        (session_paths.ready / "041.plan.md").read_text(encoding="utf-8"),
        source=session_paths.ready / "041.plan.md",
    )
    assert ready_plan.anti_affinity == ("042",)
    assert ready_plan.exec_order == 5
    persisted = store.get_task(session.id, "042")
    assert persisted.depends_on == ("041",)
    assert persisted.exec_order == 6


def test_resolution_matches_by_plan_id_not_filename_stem(tmp_path: Path) -> None:
    """Regression: when staging filename has a descriptive suffix (e.g. 001_foo.plan.md)
    but PLAN_ID is just '001', the resolver output using '001' must still match."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-planid-mismatch",
        name="PLAN_ID vs filename",
        pack="agent-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="agent-pack", resolution_executor="agent")
    session_paths = runtime_paths.session_paths(session.id)

    # Write staging plans with descriptive filenames but short PLAN_IDs
    (session_paths.staging / "001_reorder_topbar.plan.md").write_text(
        _staged_plan_text("001"), encoding="utf-8"
    )
    (session_paths.staging / "002_auto_generate.plan.md").write_text(
        _staged_plan_text("002"), encoding="utf-8"
    )

    def resolver_agent(*, model: str, prompt_path: Path, session_root: Path, **_: object) -> str:
        return json.dumps({
            "resolved_at": "2026-03-09T11:00:00Z",
            "tasks": [
                {"task_id": "001", "depends_on": [], "anti_affinity": [], "exec_order": 1},
                {"task_id": "002", "depends_on": [], "anti_affinity": [], "exec_order": 1},
            ],
            "groups": [],
            "conflicts": [],
            "notes": "No conflicts",
        })

    result = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        resolver_agent=resolver_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.conflicts == ()
    assert sorted(result.ready_task_ids) == ["001", "002"]
    assert (session_paths.ready / "001.plan.md").is_file()
    assert (session_paths.ready / "002.plan.md").is_file()
    # Original descriptive-named files should be cleaned up
    assert not (session_paths.staging / "001_reorder_topbar.plan.md").exists()
    assert not (session_paths.staging / "002_auto_generate.plan.md").exists()


def test_unparseable_planner_output_goes_to_review_not_crash(tmp_path: Path) -> None:
    """Regression: when planner returns garbage (no YAML front matter),
    the item must go to review/ with an error note, not crash the pipeline."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-parse-error",
        name="Parse Error",
        pack="parse-err-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="parse-err-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_garbled.md", "# Garbled task\n")

    def planner_agent(**_: object) -> str:
        # Return output without YAML front matter — will trigger ArtifactParseError
        return "This is just plain text with no front matter at all.\nNo dashes."

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.staged_task_ids == ()
    assert result.review_task_ids == ("001",)
    review_path = session_paths.review / "001.plan.md"
    assert review_path.is_file()
    review_text = review_path.read_text(encoding="utf-8")
    assert "Planner output was unparseable" in review_text
    assert "This is just plain text" in review_text
    assert not any(session_paths.claimed.iterdir()), "claimed/ should be empty after planning"


def test_prepare_session_emits_pipeline_events_for_every_file_move(tmp_path: Path) -> None:
    """Every file transition (intake→claimed, claimed→staging/review) must fire
    on_pipeline_event so the WebSocket gets a fresh snapshot."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-pipeline-events",
        name="Pipeline Events",
        pack="evt-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="evt-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_good.md", "# Good task\n")
    _write_intake(session_paths.intake, "002_review.md", "# Review task\n")

    events: list[tuple[str, dict]] = []

    def on_pipeline_event(event_type: str, detail: dict) -> None:
        events.append((event_type, detail))

    def planner_agent(*, intake_path: Path, **_: object) -> str:
        task_id = intake_path.name.split("_", 1)[0]
        if "review" in intake_path.name:
            return _staged_plan_text(
                task_id,
                body_extra="\n## Questions for Review\n\n1. Why?\n",
            )
        return _staged_plan_text(task_id)

    prepare_session_for_execution(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        on_pipeline_event=on_pipeline_event,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    event_types = [e[0] for e in events]
    # Must have file_claimed events (intake → claimed)
    assert event_types.count("file_claimed") == 2, f"Expected 2 file_claimed events, got: {event_types}"
    # Must have file_planned events (claimed → staging/review)
    assert event_types.count("file_planned") >= 2, f"Expected 2+ file_planned events, got: {event_types}"
    # Must have file_resolved events (staging → ready)
    assert "file_resolved" in event_types, f"Expected file_resolved event, got: {event_types}"
    # Must have status_change events (planning, resolving, created)
    assert "status_change" in event_types, f"Expected status_change event, got: {event_types}"

    # Verify event details carry useful info
    claimed_events = [(t, d) for t, d in events if t == "file_claimed"]
    for _, detail in claimed_events:
        assert "file" in detail, "file_claimed events must include file name"

    planned_events = [(t, d) for t, d in events if t == "file_planned"]
    for _, detail in planned_events:
        assert "task_id" in detail, "file_planned events must include task_id"
        assert "destination" in detail, "file_planned events must include destination"


def test_prepare_session_all_review_reverts_to_created(tmp_path: Path) -> None:
    """When ALL items go to review and nothing is staged, the session
    must revert to 'created' so the operator can act."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-all-review",
        name="All Review",
        pack="all-review-pack",
        created_at="2026-03-09T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="all-review-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_task.md", "# Task\n")

    def planner_agent(**_: object) -> str:
        return _staged_plan_text(
            "001",
            body_extra="\n## Questions for Review\n\n1. Unclear scope.\n",
        )

    result = prepare_session_for_execution(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.review_task_ids == ("001",)
    assert result.ready_task_ids == ()
    assert store.get_session(session.id).status == "created"


def test_agent_writing_files_directly_does_not_create_ghost_duplicates(tmp_path: Path) -> None:
    """Regression: if the planner agent writes plan files directly to staging/review
    AND returns conversational summary text (not parseable as a plan), the pipeline
    must NOT create ghost duplicate entries like '001.plan.md' alongside the agent's
    '001_description.plan.md'.
    """
    store, runtime_paths = _build_store(tmp_path)
    pack_root = _write_pack(
        runtime_paths.packs, name="claude-code", planning_enabled=True,
    )
    session = store.create_session(session_id="ghost-test", name="Ghost Test", pack="claude-code", created_at="2026-03-10T00:00:00Z")
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_reorder_topbar.md", "# Reorder the topbar\n")
    _write_intake(session_paths.intake, "002_auto_generate.md", "# Auto generate intake\n")

    call_count = 0

    def agent_that_writes_files_directly(**kwargs: object) -> str:
        """Simulates a planner agent that writes plan files AND returns a summary."""
        nonlocal call_count
        call_count += 1
        intake_path = kwargs["intake_path"]
        prefix = intake_path.name.split("_", 1)[0]

        if prefix == "001":
            # Agent writes a review plan directly
            plan_text = _staged_plan_text(
                "001", body_extra="\n## Questions for Review\n\n1. Which topbar?\n",
            )
            review_path = session_paths.review / "001_reorder_topbar.plan.md"
            review_path.write_text(plan_text, encoding="utf-8")
            return "Intake is empty. Plan 001 routed to review/."
        else:
            # Agent writes a staging plan directly
            plan_text = _staged_plan_text("002")
            staging_path = session_paths.staging / "002_auto_generate.plan.md"
            staging_path.write_text(plan_text, encoding="utf-8")
            return "Intake is empty. Plan 002 written to staging/."

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=agent_that_writes_files_directly,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    # The agent wrote files directly — pipeline should detect them, not create ghosts.
    review_files = sorted(p.name for p in session_paths.review.glob("*.plan.md"))
    staging_files = sorted(p.name for p in session_paths.staging.glob("*.plan.md"))

    # No ghost "001.plan.md" or "002.plan.md" — only the agent's named files.
    assert "001.plan.md" not in review_files, f"Ghost duplicate in review: {review_files}"
    assert "002.plan.md" not in review_files, f"Ghost duplicate in review: {review_files}"
    assert "002.plan.md" not in staging_files or staging_files == ["002_auto_generate.plan.md"], \
        f"Ghost duplicate in staging: {staging_files}"

    # The correctly-named files should exist.
    assert "001_reorder_topbar.plan.md" in review_files
    assert "002_auto_generate.plan.md" in staging_files

    # Pipeline should account for both files.
    assert "001_reorder_topbar" in result.review_task_ids or "001" in result.review_task_ids
    assert "002_auto_generate" in result.staged_task_ids or "002" in result.staged_task_ids


def test_planner_agent_receives_repo_root_when_env_specifies_it(tmp_path: Path) -> None:
    """The planner agent must receive the repo root as session_root (not the
    session pipeline directory) when COGNITIVE_SWITCHYARD_REPO_ROOT is set."""
    store, runtime_paths = _build_store(tmp_path)
    pack_root = _write_pack(
        runtime_paths.packs, name="claude-code", planning_enabled=True,
    )
    session = store.create_session(session_id="cwd-test", name="CWD Test", pack="claude-code", created_at="2026-03-10T00:00:00Z")
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_task.md", "# Task\n")

    repo_root = tmp_path / "fake_repo"
    repo_root.mkdir()

    captured_session_root = []

    def capture_cwd_agent(**kwargs: object) -> str:
        captured_session_root.append(kwargs["session_root"])
        return _staged_plan_text("001")

    run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=capture_cwd_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(repo_root)},
    )

    assert len(captured_session_root) == 1
    assert captured_session_root[0] == repo_root


def test_plan_id_collision_with_done_raises_value_error(tmp_path: Path) -> None:
    """Intake items whose numeric prefix matches a completed plan in done/
    must be rejected with a ValueError before any planning work begins."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-collision",
        name="Collision Test",
        pack="collision-pack",
        created_at="2026-03-10T00:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="collision-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)

    # Place a completed plan in done/
    done_plan = session_paths.done / "001_old_feature.plan.md"
    done_plan.write_text(_staged_plan_text("001"), encoding="utf-8")

    # Place a new intake item with the same numeric prefix
    _write_intake(session_paths.intake, "001_new_feature.md", "# New feature\n")
    # Also place a non-colliding intake item
    _write_intake(session_paths.intake, "002_safe.md", "# Safe\n")

    events: list[tuple[str, dict]] = []

    def on_event(event_type: str, detail: dict) -> None:
        events.append((event_type, detail))

    with pytest.raises(ValueError, match="Plan ID collisions"):
        run_planning_phase(
            store=store,
            session_id=session.id,
            pack_manifest=load_pack_manifest(pack_root),
            planner_agent=lambda **_: "",
            env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
            on_pipeline_event=on_event,
        )

    # Verify the collision event was emitted
    collision_events = [e for e in events if e[0] == "plan_id_collision"]
    assert len(collision_events) == 1
    assert "001_new_feature.md" in collision_events[0][1]["collisions"][0]


def test_plan_id_collision_with_dash_separator_in_done(tmp_path: Path) -> None:
    """Collision detection must also match done files using dash separator
    (e.g. 003-description.plan.md)."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-collision-dash",
        name="Collision Dash Test",
        pack="collision-dash-pack",
        created_at="2026-03-10T00:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="collision-dash-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)

    # Place a completed plan using dash separator in done/
    done_plan = session_paths.done / "003-old_feature.plan.md"
    done_plan.write_text(_staged_plan_text("003"), encoding="utf-8")

    _write_intake(session_paths.intake, "003_new_feature.md", "# New feature\n")

    with pytest.raises(ValueError, match="Plan ID collisions"):
        run_planning_phase(
            store=store,
            session_id=session.id,
            pack_manifest=load_pack_manifest(pack_root),
            planner_agent=lambda **_: "",
            env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
        )


def test_no_collision_when_done_is_empty(tmp_path: Path) -> None:
    """When done/ has no matching plans, planning should proceed normally."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-no-collision",
        name="No Collision Test",
        pack="no-collision-pack",
        created_at="2026-03-10T00:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="no-collision-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_task.md", "# Task\n")

    def planner_agent(**_: object) -> str:
        return _staged_plan_text("001")

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert result.staged_task_ids == ("001",)


def test_missing_repo_root_raises_when_planning_enabled(tmp_path: Path) -> None:
    """When agent planning is enabled, COGNITIVE_SWITCHYARD_REPO_ROOT must be
    present in env.  Missing env or missing key must raise ValueError."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-no-repo-root",
        name="No Repo Root",
        pack="no-root-pack",
        created_at="2026-03-10T00:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="no-root-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)
    _write_intake(session_paths.intake, "001_task.md", "# Task\n")

    # env=None
    with pytest.raises(ValueError, match="COGNITIVE_SWITCHYARD_REPO_ROOT"):
        run_planning_phase(
            store=store,
            session_id=session.id,
            pack_manifest=load_pack_manifest(pack_root),
            planner_agent=lambda **_: "",
            env=None,
        )

    # env without the key
    with pytest.raises(ValueError, match="COGNITIVE_SWITCHYARD_REPO_ROOT"):
        run_planning_phase(
            store=store,
            session_id=session.id,
            pack_manifest=load_pack_manifest(pack_root),
            planner_agent=lambda **_: "",
            env={"OTHER_VAR": "value"},
        )


def test_missing_repo_root_raises_when_agent_resolution_enabled(tmp_path: Path) -> None:
    """When resolution executor is 'agent', COGNITIVE_SWITCHYARD_REPO_ROOT must
    be present in env."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-no-repo-root-resolve",
        name="No Repo Root Resolve",
        pack="no-root-resolve-pack",
        created_at="2026-03-10T00:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="no-root-resolve-pack", resolution_executor="agent")
    session_paths = runtime_paths.session_paths(session.id)
    _write_staging_plan(session_paths.root, "041")

    def resolver_agent(**_: object) -> str:
        return "{}"

    with pytest.raises(ValueError, match="COGNITIVE_SWITCHYARD_REPO_ROOT"):
        run_resolution_phase(
            store=store,
            session_id=session.id,
            pack_manifest=load_pack_manifest(pack_root),
            resolver_agent=resolver_agent,
            env=None,
        )

    with pytest.raises(ValueError, match="COGNITIVE_SWITCHYARD_REPO_ROOT"):
        run_resolution_phase(
            store=store,
            session_id=session.id,
            pack_manifest=load_pack_manifest(pack_root),
            resolver_agent=resolver_agent,
            env={"OTHER_VAR": "value"},
        )


# ---------------------------------------------------------------------------
# Dual-state guard tests (Guard 1, Guard 2, Guard 3)
# ---------------------------------------------------------------------------


def test_intake_skips_task_already_in_ready(tmp_path: Path) -> None:
    """Guard 1: intake item whose prefix already exists in ready/ is skipped."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-guard1-ready",
        name="Guard 1 ready",
        pack="guard1-pack",
        created_at="2026-03-16T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="guard1-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)

    # Pre-place a plan with prefix 001 in ready/
    (session_paths.ready / "001.plan.md").write_text(
        _staged_plan_text("001"), encoding="utf-8"
    )

    # Intake: 001 conflicts with ready, 002 should proceed
    _write_intake(session_paths.intake, "001_rework.md", "# Rework\n")
    _write_intake(session_paths.intake, "002_new.md", "# New\n")

    planner_call_count = 0

    def planner_agent(*, intake_path: Path, **_: object) -> str:
        nonlocal planner_call_count
        planner_call_count += 1
        return _staged_plan_text(intake_path.name.split("_", 1)[0])

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    # 001_rework.md must still be in intake/ (not claimed or planned)
    assert (session_paths.intake / "001_rework.md").exists(), \
        "001_rework.md should remain in intake/"
    # Only 002 should have been staged
    assert result.staged_task_ids == ("002",)
    assert "001" not in result.staged_task_ids
    assert "001" not in result.review_task_ids
    # Planner was called exactly once (for 002)
    assert planner_call_count == 1


def test_intake_skips_task_in_review(tmp_path: Path) -> None:
    """Guard 1: intake item whose prefix already exists in review/ is skipped."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-guard1-review",
        name="Guard 1 review",
        pack="guard1r-pack",
        created_at="2026-03-16T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="guard1r-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)

    # Pre-place a plan with prefix 001 in review/
    (session_paths.review / "001.plan.md").write_text(
        _staged_plan_text("001", body_extra="\n## Questions for Review\n\n1. Unclear.\n"),
        encoding="utf-8",
    )

    _write_intake(session_paths.intake, "001_retry.md", "# Retry\n")

    planner_called = False

    def planner_agent(**_: object) -> str:
        nonlocal planner_called
        planner_called = True
        return _staged_plan_text("001")

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert (session_paths.intake / "001_retry.md").exists(), \
        "001_retry.md should remain in intake/"
    assert not planner_called, "Planner must not be called for duplicate intake"
    assert result.staged_task_ids == ()
    assert result.review_task_ids == ()


def test_intake_skips_task_in_active_slot(tmp_path: Path) -> None:
    """Guard 1: intake item whose prefix already exists in an active worker slot is skipped."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-guard1-slot",
        name="Guard 1 slot",
        pack="guard1s-pack",
        created_at="2026-03-16T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="guard1s-pack", planning_enabled=True)
    session_paths = runtime_paths.session_paths(session.id)

    # Simulate an active worker slot with task 001
    worker_slot = session_paths.workers / "0"
    worker_slot.mkdir(parents=True, exist_ok=True)
    (worker_slot / "001.plan.md").write_text(_staged_plan_text("001"), encoding="utf-8")

    _write_intake(session_paths.intake, "001_redo.md", "# Redo\n")

    planner_called = False

    def planner_agent(**_: object) -> str:
        nonlocal planner_called
        planner_called = True
        return _staged_plan_text("001")

    result = run_planning_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
        planner_agent=planner_agent,
        env={"COGNITIVE_SWITCHYARD_REPO_ROOT": str(tmp_path)},
    )

    assert (session_paths.intake / "001_redo.md").exists(), \
        "001_redo.md should remain in intake/"
    assert not planner_called, "Planner must not be called for duplicate intake"
    assert result.staged_task_ids == ()
    assert result.review_task_ids == ()
    # Worker slot file must be untouched
    assert (worker_slot / "001.plan.md").exists(), "Worker slot file must be untouched"


def test_pre_write_cleanup_removes_stale_ready(tmp_path: Path) -> None:
    """Guard 2 (_clear_task_from_dirs) removes stale plan files from specified directories."""
    from cognitive_switchyard.planning_runtime import _clear_task_from_dirs

    ready = tmp_path / "ready"
    review = tmp_path / "review"
    staging = tmp_path / "staging"
    for d in (ready, review, staging):
        d.mkdir()

    # Place stale files
    (ready / "001.plan.md").write_text("stale", encoding="utf-8")
    (review / "001_old.plan.md").write_text("stale", encoding="utf-8")

    removed = _clear_task_from_dirs("001", [ready, review, staging])

    assert not (ready / "001.plan.md").exists()
    assert not (review / "001_old.plan.md").exists()
    assert len(removed) == 2


def test_resolution_cleanup_removes_stale_review(tmp_path: Path) -> None:
    """Guard 3: stale review/ copy is removed when a task is written to ready/ during resolution."""
    store, runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-guard3-review",
        name="Guard 3 review cleanup",
        pack="guard3-pack",
        created_at="2026-03-16T10:00:00Z",
    )
    pack_root = _write_pack(tmp_path, name="guard3-pack", resolution_executor="passthrough")
    session_paths = runtime_paths.session_paths(session.id)

    # Place plan in staging (resolution input) and a stale copy in review/
    _write_staging_plan(session_paths.root, "001")
    (session_paths.review / "001.plan.md").write_text(
        _staged_plan_text("001", body_extra="\n## Questions for Review\n\n1. Old?\n"),
        encoding="utf-8",
    )

    result = run_resolution_phase(
        store=store,
        session_id=session.id,
        pack_manifest=load_pack_manifest(pack_root),
    )

    assert result.ready_task_ids == ("001",)
    assert (session_paths.ready / "001.plan.md").is_file(), "Plan must be in ready/"
    assert not (session_paths.review / "001.plan.md").exists(), \
        "Stale review/ copy must be removed by Guard 3"
    assert not (session_paths.staging / "001.plan.md").exists(), \
        "Staging copy must be cleaned up"


def test_no_cleanup_for_active_tasks(tmp_path: Path) -> None:
    """_clear_task_from_dirs does not touch directories not in its dirs list,
    confirming active worker slots are protected."""
    from cognitive_switchyard.planning_runtime import _clear_task_from_dirs

    worker_slot = tmp_path / "workers" / "0"
    worker_slot.mkdir(parents=True)
    staging = tmp_path / "staging"
    staging.mkdir()

    (worker_slot / "001.plan.md").write_text("active", encoding="utf-8")
    (staging / "001.plan.md").write_text("stale", encoding="utf-8")

    # Only pass staging, not the worker slot
    removed = _clear_task_from_dirs("001", [staging])

    assert not (staging / "001.plan.md").exists()
    assert (worker_slot / "001.plan.md").exists(), "Worker slot file must be untouched"
    assert len(removed) == 1
