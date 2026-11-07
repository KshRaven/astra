# TODO

## Windows / Windows Server validation

- [ ] Run `install.ps1`, `uninstall.ps1`, `scripts/doctor.ps1`, `scripts/dev.ps1`, `tests/run.ps1`, and `tests/demo.ps1` on supported Windows 10/11 and Server versions.
- [ ] Verify the config-directory ACL created by `astra init` and the trust checks for user extensions on Windows.
- [ ] Check the Security page's Windows-specific checks and document unsupported checks clearly.
- [ ] Verify service, firewall (`netsh advfirewall`), and Task Scheduler behavior on localized Windows installations.
- [ ] Verify Docker Desktop discovery, permissions, and container actions.
- [ ] Test upgrade, reboot, and uninstall behavior for the SYSTEM scheduled task.

## Other validation and maintenance

- [ ] Exercise the optional Linux desktop install/start/stop flow on a disposable Debian or Ubuntu host.
- [ ] Review external examples and deployment references for the `astra` name when publishing releases.
