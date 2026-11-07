# astra

A personal, hackable server control panel in the spirit of aaPanel. **Python standard library only** (3.9+, Linux and Windows 10/11 / Server 2016+): no pip packages, no Node build, no third-party scripts or fonts.

- **Web GUI**: dashboard with live charts, 5 themes, 3 text sizes, 2 densities, keyboard-friendly and screen-reader friendly
- **CLI**: every feature is scriptable (`astra call <extension> <route> key=value`)
- **TUI**: live terminal dashboard (`astra tui`)
- **Desktop tab**: window-based web desktop over every tab (zero dependencies); an optional real Linux GUI session installs only after you confirm
- **Sign-in**: access token plus optional authenticator-app (Google Authenticator) and e-mail codes
- **Extensions**: 12 built in, drop-in Python files for your own; each one defines its API and its GUI tab together

## Built-in extensions

| Tab | What it does | Needs |
|---|---|---|
| Desktop | draggable, keyboard-operable windows hosting every other tab; optional Linux GUI (Openbox + terminal) installed on demand | nothing (GUI: apt) |
| Dashboard | CPU/memory/swap/disk/network meters, 30 min history charts, alerts, top processes | nothing |
| Services | start/stop/restart/enable/disable allowlisted systemd units | systemd |
| Websites | create static or reverse-proxy nginx sites, enable/disable/delete, Let's Encrypt | nginx (+certbot) |
| Files | sandboxed browser, editor, upload, download, rename, delete, new folder | nothing |
| Cron | managed `/etc/cron.d/astra`, run-now, enable/disable | cron |
| Firewall | list/add/delete UFW rules, enable/disable | ufw |
| Docker | containers (start/stop/restart/logs/remove) and images | docker |
| Databases | list/create/drop/back up MySQL/MariaDB and PostgreSQL | mysql / psql |
| Backups | tar.gz of folders, download, safe restore | nothing |
| Logs | tail log files and service journals (allowlisted) | nothing |
| Processes | top by memory, SIGTERM/SIGKILL | nothing |
| Security | SSH/firewall/fail2ban/update checks, listening ports, panel audit log | nothing |
| Settings | theme, size, density, token rotation, extension status | nothing |

A tab whose tool is missing is shown with what to install instead of failing.

**Deliberately not included:** a web terminal/SSH shell (a browser-reachable root shell is the biggest risk a panel can add; use SSH) and mail-server management. Both can be added as extensions if you accept the risk.

## Repository layout

```
install.sh / uninstall.sh      Linux (apt) installer and remover
install.ps1 / uninstall.ps1    Windows installer and remover (elevated PowerShell, scheduled task "AstraPanel")
scripts/*.ps1, tests/*.ps1     Windows equivalents of the .sh helper scripts
Makefile                       make dev | test | check | install | doctor
systemd/astra.service        hardened unit file
nginx/astra.conf.example     HTTPS reverse proxy with IP allowlist
scripts/                       dev.sh, doctor.sh, backup-config.sh
examples/hello_extension.py    minimal custom extension
docs/                          EXTENSIONS.md, SECURITY.md
tests/                         run.sh, demo.sh, test_*.py; docker/ is an OPTIONAL harness
astra/
  server.py   HTTP server, auth, rate limiting, routing, security headers
  config.py   config file, token hashing         audit.py  audit log
  monitor.py  /proc metrics + sampler thread     shell.py  safe subprocess + validators
  cli.py      CLI                                tui.py    curses dashboard
  extensions/ __init__.py (framework) + one file per tab
  mfa.py      sessions, TOTP, e-mail codes          legal.py   /legal/privacy and /legal/terms
  legal/      privacy.md, terms.md templates
  web/        index.html, style.css, app.js (no framework); ui/ = modules loaded only when their tab opens
```

## Quick start

Try it without root (some tabs will say they need root):

```bash
./scripts/dev.sh          # creates ./.dev-home, prints your token, serves http://127.0.0.1:8800
make test
```

Install on a Debian/Ubuntu server:

```bash
sudo ./install.sh --port 8800 --with "nginx ufw fail2ban"
```

