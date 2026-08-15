from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from .__init__ import __version__
from .build_info import format_build_info, runtime_entrypoint
from .config import (
    ConfigError,
    default_runtime_home,
    describe_duplicate_labels,
    load_config,
    missing_credentials,
    validate_selected_providers,
)
from .diffing import compare_models
from .models import BaselineInfo, ModelDelta, ProviderScanResult
from .normalize import normalize_models
from .notifications import send_notification
from .provider_profiles import PROFILE_REGISTRY, resolve_profile
from .providers import ProviderFetchError, fetch_raw_models
from .reporting import (
    DEFAULT_REPORT_SHOW_FIELDS,
    DEFAULT_REPORT_SQUELCH_FIELDS,
    ReportDetailPolicy,
    render_changes_report,
    render_healthcheck_report,
    render_history_report,
    render_model_list_report,
    render_providers_report,
    make_report_detail_policy,
    render_scan_report,
)
from .storage import Store
from .time_utils import local_today, now_utc


COMMANDS = {"scan", "history", "changes", "providers", "healthcheck"}


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    parser = build_parser()
    argv_for_parse = _normalize_argv_for_default_scan(raw_argv)
    args = parser.parse_args(argv_for_parse)
    project_root = Path(__file__).resolve().parents[1]

    if args.command == "healthcheck":
        return run_healthcheck(args=args, project_root=project_root)

    try:
        loaded = load_config(project_root)
    except ConfigError as exc:
        parser.exit(status=2, message=f"{exc}\n")

    loaded.runtime_paths.ensure_directories()
    logger = _configure_logger(loaded)
    store = Store(loaded.runtime_paths.database_path)
    store.initialize()
    store.upsert_provider_configs(loaded.providers, updated_at=_now().isoformat())

    try:
        if args.command == "providers":
            return run_providers(args=args, loaded=loaded)
        if args.command == "history":
            return run_history(args=args, loaded=loaded, store=store)
        if args.command == "changes":
            return run_changes(args=args, loaded=loaded, store=store)
        return run_scan(args=args, loaded=loaded, store=store, logger=logger)
    except ConfigError as exc:
        parser.exit(status=2, message=f"{exc}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="model_sentinel",
        description="Track LLM provider model-list changes over time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Default behavior:\n"
            "  Fetch enabled providers, compare to a saved baseline, print a report,\n"
            "  and do not save a new snapshot unless explicitly requested.\n\n"
            "Examples:\n"
            "  model_sentinel\n"
            "      Compare current provider lists to the previous saved baseline.\n\n"
            "  model_sentinel scan --save\n"
            "      Fetch provider lists and save a new baseline snapshot.\n\n"
            "  model_sentinel history --provider openrouter --model chatgpt-5.2\n"
            "      Show saved history for one provider/model pair.\n\n"
            "  model_sentinel history --provider openrouter --model list\n"
            "      List known saved model IDs for OpenRouter.\n\n"
            "  model_sentinel history --provider openrouter --model list chatgpt\n"
            "      Filter the saved model list by partial match on model ID or display name.\n\n"
            "  model_sentinel providers\n"
            "      Show configured providers and whether their credential env vars are present.\n\n"
            "  model_sentinel healthcheck\n"
            "      Validate config, credentials, and runtime readiness.\n\n"
            "  model_sentinel changes --since 2026-03-01\n"
            "      Show all recorded changes across all providers since March 1.\n\n"
            "  model_sentinel changes --provider openrouter --since 2026-03-01 --until 2026-03-14\n"
            "      Show OpenRouter changes in a specific date range.\n\n"
            "First run:\n"
            "  If no baseline exists yet, run:\n"
            "      model_sentinel scan --save\n"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"model_sentinel {__version__} {format_build_info(full_hash=True)}",
    )
    subparsers = parser.add_subparsers(dest="command", required=False)

    scan_parser = subparsers.add_parser(
        "scan",
        help="Fetch provider model lists, compare them, and optionally save a snapshot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  model_sentinel scan\n"
            "      Compare all enabled providers against the previous saved baseline.\n\n"
            "  model_sentinel scan --save\n"
            "      Save a new snapshot after reporting differences.\n\n"
            "  model_sentinel scan --provider abacus --save --format json --output abacus.json\n"
            "      Save a new Abacus snapshot and write a JSON report.\n\n"
            "  model_sentinel scan --baseline-date 2025-10-31\n"
            "      Compare against a saved scrape from 2025-10-31.\n"
        ),
    )
    _add_scan_arguments(scan_parser)

    history_parser = subparsers.add_parser(
        "history",
        help="Query saved history for one provider/model pair.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  model_sentinel history --provider openrouter --model chatgpt-5.2\n"
            "      Show the saved history for that model on OpenRouter.\n\n"
            "  model_sentinel history --provider openrouter --model list\n"
            "      List known saved model IDs for OpenRouter.\n\n"
            "  model_sentinel history --provider openrouter --model list chatgpt\n"
            "      Filter the saved model list by partial match on model ID or display name.\n\n"
            "  model_sentinel history --provider abacus --model gpt-4.1 --since 2025-01-01\n"
            "      Show changes since January 1, 2025.\n\n"
            "  model_sentinel history --provider openrouter --model chatgpt-5.2 \\\n"
            "      --since 2025-01-01 --until 2025-12-31\n"
            "      Show changes within the inclusive 2025 date range.\n"
        ),
    )
    history_parser.add_argument("--provider", required=True, help="configured provider ID to query")
    history_parser.add_argument("--model", required=True, help="provider-local model ID to query")
    history_parser.add_argument("--since", type=_parse_date, help="restrict results to dates on or after this date (inclusive)")
    history_parser.add_argument("--until", type=_parse_date, help="restrict results to dates on or before this date (inclusive)")
    history_parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    history_parser.add_argument("--detail", choices=("default", "all", "squelched"), help="field detail mode for human-readable change output")
    history_parser.add_argument("--output", type=Path, help="write the result to a file")
    history_parser.add_argument("pattern", nargs="?", help="optional partial-match filter for `--model list`")

    changes_parser = subparsers.add_parser(
        "changes",
        help="Show all recorded changes across providers and models in a date range.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  model_sentinel changes --since 2026-03-01\n"
            "      Show all changes since March 1 across all providers.\n\n"
            "  model_sentinel changes --since 2026-03-01 --until 2026-03-14\n"
            "      Show changes within a date range.\n\n"
            "  model_sentinel changes --provider openrouter --since 2026-03-01\n"
            "      Show changes for one provider only.\n\n"
            "  model_sentinel changes\n"
            "      Show all recorded changes (full history).\n"
        ),
    )
    changes_parser.add_argument("--provider", help="limit to one configured provider")
    changes_parser.add_argument("--since", type=_parse_date, help="start date (inclusive, YYYY-MM-DD)")
    changes_parser.add_argument("--until", type=_parse_date, help="end date (inclusive, YYYY-MM-DD)")
    changes_parser.add_argument("--format", choices=("text", "json"), default="text")
    changes_parser.add_argument("--detail", choices=("default", "all", "squelched"), help="field detail mode for human-readable change output")
    changes_parser.add_argument("--output", type=Path, help="write the result to a file instead of stdout")

    providers_parser = subparsers.add_parser("providers", help="List configured providers and their status.")
    providers_parser.formatter_class = argparse.RawDescriptionHelpFormatter
    providers_parser.epilog = (
        "examples:\n"
        "  model_sentinel providers\n"
        "      Show configured providers and whether they are enabled.\n\n"
        "  model_sentinel providers --format json\n"
        "      Emit provider configuration summary as JSON.\n"
    )
    providers_parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")

    healthcheck_parser = subparsers.add_parser(
        "healthcheck",
        help="Validate config, secrets, and runtime readiness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  model_sentinel healthcheck\n"
            "      Run a human-readable readiness check.\n\n"
            "  model_sentinel healthcheck --format json\n"
            "      Emit structured validation results.\n"
        ),
    )
    healthcheck_parser.add_argument("--format", choices=("text", "json", "markdown"), default="text")

    return parser


