# Local SQLite delivery and validation — 2026-11-06

## Implemented scope

The original Django modules/models and historical relationships are preserved.
SQLite (`db.sqlite3`) is the default and only backend touched by local operation.
Optional legacy MySQL settings/requirements and existing private DB_* values are
retained; no MySQL data or credentials were reset, copied or deleted. MySQL-to-SQLite
data import was not performed or claimed. No real student data or demo data was seeded.

The application now has an operational Arabic interface for the student/accommodation
cycle, academic and dormitory configuration, violations, maintenance, live dashboard,
14 filtered reports (Excel, Arabic PDF and browser printing), full local backup bundles,
safe offline recovery commands, and authentication/RBAC with the explicit local
no-login override requested by the operator.

## Database and transaction design

Existing persisted generated active_student_key/active_bed_key UNIQUE columns work
on the tested SQLite runtime. They produce NULL after an assignment ends, allowing
unlimited completed history while preserving one active student/bed. No partial
index substitution or historical-table rebuild outside migrations was introduced.
CHECK/FK constraints, PROTECT deletion and all existing indexes remain managed by
Django. New migrations add renewal linkage, report/application permissions and a
backup metadata ledger. Migration application is preceded by a safety snapshot.

SQLite uses `transaction_mode=IMMEDIATE`, a 20-second busy timeout and short write
transactions. It has a single writer, not MySQL row-level locking. `select_for_update`
is not relied on for safety. Competing allocations through both raw inserts and the
real business service are tested on separate connections to a file-backed test DB.
An overloaded/disk-locked system can still reject writes; the UI reports failure and
does not silently retry or report success. Large backups reserve the writer while
capturing the database and immutable uploads; do not schedule mass edits during them.

Allocation is not check-in. Transfer closes/creates/logs in one transaction and
preserves the prior assignment; renewal links to the prior period. Operational
facility edits cannot move historical beds/rooms into different parents or disable
occupied facilities. Required-document checks run at submission, approval and allocation.
Closing intake prevents new submissions, but does not invalidate an already approved
request. No university-specific admission, fee or disciplinary policy is invented.

## Validation commands and evidence

Commands run in the supported Python 3.14.4 virtual environment include Django
database/system checks, actual migrations, `setup_roles`, migration drift checks,
`verify_database`, dependency checks, and the automated test suite. The detailed
latest executed counts are recorded in the final delivery response and phase reports.

Final executed full suite: **99 tests passed**, with no skips on this computer
(68 prior regressions, 27 workflow/report/concurrency cases and 4 bundle-backup/security
cases). The run includes real Arabic PDF generation using installed Edge. Live
`verify_database` passed for **35 tables on SQLite 3.50.4**; database checks passed,
`migrate --check` passed, migration drift check reported no changes, `pip check`
found no broken requirements, and Python compilation succeeded.

Automated isolated-browser layout checks measured 1440-pixel desktop and 390-pixel
mobile viewports: document scroll width did not exceed the client width, four
nonempty dashboard charts instantiated on the current data, and zero runtime script
exceptions were reported. Screenshots at both sizes were inspected. The fictional
Arabic PDF was rasterized and visually inspected for joined RTL text, table alignment
and legibility. No Pango/GTK installation is required. PyMuPDF/WebSocket QA tools
live only under ignored `.tools`, not runtime requirements. This is not exhaustive
testing of every browser/physical mobile device or large multi-page dataset.

`verify_database` checks migration consistency, required managed/join tables,
columns/nullability, PK/unique/FK/index presence, named CHECK enforcement, SQLite
integrity/foreign-key checks, and persisted generated expressions. It is not a
byte-for-byte proof of every column type/CHECK clause; behavior tests exercise the
critical integrity rules.

## Backup and restore contract

- Database-only backups use SQLite Backup API, validate integrity/FKs, and refuse
  overwriting an existing destination.
- Web ZIP bundles include a consistent DB snapshot plus private_media, with SHA-256
  checksums, and exclude .env and recovery mail. Downloads are administrator-only.
- `prepare_restore` checks the manifest, duplicate entries, paths and checksums and
  validates the database before approving a new recovery directory. It never changes
  live files. The 5 GiB recovery cap is explicit; larger deployments need an adjusted
  operational limit, not partial recovery.
- `restore_database --confirm-stopped` requires all app/database-browser processes
  stopped, refuses active sidecars, validates the source, saves an automatic safety
  snapshot and replaces the database atomically. It invalidates restored sessions.
- Restore matching media separately as documented in README. Retain the previous
  media first. Extra unreferenced private files are not made public.
- Checksums detect corruption, not authenticity; only restore trusted local backups.
  No encryption is claimed. Protect the Windows account, backups and private folders.

## Practical limits

This is a local administrative application, not a public multi-host service. No-login
mode deliberately grants all local users full access and attributes actions to one
technical operator. Re-enable accounts before requiring individual staff separation.
Database/file permissions cannot stop the owner of the Windows account from directly
editing files; do not share that OS session with untrusted users.

PDF uses the installed Edge browser in an isolated temporary headless profile and
loads only trusted locally rendered HTML/Cairo assets. If no renderer is installed,
the UI gives an actionable message and browser printing remains available. Export
limits are explicit (PDF 2000 records; Excel 20000). Initial dependency installation
needs internet or a pre-staged wheel cache; daily operation uses no network service.

No claims are made about university policy approval, penetration testing, extensive
load testing, or deployment on other Windows computers. Rehearse recovery on the
actual operating computer and verify its backup destination remains accessible.

## Administrative workflow extension — 2026-11-06

Implemented scoped room/bed maps and employee-confirmed suggestions; XLSX template,
private expiring preview and atomic student/enrollment import; editable Arabic housing,
pledge, transfer and checkout print/PDF forms; configurable document/application/
maintenance/renewal alerts; and a Windows standalone launcher/installer using bundled
Python, Django and Waitress. See windows-desktop.md and operations.md.

Executed after these changes:

- `python manage.py test --noinput --verbosity 1`: 114 tests passed (including actual PDF output).
- `check --database default`, `makemigrations --check --dry-run`, `migrate --check`:
  passed; no pending model or migration changes.
- `verify_database`: 36 tables verified on SQLite 3.50.4, including relationships,
  columns, keys, indexes and declared CHECK constraints.
- `python -m pip check`: no broken requirements.
- Isolated recovery rehearsal restored database values and private media, preserving
  a full safety archive and previous media directory; no live student data was used.
- Built EXE smoke test returned HTTP 200 for home, local CSS, map, alerts and import
  pages on a separate empty SQLite database.
- Final built EXE installed twice into an isolated directory, updated its Arabic
  shortcut, retained both version directories, then ran successfully from the installed
  path. Tk initialized and all five HTTP probes returned 200. No external Python was
  invoked by that executable.
- Reviewed Arabic map and administrative form screenshots. Browser measurements at
  desktop (1440), tablet (768) and mobile (390) showed no horizontal document overflow
  or JavaScript exceptions in the completed capture run. Automated browser teardown
  encountered Windows process/file locks; this is not a claim of fully passing end-to-end UI automation.

Packaging excludes local databases, `.env`, private uploads/mail and backups. Source
tests use a separate test database; installer/recovery smoke data stays in ignored
`.tools` folders. No existing MySQL database or credentials were removed.
