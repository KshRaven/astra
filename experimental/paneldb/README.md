# paneldb (framework sketch, not in use)

Today the panel keeps its state in small files under the config folder: `config.json` (one admin account), `notifications.json`,
`logs/audit.log`, `logs/panel.log`. That is fine for one operator. A database would be needed once the panel grows:

* several users with different privilege levels (see `roles` / `role_grants`)
* a searchable audit trail and security-event history instead of rotating text files
* notifications with read / unread state and categories
* a registry of installed apps and their health
* mail (outgoing queue, sign-in codes) for the email-server service
* credentials and API tokens kept apart from ordinary settings

## What is here

| File | Purpose |
| --- | --- |
| `schema.sql` | Portable DDL (SQLite first; written to also load on PostgreSQL / MySQL with small type changes). |
| `model.py` | Plain dataclasses describing each table. No I/O, no engine. |
| `__init__.py` | Marks the folder; defines nothing. |

## Rules for the future engine

1. **No engine is chosen yet.** SQLite is the likely default because it needs nothing installed (it is what the Databases tab already uses). The panel must keep working with the existing JSON files when no database exists.
2. **Migrations only go forward.** `schema_version` holds one row; each change is a numbered step.
3. **Secrets:** password hashes stay PBKDF2 (as in `astra/config.py`). TOTP secrets and SMTP passwords are encrypted with a key kept outside the database (config folder, owner-only ACL). API tokens are stored as hashes; the plain token is shown once.
4. **Retention:** `audit_actions`, `security_events` and `notifications` are pruned by age (default 90 days, like `audit_retention_days`), never silently by size.
5. **Import path:** a one-time importer reads `config.json`, `notifications.json` and `audit.log` into the tables, then leaves the files untouched as a backup.
6. **Panel first:** nothing may depend on this. A failing database must degrade to "history unavailable", never to "panel will not start".
