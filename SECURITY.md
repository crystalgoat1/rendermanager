# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in the RenderManager agent, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, email **security@rendermanager.com** with:

- A description of the vulnerability
- Steps to reproduce
- The potential impact
- Any suggested fixes (optional)

We will acknowledge your report within 48 hours and aim to release a fix within 7 days for critical issues.

## Scope

This policy covers:
- The RenderManager agent (`agent/`)
- The Blender addon (`blender_addon/`)

Server-side vulnerabilities should also be reported to the same email address.

## Security Model

The agent authenticates to the RenderManager server using a per-user token provisioned via PKCE OAuth flow. The token is stored locally in `%APPDATA%/RenderManager/agent_config.json` and transmitted via the `X-Agent-Token` HTTP header (never in URL parameters).

Render overrides are validated against a strict allowlist with type and range checking. No arbitrary code execution is possible through the override system.

The agent never uploads or transmits the contents of your `.blend` files — only file paths, metadata, and rendered frame previews.
