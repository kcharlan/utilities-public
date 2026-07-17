# Actual Budget - Local Docker Setup

This directory hosts the Docker configuration and data for [Actual Budget](https://actualbudget.com/), a local-first personal finance application.

**⚠️ IMPORTANT:** Once the server has been run, this directory is the mounted `/data` volume and may contain live financial data. Back up the generated `server-files` and `user-files` directories regularly.

## Usage

The following helper scripts are available to manage the container:

-   **`./start.sh`**: Starts the Docker container in detached mode.
-   **`./run.sh`**: Starts the container (via `./start.sh`) and attempts to open the interface in your browser.
-   **`./stop.sh`**: Stops and removes the `actual` container.
-   **`./update.sh`**: Pulls the latest image, recreates the container with its built-in health check, and mounts the existing data volume.

## Access

Once running, the application is accessible at: **[http://127.0.0.1:5006](http://127.0.0.1:5006)**. The helper scripts bind the service to loopback only; financial data is not intentionally exposed to the local network.

## Directory Structure

-   `server-files/`: Runtime directory created by Actual for the server-side database (`account.sqlite`) and other system files; it may not exist in a fresh checkout.
-   `user-files/`: Runtime directory created for budget data blobs and SQLite databases; it may not exist in a fresh checkout. **Do not delete it from an active installation.**
-   `*.sh`: Management scripts described above.

## Configuration Details

-   **Container Name:** `actual`
-   **Image:** `actualbudget/actual-server:latest`
-   **Port:** `5006` (mapped to container port `5006`)
-   **Volume:** Maps this project directory (`docker/actual-data`) to `/data` inside the container.
-   **Health check:** Runs the image's `/app/scripts/health-check.js` every 30 seconds.

---
*Note: This runs locally on your machine. Ensure this directory is included in your system backups.*
