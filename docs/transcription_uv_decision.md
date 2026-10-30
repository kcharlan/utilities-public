# Transcription uv delivery decision

This is an investigation and recommendation, not an implementation or release.
The owner chooses whether to migrate. The spike was discarded and did not
change the application, deployment, guard, or existing environments.

## Recommendation and evidence

Use one uv-managed launcher, with `app.py` as the default and an explicit
divider mode for `transcribe.py`. Keep the two interfaces. Use a Python
`>=3.12,<3.13` header, matching the Python 3.12 in `setup.sh`, and declare the
five currently pinned direct dependencies: `openai-whisper==20250625`,
`streamlit==1.66.0`, `pandas==3.0.6`, `openai==3.31.0`, and
`librosa==1.0.0`. Retain FFmpeg as a separate machine prerequisite.

The temporary launcher called `streamlit.web.cli.main()` in process with a
selected absolute script path and no `os.execv`. Both modes served `/` and
`/_stcore/health` with HTTP 200 and `ok` health, then exited with status 0 on
Ctrl-C; the process group had no surviving processes. These are HTTP server
startup checks, not proof that Streamlit executed the application script. A
separate Streamlit AppTest executed each script and clicked its cumulative
reset, writing a synthetic counter in the isolated runtime home. No browser,
audio, model load, API call, or real state was used. A child process was not
needed for the observed shutdown behavior.

On this macOS Apple Silicon machine, uv 0.13.6 and Homebrew Python 3.12,
fresh independent `UV_CACHE_DIR` measurements from another working directory
gave the following times to the first successful HTTP response. Warm results
use the same cache after the cold run; the timed modes differ but start the
same Streamlit server, and the HTTP response does not execute the app script.
Times include 250 ms polling granularity and depend on network and machine.
Disk is `du` cache size, not a standalone installed environment, and includes
download/build artifacts. No Whisper model was downloaded.

| Dependency graph | Cold | Warm | Cache disk |
| --- | ---: | ---: | ---: |
| Core pins | 7.07 s | 0.26 s | 2,212,936 KiB (about 2.11 GiB) |
| Core plus both optional pins | 8.55 s | 0.51 s | 2,476,552 KiB (about 2.36 GiB) |

The optional graph added 263,616 KiB (about 257 MiB) and 1.49 seconds in this
single cold sample. That increment is acceptable for a tool whose core graph
already uses about 2.11 GiB, so declare both optionals and avoid a new guard
exception. This changes optional installation into default availability, not
the existing condition that the API fallback needs an environment key. The
total first-use footprint is substantial; cold start was acceptable in this
sample but is not a guarantee for slower networks or machines.

Use `~/.transcription/` by default and honor `TRANSCRIPTION_HOME`. Move both
interfaces' counters there explicitly, with a private runtime directory and
private files, and document manual migration of any existing counters; never
automatically import old state. The spike set `app.py`'s two existing counter
environment variables and changed its working directory to the synthetic home
before starting Streamlit, which also isolated the divider interface's relative
counter paths. This proves the synthetic reset path, but changing the working
directory also changes relative audio paths and upload locations. Production
should instead update both scripts to use explicit runtime paths, preserve the
caller's working-directory semantics for audio selection, and place temporary
uploads safely outside the checkout. Test both interfaces, overrides, file
permissions, failure handling and manual migration with synthetic fixtures.

Whisper's installed `load_model` source selects `$XDG_CACHE_HOME/whisper`, or
`~/.cache/whisper` if that variable is unset, when no `download_root` is
provided. Both interfaces call `whisper.load_model` without that argument, so
the launcher need not move the model cache. This conclusion is from source
inspection; model download and transcription were deliberately not tested.

The guard's `check_launcher` passes only the launcher's own text to
`missing_declared_imports`; the latter walks imports at all scopes in that one
file, and does not follow a thin launcher's targets. Add explicit, narrowly
registered target scanning for both scripts using the launcher's declarations,
with tests for missing imports, rather than assuming thin-launcher coverage.
Add `whisper: openai-whisper` to `IMPORT_DISTRIBUTION_ALIASES`; verify manifest
comparison covers both pinned requirements files. This decision does not set a
general sibling-module scanning policy.

After checking deployed callers, remove `run.sh`, `m4a-run.sh`, and `help.sh`
(already documented as unsupported), plus `ui.sh` and `setup.sh`, when their
replacement is ready. Repository references were reviewed, but deployed or
external callers have not been checked; deletion is conditional on that check.
The deployed `~/transcription` copy and its local-only counters must be
preserved and handled according to `docs/local_deployment_sync.md`.

## Future implementation plan scope

- Implement and validate both modes and their runtime-state paths, including
  safe uploads, caller-relative input behavior, manual-only migration and
  recovery; do not copy real state into the public repository.
- Register the launcher and target scans in the fleet guard, add the Whisper
  alias, reconcile both dependency manifests, remove `transcription/app.py`
  from `NON_UV_ENTRYPOINT_ALLOWLIST`, and test the guard changes and consumers.
- Update the README Setup, Run, optional dependency, counters and Validation
  sections, plus the `agents.md` Streamlit and setup-script entries. Replace
  wrappers only after the deployed-caller check.
- Run the full documented core and optional validation, including AppTest,
  headless HTTP and teardown, synthetic audio and model acceptance, dependency
  checks and audit, plus fleet guard and all affected project suites. The spike
  results above do not satisfy those release acceptance gates.
- Plan deployment of the tracked copy without deleting local-only state, and
  verify source and deployed behavior. Remove the source and deployed
  Transcription venvs only after verified migration and deployment, under the
  applicable retention and authorization rules.
