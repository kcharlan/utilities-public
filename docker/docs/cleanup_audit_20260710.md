# Docker Dependency and Container Audit — 2026-07-10

## Scope and Outcome

This was a read-only dependency and operational scan of:

- The live deployment tree at `/Users/example/docker`
- The corresponding Git repository at `/Users/example/source/utilities/docker`
- All running Docker containers and their last seven days of logs
- Direct Node and Python dependencies, base images, image tags, and fixable critical/high CVEs

No containers, images, dependencies, secrets, or deployment files were changed. This report is the only artifact created.

The six running containers were stable at scan time: zero restarts since the most recent Docker start, `llm-collector` healthy, and no application warning/error matches in the previous seven days of logs. The two Node package-lock files had zero npm audit findings and no outdated direct packages. Updates are nevertheless needed for stale base images, dependency reproducibility, and dormant configurations.

## Remediation Completed — 2026-07-10

- Preserved the intentional moving-tag/range policy and added explicit clean-refresh `update.sh` workflows for webserver, collector, LLM proxy, and Excalidraw.
- Moved webserver Node dependency installation from container startup to image build; application code and dependencies are now included in the images.
- Switched Nginx from `1.27-alpine` to the moving `stable-alpine` channel; deployed version is 1.30.3.
- Refreshed both Node services to Node 24.18.0 and removed the unused npm CLI from the final runtime filesystems.
- Refreshed `app_py` to FastAPI 0.139.0 and Uvicorn 0.51.0 through its intentional unpinned dependency policy.
- Updated the collector to Gunicorn 26.0.0, refreshed Python 3.12, and removed the unnecessary compiler toolchain and curl from its runtime image.
- Added health checks to every webserver service and the LLM proxy; webserver startup now waits for healthy dependencies.
- Added Actual's built-in health check to its moving-`latest` start/update workflow; Actual remains current at 26.7.0 with its existing data mount preserved.
- Preserved the collector's external API key and state through its migration/backup workflow.
- Mirrored all finalized runtime files between the utilities repository and `/Users/example/docker`; parity checks passed.
- Final Docker Scout result: zero fixable critical/high findings across Nginx, both Node services, app_py, collector, and the built LLM proxy image.
- Final validation: 5 collector tests and 75 LLM proxy tests passed; all Compose files validated; live routes, Nginx config, collector health/authentication, container health, and recent logs passed verification.
- n8n remains dormant/out of scope. `MY_API_KEY.txt` remains the confirmed non-secret placeholder used by the existing preservation workflow.

## Assumptions

- **Deployment model**: Personal, single-host Docker Desktop services on Apple Silicon; no horizontal scaling requirement.
- **Availability**: Brief planned downtime during rebuild/recreate is acceptable, but persistent data must be preserved.
- **Network exposure**: Ports bound to `0.0.0.0` may be reachable from the local network unless the host firewall prevents it.
- **Version policy**: Prefer supported LTS/stable release lines and immutable application versions; refresh mutable base tags deliberately.
- **Security policy**: Fixable critical/high image findings warrant a rebuild even if the application currently behaves correctly.
- **Public API**: Existing ports, URLs, mounted data paths, and application behavior are treated as stable interfaces.
- **Load**: Low-concurrency personal services; dependency safety and reproducibility matter more than throughput tuning.
- **Source of truth**: `/Users/example/source/utilities/docker` is authoritative; deployment changes must then be mirrored to `/Users/example/docker`.

## Rules and Standards Applied

### Correctness/Safety

- Do not leave known fixable critical/high CVEs in network-facing base images.
- Do not commit live credentials or embed encryption keys in Compose files.
- Preserve Actual and n8n data volumes before image/version changes.

### Robustness & Resilience

- Add health checks where Compose currently only knows that a process started.
- Validate every changed Compose file and smoke-test every rebuilt endpoint.
- Keep an explicit rollback image/version for stateful services.

### Scalability & Capacity

- No material capacity issue was observed for this personal, single-host workload.
- Gunicorn's single worker is reasonable for current load; measure latency/concurrency before increasing it.

### Best Practices & Maintainability

