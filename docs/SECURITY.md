# Security Model

Astra can run commands, install software, manage services, edit files, and change firewall rules. Treat a panel account as having the privileges of the Astra process. The Linux system installer runs Astra as root; the Windows installer runs it as SYSTEM. The web command console is enabled by default and executes shell commands with those same privileges.

## Defaults and Protections

- The default listener is `0.0.0.0:8800` using plain HTTP. It is reachable on the machine's network unless a firewall blocks it. Configure TLS or bind to loopback before use on an untrusted network.
- Sign-in uses one administrator username and password. Passwords are stored as salted PBKDF2-SHA256 hashes, not plaintext. There are no separate user accounts or roles.
- Sessions are random, held server-side in memory, and expire after `session_ttl_hours` (default 8 hours). The browser receives an `HttpOnly`, `SameSite=Strict` session cookie. Astra adds the `Secure` cookie flag when its own TLS certificate and key are configured. Sessions end when the server restarts or the user signs out.
- Optional TOTP and e-mail factors can be enabled in Settings. Login challenges expire after 5 minutes; e-mail codes expire after 10 minutes and allow five attempts; TOTP codes cannot be reused.
- Failed logins are limited per client IP: five failures within five minutes cause further API requests from that IP to be blocked until the window passes. `allowed_ips` can further restrict API access.
- API requests require a valid session before the request body is read. Authentication request bodies are limited to 4 KB; other API bodies are limited to 12 MB. POST requests with a mismatched `Origin` are rejected.
- The console can be disabled with `astra config set console_enabled false`. Console commands are run by a shell, and the command text (up to 300 characters) and working directory are written to the audit log. Avoid putting secrets in commands.
- Extension routes marked `write=True` require POST and are audited. Extension Python runs in-process with the panel's full OS privileges. Install only code you have reviewed.
- The extension subprocess helper uses argument lists and avoids `shell=True`; this does not apply to the explicitly shell-based command console.
- File operations are constrained by `file_roots` after resolving symlinks. Services, logs, and process targets have allowlists or guards. A local attacker able to race filesystem changes may still exploit the gap between path validation and use; keep roots writable only by trusted users.
- The web server sends a restrictive Content Security Policy, frame protections, MIME protections, and cache controls. Systemd adds `NoNewPrivileges`, `PrivateTmp`, and kernel protections.
- The optional Linux desktop session is separate from the web desktop. Its VNC server is bound to loopback, runs as configured unprivileged `desktop.user`, is memory-capped, and uses a generated password. Installation requires confirmation and resource checks.

## Recommended Deployment

1. For local-only access, set `host` to `127.0.0.1` and connect through an SSH tunnel.
2. For remote access, use HTTPS and a firewall or `allowed_ips` allowlist. See [nginx/astra.conf.example](../nginx/astra.conf.example) for a reverse-proxy example. When TLS terminates at a proxy, configure that proxy to accept only HTTPS and restrict access; Astra cannot infer the original scheme from the proxy.
3. Disable the command console if it is not required: `astra config set console_enabled false`.
4. Run `astra doctor` after deployment and review the Security tab.
5. Change the generated password with `astra passwd` if it may have been exposed. Keep the config directory private; it contains the password hash, MFA secret, SMTP credentials, and other settings.
6. Review and back up the config directory using `scripts/backup-config.sh` or `scripts/backup-config.ps1`.

## Audit and Data

Audit events are stored in `<config directory>/logs/audit.log`, rotated at about 5 MB, and pruned according to `audit_retention_days` (default 90 days). Events can include client IPs, account names, action parameters, and console command text. Passwords and fields named `password`, `token`, `content`, or `data` are redacted from extension/action parameters; console command text is not redacted. Panel diagnostics are stored in `<config directory>/logs/panel.log`. Notifications are stored separately in `<config directory>/notifications.json`.

The config directory is `/etc/astra` for root on Linux, `%ProgramData%\astra` for an elevated Windows install, or `~/.astra` for an unprivileged user unless `ASTRA_HOME` overrides it. On Linux, Astra sets private directory/file modes when it creates them. On Windows, it applies an ACL to the config directory.

## Known Limits

- This is a single-operator panel. It has no role separation or independent identities for audit attribution; actions should not be treated as non-repudiable records.
- TOTP secrets and SMTP credentials are stored in the protected config file. Anyone who can read that file can access those secrets.
- E-mail MFA is only as secure as the mailbox and SMTP account. The Linux desktop contains a terminal and should be treated as shell access for `desktop.user`.
- Security-tab checks are informational heuristics, not a formal security audit. Software installation and management commands invoke real tools on the host.
- Windows and some optional package-install paths require additional real-system validation; see [TODO.md](../TODO.md).
