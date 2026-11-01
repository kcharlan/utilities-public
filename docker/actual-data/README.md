# Actual Budget - Local Docker Setup

This directory contains helper scripts for running
[Actual Budget](https://actualbudget.com/), a local-first personal finance
application.

**Privacy warning:** the scripts bind-mount their directory as Actual's
`/data` and refuse to start or update from inside a Git worktree. Use a private
operational copy outside every checkout, back up its data, and keep it private.
Existing data under `server-files/` and `user-files/` must be moved to that
private copy before starting it.

## Usage

The following helper scripts are available to manage the container:

- **`./start.sh`**: Starts the Docker container in detached mode.
- **`./run.sh`**: Starts the container (via `./start.sh`) and attempts to open
  the interface in your browser.
- **`./stop.sh`**: Stops and removes the `actual` container.
- **`./update.sh`**: Pulls the latest image, recreates the container with its
  health check, and mounts the existing data directory. A failed pull leaves
  the old container running; if starting the replacement or waiting for its
  health check fails, the script
  attempts to restore the previous container. Back up the data separately:
  an image update can change it.

## Access

Once running, the application is accessible at: **[http://127.0.0.1:5006](http://127.0.0.1:5006)**. The helper scripts bind the service to loopback only; financial data is not intentionally exposed to the local network.

## Directory Structure

- `server-files/`: Private runtime directory created by Actual for server-side
  data; it may not exist before first use.
- `user-files/`: Private runtime directory created for budget data; it may not
  exist before first use. **Do not delete it from an active installation.**
- `*.sh`: Management scripts described above.

## Configuration Details

- **Container Name:** `actual`
- **Image:** `actualbudget/actual-server:latest`
- **Port:** `127.0.0.1:5006` mapped to container port `5006`
- **Restart policy:** `unless-stopped`
- **Volume:** Maps this project directory to `/data` inside the container.
- **Health check:** Runs the image's `/app/scripts/health-check.js` every 30
  seconds.

---
*The service is loopback-only, but the mounted data still needs a private,
restorable backup.*