- Use lock files or fully pinned Python dependency sets for reproducible builds.
- Avoid installing dependencies at every container start.
- Prefer versioned application tags and refreshed, supported base-image lines.
- Keep the source and deployment copies synchronized.

### Readability

- Remove obsolete Compose schema keys and comments that no longer describe the configuration.

### Performance/Efficiency

- Do not install npm and application dependencies on every `app_node` restart.
- Remove build-only packages from the final collector image via a multi-stage build or omit them when wheels are available.

## Findings

### [Correctness/Safety] Finding #1: Stale Nginx Image Has Fixable Critical Vulnerabilities

- **Severity**: Critical
- **Category**: Correctness/Safety
- **Evidence**:
  - `webserver/docker-compose.yml:3` pins `nginx:1.27-alpine`; the running container is Nginx 1.27.5 and its image was created 2025-04-16.
  - Docker Scout found 4 critical and 23 high fixable findings in the local image, including critical findings in `libxml2`, OpenSSL, and Expat.
  - The supported stable release is Nginx 1.30.2; the 1.30.2 release includes the CVE-2026-9256 fix. A registry scan of `nginx:1.30-alpine` found zero fixable critical/high findings.
- **Impact**: The reverse proxy is the stack's ingress point. Continuing to use an old image retains publicly documented, fixed vulnerabilities in parsers and cryptographic libraries.
- **Recommended Fix**: Change both deployment copies to `nginx:1.30-alpine` (or an immutable 1.30.2 digest), pull, recreate only the `web` service, and smoke-test proxied routes.
- **Effort**: S (<1 hour)
- **Risk**: Medium; Nginx 1.30 changes some defaults, including upstream HTTP behavior, so config testing is required.
- **Acceptance Criteria**:
  - `nginx -v` reports 1.30.2 or later on the 1.30 stable line.
  - `docker scout cves --only-severity critical,high --only-fixed nginx:1.30-alpine` reports no fixable critical/high findings.
  - `docker compose config --quiet` succeeds and all routes through `127.0.0.1:7711` behave normally.
- **Robustness Considerations**: Keep the old image digest available until the route smoke test passes; rollback is a tag/digest revert and service recreate.

### [Correctness/Safety] Finding #2: Running Node Images Predate Security Releases

- **Severity**: Critical
- **Category**: Correctness/Safety
- **Evidence**:
  - `webserver/docker-compose.yml:36`, `webserver/app_node_Dockerfile:1`, and `webserver/index/Dockerfile:1` use `node:24-alpine`.
  - Both running Node containers report Node 24.11.1. The current Node 24 LTS release is 24.18.0; Node 24.17.0 was explicitly a security release.
  - Docker Scout found 3 critical and 39 high fixable findings in the local `node:24-alpine`, including Node CVEs fixed by 24.13.0/24.14.1 and Alpine/OpenSSL findings. A scan of today's registry image found one high and no critical fixable finding.
  - `npm audit --omit=dev` reports zero vulnerabilities in both application lock files; the problem is the stale runtime/base image, not the direct app packages.
- **Impact**: Both web applications run on a Node build with known fixed runtime and base-library vulnerabilities.
- **Recommended Fix**: Pull the refreshed Node 24 LTS Alpine image, rebuild `index`, recreate `app_node`, and consider pinning to a tested 24.x patch/digest with a scheduled refresh process.
- **Effort**: S (<1 hour)
- **Risk**: Low to Medium; this stays within Node 24 LTS but changes patch-level runtime behavior.
- **Acceptance Criteria**:
  - Both containers report Node 24.18.0 or newer on Node 24 LTS.
  - Existing Node tests/smoke checks pass; npm audit remains clean.
  - Scout reports no critical fixable findings and any remaining high finding is documented.
- **Robustness Considerations**: Rebuild one service at a time and retain the previous image IDs for immediate rollback.

### [Correctness/Safety] Finding #3: Python Images Need Base Refreshes; Web Python Dependencies Are Unpinned

