# Deployment Runbook — v0.1.79 (Chain A + B)

> Plans: 021a, 021b, 021c, 021d, 022, 023a, 023b, 024
> Target: BSE_customer (custt0001)
> Current version: v0.1.78

## Pre-Deploy Checklist

- [x] Cosmos containers created (Step 1)
- [x] Azure Files data downloaded for migration (Step 3)
- [x] Migration dry-run verified (Step 4)
- [x] Migration executed (Step 4)
- [ ] Code merged to `main` and image built/pushed to ACR as `v0.1.79`
- [ ] Deploy via `update_aca.zsh` (Step 2)
- [ ] Post-deploy validation (Step 5)

---

## Step 1: Create Cosmos Containers (BEFORE deploy)

The new code expects these containers on startup. Create them before deploying
so the app doesn't hit errors on first request.

```bash
RG="BSE_customer"
COSMOS_ACCT="bse-cosmos-customer-custt0001"
DB="bsedb"

az cosmosdb sql container create \
  --resource-group "$RG" \
  --account-name "$COSMOS_ACCT" \
  --database-name "$DB" \
  --name extraction_results \
  --partition-key-path /partitionKey

az cosmosdb sql container create \
  --resource-group "$RG" \
  --account-name "$COSMOS_ACCT" \
  --database-name "$DB" \
  --name snapshot_schemas \
  --partition-key-path /partitionKey
```

**Verify:**
```bash
az cosmosdb sql container list \
  --resource-group "$RG" \
  --account-name "$COSMOS_ACCT" \
  --database-name "$DB" \
  --query "[].name" -o tsv
```

Expected: the existing 9 containers plus `extraction_results` and `snapshot_schemas`.

---

## Step 2: Deploy New Image

```bash
cd deploy/azure

./update_aca.zsh \
  --rg BSE_customer \
  --app bse-backend-customer-custt0001 \
  --tag v0.1.79
```

This handles both backend and frontend (frontend name is derived). The script
does blue/green with health checks and automatic rollback on failure.

**Verify after deploy:**
```bash
# Check the version endpoint
curl -s https://<backend-fqdn>/api/version | jq .

# Check health
curl -s https://<backend-fqdn>/api/health | jq .

# Check container logs for startup errors
az containerapp logs show \
  --resource-group BSE_customer \
  --name bse-backend-customer-custt0001 \
  --tail 50
```

The SQLite schema migration (11 new columns on `snapshot_documents`) runs
automatically on startup — no action needed.

---

## Step 3: Download Azure Files Data (for migration)

SMB port 445 is blocked on most networks. Use `az storage file download-batch`
to pull the data locally via REST API instead.

```bash
mkdir -p ~/Downloads/bsedata_migration

az storage file download-batch \
  --account-name bsecustt0001 \
  --source bsedata/PLANDATA \
  --destination ~/Downloads/bsedata_migration/PLANDATA
```

**Note:** The migration script appends `PLANDATA/` to `--data-dir` internally,
so pass the parent directory (not the PLANDATA directory itself).

---

## Step 4: Run Data Migration

The migration moves existing filesystem JSON into the new Cosmos containers.
The app has fallback readers, so it works before migration — but new documents
processed after deploy will only write to Cosmos, not filesystem. Run this
promptly after deploy.

```bash
COSMOS_ENDPOINT="https://bse-cosmos-customer-custt0001.documents.azure.com:443/"
COSMOS_KEY=$(az cosmosdb keys list \
  --resource-group BSE_customer \
  --name bse-cosmos-customer-custt0001 \
  --query "primaryMasterKey" -o tsv)

cd /Users/example/source/benefit_specification_engine

# Dry run first
.venv/bin/python scripts/migrate_json_to_cosmos.py \
  --cosmos-endpoint "$COSMOS_ENDPOINT" \
  --cosmos-key "$COSMOS_KEY" \
  --data-dir ~/Downloads/bsedata_migration/ \
  --dry-run

# When satisfied, run for real
.venv/bin/python scripts/migrate_json_to_cosmos.py \
  --cosmos-endpoint "$COSMOS_ENDPOINT" \
  --cosmos-key "$COSMOS_KEY" \
  --data-dir ~/Downloads/bsedata_migration/
```

**Completed output:**
```
[H11111] Migrating...
  [H11111] 3 migrated (1 extraction, 1 metadata, 1 schema)

=== Migration complete ===
  Extraction results: 1 migrated, 0 skipped, 0 failed
  Metadata:           1 migrated, 0 skipped, 0 failed
  Schemas:            1 migrated, 0 skipped, 0 failed
  Total written:      3
```

---

## Step 5: Post-Deploy Validation

After deploying the new image, verify the app reads from Cosmos correctly:

```bash
# Spot-check: open the app UI, navigate to plan H11111,
# verify extraction results and schema data load correctly.
# The data should come from Cosmos now, not filesystem.
```

Optional — run the comparison tool:
```bash
.venv/bin/python scripts/cosmos_dump.py \
  --endpoint "$COSMOS_ENDPOINT" \
  --key "$COSMOS_KEY" \
  --data-dir ~/Downloads/bsedata_migration/ \
  --compare
```

---

## Rollback Plan

If something goes wrong after deploy:

```bash
cd deploy/azure
./update_aca.zsh \
  --rg BSE_customer \
  --app bse-backend-customer-custt0001 \
  --rollback
```

The old code reads from filesystem JSON, so rolling back is safe even after
migration — Cosmos data is additive. The old code simply ignores the new
containers.

**Note:** If you rollback, the two new Cosmos containers (`extraction_results`,
`snapshot_schemas`) remain but are unused. That's fine — they don't affect the
old code. Do NOT delete them, as they'll be needed when you re-deploy.

---

## What Changed (Summary)

| Area | Change | Impact |
|------|--------|--------|
| Cosmos | 2 new containers: `extraction_results`, `snapshot_schemas` | New data storage for extraction results and schemas |
| Data path | Sidecar JSON files no longer written in Cosmos mode | External tooling reading `-meta.json`, `.pdf.json`, `.SIG` must switch to API or `cosmos_dump.py` |
| LLM default | Default provider changed from `abacusai` to `openrouter` | Only affects environments without persisted runtime config |
| SRE logging | Structured error events on route handlers and extraction pipeline | Transparent — no config needed |
| Frontend | Schema editor button/dialog CSS uplift | Visual only |

---

## Brownfield Exception

This deployment bypasses the brownfield delta pack requirement for Bicep changes.
The two new Cosmos containers are created via `az cli` (above) rather than through
the formal delta pack workflow. This exception is acceptable for a single test
customer but **must not be carried forward** — enforce brownfield delta packs
once additional customers are onboarded.
