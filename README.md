docs/                          EXTENSIONS.md, SECURITY.md
tests/                         run.sh, demo.sh, test_*.py; docker/ is an OPTIONAL harness
astra logs -n 50               # audit log
# Astra

A personal server control panel with a web interface, CLI, and terminal UI. Requires Python 3.9+ on Linux or Windows. The application uses the Python standard library; Windows installs the `windows-curses` package for the terminal UI. The web interface has no build step or external frontend dependencies.

The panel manages services and software, websites, files, scheduled jobs, firewalls, containers, databases, backups, logs, processes, and security checks. It also includes monitoring, notifications, a command console, optional MFA, user extensions, and a web desktop.

## Security First

The default listener is `0.0.0.0:8800` and uses plain HTTP unless TLS is configured. The command console is enabled by default and executes commands as the panel process account. The Linux installer runs the service as root; the Windows installer runs it as SYSTEM. Do not expose Astra directly to an untrusted network. Bind it to loopback and use an SSH tunnel, or configure HTTPS and restrict network access. Disable the console with `astra config set console_enabled false` if it is not needed. See [docs/SECURITY.md](docs/SECURITY.md).

## Interfaces and Features

- **Web panel**: live system dashboard, software library, notifications, settings, and management tabs. Supports six themes, five accent colors, three text sizes, and two density settings.
- **CLI**: manage the panel, inspect system state, install catalog software, and call extension routes.
- **Terminal UI**: dashboard, services and software, processes, notifications, and panel controls. On Windows it uses `windows-curses`.
- **Command console**: interactive shell running as the panel process account. It can be disabled in settings or configuration.
- **Extensions**: 12 built-in management extensions plus the dashboard and settings (Files, Websites, Docker, Databases, Logs, Processes, Tasks, Firewall, Security, Backups, Services, Desktop). Custom Python extensions can add API routes and declarative GUI sections.
- **Websites without nginx**: a built-in site host (static folders, reverse proxy, redirects by Host header, default port 8080) is used when nginx is not installed. HTTPS and WebSockets still need nginx.
- **Databases**: SQLite works everywhere; MySQL/MariaDB and PostgreSQL appear when installed and can be installed from the Services catalog.
- **E-mail**: Settings > E-mail holds the SMTP details and a test button; a mail server (Postfix, hMailServer) can be installed from the catalog.
- **Mapped address and domain**: the panel answers at `http://host:8800/astra/` as well as the bare port (`base_path`), and can be launched at boot under a domain name (`astra service install`, `astra domain set`).
- **Optional Linux desktop session**: TigerVNC/noVNC, Openbox, and xterm installed only after confirmation and resource checks. The browser-based desktop works on Linux and Windows without those packages.

Some actions require system tools or elevated privileges. The UI reports missing tools; the Services page includes a software catalog for supported package managers.

## Quick Start

For a development checkout, run on Linux/macOS shell:

```bash
./scripts/dev.sh
```

On Windows, run `.\scripts\dev.ps1`. If port 8800 is occupied, the script selects the next available port; specify one with `.\scripts\dev.ps1 -Port 8801`.

This creates `.dev-home`, initializes an admin account, and starts the panel at port 8800. The generated password is printed once. To install from the project directory instead:

```bash
python3 -m venv .venv && . .venv/bin/activate    # needed on Debian/Ubuntu 23.04+ (PEP 668: "externally-managed-environment")
python -m pip install .
astra init
astra web
```

`pipx install .` works too. For a server install use the installer below instead; its `astra` command re-runs itself through `sudo` when your user cannot read `/etc/astra`.

If `./install.sh` says "Permission denied" (a zip or Windows checkout drops the executable bit), run `sudo bash install.sh`, or fix it once with `git update-index --chmod=+x install.sh uninstall.sh scripts/*.sh tests/*.sh`.

On first start, Astra creates the `admin` account and prints a generated password if you have not run `astra init`. Use `astra passwd` to change it.

### Linux system install

The installer supports apt-based distributions with systemd:

```bash
sudo ./install.sh --port 8800 --with "nginx ufw fail2ban"
```

It installs Python and requested OS packages, installs the service under `/opt/astra`, stores configuration under `/etc/astra`, and starts the `astra` systemd service as root. The generated admin password is printed during setup. The panel listens on all interfaces; configure HTTPS and firewall restrictions before remote use.

### Windows system install

Run elevated PowerShell. Install Python 3.9+ for all users first, or use `-InstallPython` when `winget` is available:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Port 8800
```

The installer places the application under `%ProgramFiles%\Astra`, uses `%ProgramData%\astra` for configuration and logs, and registers the `AstraPanel` scheduled task to run as SYSTEM. The panel listens on all interfaces. Windows behavior is not yet fully verified; see [TODO.md](TODO.md). Remove it with `uninstall.ps1`.

### Safe browser access

For local-only access, set the bind address and restart the panel:

```bash
astra config set host 127.0.0.1
astra restart
ssh -L 8800:127.0.0.1:8800 you@your-server
```

Then browse to `http://127.0.0.1:8800`. For remote access, use HTTPS with a reverse proxy or configure `tls_cert` and `tls_key` in Astra, and apply an IP allowlist/firewall rule. Read [docs/SECURITY.md](docs/SECURITY.md) before exposing it.