- **Severity**: High
- **Category**: Correctness/Safety / Best Practices & Maintainability
- **Evidence**:
  - `llm_collector/llm_collector_container/Dockerfile:2`, `llm_proxy/Dockerfile:1`, and `webserver/app_py/Dockerfile:1` use mutable `python:3.12-slim`.
  - The running collector image has 14 high fixable findings; the running web Python image has 11. Today's registry `python:3.12-slim` scan has zero fixable critical/high findings, so rebuilds are actionable.
  - `webserver/app_py/requirements.txt:1-2` has no version bounds. The running image has FastAPI 0.135.2 and Uvicorn 0.42.0; current releases are FastAPI 0.139.0 and Uvicorn 0.51.0.
  - `llm_proxy/pyproject.toml:7-11` contains only broad lower bounds and has no committed lock file, so builds can change without source changes.
- **Impact**: Rebuilding can silently change the Python application graph, while not rebuilding leaves fixed OS-library findings in place. This is both a security and reproducibility gap.
- **Recommended Fix**: First establish tested lock/pin sets, then rebuild all Python images with a refreshed 3.12-slim digest. Keep Python 3.12 for this pass; it remains supported and avoids combining runtime-major and package upgrades.
- **Effort**: M (1-4 hours)
- **Risk**: Medium; locking the currently resolved graph is low risk, but intentionally upgrading FastAPI/Uvicorn requires application tests.
- **Acceptance Criteria**:
  - Repeated clean builds resolve identical Python package versions.
  - Collector, app_py, and llm_proxy tests pass in their project virtual environments.
  - `/health` for the collector and smoke endpoints for both FastAPI apps succeed.
  - Rebuilt images have no fixable critical/high base-layer findings.
- **Robustness Considerations**: Separate dependency upgrades from the base refresh where possible so failures can be attributed and rolled back cleanly.

### [Best Practices & Maintainability] Finding #4: Gunicorn Has a New Major Release; Other Collector Direct Dependencies Are Current

- **Severity**: Medium
- **Category**: Best Practices & Maintainability
- **Evidence**:
  - `llm_collector/collector/requirements.txt:1` pins Flask 3.1.3, which is current.
  - `llm_collector/collector/requirements.txt:2` pins Gunicorn 25.3.0; current is 26.0.0.
- **Impact**: There is no immediate log or health symptom, but the collector misses the current Gunicorn release. As a major update, it should not be bundled blindly with the urgent base refresh.
- **Recommended Fix**: Review the Gunicorn 26 changelog, test it as a separate change, and retain 25.3.0 if compatibility risk outweighs the benefit.
- **Effort**: S (<1 hour)
- **Risk**: Medium due to major-version server behavior changes.
- **Acceptance Criteria**:
  - Collector unit tests pass.
  - Gunicorn starts with the existing command and the health endpoint remains healthy.
  - A POST/ingestion smoke test persists state correctly.

### [Correctness/Safety] Finding #5: Dormant n8n Configuration Is Far Behind and Contains a Plaintext Key

- **Severity**: High if reactivated; Medium while dormant
- **Category**: Correctness/Safety
- **Evidence**:
  - `/Users/example/docker/n8n-poc/docker-compose.yml:4` uses n8n 2.0.2; n8n's stable channel had reached 2.26.0 by 2026-06-09, including dependency CVE fixes.
  - `/Users/example/docker/n8n-poc/docker-compose.yml:8` embeds the encryption key directly in Compose.
  - The entire n8n POC exists only in the deployment tree and is absent from the source repository.
  - No n8n container is currently present, so this does not affect the live six-container stack.
- **Impact**: Restarting the POC would deploy an old application and expose a credential through the Compose file and Docker inspection. The missing source copy also makes maintenance non-repeatable.
- **Recommended Fix**: Before reactivation, back up the SQLite data, move the key to a non-tracked environment/secret file without changing its value, copy a sanitized configuration into the source repository, review n8n's 2.0.2-to-current migration notes, and upgrade incrementally or directly only as officially supported.
- **Effort**: M (1-4 hours)
- **Risk**: High because n8n is stateful and spans many releases.
- **Acceptance Criteria**:
  - A restorable database/config backup exists.
  - No secret value appears in tracked or Compose files.
  - Workflows and credentials load after the upgrade; the pinned version is on a supported stable release.