def run_scan(*, args: argparse.Namespace, loaded, store: Store, logger: logging.Logger) -> int:
    logger.info(
        "Runtime build: %s executable=%s",
        format_build_info(full_hash=False),
        runtime_entrypoint(),
    )
    selected = validate_selected_providers(loaded.providers, provider_id=args.provider)
    missing = missing_credentials(selected, os.environ)
    if missing:
        message = "Missing required credential environment variables: " + ", ".join(sorted(missing))
        logger.error(message)
        report_path = _determine_error_report_path(args=args, loaded=loaded, generated_at=_now().isoformat())
        _emit_output(message, output_path=report_path if args.output else None)
        if report_path and not args.output:
            report_path.write_text(message, encoding="utf-8")
        if _should_notify_for_errors(args=args, loaded=loaded):
            send_notification(
                title="Model Sentinel: credential error",
                message=f"Report: {report_path or 'stdout only'}",
                report_path=report_path,
                open_target=loaded.settings.notify_open_target,
                terminal_notifier_path=loaded.settings.terminal_notifier_path,
                sound_name=loaded.settings.notify_sound,
                runtime_home=loaded.settings.runtime_home,
            )
        return 2

    generated_at = _now().isoformat()
    provider_results: list[ProviderScanResult] = []
    selected_provider_ids = ", ".join(provider.provider_id for provider in selected)
    logger.info("Scanning providers: %s", selected_provider_ids)

    for provider in selected:
        started = _now()
        profile = resolve_profile(
            provider.kind,
            price_multiplier=provider.price_multiplier,
            price_divisor=provider.price_divisor,
        )
        baseline = _resolve_baseline(store, provider.provider_id, args)
        if isinstance(baseline, str):
            result = ProviderScanResult(
                provider_id=provider.provider_id,
                provider_label=provider.label,
                status="baseline_missing",
                current_count=0,
                saved=False,
                baseline=None,
                baseline_message=baseline,
                scrape_id=None,
                added=(),
                removed=(),
                changed=(),
                profile=profile,
            )
            provider_results.append(result)
            continue
        try:
            raw_models = fetch_raw_models(
                provider,
                os.environ[provider.credential_env_var],
                profile,
            )
            normalized_models = normalize_models(
                provider,
                raw_models,
                profile,
            )
            current_map = {model.provider_model_id: model for model in normalized_models}
            if baseline:
                baseline_models = store.load_saved_models(baseline.scrape_id)
                added, removed, changed = compare_models(
                    baseline_models=baseline_models,
                    current_models=current_map,
                )
            else:
                added = tuple(
                    ModelDelta("added", model.provider_model_id, model.display_name, ())
                    for model in normalized_models
                )
                removed = ()
                changed = ()
            completed = _now()
            scrape_id = store.create_scrape(
                provider_id=provider.provider_id,
                started_at=started.isoformat(),
                completed_at=completed.isoformat(),
                status="success",
                baseline_mode=_baseline_mode(args),
                baseline_scrape_id=baseline.scrape_id if baseline else None,
                saved_snapshot=bool(args.save),
                model_count=len(normalized_models),
                error_message=None,
            )
            if args.save:
                store.save_snapshot_models(scrape_id=scrape_id, provider_id=provider.provider_id, models=normalized_models)
                store.record_field_changes(
                    provider_id=provider.provider_id,
                    from_scrape_id=baseline.scrape_id if baseline else None,
                    to_scrape_id=scrape_id,
                    deltas=added + removed + changed,
                    detected_at=completed.isoformat(),
                )
            baseline_message = None
            if baseline is None and args.save:
                baseline_message = "No prior saved baseline existed; current snapshot was saved as the initial baseline."
            result = ProviderScanResult(
                provider_id=provider.provider_id,
                provider_label=provider.label,
                status="success",
                current_count=len(normalized_models),
                saved=bool(args.save),
                baseline=baseline,
                baseline_message=baseline_message,
                scrape_id=scrape_id,
                added=tuple(added),
                removed=tuple(removed),
                changed=tuple(changed),
                profile=profile,
            )
            provider_results.append(result)
        except (ProviderFetchError, ValueError) as exc:
            completed = _now()
            scrape_id = store.create_scrape(
                provider_id=provider.provider_id,
                started_at=started.isoformat(),
                completed_at=completed.isoformat(),
                status="error",
                baseline_mode=_baseline_mode(args),
                baseline_scrape_id=baseline.scrape_id if isinstance(baseline, BaselineInfo) else None,
                saved_snapshot=False,
                model_count=0,
                error_message=str(exc),
            )
            result = ProviderScanResult(
                provider_id=provider.provider_id,
                provider_label=provider.label,
                status="error",
                current_count=0,
                saved=False,
                baseline=baseline if isinstance(baseline, BaselineInfo) else None,
                baseline_message=None if isinstance(baseline, BaselineInfo) else baseline,
                scrape_id=scrape_id,
                added=(),
                removed=(),
                changed=(),
                profile=profile,
                error_message=str(exc),
            )
            provider_results.append(result)
            logger.error("%s failed: %s", provider.provider_id, exc)

    report_path = _determine_report_path(args=args, loaded=loaded, provider_results=provider_results, generated_at=generated_at)
    detail_policy = _report_detail_policy(args=args, loaded=loaded)
    report_text = render_scan_report(
        generated_at=generated_at,
        command="scan",
        format_name=args.format,
        provider_results=provider_results,
        detail_policy=detail_policy,
    )
    _emit_output(report_text, output_path=report_path if args.output else None)
    if report_path and not args.output:
        report_path.write_text(report_text, encoding="utf-8")

    # Auto-generate HTML companion report when changes are detected
    has_changes = any(r.change_count > 0 for r in provider_results)
    html_report_path = None
    if has_changes and report_path and not args.output:
        html_report_path = report_path.with_suffix(".html")
        html_text = render_scan_report(
            generated_at=generated_at,
            command="scan",
            format_name="html",
            provider_results=provider_results,
            detail_policy=detail_policy,
        )
        html_report_path.write_text(html_text, encoding="utf-8")
        logger.info("HTML report written to %s", html_report_path)
        full_html_report_path = report_path.with_name(f"{report_path.stem}_full.html")
        full_html_text = render_scan_report(
            generated_at=generated_at,
            command="scan",
            format_name="html",
            provider_results=provider_results,
            detail_policy=make_report_detail_policy(
                mode="all",
                show_fields=detail_policy.show_fields,
                squelch_fields=detail_policy.squelch_fields,
                unclassified_limit=detail_policy.unclassified_limit,
            ),
        )
        full_html_report_path.write_text(full_html_text, encoding="utf-8")
        logger.info("Full HTML report written to %s", full_html_report_path)

    _maybe_notify(args=args, loaded=loaded, provider_results=provider_results, report_path=html_report_path or report_path)

    _cleanup_old_reports(loaded.runtime_paths.report_dir, loaded.settings.report_retention_days, logger)

    return 1 if any(result.status == "error" for result in provider_results) else 0


