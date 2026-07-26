# Mermaid Live Editor (Docker)

This directory contains scripts to run a local instance of the
[Mermaid Live Editor](https://github.com/mermaid-js/mermaid-live-editor) using
Docker. The editor is published only on the host loopback interface.

## Prerequisites

- **Docker:** Docker must be installed and running.

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

The scripts run `ghcr.io/mermaid-js/mermaid-live-editor` using its implicit
`latest` tag, bind `127.0.0.1:5008` to container port `8080`, set the restart
policy to `unless-stopped`, and name the container `mermaid`. Change the port
mapping in both `start.sh` and `update.sh` if needed.
