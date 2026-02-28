# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.4.x   | Yes       |
| < 0.4   | No        |

## Reporting a Vulnerability

If you discover a security vulnerability in GridBear, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

### How to Report

1. Email: **security@gridbear.io**
2. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

For non-sensitive security questions or general discussion, you can also reach us on [Discord](https://discord.gg/WhTK4PPmaE).

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix timeline**: Depends on severity (critical: days, high: 1-2 weeks, medium/low: next release)
- **Credit**: You will be credited in the release notes unless you prefer anonymity

### Scope

The following are in scope:
- Authentication and authorization bypasses
- SQL injection, XSS, CSRF, path traversal
- MCP Gateway security (token leaks, permission escalation)
- Plugin isolation failures
- Secret/credential exposure
- Docker container escape or privilege escalation

The following are out of scope:
- Vulnerabilities in third-party dependencies (report to upstream)
- Denial of service via resource exhaustion (known limitation of self-hosted deployments)
- Issues requiring physical access to the server

## Security Architecture

### Authentication
- Admin UI: bcrypt password hashing + optional WebAuthn/FIDO2 passkeys
- Session tokens: cryptographically random, stored server-side with expiration
- Rate limiting on login and setup endpoints

### Secrets Management
- Plugin secrets encrypted at rest (AES-GCM via `ui/secrets_manager.py`)
- OAuth tokens stored in encrypted secrets database
- No secrets in environment variables except bootstrap keys

### Network Isolation
- Code executor runs on isolated Docker network (no internet access)
- Internal services communicate on `gridbear-internal` bridge network
- Only the UI container exposes a public port

### MCP Gateway
- Per-user OAuth2 connections with token isolation
- Circuit breakers prevent cascading failures
- Rate limiting per client per window