**Windows / Windows Server** (elevated PowerShell, Python 3.9+ installed for all users, or add `-InstallPython` where winget exists):

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Port 8800
```

It copies the code to `%ProgramFiles%\Astra`, keeps config, token and logs in `%ProgramData%\astra` (ACL: SYSTEM + Administrators), adds `astra` to the machine PATH and registers the scheduled task `AstraPanel` (starts at boot as SYSTEM). Services use `sc.exe`, the firewall uses `netsh advfirewall`, scheduled jobs use Task Scheduler, and nginx/databases are found on PATH or in `bin_dirs`. Remove with `uninstall.ps1 [-Purge]`. Linux-only pieces (the optional GUI session, apt, ufw, fail2ban, cron.d) are hidden or marked unavailable on Windows. See `TODO.md` for what is still unverified.

Linux: the installer installs Python and the packages you list, copies the code to `/opt/astra/src`, creates `/usr/local/bin/astra`, creates `/etc/astra/config.json` (mode 600) and an access token (shown once), installs and starts the `astra` systemd service, then runs `astra doctor`.

Open it through an SSH tunnel (the panel listens on `127.0.0.1` only):

```bash
ssh -L 8800:127.0.0.1:8800 you@your-server      # then browse http://127.0.0.1:8800
```

For public access use HTTPS: either nginx (`nginx/astra.conf.example`) or set `tls_cert` and `tls_key` in the config. Read `docs/SECURITY.md` first.

Other distributions: copy the folder anywhere, then run `PYTHONPATH=<folder> ASTRA_HOME=/etc/astra python3 -m astra init` and `... serve`, and adapt the unit file.

## Command line

```bash
astra init [--new-token]       # first-time setup / rotate token
astra serve                    # run in the foreground (the service does this)
astra status                   # colour bars: CPU, memory, disks
astra tui                      # live terminal dashboard (Tab switches views, q quits)
astra doctor                   # diagnose setup problems
astra ext                      # list extensions and what each needs
astra services | svc nginx restart
astra call files list path=/var/www
astra call firewall add port=443 proto=tcp action=allow
astra call databases backup engine=mysql name=shop
astra config | config set file_roots '["/var/www","/srv","/home/me"]'
astra logs -n 50               # audit log
```

`astra call` runs the exact same code as the web GUI, so anything you can click you can script or cron.

## Configuration

`/etc/astra/config.json` (or `~/.astra/` when not root). Apply changes with `systemctl reload astra`; changing `host`, `port` or TLS needs `systemctl restart astra`.

| Key | Default | Meaning |
|---|---|---|
| `host`, `port` | `127.0.0.1`, `8800` | listen address |
| `tls_cert`, `tls_key` | empty | serve HTTPS directly when both set |
| `allowed_ips` | `[]` | if non-empty only these client IPs may call the API |
| `services` | `["nginx","ssh"]` | systemd allowlist (also editable in the Services tab) |
| `file_roots` | `/var/www`, `/srv` | the only folders the Files and Backups tabs may touch |
| `web_roots` | `/var/www` | where new static sites may live |
| `log_files` | common system logs | the only files the Logs tab may read |
| `backup_dir` | `/var/backups/astra` | backups and database dumps |
| `cron_user` | `root` | user that scheduled jobs run as |
| `disabled_extensions` | `[]` | hide extensions by name |
| `alerts` | cpu/mem/disk 90 | percent thresholds; 0 disables |
| `session_ttl_hours` | `8` | how long a sign-in lasts |
| `audit_retention_days` | `90` | older audit lines are deleted at start-up (0 keeps all) |
| `smtp` | empty | `host`, `port`, `security` (`starttls`/`ssl`/`none`), `user`, `password`, `from`; for e-mail codes |
| `operator` | empty | `name`, `email`, `address`, shown on the privacy and terms pages |
| `desktop` | `{}` | `user` (required for the Linux GUI), `geometry`, `mem_max_mb` |
| `sample_interval`, `history_len` | `5`, `360` | monitoring resolution (5 s x 360 = 30 min) |

## Multi-factor sign-in

Settings → Multi-factor sign-in. The access token is always step one; with a factor on, the token alone no longer works (not even in API calls), only a session obtained after step two.

- **Authenticator app** (Google Authenticator, Authy, 1Password, ...): press Set up, enter the shown key as a time-based setup key, confirm one code. Standard RFC 6238; codes cannot be reused.
- **E-mail codes**: configure SMTP first, e.g. `astra config set smtp '{"host":"smtp.example.com","port":587,"security":"starttls","user":"me","password":"app-password","from":"panel@example.com"}'`, check with `astra mfa test-email you@example.com`, then Set up in Settings. Codes are 6 digits, valid 10 minutes, 5 tries. The e-mail factor is only as strong as that mailbox; prefer the authenticator app, or use both.
- Locked out: on the server run `astra mfa reset` (needs root access to the config). `astra mfa` shows status.
- Sessions live in memory for `session_ttl_hours`; a restart, sign-out or token rotation ends them.

## Desktop tab

Opens a window manager inside the page: Start menu, taskbar, draggable and resizable windows (keyboard: Tab to a title bar, arrows move, Shift+arrows resize, Esc closes), layout remembered in your browser. Each window is one of the normal tabs, so it costs nothing extra to run, and the code for it downloads only when you open the tab.

The **Linux desktop (optional)** app is a real graphical session (TigerVNC + noVNC + Openbox + xterm). It is **not installed until you press Install and confirm**; the panel first checks root, apt, ≥ 800 MB free disk and ≥ 400 MB free memory and refuses on small servers. Starting it also refuses when memory is low. It runs as the unprivileged user in `desktop.user` (never root), capped by `desktop.mem_max_mb`, bound to `127.0.0.1` with a random one-time VNC password. Reach it through an SSH tunnel (the panel shows the exact command). The panel installs nothing beyond those five packages; add browsers or other apps yourself with apt. Written for Debian/Ubuntu; the package install and session start could not be exercised in the build environment, so try them on a spare machine first (the gating logic is covered by tests).

## Theming and customising

- Pick a theme, text size and spacing in **Settings** (saved in your browser).
- Put your own CSS in `/etc/astra/custom.css`; it loads after the built-in styles. Override variables such as `--bg`, `--fg`, `--ac` or restyle anything.
- Add features with extensions: see `docs/EXTENSIONS.md` and `examples/hello_extension.py`.

## Debugging

| Symptom | Check |
|---|---|
| Panel will not load | `systemctl status astra`, `journalctl -u astra -e`, `astra doctor` |
| "Token rejected" | rotate it: `astra init --new-token` then `systemctl reload astra` |
| "Too many failed attempts" | wait 5 minutes or `systemctl restart astra` |
| A tab says something is missing | install the listed package, reload the page |
| Action fails with "permission denied" | the service is not running as root |
| What changed on my server? | Security tab, or `astra logs` (every write is recorded, passwords and file contents are redacted) |
| Run in the foreground with logs | `systemctl stop astra && astra serve` |

## Testing and trying things

```bash
make test          # tests/run.sh: syntax checks + 36 tests, no root, no network
make demo          # tests/demo.sh: throwaway sandbox on :8800, e-mail codes print in the terminal
make test-docker   # OPTIONAL: same tests in a container (Docker is never needed to run the panel)
docker compose -f tests/docker/compose.yml up demo     # OPTIONAL: demo in a container, loopback only
```

Tests cover path sandboxing, symlink escapes, input validation, auth and lockout, TOTP (RFC vectors, replay, drift), e-mail codes, session revocation, privacy export/delete, legal pages, accessibility/contrast, static caching, and the desktop install and start gates.

## Privacy, accessibility and legal

astra is a single-user tool for your own servers. The website checklist was applied only where it fits; the full item-by-item answer, including what was deliberately left out and why, is in `docs/COMPLIANCE.md`. In short:

- **Included**: privacy notice and terms (`/legal/privacy`, `/legal/terms`, filled from the `operator` config), data minimisation with audit-log retention, data export and deletion (Settings → Privacy, `astra privacy export|delete`), no third-party code, keyboard navigation, labelled controls, tested WCAG AA colour contrast in all themes, font/image licensing statement (`THIRD_PARTY.md`).
- **Not applicable, so absent**: refund policy, cookie banner (no cookies are set), marketing-consent forms, unsubscribe links (the only e-mail is the one-time sign-in code), age gates, business details beyond the operator contact, fake reviews, hidden fees, dark patterns.

`make test` checks these claims (no external URLs, contrast ratios, no cookies, retention, deletion).

## Limits you should know about

Linux and Windows. Tested here with the automated suite on Ubuntu only; the Windows code paths have not been run, so try them on a non-critical Windows machine first; the nginx, ufw, docker, certbot and database tabs call the real tools, so try them on a non-critical machine before relying on them. This is a personal-use tool without multi-user accounts (one operator, optional 2FA); the web UI has not been exercised in a real browser during the build (only syntax-checked and API-tested), so look it over after installing. Protect it with the network measures in `docs/SECURITY.md`.
