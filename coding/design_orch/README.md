# design_orch

Reusable design-to-implementation orchestration kit extracted from `utilities/git-multirepo-dashboard`.

The process is:

1. Feed a design document plus `docs/design_doc_packetization_playbook.md` to a coding LLM
2. Generate `docs/implementation_packet_playbook.md`, `plans/packet_status.md`, `plans/packet_status.json`, and the first packet docs
3. Use `scripts/codex_packet_loop.zsh` to plan, implement, validate, and audit packets one at a time

Included here:

- `orch_launch.sh` as a sample launcher for the packet loop
- `scripts/codex_packet_loop.zsh` for the packet orchestration loop
- `scripts/codex_json_progress.py` for progress/event normalization
- `docs/design_doc_packetization_playbook.md` as the packetization prompt and output contract
- Empty `plans/`, `audits/`, and `automation_logs/` directories for generated state

Notes:

- `orch_launch.sh` is sample-project specific and still points to `docs/git_dashboard_final_spec.md`; that Git Fleet spec is intentionally not included in this stripped snapshot, so supply the file or change `DESIGN_DOC` before running it.
- For a new project, replace the design-doc path and keep the rest of the structure.
- The loop can drive either Codex or Claude via environment configuration in `scripts/codex_packet_loop.zsh`.
