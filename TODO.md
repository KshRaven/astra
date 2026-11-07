# TODO

Not relied on by anything. Rarely worked on.

## Windows / Windows Server (written, not run)
- [ ] Run `install.ps1`, `uninstall.ps1`, `scripts/doctor.ps1`, `scripts/dev.ps1`, `tests/run.ps1`, `tests/demo.ps1` on Windows 10/11 and Server 2016/2019/2022.
- [ ] Verify the ACL set by `astra init` on the config folder and the extensions-folder trust check (`extensions/__init__.py`, `_trusted`).
- [ ] Security tab: Windows Update status check (skipped on Windows).
- [ ] Confirm service, firewall (`netsh advfirewall`) and Task Scheduler extensions against localized Windows installs.
- [ ] Desktop tab: the VNC/Openbox GUI session is Linux-only; the web desktop works everywhere.
- [ ] Windows containers / Docker Desktop paths in the Docker tab.

## Rename (mypanel -> astra)
- [ ] Linux upgrades migrate `/etc/mypanel` via `install.sh`. Remove that block once no old installs remain.
- [ ] Update any external references (reverse proxy configs, bookmarks, scripts) to the new name.