def run_history(*, args: argparse.Namespace, loaded, store: Store) -> int:
    selected = validate_selected_providers(
        loaded.providers,
        provider_id=args.provider,
    )
    provider = selected[0]
    profile = resolve_profile(
        provider.kind,
        price_multiplier=provider.price_multiplier,
        price_divisor=provider.price_divisor,
    )
    if args.since and args.until and args.since > args.until:
        raise SystemExit("--since cannot be later than --until")
    if args.pattern and args.model != "list":
        raise ConfigError("The optional history pattern is only supported with `--model list`.")
    if args.model == "list":
        models = store.list_known_models(
            provider_id=args.provider,
            since=args.since,
            until=args.until,
        )
        if args.pattern:
            needle = args.pattern.casefold()
            models = tuple(
                row for row in models
                if needle in (row["provider_model_id"] or "").casefold()
                or needle in (row["display_name"] or "").casefold()
            )
        report = render_model_list_report(
            provider_id=args.provider,
            format_name=args.format,
            models=models,
        )
        _emit_output(report, output_path=args.output)
        return 0
    first_seen, last_seen, events = store.history_events(
        provider_id=args.provider,
        model_id=args.model,
        since=args.since,
        until=args.until,
    )
    latest_model = store.get_latest_model_snapshot(provider_id=args.provider, model_id=args.model)
    report = render_history_report(
        provider_id=args.provider,
        model_id=args.model,
        format_name=args.format,
        first_seen=first_seen,
        last_seen=last_seen,
        events=events,
        latest_model=latest_model,
        profile=profile,
        detail_policy=_report_detail_policy(args=args, loaded=loaded),
    )
    _emit_output(report, output_path=args.output)
    return 0


