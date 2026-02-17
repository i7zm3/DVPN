# Security Policy

## Reporting Vulnerabilities

Do not disclose vulnerabilities publicly before a fix is available.

Send reports with:

- affected version/commit
- reproduction steps
- impact and exploitability
- suggested remediation

## Security Controls In This Repo

- TLS minimum version enforcement for pool/payment/fallback transport
- encrypted token storage (PBKDF2 + integrity MAC)
- provider input validation (endpoint/public key/CIDR)
- control plane health/metrics endpoints for runtime monitoring
- production compose hardening (no-new-privileges, resource limits, log rotation)

## Out-of-Scope For Code-Only Changes

The following require operational/org work outside this repository:

- independent penetration testing
- key custody/HSM policy
- legal/compliance certifications
- SOC2/ISO process controls
- incident response staffing and runbooks in production org tooling
