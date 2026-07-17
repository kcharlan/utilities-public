# Excalidraw Local Environment

This directory contains the Docker configuration to run a local instance of [Excalidraw](https://excalidraw.com/), a virtual whiteboard for sketching hand-drawn like diagrams.

## Quick Start

You can use the provided helper scripts to manage the container:

- **Start Excalidraw:** `./up.sh`
- **Stop Excalidraw:** `./down.sh`
- **Refresh the image and recreate the service:** `./update.sh`

Once started, the application will be available at: **[http://localhost:5010](http://localhost:5010)**

## Configuration Details

The setup uses Docker Compose with the following parameters:

- **Image:** `excalidraw/excalidraw:latest`
- **Port Mapping:** Host port `5010` is mapped to container port `80`.
- **Restart Policy:** Set to `unless-stopped`, ensuring the whiteboard is available after system reboots or Docker restarts.

### Manual Commands

If you prefer using Docker Compose directly:

```bash
# Start the service
docker compose up -d

# Stop the service
docker compose down
```

## Scripts

- `up.sh`: Navigates to the directory and runs `docker-compose up --build -d`.
- `down.sh`: Navigates to the directory and runs `docker-compose down -v` (removes Compose-managed volumes; this stack currently defines none).
- `update.sh`: Pulls the latest Excalidraw image, force-recreates the service, waits for readiness, and prints Compose status.

## Customization

To change the port Excalidraw runs on, edit the `ports` section in `docker-compose.yml`:

```yaml
ports:
  - "NEW_PORT:80"
```

---
*Note: This setup is intended for local development and personal use.*
