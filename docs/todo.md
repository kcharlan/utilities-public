# Maintenance to-do

- [ ] Resolve the historical evidence gap for Model Sentinel's anonymous endpoint
  access and shadow evaluation of its display cap and telemetry fields. See
  [Hosts and endpoint capture](../model_sentinel/docs/hosts_and_endpoints.md#validation-and-live-evidence).
  Any new live provider requests or saved scans require separate authorization;
  keep evidence private.
- [ ] Decide whether existing CDN-backed browser tools need offline delivery.
  For tools selected for migration, vendor exact-version scripts, styles, and
  fonts with source URLs, hashes, and licenses; verify browser behavior with
  external requests blocked. Follow the delivery rules in [agents.md](../agents.md).
- [ ] Decide whether to enable Colophon's OpenCode Continue in CLI action
  (currently disabled; see [runtime](../colophon/docs/runtime.md)). Before
  enabling it, prove against disposable synthetic OpenCode databases outside
  the repository that the candidate copied command
  `cd <cwd> && OPENCODE_DB=<absolute-db> opencode --session <id>` resumes the
  existing session in its originating database without creating another,
  including overridden and sibling databases and a running OpenCode service;
  confirm the CLI launch mode `OPENCODE_DB` requires. Add browser tests for
  the copied command's shell round trip, unusable cwd rejection and database
  targeting, then record the verified behavior and CLI version in the runtime
  doc. Archived, project-archived and subagent sessions stay ineligible.
- [ ] Resolve Colophon's unknown Antigravity real-source parity and
  credential-access acceptance status. See [evidence and acceptance](../colophon/docs/development.md#antigravity-evidence-and-acceptance);
  real-source work requires separate authorization and private evidence.
- [ ] Review the container image update policy: retain deliberate tag-based
  refreshes or pin digests with an explicit refresh process. Validate any
  change through each affected stack's complete suite and health checks.
- [ ] Resolve the [post-uv decision tasks](post_uv_retirement_implementation_plan.md#decision-tasks)
  and [owner items](post_uv_retirement_implementation_plan.md#owner-items), including
  evidence location and retention; the home residue name heuristic does not settle them.
