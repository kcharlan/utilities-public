# Nginx Configuration (`nginx`)

This directory contains the Nginx configuration files for the `web` service. Nginx acts as the reverse proxy and static file server for the entire web server setup.

## Overview

*   **`default.conf`**: The primary Nginx configuration file, defining server blocks, locations, and proxy rules.

## Functionality

The `default.conf` file configures Nginx to:

1.  **Listen on Port 80:** The Nginx server listens for incoming HTTP requests on port 80 (which is mapped to `localhost:7711` on your host machine).
2. **Serve Static Files:** It serves content from `/usr/share/nginx/html`,
   mounted from the external host directory named by `WEBROOT_PATH`.
3.  **File Sync & Caching:**
    *   **`sendfile off;`**: Disables `sendfile` to ensure that changes to files in mounted Docker volumes are detected immediately, which is especially important on macOS.
    *   **Dev-Friendly Caching**: Sets `Cache-Control: no-cache` for common static assets (CSS, JS, images, fonts) to force the browser to validate the file with the server on every request, ensuring you always see the latest version during development.
4.  **Reverse Proxy:** Routes requests to the appropriate backend services:
    * **Dynamic Index:** The root path (`/`) tries to serve `index.html` first,
      falling back to the `index` Node.js service. Other missing paths are sent
      to `@dynamic_index`, except common static asset extensions matched by the
      cache-control location; those return 404 when the file is absent.
    *   **Python API:** Requests to `/api/py/` are proxied to the `app_py` FastAPI service (running on port `80`).
    *   **Node.js API:** Requests to `/api/node/` are proxied to the `app_node` Express.js service (running on port `4000`), with WebSocket upgrade support (`proxy_http_version 1.1`, `Upgrade`, and `Connection` headers).

## Integration with Docker Compose

In `docker-compose.yml`:

*   The `web` service uses the moving `nginx:stable-alpine` Docker image.
*   It mounts the `default.conf` file from this directory into the Nginx container at `/etc/nginx/conf.d/default.conf` (read-only), overriding the default Nginx configuration.
- It also mounts the external directory named by `WEBROOT_PATH` in the ignored
  `.env` to `/usr/share/nginx/html` read-only.

## How to Modify and Extend

### Modifying Nginx Configuration

To change how Nginx behaves, you will edit `default.conf`.

*   **Add New Proxy Rules:** To integrate new backend services, add new `location` blocks similar to those for `/api/py/` or `/api/node/`.
    *   Ensure the `proxy_pass` directive points to the correct service name and port as defined in `docker-compose.yml`.
*   **Adjust Caching:** Modify the `Cache-Control` directives for static assets.
*   **Custom Error Pages:** You can configure custom error pages (e.g., `error_page 404 /404.html;`).
*   **HTTPS/SSL:** For production environments, you would configure SSL certificates here. This typically involves adding `listen 443 ssl;` and specifying `ssl_certificate` and `ssl_certificate_key` directives.

### Applying Changes

After modifying `default.conf`, you need to restart the Nginx `web` service for the changes to take effect:

```bash
docker compose restart web
```

### Testing Nginx Configuration

Before restarting, you can test the syntax of your Nginx configuration to catch errors early:

```bash
docker compose exec web nginx -t
```

This command will execute `nginx -t` inside the running `web` container, which checks the configuration file for syntax errors and then exits.
