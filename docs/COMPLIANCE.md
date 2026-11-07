# Compliance checklist: what applies to astra and what does not

astra is self-hosted admin software for one operator. It sells nothing, advertises nothing and is not a public website. Each item was judged on that basis. `tests/test_compliance.py` verifies the claims marked (tested). This is practical engineering guidance, not legal advice.

| Item | Status | Where / why |
|---|---|---|
| Privacy policy | Included | `/legal/privacy`, source `astra/legal/privacy.md`; lists every stored item, retention, recipients, rights |
| Terms of service | Included (short) | `/legal/terms`; access, acceptable use, no-warranty (tested) |
| Refund policy | Not applicable | Nothing is sold; `/legal/refund` is 404 on purpose (tested) |
| Cookie policy | Folded into the privacy notice | The panel sets no cookies (tested); one paragraph says so |
| Cookie consent banner | Not applicable | Only strictly necessary browser storage is used, so consent is not required |
| Check form consents | Not applicable | No marketing or newsletter forms. MFA setup is an explicit action by the operator |
| No unnecessary data | Included | No telemetry; audit log keeps action, time, IP only; `audit_retention_days` auto-prunes (tested); secrets masked in logs (tested) |
| Audit third-party SDKs | Included | There are none: no external URL in any shipped web file (tested) |
| Remove dark patterns | Nothing to remove | Destructive actions ask for confirmation; no nagging, no pre-ticked options |
| Remove hidden fees | Nothing to remove | Free, MIT licensed |
| Remove fake reviews | Nothing to remove | No reviews or testimonials exist |
| Remove unsupported claims | Reviewed | README states what was and was not exercised (e.g. real apt install, real browser) |
| Accessibility alt text | Included | No images in the UI (icons are text); a test fails if an `<img>` without `alt` is ever added |
| Fix color contrast | Included | All five themes meet WCAG AA for text and 3:1 for borders (tested); status shown by icon plus colour |
| Keyboard navigation | Included | Skip link, visible focus, desktop windows movable/resizable/closable by keyboard, arrow-key Start menu |
| Add business details | Reduced | A personal tool has no business; `operator` name, address and contact e-mail render on the legal pages if you set them |
| Age consent for kids' data | Not applicable | Admin tool for adults, stated in terms and privacy; no child data collected |
| Unsubscribe link in emails | Not applicable | The only e-mail is a one-time security code requested by the operator; it says so. No marketing mail exists |
| License fonts/images | Included | System fonts only, no images; `THIRD_PARTY.md`; MIT `LICENSE` |
| Data deletion request | Included | Settings → Privacy, `astra privacy delete` (tested); export via `astra privacy export` |

If you ever let other people use your panel (customers, a team), add the missing pieces yourself: consent records, a DPA, per-user accounts and a real legal review.