- **Robustness Considerations**: Do not rotate the encryption key unless credentials will be re-created; losing the original key makes stored credentials unreadable.
- **Disposition (2026-07-10)**: Accepted/out of scope. The POC is unused and would be rebuilt on a current release before any future reactivation. The dormant plaintext key is acknowledged but does not require current remediation.

### [Correctness/Safety] Finding #6: A File Named as an API Key Is Tracked in Git

- **Severity**: High pending verification
- **Category**: Correctness/Safety
- **Evidence**:
  - `llm_collector/MY_API_KEY.txt` is tracked in Git and there is no repository `.gitignore`.
  - The file has been in history since at least commit `dbdc37c`; its content was deliberately not displayed during this audit.
- **Impact**: If the file contains a real active credential, it is exposed to every clone and remains in Git history even after normal deletion.
- **Recommended Fix**: Verify whether it is a real credential. If real, rotate it first, remove it from tracking, add secret patterns to `.gitignore`, and decide whether history rewriting is warranted based on repository exposure. If it is only a placeholder, rename it to an obvious `.example` file with a non-secret value.
- **Effort**: S for rotation/removal; M for coordinated history cleanup
- **Risk**: Medium; rotating without updating the extension/collector together causes authentication failures.
- **Acceptance Criteria**:
  - No active credential is tracked in the current tree.
  - The collector and extension authenticate using the replacement secret path.
  - Secret scanning of the repository is clean.
- **Robustness Considerations**: Coordinate credential replacement atomically and retain a rollback window that does not reintroduce the compromised value.
- **Disposition (2026-07-10)**: Closed as not an issue. The tracked file contains only the documented `<your key here>` placeholder. Installation/migration scripts preserve the real external/local key and do not overwrite it with this placeholder.

### [Best Practices & Maintainability] Finding #7: Mutable Tags and Startup-Time Installs Reduce Reproducibility

- **Severity**: Medium
- **Category**: Best Practices & Maintainability / Performance/Efficiency
- **Evidence**:
  - `actual-data/start.sh:11`, `excalidraw/docker-compose.yml:5`, and `mermaid/start.sh:7` use unversioned `latest` images.
  - `webserver/docker-compose.yml:38` upgrades npm globally and installs app dependencies on every `app_node` start, while explicitly ignoring the committed lock file with `--no-package-lock`.
  - `webserver/index/Dockerfile:3-4` copies only `package.json` and also installs without using `package-lock.json`.
  - Actual is currently up to date at 26.7.0 and its remote `latest` digest matches local, but Scout still reports two high fixable transitive findings in the current upstream image.
- **Impact**: Identical source can produce different containers, startup depends on registry availability, and a routine restart can introduce an untested package graph. Current Actual cannot be locally fixed without a newer upstream image or maintaining a custom image.
- **Recommended Fix**: Use `npm ci --omit=dev` during image builds, include lock files, remove startup-time installation, and pin application images to tested version tags/digests with an explicit update script/process. Pin Actual to `26.7.0` after confirming the update policy; monitor upstream for a rebuilt/fixed image.
- **Effort**: M (1-4 hours)
- **Risk**: Low to Medium; behavior should remain the same, but lock-file enforcement may reveal drift currently hidden by runtime installs.
- **Acceptance Criteria**:
  - Containers start without network package installation.
  - Two clean builds from the same commit produce the same dependency graph.
  - `npm audit --omit=dev` stays at zero and Node service smoke tests pass.
  - Version/digest refresh steps are documented.
- **Disposition (2026-07-10)**: Mutable tags and compatible dependency ranges are intentional to minimize maintenance. Remediation should preserve that policy while adding explicit `update.sh` maintenance boundaries, moving dependency installation from container startup to image build, and verifying health after refreshes. No patch-version inventory will be maintained.

### [Robustness] Finding #8: Most Running Services Lack Health Checks

- **Severity**: Low
- **Category**: Robustness & Resilience
- **Evidence**:
  - Only `llm_collector/llm_collector_container/docker-compose.yml:25-30` defines a health check.
  - Actual, Nginx, index, app_node, and app_py show no Docker health status despite currently clean logs and zero restarts.
