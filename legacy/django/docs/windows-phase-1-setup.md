# Windows Phase 1 setup and verification

> Historical MySQL setup notes. The current application uses local SQLite by the
> operator's explicit choice. Use [README](../README.md) for installation and
> [operations](operations.md) for daily work. Do not reinstall or reset MySQL for
> this application. Its old data and credentials remain untouched.

## Latest diagnosis (2026-11-06, Asia/Baghdad)

**Latest retry:** the application password is now configured, but both Django and
a direct connection using `.env` return **1045 (using password: YES)**. No process
environment overrides were found. Verify the application account/password locally
before proceeding; the earlier empty-password diagnosis below is historical.
Test with the installed 8.0 client (it prompts without putting the password in the
command):

```powershell
& 'C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe' --protocol=TCP -h 127.0.0.1 -P 3306 -u almuthanna_app -p almuthanna_dormitory
```

If this also returns 1045, the account/password/host authentication needs inspection
by the database administrator locally. Do not send or expose the root password,
change authentication plugins blindly, or widen host grants to `%`.

**Update after installation:** MySQL **8.0.46** is installed and the `MySQL80`
service is running. A TCP connection to 127.0.0.1:3306 reaches authentication.
The project `.env` exists and its missing Django secret was generated privately.
The remaining connection blocker is an empty `DB_PASSWORD` (MySQL error 1045,
using password: NO). The database and account are reported provisioned by the
operator; their schema/grants cannot be independently verified until application
authentication succeeds. Do not reinstall MySQL or recreate/reset the account.

Enter the application password directly in `.env`, or use this hidden local prompt:

```powershell
& .\.venv\Scripts\python.exe scripts/configure_local.py --prompt-password
```

Do not send passwords in chat. Then run the commands in section 4. The 8.4
installation instructions below are for a new machine; this machine uses service
`MySQL80` and client `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe`.

The host has **Python 3.14.4**, registered at:

```text
C:\Users\Windows 11\AppData\Local\Programs\Python\Python314\python.exe
```

The ordinary sandbox terminal cannot read that executable and does not have
`python`/`py` on PATH. An authorized host-level check executed it successfully.
This is a terminal visibility/PATH issue, not a missing Python installation.
A project `.venv` was created using this interpreter and `requirements.txt`
installed successfully. Select `.venv\Scripts\python.exe` in VS Code using
**Python: Select Interpreter**. No replacement Python installation is necessary.

The earlier pre-installation host-level service inventory found **zero MySQL/MariaDB services**, and
there were **zero listening TCP sockets on port 3306**. Standard MySQL installation
directories and installed-program records did not contain MySQL Server. There is
no project `.env`. Django currently defaults to 127.0.0.1:3306; connecting produces
error 2002 / Windows 10061 (connection refused), before account authentication.
A nonstandard portable MySQL installation elsewhere was not ruled out by a whole
disk search. If one already exists, configure/start it instead of installing a
second server. No database was created and no migrations were applied by this run.

## 1. Install/configure the missing MySQL Server

