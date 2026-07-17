# n8n Local Proof of Concept

This Compose project runs n8n locally without storing its encryption key or mutable state in the public repository.

## Private configuration

Copy `.env.example` to `.env`, replace every synthetic value, and keep the file mode at `0600`. The local `.env` is ignored by Git.

`N8N_ENCRYPTION_KEY` protects credentials stored in the n8n database. Once a database contains encrypted credentials, do not change this key unless you have followed an n8n-supported key-rotation or credential-migration procedure. Losing or casually replacing it can make stored credentials unreadable.

`N8N_DATA_DIR` must be an absolute path to a private local state directory. Keep that directory at `0700` and its files at `0600`. Do not point it at this public source checkout.

## Run

```bash
./up.sh
```

The UI is available at `http://127.0.0.1:5678` by default. To stop it:

```bash
./down.sh
```

The stack binds to loopback by default, validates its private configuration before starting, pulls the configured image, and waits for the n8n health endpoint.
