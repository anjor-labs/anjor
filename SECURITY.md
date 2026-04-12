# Security Policy

## Supported Versions

Anjor is currently in early development (v0.x). Only the latest release receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.5.x   | Yes       |
| < 0.5   | No        |

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing: **anjistic@gmail.com**

Include:

- A description of the vulnerability and its impact
- Steps to reproduce
- Any relevant code snippets or proof-of-concept (non-destructive only)

You will receive an acknowledgement within 48 hours. We aim to release a fix within 14 days for critical issues.

---

## Security Design

Anjor is designed with the following security properties:

1. **API keys never logged or stored.** Payloads are sanitised before persistence — keys matching `*api_key*`, `*secret*`, `*password*`, `*token*`, `*auth*`, `*bearer*` are replaced with `[REDACTED]`.

2. **Parameterised queries only.** No f-strings or string concatenation in SQL. All user-controlled values go through SQLite parameter binding.

3. **Local-only by default.** The collector runs on `localhost:7843`. No data leaves the machine unless you explicitly configure it to.

4. **No shell execution.** `shell=True`, `eval`, `exec`, `pickle` are not used anywhere in the codebase.

5. **Payload size limits.** The `/events` endpoint rejects payloads exceeding `max_payload_size_kb` (default: 1 MB) to prevent memory exhaustion.