Use the official [MySQL Community Server downloads](https://dev.mysql.com/downloads/mysql/)
and select **8.4 LTS**, Microsoft Windows, x86 64-bit, **MSI Installer**. Run the
MSI and its bundled MySQL Configurator. Oracle documents this path in the
[Windows installation guide](https://dev.mysql.com/doc/refman/8.4/en/windows-installation.html)
and [Configurator guide](https://dev.mysql.com/doc/refman/8.4/en/mysql-configurator.html).

In the installer/configurator:

1. Install MySQL Server and command-line client. Workbench is optional.
2. Use a development computer configuration and TCP/IP port **3306**. For this local
   development database, do not open a Windows Firewall inbound port for remote
   access; bind the server to `127.0.0.1` in its `my.ini` (`[mysqld]` section:
   `bind-address=127.0.0.1`).
3. Keep the default strong authentication. Set a unique root password locally and
   retain it securely; do not place root credentials in Django's `.env`.
4. Configure the Windows service name **MySQL84**, start it automatically, and apply
   configuration. Use the default restricted service account. Installation/service
   configuration requires a Windows administrator; ordinary project commands do not.
5. Confirm service startup. If you used a different name, replace `MySQL84` below.

```powershell
Get-Service MySQL84
# Only if installed but stopped; run this line in Administrator PowerShell:
Start-Service MySQL84
Get-NetTCPConnection -State Listen -LocalPort 3306
Test-NetConnection 127.0.0.1 -Port 3306
$mysqlExe = 'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe'
& $mysqlExe --version
& $mysqlExe --protocol=TCP -h 127.0.0.1 -P 3306 -u root -p
```

If startup fails, inspect the service executable/configuration using
`sc.exe qc MySQL84` and the `*.err` file in the configured data directory (normally
`C:\ProgramData\MySQL\MySQL Server 8.4\Data`). Check for an occupied port and invalid
`my.ini` options. Do not reinitialize or delete an existing data directory. A
firewall exception cannot repair an absent listener. Authentication error 1045
means the server is now reachable but account/password/host grants need attention;
unknown database 1049 means it is reachable but the named database is absent.

## 2. Verify or provision database and development account

Inside the MySQL root console, inspect first:

```sql
SELECT VERSION(), @@default_storage_engine, @@port, @@bind_address;
SELECT @@partial_revokes;
SHOW DATABASES LIKE 'almuthanna_dormitory';
SELECT User, Host FROM mysql.user WHERE User = 'almuthanna_app';
```

If the database/account **do not exist**, run the statements below. Replace the
password placeholder locally. If an account exists, inspect `SHOW GRANTS FOR
'almuthanna_app'@'localhost';` instead and preserve its credentials. The local
account host is `localhost`, while Django connects by TCP to `127.0.0.1`.
Do not use `%` host grants. Do not use `CREATE OR REPLACE`, drop tables, fake
migrations, or reset an existing password merely to get setup to pass.

```sql
CREATE DATABASE almuthanna_dormitory
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'almuthanna_app'@'localhost'
  IDENTIFIED BY '<choose-a-unique-development-password>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON `almuthanna\_dormitory`.* TO 'almuthanna_app'@'localhost';
-- Development/testing ONLY: Django creates and drops this separate test database.
GRANT ALL PRIVILEGES ON `test\_almuthanna\_dormitory`.*
  TO 'almuthanna_app'@'localhost';
SHOW GRANTS FOR 'almuthanna_app'@'localhost';
```

The escaped underscores in these grants keep access limited to the named schemas
with MySQL's default `partial_revokes=OFF`. If your existing server has
`partial_revokes=ON`, omit the backslashes in the two GRANT database identifiers
because that mode treats them literally. See the official
[GRANT reference](https://dev.mysql.com/doc/refman/8.4/en/grant.html).
The test grant is not a global grant.
Use separate migration, runtime and test accounts for production. No `FLUSH
PRIVILEGES` is needed after CREATE USER/GRANT. Verify the actual connection account:

```powershell
& $mysqlExe --protocol=TCP -h 127.0.0.1 -P 3306 -u almuthanna_app -p almuthanna_dormitory
```

```sql
SELECT DATABASE(), CURRENT_USER(), VERSION(), @@default_storage_engine;
```

If host resolution means a different account is required, diagnose the actual
reported connection/host first and create an explicit loopback grant for that host;
do not widen access to remote clients.

## 3. Configure the project without overwriting existing settings

Run from the project root in normal Windows PowerShell/VS Code:

```powershell
$pythonExe = 'C:\Users\Windows 11\AppData\Local\Programs\Python\Python314\python.exe'
& $pythonExe --version
if (!(Test-Path .venv\Scripts\python.exe)) { & $pythonExe -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip check
if (!(Test-Path .env)) { Copy-Item .env.example .env }
& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(64))"
```

Paste the generated secret into `.env` as `DJANGO_SECRET_KEY` and set:

```dotenv
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DB_NAME=almuthanna_dormitory
DB_USER=almuthanna_app
DB_PASSWORD='<the-account-password-you-chose>'
DB_HOST=127.0.0.1
DB_PORT=3306
```

Keep `.env` private and ignored by Git. If a password contains a literal single
quote or backslash, use python-dotenv's documented quoting/escape rules rather than
copying the placeholder syntax blindly. Process environment variables override
`.env`; check stale `DB_*` variables if connection settings appear unchanged.
Use `DJANGO_DEBUG=false` and the documented HTTPS settings for deployment.

If Python truly is missing on another Windows computer, install a supported
64-bit Python 3.12+ from [Python's Windows releases](https://www.python.org/downloads/windows/),
include pip/venv, and add Python to PATH or use the installed executable's full path.
The project does not require the `py` launcher when a full path is used.

## 4. Apply migrations, inspect the live schema, run tests

Back up an existing nonempty database first. These commands must complete
successfully before declaring Phase 1 complete or starting Phase 2:

```powershell
& .\.venv\Scripts\python.exe manage.py check --database default
& .\.venv\Scripts\python.exe manage.py showmigrations
& .\.venv\Scripts\python.exe manage.py migrate --plan
& .\.venv\Scripts\python.exe manage.py migrate
& .\.venv\Scripts\python.exe manage.py migrate --check
& .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
& .\.venv\Scripts\python.exe manage.py verify_database
& .\.venv\Scripts\python.exe manage.py test tests --verbosity 2
& .\.venv\Scripts\python.exe manage.py createsuperuser
```

Execute one command at a time and stop on the first nonzero exit code. Never use
`--fake` to bypass schema failures. Django's test runner creates and removes
`test_almuthanna_dormitory`; no SQLite fallback is configured. Do not run the suite
with a production database/test account or approve dropping an unrelated existing
test schema. For production-settings checks, set `DJANGO_DEBUG=false` for
`manage.py check --deploy`; passing it does not prove HTTPS deployment works.

`verify_database` is read-only. It checks MySQL version, migration consistency,
managed and automatic join tables, required columns/nullability, primary/unique/
foreign keys, indexes, named CHECK presence/enforcement, InnoDB/utf8mb4 and stored
generated expressions. It does not prove every column type or CHECK expression
is unchanged; behavioral integration tests cover the critical constraints.

The integration suite covers uniqueness, foreign-key history protection, schema
introspection, CHECK enforcement, availability, and competing inserts. It does
not yet validate the Phase 2 permission matrix or Phase 3 workflow services.

## Phase 2 gate

Only after the commands above pass against MySQL: implement login/logout and
Django Groups/Permissions, then apply fail-closed gender scopes to all list/detail,
write, download and export paths. Male/female manager groups must receive only
their respective explicit scopes; membership alone must not grant both. Privileged
cross-gender access requires an explicit authorized grant. Audit permission/scope
changes and test direct URL access as well as interface navigation.
