"""Plain dataclasses mirroring schema.sql. No I/O and no database engine: this only fixes the vocabulary."""
from dataclasses import dataclass, field
from typing import Optional

Level = str      # 'none' | 'read' | 'write' | 'admin'
Severity = str   # 'info' | 'warning' | 'critical'


@dataclass
class Role:
    id: int
    name: str
    description: str = ""
    grants: dict = field(default_factory=dict)      # area -> Level


@dataclass
class User:
    id: int
    username: str
    role_id: int
    display: str = ""
    email: str = ""
    disabled: bool = False
    created_at: int = 0
    last_login: Optional[int] = None


@dataclass
class Credential:
    id: int
    user_id: int
    kind: str            # password | totp | email_code | api_token | recovery_code
    secret: str          # hash or ciphertext, never plain text
    label: str = ""
    created_at: int = 0
    last_used: Optional[int] = None
    expires_at: Optional[int] = None


@dataclass
class AuditAction:
    at: int
    area: str
    action: str
    user_id: Optional[int] = None
    ip: str = ""
    target: str = ""
    ok: bool = True
    detail: dict = field(default_factory=dict)


@dataclass
class SecurityEvent:
    at: int
    kind: str
    severity: Severity
    user_id: Optional[int] = None
    ip: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class Notification:
    at: int
    category: str        # security | service | job | system | update
    severity: Severity
    title: str
    body: str = ""
    link: str = ""
    user_id: Optional[int] = None
    read_at: Optional[int] = None


@dataclass
class AppRecord:
    id: str
    version: str = ""
    managed: bool = True
    state: str = "unknown"
    installed_at: Optional[int] = None
    settings: dict = field(default_factory=dict)


@dataclass
class MailAccount:
    name: str
    host: str
    from_addr: str
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str = ""   # encrypted
    is_default: bool = False