def run_providers(*, args: argparse.Namespace, loaded) -> int:
    store = Store(loaded.runtime_paths.database_path)
    store.initialize()
    provider_rows = []
    for provider in loaded.providers:
        provider_rows.append(
            {
                "provider_id": provider.provider_id,
                "label": provider.label,
                "kind": provider.kind,
                "enabled": provider.enabled,
                "base_url": provider.base_url,
                "models_path": provider.models_path,
                "credential_env_var": provider.credential_env_var,
                "credential_present": bool(os.environ.get(provider.credential_env_var, "").strip()),
                "last_successful_scan": store.get_latest_successful_scrape_time(provider.provider_id) or "none",
            }
        )
    report = render_providers_report(format_name=args.format, provider_rows=provider_rows)
    _emit_output(report, output_path=None)
    return 0


def run_changes(*, args: argparse.Namespace, loaded, store: Store) -> int:
    if args.provider:
        validate_selected_providers(loaded.providers, provider_id=args.provider)
    if args.since and args.until and args.since > args.until:
        raise SystemExit("--since cannot be later than --until")
    changes = store.recent_changes(
        provider_id=args.provider,
        since=args.since,
        until=args.until,
    )
    provider_profiles = {
        p.provider_id: resolve_profile(
            p.kind,
            price_multiplier=p.price_multiplier,
            price_divisor=p.price_divisor,
        )
        for p in loaded.providers
    }
    since_iso = args.since.isoformat() if args.since else None
    until_iso = args.until.isoformat() if args.until else None
    report = render_changes_report(
        format_name=args.format,
        provider_id=args.provider,
        since=since_iso,
        until=until_iso,
        changes=changes,
        provider_profiles=provider_profiles,
        detail_policy=_report_detail_policy(args=args, loaded=loaded),
    )

    if args.output:
        _emit_output(report, output_path=args.output)
    else:
        _emit_output(report, output_path=None)
        # Auto-save text + HTML to the report directory when changes exist
        if changes:
            report_dir = loaded.runtime_paths.report_dir
            report_dir.mkdir(parents=True, exist_ok=True)
            safe_stamp = _now().isoformat().replace(":", "").replace("+", "_")
            text_path = report_dir / f"changes_{safe_stamp}.txt"
            text_path.write_text(report, encoding="utf-8")
            html_text = render_changes_report(
                format_name="html",
                provider_id=args.provider,
                since=since_iso,
                until=until_iso,
                changes=changes,
                provider_profiles=provider_profiles,
                detail_policy=_report_detail_policy(args=args, loaded=loaded),
            )
            html_path = text_path.with_suffix(".html")
            html_path.write_text(html_text, encoding="utf-8")
    return 0


