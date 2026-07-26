# Python FastAPI Application (`app_py`)

This directory contains a simple Python application built with FastAPI. It demonstrates a basic Python backend service that can be integrated into the main web server setup via Nginx.

## Overview

*   **`main.py`**: The main application file, defining a FastAPI application and a single API endpoint.
*   **`Dockerfile`**: Builds the container image from `python:3.12-slim`, installs dependencies from `requirements.txt`, and runs the app with Uvicorn on port 80.
*   **`requirements.txt`**: Lists Python dependencies (`fastapi`, `uvicorn[standard]`).

## Functionality

The `app_py` service exposes a single GET endpoint:

*   `GET /api/py/hello`
    *   **Description:** Returns a JSON object indicating the API is working and its origin.
*   **Response:** `{"ok": true, "from": "python"}`

This service runs on port `80` within its Docker container and is exposed externally via the Nginx reverse proxy under the `/api/py/` path.

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `app_py` service is built from the local `Dockerfile` in this directory (`build: ./app_py`).
*   The Dockerfile uses `python:3.12-slim` as the base image, installs dependencies via pip, and runs `uvicorn main:app --host 0.0.0.0 --port 80`.
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

2.  **Add Dependencies:**
    *   Add new Python packages to `requirements.txt` in this directory. The Dockerfile installs them during the image build.
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
