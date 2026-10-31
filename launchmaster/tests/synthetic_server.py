"""Start the real app with discovery isolated to the synthetic test manifest."""
import runpy
import sys
import json
import os

import uvicorn
from fastapi.responses import JSONResponse

namespace = runpy.run_path(sys.argv[1], run_name="launchmaster_test_server")
# Functions retain the runpy globals, which are distinct from its returned dict.
globals_ = namespace["build_job_list"].__globals__
jobs = json.loads(open(os.environ.pop("LAUNCHMASTER_SYNTHETIC_JOBS")).read())
state = {job["label"]: {"pid": job["pid"], "last_exit": job["last_exit"]} for job in jobs}
globals_["PLIST_DIRS"] = {"user-agent": os.environ["LAUNCHMASTER_HOME"]}
globals_["get_launchctl_state"] = lambda: dict(state)
globals_["get_disabled_labels"] = lambda: {"com.example.synthetic-disabled"}
globals_["get_job_detail"] = lambda *args: {}
globals_["get_job_blame"] = lambda *args: None
def forbid_launchctl(*args, **kwargs):
    raise RuntimeError("native launchctl is forbidden in the synthetic server")

async def synthetic_unified_log(*args, **kwargs):
    return []

globals_["_run_launchctl"] = forbid_launchctl
globals_["read_unified_log"] = synthetic_unified_log

@namespace["app"].middleware("http")
async def deny_mutations(request, call_next):
    if request.method not in ("GET", "HEAD") and request.url.path != "/api/settings":
        return JSONResponse({"detail": "Synthetic server forbids job mutations"}, status_code=403)
    return await call_next(request)

uvicorn.run(namespace["app"], host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
