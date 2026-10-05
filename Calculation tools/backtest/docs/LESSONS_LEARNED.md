# Market Atlas lessons

## Keep the scope concrete

This is one owner's static app on one MacBook Pro, served by the existing
localhost webserver. A twelve-file copy, a private backup and byte comparisons
address its deployment needs. Brief downtime is acceptable. Release generations,
receipts, AST/import proofs and exact native metadata restoration added complexity
without serving that scope. Do not reintroduce them without a changed requirement.

## Keep real history outside public source

A filename or `.gitignore` is not a privacy boundary. Real workbooks, compiled
observations, builds, exports, browser downloads and private validation records
belong outside Git and the public checkout. Tests generate unmistakably invented
inputs at runtime. Review every staged file and the full staged diff contextually
before committing; automatic admission checks are defense in depth.

The ordinary defaults are synthetic and the custom barbell method is generic.
Preserve those behaviors. Hashes bind exact data/recipe bytes for reproduction;
they do not prove publisher authenticity or redistribution rights. Attribution,
source lineage and restrictions remain in the source notice. Compilation dates
record actual generation; explicit recorded dates are for reproduction.

## Preserve numerical and browser evidence

Keep financial assertions and historical controls when deployment tooling changes.
Synthetic failure-path fixtures cannot replace real-history acceptance. Exercise
actual CSV exports, errors, cancellation, performance, narrow layouts, keyboard
behavior and theme reload. Browser expected bytes come independently from source
and selected data, not from the target artifact. Missing prerequisites fail clearly.

## Prove the simple lifecycle early

Test cold setup, warm/offline reuse, failed refresh and a second build before
expanding tooling. Validate only selected inputs and files actually consumed;
unrelated cache or legacy entries are not acquisition inputs. Python scripts and
packages run in an external venv, with actual dependency checks rather than an
exact patch/CPU admission string.

Use isolated invented build/install/audit fixtures. Verify whole-tree backup,
copy, restoration after a real injected copy failure, no-write dry-run and drift.
Preserve legacy symlinks inside the private backup. Do not strip native attributes
or change shared ancestor permissions to satisfy a gate. Report original and
restoration errors with the actual retained recovery location.

## Audit installed data by presence, not against a local dataset

The fleet audit once required the selected external dataset to verify the
installed data pair. On a machine without local history it could never pass, and
fixing that meant running data setup, which agents must not do. Market data is not
redistributable, so the audit now checks only that the installed pair exists as
regular, non-empty files, and still compares code and notice bytes with source.
Keep the audit independent of the data home; data acquisition stays a manual
step for the owner.

## Keep routing and authorization explicit

Use `/calculators/backtest/index.html`. The folder route may remain the shared
file browser; no proxy edits or service reloads are needed. Source tests and
fixture installation do not establish live deployment. Validate changes and
obtain live-cutover authorization before installing them. Data-bearing public
distribution needs its own decision.

The repository [deployment guide](../../../docs/local_deployment_sync.md#adding-a-deployment)
describes choosing direct copy, maintained tree or generated static deployment
and proving a small fixture lifecycle before considering shared abstractions.
