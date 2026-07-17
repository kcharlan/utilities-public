# Dynamic Index Server (`index`)

This directory contains a Node.js application built with Fastify that provides a dynamic directory listing for the `webroot` content served by Nginx, a configuration UI for managing reverse-proxy endpoints, and a transparent proxy for those dynamic endpoints. It enhances the static file serving by offering a browsable interface with inferred titles for HTML files.

## Overview

*   **`server.js`**: The main application file, defining a Fastify server that handles three responsibilities: file browsing, endpoint configuration, and dynamic reverse proxying.
*   **`package.json`**: Defines project metadata and dependencies.

## Functionality

### File Browser (`/files`)

1.  **Scanning `webroot`:** Reads the contents of the `/mnt/webroot` directory (mounted from your host's `~/webroot`).
2.  **Inferring Titles:** For HTML files, extracts the content of the `<title>` tag to provide a more descriptive link in the index.
3.  **Generating HTML Index:** Dynamically creates an HTML page listing directories and files, with links to navigate through the `webroot` structure.

### Endpoint Configuration UI (`/configure`)

A built-in control panel for creating and managing reverse-proxy endpoints without editing Nginx configuration:

*   **CRUD operations:** Create, read, update, and delete endpoints via a REST API at `/configure/api/endpoints`.
*   **Live editing:** Changes take effect on the very next request without container restarts.
*   **Path validation:** Reserved prefixes (`/files`, `/configure`, `/api/py`, `/api/node`) are blocked to protect built-in routes.
*   **Persistence:** Configuration is saved as JSON to `endpoints.json` under the `CONFIG_ROOT` mount (default: `~/webroot/.webserver`).

### Dynamic Reverse Proxy

*   **Transparent proxying:** Proxies requests matching configured endpoint paths to upstream targets using `@fastify/reply-from`. Common request bodies (including `application/x-www-form-urlencoded`) are streamed through without server-side parsing.
*   **Strip path option:** Each endpoint can strip or preserve the public prefix when forwarding traffic.
*   **Host access:** Targets using `localhost` or `127.0.0.1` are automatically rewritten to `host.docker.internal` (or the value of `HOST_DOCKER_GATEWAY`) so containers can reach host-side services.
*   **Sticky routing:** When an app served via a stripped-path alias makes follow-up requests to absolute paths (e.g., `/search`), the proxy remembers the client (5 minutes per IP+User-Agent) and continues routing to the same upstream.

This service runs on port `3000` within its Docker container and is accessed by Nginx as the fallback for requests where no static file is found.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `WEBROOT` | `/mnt/webroot` | Directory the file browser reads from |
| `CONFIG_ROOT` | `/mnt/config` | Directory where `endpoints.json` is stored |
| `CONFIG_FILE` | `$CONFIG_ROOT/endpoints.json` | Full path to the endpoint config file |
| `HOST_DOCKER_GATEWAY` | `host.docker.internal` | Loopback remap target so containers can reach localhost services on the host |

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `index` service is built from `index/Dockerfile` using the `node:24-alpine` base.
*   The image installs production dependencies and copies `server.js` at build time; source and `node_modules` are not host-mounted.
*   It mounts your host's `~/webroot` to `/mnt/webroot` (read-only) and `~/webroot/.webserver` to `/mnt/config` (read-write for persistence).
*   npm is removed from the final image after dependencies are installed, and the service starts with `node server.js`.
*   Port `3000` is exposed internally for Nginx to access.

## How to Modify and Extend

### Theming the Index

The dynamic index uses inline CSS and a basic HTML structure. To customize its appearance:

1.  **Edit `server.js`:**
    *   Locate the large HTML template string within the file browser route.
    *   You can directly modify the `<style>` block to change fonts, colors, layout, etc.
    *   For more advanced theming, you could add a link to an external CSS file placed in your `~/webroot` directory.

2.  **Rebuild and Restart `index` service:**
    After making changes to `server.js` or `package.json`, you need to rebuild the `index` service to apply them:
    ```bash
    docker compose up -d --build index
    ```

### Modifying Index Logic

*   **Change File/Directory Display:** You can modify the directory scanning logic in `server.js` to change how files and directories are filtered, sorted, or displayed.
*   **Add New Features:** For example, you could add search functionality or different viewing modes.

## Dependencies

*   `fastify`: A fast and low-overhead web framework for Node.js.
*   `@fastify/reply-from`: Fastify plugin for proxying requests to upstream services (powers the dynamic reverse proxy).
*   `cheerio`: Used for parsing and manipulating HTML, specifically to infer titles from HTML files.
*   `mime`: MIME type lookup for serving correct content types.