## CLI

```text
astra init [--user NAME] [--password PASSWORD] [--reset]  Create/reset the admin account
astra web [--host HOST] [--port PORT] [--open]            Run in the foreground
astra start | stop | restart                              Control the background panel (stop also ends the boot service)
astra service [install|remove|status]                     Start the panel at boot (systemd / Task Scheduler)
astra domain [set NAME|remove|show] [--persist]           Publish the panel under a domain name
astra url | user                                          Print panel addresses / the admin user name
astra passwd [--user NAME] [--password PASSWORD]          Change account credentials
astra status | doctor | ext | services                    Inspect the system and extensions
astra catalog                                             List software in the catalog
astra install NAME | uninstall NAME                       Manage catalog software
astra svc NAME start|stop|restart|reload|enable|disable   Manage a watched service
astra call EXT ROUTE key=value                            Call an extension route locally
astra config [show] | config set KEY VALUE                 Read or update configuration
astra mfa [reset|test-email ADDRESS]                      Check or reset MFA
astra privacy export|delete                               Export or delete selected data
astra logs [-n COUNT] | notes [-n COUNT]                   Show audit events or notifications
astra tui                                                 Open the full-screen terminal UI
```

`astra call` invokes extension code directly in the local process, not through the web login. Run it only as a trusted OS account. See `astra --help` for full options.

## Configuration

Configuration is stored in `$ASTRA_HOME/config.json` when `ASTRA_HOME` is set; otherwise `/etc/astra` when running as root on Linux, `%ProgramData%\astra` when elevated on Windows, or `~/.astra` for an unprivileged user. Use `astra config` to inspect it. Changes to ordinary settings are reloaded automatically; changing `host`, `port`, or TLS settings requires a panel restart.

| Setting | Default | Purpose |
|---|---|---|
| `host`, `port` | `0.0.0.0`, `8800` | Listener address and port |
| `tls_cert`, `tls_key` | empty | Certificate and key paths; both are needed for direct HTTPS |
| `allowed_ips` | `[]` | Optional client IP/network allowlist for API requests |
| `services`, `file_roots`, `web_roots`, `log_files` | OS-specific | Service allowlist and filesystem access roots |
| `backup_dir`, `cron_user`, `bin_dirs`, `nginx_dir` | OS-specific | Backup location, job account, executable search paths, and nginx config path |
| `disabled_extensions` | `[]` | Extension names to hide/disable |
| `alerts` | CPU, memory, disk at 90% | Alert thresholds; set a value to 0 to disable it |
| `sample_interval`, `history_len` | `5`, `360` | Monitoring interval in seconds and retained sample count |
| `session_ttl_hours` | `8` | Session lifetime; range 0.25 to 720 hours |
| `console_enabled` | `true` | Enable the web command console |
| `audit_retention_days` | `90` | Prune older audit entries; 0 disables pruning |
| `base_path`, `domain` | `/astra`, empty | Extra path the panel answers at, and the domain it is published under |
| `site_engine`, `site_port` | `auto`, `8080` | `auto` uses nginx if installed, else the built-in site host on `site_port`; `builtin` forces the built-in one |
| `job_concurrency` | `1` | Installs/updates run at once (1 = one after another, for small servers) |
| `smtp`, `desktop` | See defaults in `astra/config.py` | Mail/MFA and optional Linux desktop settings |

Use JSON values when setting structured configuration, for example:

```bash
astra config set file_roots '["/var/www","/srv"]'
```

## Multi-Factor Sign-In

The admin username and password are always the first step. Optionally enable an authenticator app (TOTP) and/or e-mail codes under Settings. TOTP follows RFC 6238 and rejects reused codes. E-mail codes require SMTP configuration, expire after 10 minutes, and allow five attempts. Test SMTP with `astra mfa test-email you@example.com`; inspect status with `astra mfa`. To reset factors from the server, run `astra mfa reset`.

## Customization and Extensions

- Appearance preferences are saved in browser local storage.
- Place custom CSS at `<config directory>/custom.css`.
- Place trusted extension modules in `<config directory>/extensions/`; restart Astra after adding or changing one.
- See [docs/EXTENSIONS.md](docs/EXTENSIONS.md) and [examples/hello_extension.py](examples/hello_extension.py).

## Testing

```bash
make test          # tests/run.sh; 35 automated tests
make check         # Python and JavaScript syntax checks
make demo          # disposable local demo on port 8800
make test-docker   # optional Docker test harness
```

The tests cover authentication and MFA, file sandboxing, extension routes, backups, cron validation, audit retention, web assets, static assets, and optional desktop resource gates. The demo and test suite do not require a production server.

## Documentation and Limitations

- [docs/SECURITY.md](docs/SECURITY.md): deployment and security model
- [docs/EXTENSIONS.md](docs/EXTENSIONS.md): extension API and UI schema
- [experimental/](experimental/README.md): unfinished ideas (panel database framework); not part of the running panel
- [THIRD_PARTY.md](THIRD_PARTY.md): dependencies and external tools

Astra is intended for a single trusted operator and has no separate user roles. The console and extensions inherit the panel process privileges. The Windows paths and optional Linux desktop installation still need additional real-system validation. The software catalog invokes real OS package managers and external tools; review actions before running them on important servers.
