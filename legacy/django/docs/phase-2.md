# Authentication, roles and access scopes

The local installation currently enables the user-requested no-login mode. Its
reserved technical operator has an unusable password and supplies audit/FK actor
references, without creating a login session. All local browser users then have
full access. This intentionally suspends individual employee separation. Set
`DJANGO_LOCAL_NO_LOGIN=false` and restart to enforce the controls described below.

Operational application review/assignment/transfer/check-out services now use this
same policy. Custom submit/review/decide permissions keep registration separate
from approval; the 14 report exports and full-backup downloads are also enforced
on the backend. Local no-login mode remains enabled as requested.

## Authentication

Django authentication/password hashing, CSRF, POST-only logout, safe redirect
validation, generic login failures, five-failure/five-minute persistent local
throttling, 30-minute browser sessions and browser-close expiry are implemented.
Deactivation prevents further session authentication. Password changes invalidate
other sessions. Recovery tokens expire after 30 minutes and are single-use.

Offline password recovery writes mail to the private `private_mail` directory,
never a public URL or console email backend. The authorized Windows operator must
deliver the local recovery link to the intended employee and remove obsolete mail.
Access logging redacts recovery URLs. No SMTP/internet service is required.

HTTP mode only accepts actual loopback peers. It does not trust forwarded headers.
Secure cookies/SSL redirection can be restored by disabling local HTTP, but the
no-login setting then fails closed. This project is not a public-server deployment.

## Role matrix

| Role | View scoped records | Register/edit students and applications | Review/decide applications | Allocate/move/end housing | Maintenance/violations | Reports/export | Employee administration |
|---|---|---|---|---|---|---|---|
| Active superuser | All | Yes | Yes | Yes | Yes | Yes | Yes |
| Housing administration | Explicit scopes | Yes | Yes | Yes | Yes | Yes | No |
| Male dormitory manager | Explicit male grant; cross-grants require administrator | Yes | Yes | Yes | Yes | Yes | No |
| Female dormitory manager | Explicit female grant; cross-grants require administrator | Yes | Yes | Yes | Yes | Yes | No |
| Building supervisor | Granted buildings AND gender | View | No | View | Add/change | View reports | No |
| Authorized registration officer | Explicit scopes | Yes; submit/cancel, no approval | No | View | View | View reports | No |
| Read-only auditor | Explicit scopes | View only | No | View | View | View only | No |
| Reports officer | Explicit scopes | View only | No | View | View | Export | No |

`setup_roles` resets managed group permission definitions idempotently, without
creating memberships or gender/building grants. A group called System Administrator
is not itself a superuser flag: actual employee administration and university-wide
reference-data edits require the explicit Django superuser. The employee form never
accepts is_superuser/is_staff/direct permission grants from submitted fields.

The auditor write prohibition applies even if an extra direct write permission was
granted. Supervisor building restrictions apply even when their scope_mode is
gender. No explicit gender scope means no domain rows. Cross-gender access requires
an explicit grant, not merely a group name. Building-scoped student/profile access
requires a current allocation in an assigned building; old building assignments do
not reveal the student's current profile. Transfer visibility requires both endpoints.

## Enforcement and audit

`apps/accounts/policy.py` is the shared fail-closed query policy; unknown models
are denied. All application views, FK choice fields, mutations, downloads and report
datasets check backend permissions/scopes. Transactional services recheck scope
inside their write transaction. Non-visible object IDs return 404; missing operation
permissions return 403. No public Django-admin route, private-media route or API
exists that bypasses these checks.

Students and workflow changes, document access, account/access changes, login
events, reports, backup creation and settings changes write AuditLog records. Form
field names can be recorded; arbitrary request bodies, credentials, documents and
full personal snapshots are not serialized. Audit has no edit/delete endpoint.
Direct edits using a database tool or arbitrary custom shell code are outside the
application service/audit boundary; Windows account/file access remains critical.

Future views must use the same query policy and services. A hidden button is never
the authorization boundary. Tests cover unauthorized direct URLs, cross-gender and
cross-building data, forged FK inputs, export/download scope, privilege escalation,
session changes, CSRF and audit writes.

Current delivery regression result: **99 tests passed** across the complete suite,
including the original authentication/scope/no-login tests and new operational
workflow/report/backup tests. Refer to delivery.md for environment and exact checks.