def run_healthcheck(*, args: argparse.Namespace, project_root: Path) -> int:
    checks: list[dict[str, str]] = [
        {
            "check": "runtime_build",
            "status": "ok",
            "detail": (
                f"{format_build_info(full_hash=False)} "
                f"executable={runtime_entrypoint()}"
            ),
        }
    ]
    runtime_home = default_runtime_home()
    providers_path = runtime_home / "providers.env"
    settings_path = runtime_home / "settings.env"
    checks.append(_file_check("providers.env", providers_path))
    checks.append(_file_check("settings.env", settings_path))

    status_code = 0
    try:
        loaded = load_config(project_root)
    except ConfigError as exc:
        checks.append({"check": "config_load", "status": "error", "detail": str(exc)})
        report = render_healthcheck_report(format_name=args.format, checks=checks)
        _emit_output(report, output_path=None)
        return 1

    # Advisory, and deliberately over EVERY provider rather than the enabled
    # ones: a disabled provider still appears in `providers` listings and still
    # owns recorded history that `changes` renders under its label, so its
    # label is just as readable-or-not. `warn` leaves `status_code` alone --
    # this is a legibility note about a config that works, not a failure.
    duplicate_labels = describe_duplicate_labels(loaded.providers, providers_path)
    if duplicate_labels:
        checks.append({"check": "provider_labels", "status": "warn", "detail": duplicate_labels})
    else:
        checks.append(
            {"check": "provider_labels", "status": "ok", "detail": "Every provider label is distinct"}
        )

    for provider in loaded.providers:
        if provider.kind.lower() in PROFILE_REGISTRY:
            continue
        checks.append(
            {
                "check": "provider_profile",
                "status": "warn",
                "detail": (
                    f"Provider '{provider.provider_id}' kind '{provider.kind}' has no "
                    "registered profile; using the generic profile (labels and "
                    "price-field detection will be best-effort)."
                ),
            }
        )

    selected = tuple(provider for provider in loaded.providers if provider.enabled)
    missing = missing_credentials(selected, os.environ)
    if missing:
        status_code = 1
        checks.append(
            {
                "check": "credentials",
                "status": "error",
                "detail": "Missing required env vars: " + ", ".join(sorted(missing)),
            }
        )
    else:
        checks.append({"check": "credentials", "status": "ok", "detail": "All required credential env vars are present"})
    try:
        loaded.runtime_paths.ensure_directories()
        store = Store(loaded.runtime_paths.database_path)
        store.initialize()
        checks.append({"check": "runtime_paths", "status": "ok", "detail": f"Runtime home ready at {loaded.runtime_paths.runtime_home}"})
        checks.append({"check": "database", "status": "ok", "detail": f"SQLite database ready at {loaded.runtime_paths.database_path}"})
    except OSError as exc:
        status_code = 1
        checks.append({"check": "runtime_paths", "status": "error", "detail": str(exc)})
    report = render_healthcheck_report(format_name=args.format, checks=checks)
    _emit_output(report, output_path=None)
    return status_code


