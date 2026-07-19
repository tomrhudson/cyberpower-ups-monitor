# Security Policy

## Reporting a vulnerability

Please report security issues through GitHub's private vulnerability reporting
feature rather than a public issue.

Do not include production tokens, UPS serial numbers, internal hostnames,
network addresses, database files, or other private deployment details in a
report.

## Deployment guidance

The collector ingest endpoint requires a bearer token. Generate a unique,
high-entropy token, store it in a file readable only by the service account,
and rotate it if it is exposed.

The dashboard and read API do not implement application-level authentication.
Keep them on a trusted network or protect them with an authenticated reverse
proxy. TLS termination and rate limiting should be handled at that boundary.

The macOS collector reads PowerPanel's local SQLite database in read-only mode.
The service intentionally provides no endpoint for UPS control, outlet
switching, battery tests, or host shutdown.
