# Maintenance to-do

- [ ] Decide whether existing CDN-backed browser tools need offline delivery.
  For tools selected for migration, vendor exact-version scripts, styles, and
  fonts with source URLs, hashes, and licenses; verify browser behavior with
  external requests blocked. Follow the delivery rules in [agents.md](../agents.md).
- [ ] Review the container image update policy: retain deliberate tag-based
  refreshes or pin digests with an explicit refresh process. Validate any
  change through each affected stack's complete suite and health checks.