def _resolve_baseline(store: Store, provider_id: str, args: argparse.Namespace) -> BaselineInfo | None | str:
    if args.baseline_date:
        baseline = store.get_baseline_for_date(provider_id, target_date=args.baseline_date)
        if baseline is not None:
            return baseline
        if args.save:
            return None
        prior, subsequent = store.nearest_saved_dates(provider_id, target_date=args.baseline_date)
        details = [f"No saved baseline exists for provider '{provider_id}' on {args.baseline_date.isoformat()}."]
        if prior:
            details.append(f"Nearest prior saved scrape: {prior}")
        if subsequent:
            details.append(f"Nearest subsequent saved scrape: {subsequent}")
        if not prior and not subsequent:
            details.append("Run `model_sentinel scan --save` to create the initial baseline.")
        return " ".join(details)
    if args.baseline == "previous-day":
        baseline = store.get_previous_day_baseline(provider_id, current_date=local_today())
        if baseline is None:
            if args.save:
                return None
            return (
                f"No saved prior-day baseline exists for provider '{provider_id}'. "
                "Run `model_sentinel scan --save` to create an initial baseline."
            )
        return baseline
    baseline = store.get_latest_saved_baseline(provider_id)
    if baseline is None:
        if args.save:
            return None
        return (
            f"No saved baseline exists for provider '{provider_id}'. "
            "Run `model_sentinel scan --save` to create the initial baseline, then rerun compare mode."
        )
    return baseline


def _baseline_mode(args: argparse.Namespace) -> str:
    if args.baseline_date:
        return "date"
    return args.baseline


def _determine_report_path(*, args: argparse.Namespace, loaded, provider_results: list[ProviderScanResult], generated_at: str) -> Path | None:
    if args.output:
        return args.output
    if not _should_notify(args=args, loaded=loaded, provider_results=provider_results):
        return None
    loaded.runtime_paths.report_dir.mkdir(parents=True, exist_ok=True)
    safe_stamp = generated_at.replace(":", "").replace("+", "_")
    extension = {"text": ".txt", "json": ".json", "markdown": ".md"}[args.format]
    return loaded.runtime_paths.report_dir / f"scan_{safe_stamp}{extension}"


def _determine_error_report_path(*, args: argparse.Namespace, loaded, generated_at: str) -> Path | None:
    if args.output:
        return args.output
    if not _should_notify_for_errors(args=args, loaded=loaded):
        return None
    loaded.runtime_paths.report_dir.mkdir(parents=True, exist_ok=True)
    safe_stamp = generated_at.replace(":", "").replace("+", "_")
    extension = {"text": ".txt", "json": ".json", "markdown": ".md"}[args.format]
    return loaded.runtime_paths.report_dir / f"error_{safe_stamp}{extension}"


def _maybe_notify(*, args: argparse.Namespace, loaded, provider_results: list[ProviderScanResult], report_path: Path | None) -> None:
    if not _should_notify(args=args, loaded=loaded, provider_results=provider_results):
        return
    change_count = sum(result.change_count for result in provider_results)
    error_count = sum(1 for result in provider_results if result.status == "error")
    if error_count:
        title = f"Model Sentinel: {error_count} provider error(s)"
    else:
        title = f"Model Sentinel: {change_count} change(s) detected"
    path_text = str(report_path) if report_path is not None else "no report path"
    message = f"Report: {path_text}"
    send_notification(
        title=title,
        message=message,
        report_path=report_path,
        open_target=loaded.settings.notify_open_target,
        terminal_notifier_path=loaded.settings.terminal_notifier_path,
        sound_name=loaded.settings.notify_sound,
        runtime_home=loaded.settings.runtime_home,
    )


