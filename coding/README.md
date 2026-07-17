# coding

This directory collects reusable coding orchestration tools and reference process assets.

- `task_orch/`: legacy task intake -> planning -> dependency resolution -> worker orchestration scaffold extracted from Benefit Specification Engine. This package is being deprecated in favor of Cognitive Switchyard.
- `design_orch/`: design-document packetization and implementation loop extracted from Git Fleet. It uses a design playbook to generate an implementation playbook, then executes packets through planning, implementation, validation, and drift-audit stages.

These folders are curated infrastructure snapshots. Historical tickets, packet runs, logs, and other project-specific execution artifacts were intentionally removed.
