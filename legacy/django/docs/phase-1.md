# Phase 1 delivery and validation

## Current SQLite validation (supersedes the historical MySQL blockers below)

The operator explicitly chose SQLite for a single local Windows computer. The
default backend is now `django.db.backends.sqlite3`, stored in `db.sqlite3`.
Existing MySQL databases, credentials and optional legacy settings are preserved.
Initial migrations were actually applied, generated unique active keys retained,
and the live schema/foreign keys/CHECK constraints/indexes verified. Initial SQLite
validation passed 25 tests, then 29 including backup/recovery tests, before Phase 2
began. The authentication/no-login phase subsequently passed 68 tests.

The latest operational workflow/report/backup delivery and executed final test
results are documented in [delivery.md](delivery.md). The latest full run passed
**99 tests**, and live verification passed for **35 tables on SQLite 3.50.4**.
All migrations are applied, no model/migration drift was detected, dependency
integrity and compilation passed, and database/system checks reported no issues.
No MySQL authentication step is required for local use. Earlier connection errors
below describe the prior backend and do not block SQLite operation.

## Password-configured retry — 2026-11-06 (Asia/Baghdad)

After the operator confirmed local password entry, `check --database default`
was retried. MySQL still returned **1045**, now **using password: YES**. A direct
mysqlclient connection using only `.env` also returned 1045. No process-level
`DB_*` overrides were present, ruling out stale environment precedence in this run.
The application credentials/account authentication need verification by the
operator. No passwords were printed, root credentials accessed, migrations applied,
or database accounts changed. Phase 2 remains gated on successful Phase 1 validation.

## Post-installation connection check — 2026-11-06 (Asia/Baghdad)

The user has installed MySQL **8.0.46** and provisioned the application database
and account. Host checks now confirm **MySQL80 is running**, the installed MySQL
client reports 8.0.46, and Django reaches server authentication on 127.0.0.1:3306.
The previous server-absent diagnosis below is historical.

The existing `.env` was preserved and its missing/invalid Django secret was
generated privately. `DB_PASSWORD` is still empty locally; the database check
fails with **1045 (using password: NO)**. Application authentication must succeed
before verifying the reported database/grants, planning/applying migrations or
running MySQL integration tests. No root credentials were accessed; no migrations
were applied and no existing data/account was changed.

Re-executed using Python 3.14.4: dependency integrity (`pip check`), Django `check`,
all **13 offline tests**, and Python compilation passed. `.env` is confirmed
ignored by Git. Added `scripts/configure_local.py --prompt-password` for hidden
local application-password entry; it refuses fallback echoing and preserves
existing configuration values. Do not send credentials in chat/tool commands.

**Phase 2 has not started.** Resume with the section 4 commands in
[Windows setup](windows-phase-1-setup.md) after the local password is configured.

## Latest revalidation — 2026-11-06 (Asia/Baghdad)

**Phase 1 is not yet fully validated; Phase 2 has not started.** Later host-level
inspection corrected the initial Python diagnosis: Python **3.14.4** exists at
`C:\Users\Windows 11\AppData\Local\Programs\Python\Python314\python.exe`.
It is not visible to the ordinary sandbox terminal. A project `.venv` was created
using it; all existing requirements installed successfully without altering the
old `.tools` environment or application settings.

Host-level Windows service inspection found **0 MySQL/MariaDB services**, **0 TCP
listeners on port 3306**, no server in the standard MySQL installation directories,
and no MySQL installed-program entry. No `.env` exists. A nonstandard portable
server elsewhere has not been exhaustively ruled out. Refusal at 127.0.0.1:3306
occurs before authentication; a missing password cannot explain the absent listener.

Executed on Python 3.14.4 / Django 5.2.19:

