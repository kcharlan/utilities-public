# Node.js Express API (`app_node`)

This directory contains a simple Node.js application built with Express.js. It serves as a basic example of a backend service that can be integrated into the main web server setup via Nginx.

## Overview

*   **`api.js`**: The main application file, defining an Express server with ES module syntax and a single API endpoint.
- **`package.json`**: Defines project metadata and the Express.js dependency.
  It uses `"type": "module"` for ES module imports.
- **`package-lock.json`**: Records a resolved dependency graph for local tooling,
  but the current Dockerfile intentionally installs from the compatible range
  in `package.json` with `--no-package-lock`.

## Functionality

The `app_node` service exposes a single GET endpoint:

*   `GET /api/node/hello`
    *   **Description:** Returns a JSON object indicating the API is working and its origin.
    *   **Response:** `{"ok": true, "from": "node"}`

This service runs on port `4000` within its Docker container and is exposed externally via the Nginx reverse proxy under the `/api/node/` path. The Nginx proxy also includes WebSocket support headers for this location.

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `app_node` service is built with `app_node_Dockerfile` from the `node:24-alpine` base.
*   The image installs production dependencies and copies `api.js` at build time; it does not mount source or install packages during container startup.
*   npm is removed from the final image after dependencies are installed, and the image starts with `node api.js`.
*   Port `4000` is exposed internally for Nginx to access.

## How to Modify and Extend

1.  **Add New Endpoints:**
    *   Edit `api.js` to add more routes and logic using Express.js.
    *   Example:
        ```javascript
        app.get('/api/node/new-endpoint', (req, res) => {
          res.json({ message: 'This is a new endpoint!' });
        });
        ```

2.  **Add Dependencies:**
    *   If your new features require additional Node.js packages, add them to `package.json` under `dependencies`.
    *   Example:
        ```json
        "dependencies": {
          "express": "^5.2.1",
          "new-package": "^1.0.0"
        }
        ```

3.  **Rebuild and Restart:**
    After changing `api.js` or dependencies, rebuild the `app_node` image:
    ```bash
    docker compose up -d --build app_node
    ```

4.  **Update Nginx (if necessary):**
    If you change the base path for your Node.js API (e.g., from `/api/node/` to `/my-node-app/`), you'll need to update the `nginx/default.conf` file accordingly and restart the `web` service:
    ```bash
    docker compose restart web
    ```
