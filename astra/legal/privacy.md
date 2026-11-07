# Privacy notice

Operator of this panel: {{operator}}

astra is self-hosted software. It runs on a server chosen and controlled by the operator above. The astra project itself receives no data from it: there is no telemetry, analytics, advertising, tracking, or call-home of any kind.

## What is stored, why, and for how long
- Access token: only a SHA-256 hash, to let you sign in. Kept until you rotate it.
- Audit log (login failures and every change made through the panel): time, action, and the IP address of the client. Purpose: security and troubleshooting. Kept {{retention}} days, then deleted automatically.
- Two-factor settings, only if you turn them on: an authenticator secret and/or an e-mail address, to check your second factor. Kept until you turn the factor off.
- Sign-in sessions: in server memory only, gone after {{session}} hours or a restart.
- Preferences (theme, text size, spacing): in your browser only.

Nothing else is collected. Files, databases and logs you manage with the panel stay on the server and are not copied anywhere by astra.

## Cookies and similar technologies
astra sets no cookies and loads no third-party scripts, fonts or images. It uses your browser's session storage (sign-in session, cleared when the tab closes) and local storage (display preferences). Both are strictly necessary for the panel to work, so no consent banner is needed or shown.

## Who receives data
- E-mail codes are sent through the SMTP server the operator configured, only if e-mail sign-in is enabled.
- Let's Encrypt receives the domain name when the operator requests a certificate in the Websites tab.
- The optional Linux desktop downloads packages from the operating system's package repositories when the operator installs it.

## Children
astra is a server administration tool for adults. It is not directed at children and knowingly collects no data about them.

## Your rights and data deletion
You can see, export, and delete the stored personal data at any time: Settings, "Privacy", or on the server `astra privacy export` and `astra privacy delete`. Deleting removes the audit log, the authenticator secret and the e-mail address. To ask the operator for anything else, write to {{contact}}.