- **Impact**: Docker can report a service as running when its application is unable to serve requests; dependency upgrades are harder to validate automatically.
- **Recommended Fix**: Add lightweight local health checks to services with stable endpoints, and change `depends_on` to health-based conditions where startup ordering matters.
- **Effort**: M (1-4 hours)
- **Risk**: Low, provided checks have realistic start periods and timeouts.
- **Acceptance Criteria**:
  - All long-running services reach `healthy` after recreation.
  - A deliberately broken endpoint transitions to `unhealthy` without restart loops or false positives.
- **Robustness Considerations**: Health checks should test readiness, avoid external dependencies, and not mutate data.

## Inventory Summary

| Component | Observed | Current / Target | Assessment |
|---|---:|---:|---|
| Actual Server | 26.7.0 | 26.7.0 | Current; monitor two upstream-image Scout findings |
| Nginx | 1.27.5 | 1.30.3 stable deployed | Remediated via moving `stable-alpine` tag |
| Node | 24.11.1 | 24.18.0 LTS deployed | Remediated; npm removed from runtime images |
| npm in app_node | 11.9.0 at scan | Build-time only | Removed from final runtime after dependency installation |
| Express | 5.2.1 | 5.2.1 | Current; audit clean |
| Fastify | 5.6.2 | 5.6.2 | Current; audit clean |
| @fastify/reply-from | 12.5.0 | 12.5.0 | Current; audit clean |
| Cheerio | 1.1.2 | 1.1.2 | Current; audit clean |
| mime | 4.1.0 | 4.1.0 | Current; audit clean |
| Flask | 3.1.3 | 3.1.3 | Current |
| Gunicorn | 25.3.0 | 26.0.0 deployed | Remediated and tested |
| FastAPI (app_py) | 0.135.2 | 0.139.0 deployed | Remediated through moving dependency policy |
| Uvicorn (app_py) | 0.42.0 | 0.51.0 deployed | Remediated through moving dependency policy |
| n8n (dormant) | 2.0.2 | 2.26.0 stable observed | Substantial update; migrate carefully |

## Implementation Plan

### Phase 1: Critical Image Refreshes

**Step 1: Upgrade Nginx stable line**

- **Files to modify in both trees**: `webserver/docker-compose.yml:3`
- **Changes**: Replace `nginx:1.27-alpine` with tested `nginx:1.30-alpine` or an immutable 1.30.2 digest.
- **Commands**:
  - `docker compose -f webserver/docker-compose.yml config --quiet`
  - `docker compose -f webserver/docker-compose.yml pull web`
  - `docker compose -f webserver/docker-compose.yml up -d --no-deps web`
  - `docker exec webserver-web-1 nginx -t`
- **Expected result**: Nginx configuration is valid and all existing proxy/static routes return expected responses.
- **Stop condition**: If `nginx -t` or any route check fails, restore the old image reference and recreate `web`.
- **Rollback**: Revert the tag/digest and recreate only `web`.

**Step 2: Refresh Node 24 LTS images**

- **Files to verify/modify in both trees**: `webserver/docker-compose.yml:36`, `webserver/app_node_Dockerfile:1`, `webserver/index/Dockerfile:1`
- **Changes**: Stay on Node 24 LTS, but pull/rebuild from a current 24.18.x image or tested digest.
- **Commands**:
  - `docker pull node:24-alpine`
  - `docker compose -f webserver/docker-compose.yml build --pull index`
  - `docker compose -f webserver/docker-compose.yml up -d --force-recreate app_node index`
  - Run Node tests/smoke checks and `npm audit --omit=dev` in both package directories.
- **Expected result**: Both services report Node 24.18.x or later and no critical fixable Scout findings.
- **Stop condition**: Roll back if either application fails its route smoke test.
- **Rollback**: Recreate using the recorded old image IDs.

### Phase 2: Python Reproducibility and Base Refresh

**Step 3: Add deterministic Python dependency sets**

