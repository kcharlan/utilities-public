# Python FastAPI Application (`app_py`)

This directory contains a simple Python application built with FastAPI. It demonstrates a basic Python backend service that can be integrated into the main web server setup via Nginx.

## Overview

*   **`main.py`**: The main application file, defining a FastAPI application and a single API endpoint.
*   **`Dockerfile`**: Builds the container image from `python:3.14-slim`, installs the fully frozen dependency graph from `requirements.lock` with hash verification, and runs the app with Uvicorn on port 80.
*   **`requirements.txt`**: Lists the direct Python dependencies (`fastapi`, `uvicorn[standard]`) used as lock input.
*   **`requirements.lock`**: Pins the complete Python 3.14 graph and records accepted distribution hashes for reproducible container installation.

## Functionality

The `app_py` service exposes a single GET endpoint:

*   `GET /api/py/hello`
    *   **Description:** Returns a JSON object indicating the API is working and its origin.
*   **Response:** `{"ok": true, "from": "python"}`

This service runs on port `80` within its Docker container and is exposed externally via the Nginx reverse proxy under the `/api/py/` path.

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `app_py` service is built from the local `Dockerfile` in this directory (`build: ./app_py`).
*   The Dockerfile uses `python:3.14-slim`, installs only the hashed versions in `requirements.lock`, and runs `uvicorn main:app --host 0.0.0.0 --port 80`.
*   It mounts the `./app_py` directory into the container at `/app` (read-only).
*   Port `80` is exposed internally for Nginx to access.

## How to Modify and Extend

1.  **Add New Endpoints:**
    *   Edit `main.py` to add more routes and logic using FastAPI.
    *   Example:
        ```python
        @app.get("/api/py/new-endpoint")
        def new_endpoint():
            return {"message": "This is a new Python endpoint!"}
        ```

2.  **Add or Update Dependencies:**
    *   Edit the direct requirements in `requirements.txt`, then regenerate the universal Python 3.14 lock from this directory:
        ```bash
        uv pip compile --python-version 3.14 --universal --generate-hashes \
          requirements.txt --output-file requirements.lock
        uvx pip-audit -r requirements.lock
        ```
    *   Review and commit both files together. The Docker build intentionally refuses distributions whose hashes are absent from the lock.
    *   After adding dependencies, rebuild the `app_py` service:
        ```bash
        docker compose up -d --build app_py
        ```

3. **Restart or Rebuild:**
    Compose bind-mounts `app_py/` read-only over `/app`, so a `main.py` change
    needs a container restart (Uvicorn is not running with reload enabled):
    ```bash
    docker compose restart app_py
    ```
    Rebuild when `requirements.txt` or the Dockerfile changes:
    ```bash
    docker compose up -d --build app_py
    ```

4.  **Update Nginx (if necessary):**
    If you change the base path for your Python API (e.g., from `/api/py/` to `/my-python-app/`), you'll need to update the `nginx/default.conf` file accordingly and restart the `web` service:
    ```bash
    docker compose restart web
    ```
