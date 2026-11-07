# Security model

astra can restart services, edit files and manage firewalls, so treat access to it as root access.

## Built in
- Listens on `127.0.0.1` by default; warns loudly if bound elsewhere without TLS.
- One 256-bit access token, stored only as a SHA-256 hash, compared in constant time. The browser exchanges it for a random session id (Bearer header, no cookies so no CSRF, kept in `sessionStorage` for the tab only, expires after `session_ttl_hours`).
- Optional second factor (authenticator app, e-mail code). With a factor on, the raw token is rejected by every API route except login; wrong codes count toward the IP lockout; codes are single-use with 5 tries; challenges expire in 5 minutes.
- Request bodies are read only after authentication (login bodies capped at 4 KB).
- Optional Linux desktop runs as an unprivileged user, memory-capped, on 127.0.0.1 only, with a random VNC password, and installs nothing without confirmation and a resource check.
- Brute-force protection: 5 bad tokens block that IP for 5 minutes. Optional `allowed_ips`.
- Every write action and failed login goes to `/etc/astra/logs/audit.log` (secrets redacted, rotated at 5 MB).
- No `shell=True` anywhere; all inputs validated by strict patterns; commands use argument lists.
- File access is limited to `file_roots` after resolving symlinks; deleting/renaming acts on the link, not its target.
- Services, log files and kill targets are allowlisted or protected; archives extract with Python's safe `data` filter.
- Strict Content-Security-Policy (`default-src 'self'`), `X-Frame-Options: DENY`, `no-store`, no inline scripts.
- Systemd unit with `NoNewPrivileges`, `PrivateTmp` and kernel protections.

## You should
1. Keep the default loopback bind and use an SSH tunnel, **or** put it behind HTTPS with an IP allowlist (`nginx/astra.conf.example`).
2. Behind a proxy the panel sees only the proxy's IP, so do the IP allowlisting and rate limiting in the proxy.
3. Run `astra doctor` and open the Security tab after changes.
4. Rotate the token (Settings) if it may have leaked; `config.json` must stay mode 600.
5. Only install extensions you have read: they run as root with full access.
6. Back up `/etc/astra` with `scripts/backup-config.sh`.

## Known limits
- Single operator, no per-user accounts. Sessions are lost on restart. TOTP secret and SMTP password sit in `config.json` (mode 600), so anyone who can read it is root already. E-mail codes are only as safe as the mailbox. The Linux desktop includes a terminal for `desktop.user`: treat it as shell access for that user.
- A path check followed by file use is not atomic (a local attacker who can swap symlinks inside a file root could race it). Keep `file_roots` to folders only you control.
- Cron commands and extension code run as the configured user by design.
- Report-only checks (Security tab) are heuristics, not an audit.
