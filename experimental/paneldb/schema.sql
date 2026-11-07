-- paneldb schema sketch (SQLite dialect). Not applied anywhere yet.
-- Times are UTC unix seconds (INTEGER). Booleans are 0/1. JSON columns hold TEXT.

CREATE TABLE schema_version (version INTEGER NOT NULL);

-- ---- people and privileges -------------------------------------------------
CREATE TABLE roles (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,            -- admin, operator, viewer, ...
  description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE role_grants (                     -- what a role may do, per tab/extension
  role_id     INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  area        TEXT NOT NULL,                   -- extension name, e.g. files, databases, '*'
  level       TEXT NOT NULL CHECK (level IN ('none','read','write','admin')),
  PRIMARY KEY (role_id, area)
);
CREATE TABLE users (
  id          INTEGER PRIMARY KEY,
  username    TEXT NOT NULL UNIQUE,
  display     TEXT NOT NULL DEFAULT '',
  email       TEXT NOT NULL DEFAULT '',
  role_id     INTEGER NOT NULL REFERENCES roles(id),
  disabled    INTEGER NOT NULL DEFAULT 0,
  created_at  INTEGER NOT NULL,
  last_login  INTEGER
);

-- ---- credentials (kept apart from ordinary settings) ------------------------
CREATE TABLE credentials (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK (kind IN ('password','totp','email_code','api_token','recovery_code')),
  secret      TEXT NOT NULL,                   -- password: PBKDF2 hash; totp: encrypted; api_token/recovery: hash only
  label       TEXT NOT NULL DEFAULT '',
  created_at  INTEGER NOT NULL,
  last_used   INTEGER,
  expires_at  INTEGER
);
CREATE TABLE sessions (
  id          TEXT PRIMARY KEY,                -- hash of the session cookie
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ip          TEXT NOT NULL DEFAULT '',
  agent       TEXT NOT NULL DEFAULT '',
  created_at  INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL
);

-- ---- history ----------------------------------------------------------------
CREATE TABLE audit_actions (                   -- every change made through the panel
  id          INTEGER PRIMARY KEY,
  at          INTEGER NOT NULL,
  user_id     INTEGER REFERENCES users(id),
  ip          TEXT NOT NULL DEFAULT '',
  area        TEXT NOT NULL,                   -- extension
  action      TEXT NOT NULL,                   -- route
  target      TEXT NOT NULL DEFAULT '',
  ok          INTEGER NOT NULL DEFAULT 1,
  detail      TEXT NOT NULL DEFAULT '{}'       -- JSON, never secrets
);
CREATE INDEX audit_at ON audit_actions(at);

CREATE TABLE security_events (                 -- sign-ins, failures, lockouts, MFA changes
  id          INTEGER PRIMARY KEY,
  at          INTEGER NOT NULL,
  kind        TEXT NOT NULL,                   -- login_ok, login_fail, lockout, mfa_on, password_change, ...
  severity    TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  user_id     INTEGER REFERENCES users(id),
  ip          TEXT NOT NULL DEFAULT '',
  detail      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX sec_at ON security_events(at);

CREATE TABLE notifications (
  id          INTEGER PRIMARY KEY,
  at          INTEGER NOT NULL,
  category    TEXT NOT NULL,                   -- security, service, job, system, update
  severity    TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
  title       TEXT NOT NULL,
  body        TEXT NOT NULL DEFAULT '',
  link        TEXT NOT NULL DEFAULT '',        -- tab to open, e.g. services/library
  user_id     INTEGER REFERENCES users(id),    -- NULL = everyone
  read_at     INTEGER
);
CREATE INDEX notif_unread ON notifications(read_at, at);

CREATE TABLE log_index (                       -- optional: searchable copy of important log lines
  id          INTEGER PRIMARY KEY,
  at          INTEGER NOT NULL,
  source      TEXT NOT NULL,                   -- panel, nginx, mysql, ...
  level       TEXT NOT NULL DEFAULT 'info',
  message     TEXT NOT NULL
);
CREATE INDEX log_at ON log_index(source, at);

-- ---- what is installed / configured ----------------------------------------
CREATE TABLE apps (                            -- registry of software the panel installed or manages
  id            TEXT PRIMARY KEY,              -- catalog id: nginx, mariadb, docker, mailserver ...
  installed_at  INTEGER,
  version       TEXT NOT NULL DEFAULT '',
  managed       INTEGER NOT NULL DEFAULT 1,
  state         TEXT NOT NULL DEFAULT 'unknown',
  checked_at    INTEGER,
  settings      TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE jobs (                            -- history of installs, updates and tasks
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  kind        TEXT NOT NULL,
  state       TEXT NOT NULL,
  started_at  INTEGER,
  ended_at    INTEGER,
  user_id     INTEGER REFERENCES users(id),
  output_tail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE settings (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,                   -- JSON
  updated_at  INTEGER NOT NULL
);

-- ---- mail (supports the email-server service and e-mail sign-in codes) -------
CREATE TABLE mail_accounts (                   -- sender identities the panel may use
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  host        TEXT NOT NULL,
  port        INTEGER NOT NULL DEFAULT 587,
  security    TEXT NOT NULL DEFAULT 'starttls',
  username    TEXT NOT NULL DEFAULT '',
  password    TEXT NOT NULL DEFAULT '',        -- encrypted
  from_addr   TEXT NOT NULL,
  is_default  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE mail_queue (
  id          INTEGER PRIMARY KEY,
  account_id  INTEGER REFERENCES mail_accounts(id),
  created_at  INTEGER NOT NULL,
  to_addr     TEXT NOT NULL,
  subject     TEXT NOT NULL,
  body        TEXT NOT NULL,
  state       TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','sent','failed')),
  attempts    INTEGER NOT NULL DEFAULT 0,
  last_error  TEXT NOT NULL DEFAULT '',
  sent_at     INTEGER
);

INSERT INTO schema_version(version) VALUES (0);