| Command | Result |
|---|---|
| `pip install -r requirements.txt` | Passed |
| `pip check` | Passed; no broken requirements |
| `manage.py check` | Passed; no issues |
| `manage.py check --deploy` with DEBUG=false | Passed; no issues; not an HTTPS deployment test |
| `manage.py test tests.test_schema tests.test_database_verification --verbosity 2` | **13 passed**, no database used |
| `manage.py makemigrations --check --dry-run` | No changes; migration-history connection warning |
| Python `compileall` on apps/config/tests/scripts/manage.py | Passed |
| `manage.py verify_database` | Blocked: connection error 2002, actionable error message |
| `manage.py check --database default` | Blocked: connection error 2002 / 10061 |
| `manage.py migrate --check` | Blocked: connection error 2002 / 10061 |
| `manage.py test tests.test_mysql_integrity --verbosity 0` | Blocked during database setup; no test body executed |

Changes in this revalidation:

- Added read-only `verify_database` management command and offline diagnostic tests.
- Expanded MySQL tests to inspect the live schema and exercise critical CHECK rules.
- Added [exact Windows setup and verification steps](windows-phase-1-setup.md) and
  updated README without overwriting `.env` or changing database settings/models.
- No MySQL data, database users or installed schema were changed. Migrations have
  not been applied or assumed applied. RBAC/login implementation remains gated.

External unblock: install/configure/start MySQL 8.4, verify/provision the database
and development account, configure `.env`, then apply migrations and run the live
schema verifier and complete MySQL test suite. The guide includes each command.

## Original foundation delivery

## Files and functionality

- `config/`, `manage.py`: Arabic locale/Baghdad timezone, MySQL environment settings,
  secure defaults, empty routes until authorized application views exist.
- `apps/`: modular academics, students, accounts, dormitories, applications,
  accommodations, violations, maintenance, audit and future reports.
- Model definitions: relational history, PROTECT references, timestamps, indexes,
  unique/check constraints, generated unique active student/bed keys.
- `apps/*/migrations/`: Django-generated initial migrations. Generated columns were
  moved after their referenced foreign keys in the split accommodations migration.
- `tests/`: offline model/upload/migration-order tests and MySQL integrity/race tests.
- `.env.example`, `requirements.txt`, `.gitignore`, README, architecture/ERD docs.
- `scripts/local_manage.py`: tooling-only helper for the embedded local interpreter;
  ordinary installations should use `python manage.py` in their virtual environment.

## Environment and commands

The inspected workspace was empty and Git was initialized without a commit.
`python`, `py`, `mysql` and a MySQL service were not available in the environment.
An embedded KiCad Python 3.11.5 was found. Django 5.2.19, mysqlclient 2.3.0,
python-dotenv, Pillow and openpyxl were installed into ignored `.tools/`, without
modifying KiCad's installed packages. This interpreter is validation tooling only;
Python 3.12+ remains required for application setup and acceptance testing.

Commands run through that interpreter and the local helper with an ephemeral random
environment secret: `check`, `makemigrations` for the model apps,
`test tests.test_schema --verbosity 2`, `makemigrations --check --dry-run`.
MySQL connection to 127.0.0.1:3306 was refused during migration-history checking.
No SQLite database or fallback settings were created.

Executed results: `check` passed without issues and all **8 offline tests passed**.
`makemigrations --check --dry-run` reported no changes (with a connection-history
warning). `check --database default` failed with MySQL connection refused (2002 /
Windows 10061), so database validation did not run. The attempted MySQL integrity
suite also failed during database setup with the same connection refusal; no
integration test body executed. Python compilation succeeded. The MySQL suite,
actual migration application, SQL server checks, Python 3.12 runtime and concurrency
behavior on MySQL remain unverified until the external runtime/database are set up.

## Remaining phases

2. Authentication pages, Django Groups/permissions, fail-closed gender scope,
   permission/scoping tests and transactional audit writes.
3. Validated student/academic/dormitory management, document authorization,
   application workflow and history, locking allocation/check-in/transfer/check-out,
   renewal and concurrent workflow tests.
4. Arabic Bootstrap RTL UI, responsive/accessibility review, database-backed charts.
5. Scoped PDF/Excel reports, violation and maintenance workflows, settings and
   operator backup/recovery tooling.
6. MySQL end-to-end acceptance sequence, production configuration validation,
   Arabic PDF rendering verification and deployment rehearsal.

External unblock steps are in README: install Python 3.12+, start MySQL, create
database/accounts, configure `.env`, install requirements, migrate, run MySQL tests.
No application-complete or production-ready claim is made for this phase.
