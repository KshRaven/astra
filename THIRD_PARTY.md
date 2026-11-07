# Third-Party Material and Dependencies

The web interface has no external script, font, or image downloads. It uses system fonts and icons rendered by the application. Astra's core uses the Python standard library. On Windows, the package declares `windows-curses` for the terminal UI; development extras include pytest and Ruff. See `pyproject.toml` for the current package declarations and their licenses.

The panel can install or call server software that is not bundled with Astra. The OS package manager installs those tools from its configured repositories under their respective licenses. Examples include nginx, certbot, ufw, fail2ban, Docker, database servers and clients, and (for the optional Linux desktop session) TigerVNC, noVNC, websockify, Openbox, and xterm. Review each package and repository before installing it.

Astra is licensed under the MIT license; see `LICENSE`.