def _should_notify(*, args: argparse.Namespace, loaded, provider_results: list[ProviderScanResult]) -> bool:
    enabled = _notifications_enabled(args=args, loaded=loaded)
    if not enabled:
        return False
    policy = loaded.settings.notify_on
    has_errors = any(result.status == "error" for result in provider_results)
    has_changes = any(result.change_count > 0 for result in provider_results)
    if policy == "never":
        return False
    if policy == "errors":
        return has_errors
    if policy == "changes":
        return has_changes
    return has_errors or has_changes


def _should_notify_for_errors(*, args: argparse.Namespace, loaded) -> bool:
    if not _notifications_enabled(args=args, loaded=loaded):
        return False
    return loaded.settings.notify_on in {"errors", "both"}


def _notifications_enabled(*, args: argparse.Namespace, loaded) -> bool:
    enabled = loaded.settings.notify_default
    if getattr(args, "notify", None) is True:
        enabled = True
    if getattr(args, "notify", None) is False:
        enabled = False
    return enabled


def _cleanup_old_reports(report_dir: Path, retention_days: int, logger: logging.Logger) -> None:
    if retention_days <= 0:
        return
    if not report_dir.is_dir():
        return
    cutoff = datetime.now().astimezone() - timedelta(days=retention_days)
    removed = 0
    for path in report_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix not in {".txt", ".html", ".json", ".md"}:
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
            if mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("Cleaned up %d report file(s) older than %d days", removed, retention_days)


def _emit_output(text: str, output_path: Path | None) -> None:
    if output_path is None:
        print(text)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def _file_check(name: str, path: Path) -> dict[str, str]:
    if path.is_file():
        return {"check": name, "status": "ok", "detail": f"Found {path}"}
    return {"check": name, "status": "error", "detail": f"Missing {path}"}


def _configure_logger(loaded):
    from .logging_utils import configure_logging

    return configure_logging(loaded.runtime_paths, loaded.settings)


def _normalize_argv_for_default_scan(argv: list[str]) -> list[str]:
    if not argv:
        return ["scan"]
    first = argv[0]
    if first in {"-h", "--help", "--version"}:
        return argv
    if first in COMMANDS:
        return argv
    if first.startswith("-"):
        return ["scan", *argv]
    return argv


def _add_scan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--save", action="store_true", help="persist the fetched snapshot as a new saved baseline entry")
    parser.add_argument("--format", choices=("text", "json", "markdown"), default="text", help="output format for the comparison report")
    parser.add_argument("--detail", choices=("default", "all", "squelched"), help="field detail mode for human-readable change output")
    notify_group = parser.add_mutually_exclusive_group()
    notify_group.add_argument("--notify", dest="notify", action="store_true", default=None, help="enable macOS notifications for this run")
    notify_group.add_argument("--no-notify", dest="notify", action="store_false", default=None, help="disable macOS notifications for this run")
    parser.add_argument("--baseline", choices=("previous", "previous-day"), default="previous", help="choose the baseline selection strategy")
    parser.add_argument("--baseline-date", type=_parse_date, help="compare against a saved scrape from this date")
    parser.add_argument("--provider", help="limit the scan to one configured provider")
    parser.add_argument("--output", type=Path, help="write the report to a file instead of stdout")


def _report_detail_policy(*, args: argparse.Namespace, loaded) -> ReportDetailPolicy:
    mode = getattr(args, "detail", None) or getattr(loaded.settings, "report_detail", "default")
    return make_report_detail_policy(
        mode=mode,
        show_fields=getattr(loaded.settings, "report_show_fields", DEFAULT_REPORT_SHOW_FIELDS),
        squelch_fields=getattr(loaded.settings, "report_squelch_fields", DEFAULT_REPORT_SQUELCH_FIELDS),
        unclassified_limit=getattr(loaded.settings, "report_unclassified_limit", 20),
    )


def _parse_date(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _now() -> datetime:
    return now_utc()