- **Files to modify in both trees**: `webserver/app_py/requirements.txt`, `llm_proxy/pyproject.toml`, a new lock/constraints file as selected, and related Dockerfiles.
- **Changes**: Pin/lock direct and transitive dependencies; initially capture a known-working graph before elective upgrades.
- **Commands**: Resolve inside project virtual environments, run each Python test suite, then perform clean image builds twice and compare installed package lists.
- **Expected result**: Identical package graphs from clean builds; all tests pass.
- **Stop condition**: Do not refresh production containers if the locked graph changes application behavior.

**Step 4: Rebuild from refreshed Python 3.12 slim images**

- **Files to verify/modify in both trees**: all three Python Dockerfiles.
- **Changes**: Pull current `python:3.12-slim`, preferably record a tested digest, and rebuild collector/app_py/llm_proxy.
- **Commands**: Build with `--pull`, run tests, scan new images, then recreate one service at a time.
- **Expected result**: No fixable critical/high base findings; health and smoke tests pass.
- **Stop condition**: Keep the previous image if tests, health checks, or state persistence fail.
- **Rollback**: Recreate using previous local image IDs.

### Phase 3: Controlled Application Updates

**Step 5: Evaluate Gunicorn 26 separately**

- **Files to modify in both trees**: `llm_collector/collector/requirements.txt:2`
- **Changes**: Update 25.3.0 to 26.0.0 only after changelog review.
- **Commands**: Run collector tests, rebuild, verify `/health`, and perform an authenticated ingestion smoke test.
- **Expected result**: No behavior or persistence regressions.
- **Stop condition**: Retain 25.3.0 if startup, request handling, or logging changes incompatibly.

**Step 6: Upgrade and pin FastAPI/Uvicorn**

- **Files to modify in both trees**: `webserver/app_py/requirements.txt` and its lock/constraints file.
- **Changes**: Upgrade through tested versions to FastAPI 0.139.x and Uvicorn 0.51.x.
- **Commands**: Run application tests, build, inspect OpenAPI output if used, and smoke-test routes/WebSockets.
- **Expected result**: Tests and contract checks pass with a reproducible graph.
- **Stop condition**: Split upgrades and bisect if framework/server behavior changes.

**Step 7: Migrate dormant n8n before reactivation**

- **Files to create/modify**: sanitized n8n configuration in the source tree, deployment Compose file, secret environment handling.
- **Changes**: Back up state, externalize the existing encryption key, follow official migration notes, and pin a supported stable tag.
- **Commands**: Validate backup restore in a disposable copy, run migration, then test workflows and credentials.
- **Expected result**: Workflows run and stored credentials decrypt successfully without secrets in tracked files.
- **Stop condition**: Stop immediately on migration errors or credential decryption failure; restore the backup and 2.0.2 image.
- **Rollback**: Restore database/config backup and old version while preserving the original encryption key.

### Phase 4: Optional Hardening and Cleanup

**Step 8: Remove tracked credentials**

- Verify and rotate `llm_collector/MY_API_KEY.txt` if live, remove it from tracking, and add a repository `.gitignore`.
- Coordinate collector and extension updates to avoid authentication downtime.

**Step 9: Build Node dependencies once with lock files**

- Update Dockerfiles to copy both package files and run `npm ci --omit=dev`.
- Remove the dependency/npm installation entrypoint from `webserver/docker-compose.yml:38`.
- Build and run npm audit plus route smoke tests.

**Step 10: Pin mutable application tags and add health checks**

- Pin Actual, Excalidraw, and Mermaid to tested versions/digests.
- Add non-mutating readiness checks to the five services without health status.
- Remove the obsolete `version` key from `excalidraw/docker-compose.yml:1`.

## Sources

- Nginx releases: https://github.com/nginx/nginx/releases
- Node release status and current LTS: https://nodejs.org/en/about/previous-releases
- Node 24.17.0 security release: https://nodejs.org/en/blog/release/v24.17.0
- Actual 26.7.0 release: https://actualbudget.org/blog/release-26.7.0/
- n8n releases: https://github.com/n8n-io/n8n/releases
- Flask package history: https://pypi.org/project/Flask/
- Gunicorn package history: https://pypi.org/project/gunicorn/
- FastAPI package history: https://pypi.org/project/fastapi/
- Uvicorn package history: https://pypi.org/project/uvicorn/
