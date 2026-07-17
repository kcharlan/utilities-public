# Mermaid Live Editor (Docker)

This directory contains scripts to run a local instance of the [Mermaid Live Editor](https://github.com/mermaid-js/mermaid-live-editor) using Docker. This allows you to create and edit Mermaid diagrams offline or without sending data to the public internet.

## Prerequisites

*   **Docker:** You must have Docker installed and running on your machine.

## Usage

### Starting the Editor

To start the Mermaid Live Editor container and automatically open it in your default browser:

```sh
./run.sh
```

Alternatively, you can just start the container in the background without opening the browser:

```sh
./start.sh
```

Once running, the editor is accessible at: **[http://localhost:5008](http://localhost:5008)**

### Stopping the Editor

To stop and remove the container:

```sh
./stop.sh
```

### Updating

To pull the latest version of the Mermaid Live Editor image and restart the container:

```sh
./update.sh
```

## Configuration

The container is configured to run on port `5008` by default to avoid conflicts with other common services. You can modify the port mapping in the `start.sh` and `update.sh` scripts if needed.
