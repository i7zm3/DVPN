# Threat Model (High Level)

## Assets

- payment token and user identity
- WireGuard private key
- pool/orchestrator trust decisions
- node routing metadata and logs

## Trust Boundaries

- client container <-> pool API
- client container <-> payment API
- client container <-> fallback orchestrator
- local host networking stack <-> public internet

## Key Threats

- MITM on control APIs
- malicious provider metadata injection
- token/key leakage from filesystem or logs
- denial-of-service on reconnect/fallback loops
- abusive node registration/spoofed endpoints

## Mitigations Implemented

- TLS v1.2+ contexts for network calls
- provider schema validation (endpoint/public-key/CIDR)
- encrypted token-at-rest with integrity check
- bounded retries and fallback-only-on-failure
- optional CA pin path for fallback orchestrator
- pool registration as best-effort (non-blocking)
- structured audit logging + Prometheus metrics endpoint

## Remaining Gaps

- mTLS or signed requests between client and backend services
- formal rate limits / anti-abuse controls at backend
- independent cryptographic review / penetration testing
- centralized SIEM + alerting and incident response integration
