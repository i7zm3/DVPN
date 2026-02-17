# Production Readiness Checklist

## Build / Release

- [ ] CI green on main branch
- [ ] release artifacts generated with checksums
- [ ] release artifacts signed

## Configuration / Secrets

- [ ] `.env.prod` populated with real endpoints and secrets
- [ ] token/passphrase rotated from defaults
- [ ] WireGuard private key generated per deployment
- [ ] secret distribution handled outside git

## Runtime Security

- [ ] run with `docker-compose.prod.yml`
- [ ] healthcheck green and restart policy active
- [ ] logs rotated and exported to centralized sink
- [ ] `/metrics` scraped by monitoring system

## Network / Pool

- [ ] node registration succeeds with verified endpoint
- [ ] fallback orchestration tested and CA trust validated
- [ ] UPnP behavior validated in target network

## Validation

- [ ] integration smoke test pass
- [ ] failure/reconnect drill pass
- [ ] backup and restore drill pass
