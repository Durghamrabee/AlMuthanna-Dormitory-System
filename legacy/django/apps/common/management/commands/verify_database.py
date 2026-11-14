"""Read-only inspection of SQLite or the optional legacy MySQL schema."""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections, models
from django.db.migrations.executor import MigrationExecutor


def inspect_model(model, description, constraints):
    """Return missing/mismatched schema elements without changing the database."""
    errors = []
    table = model._meta.db_table
    columns = {column.name: column for column in description}
    for field in model._meta.local_fields:
        if field.column not in columns:
            errors.append(f"{table}: missing column {field.column}")
            continue
        if bool(columns[field.column].null_ok) != field.null:
            errors.append(f"{table}.{field.column}: nullability differs from model")
        field_constraints = [
            item for item in constraints.values() if item["columns"] == [field.column]
        ]
        if field.primary_key and not any(item["primary_key"] for item in field_constraints):
            errors.append(f"{table}.{field.column}: missing primary key")
        if field.unique and not any(item["unique"] or item["primary_key"] for item in field_constraints):
            errors.append(f"{table}.{field.column}: missing unique constraint")
        if field.db_index and not any(
            (item["index"] or item["unique"] or item["primary_key"]) and item["columns"][:1] == [field.column]
            for item in constraints.values()
        ):
            errors.append(f"{table}.{field.column}: missing index")
        if field.is_relation and field.db_constraint:
            expected = (field.related_model._meta.db_table, field.target_field.column)
            if not any(item["foreign_key"] == expected for item in field_constraints):
                errors.append(f"{table}.{field.column}: missing foreign key to {expected}")
    for index in model._meta.indexes:
        actual = constraints.get(index.name, {})
        expected = [model._meta.get_field(name.lstrip("-")).column for name in index.fields]
        if not actual.get("index") or actual.get("columns") != expected:
            errors.append(f"{table}: missing or mismatched index {index.name}")
    for constraint in model._meta.constraints:
        actual = constraints.get(constraint.name, {})
        if isinstance(constraint, models.CheckConstraint) and not actual.get("check"):
            errors.append(f"{table}: missing check constraint {constraint.name}")
        if isinstance(constraint, models.UniqueConstraint):
            expected = [model._meta.get_field(name).column for name in constraint.fields]
            if not actual.get("unique") or actual.get("columns") != expected:
                errors.append(f"{table}: missing or mismatched unique constraint {constraint.name}")
    return errors


def normalized_expression(expression):
    # MySQL adds quoting, parentheses and whitespace to SHOW/INFORMATION_SCHEMA output.
    return "".join(char for char in expression.lower() if not char.isspace() and char not in '`"()')


class Command(BaseCommand):
    help = "Verify database integrity, migrations, columns, keys, constraints and indexes (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default", choices=tuple(connections))

    def handle(self, *args, **options):
        connection = connections[options["database"]]
        if connection.vendor not in {"mysql", "sqlite"}:
            raise CommandError("Only SQLite and the legacy MySQL backend are supported.")
        try:
            self.verify(connection)
        except DatabaseError as exc:
            code = exc.args[0] if exc.args else "unknown"
            # Do not dump connection settings or credentials into diagnostic output.
            raise CommandError(
                f"Database verification failed (database error {code}). Check database access, "
                "file permissions, disk space and configuration. No schema changes were made."
            ) from exc

    def verify(self, connection):
        connection.ensure_connection()
        if connection.vendor == "mysql" and (connection.mysql_is_mariadb or connection.mysql_version < (8, 0, 16)):
            raise CommandError("MySQL 8.0.16+ is required for enforced CHECK constraints.")
        executor = MigrationExecutor(connection)
        executor.loader.check_consistent_history(connection)
        if executor.loader.detect_conflicts():
            raise CommandError("Conflicting migration branches exist; resolve before validation.")
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise CommandError("Unapplied migrations exist. Review and run manage.py migrate first.")
        errors = []
        table_count = 0
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
            if connection.vendor == "sqlite":
                cursor.execute("SELECT sqlite_version()")
                version = cursor.fetchone()[0]
                cursor.execute("PRAGMA integrity_check")
                if cursor.fetchall() != [("ok",)]:
                    errors.append("SQLite integrity_check failed")
                cursor.execute("PRAGMA foreign_keys")
                if cursor.fetchone()[0] != 1:
                    errors.append("SQLite foreign key enforcement is disabled")
                cursor.execute("PRAGMA ignore_check_constraints")
                if cursor.fetchone()[0] != 0:
                    errors.append("SQLite CHECK constraint enforcement is disabled")
                cursor.execute("PRAGMA foreign_key_check")
                if cursor.fetchall():
                    errors.append("SQLite contains foreign key violations")
            else:
                self.inspect_mysql_options(cursor, errors)
            for model in apps.get_models(include_auto_created=True):
                if not model._meta.can_migrate(connection):
                    continue
                table = model._meta.db_table
                if table not in tables:
                    errors.append(f"Missing table {table}")
                    continue
                table_count += 1
                if connection.vendor == "mysql":
                    engine, collation = self.table_options[table]
                    if engine != "InnoDB" or not (collation or "").startswith("utf8mb4_"):
                        errors.append(f"{table}: expected InnoDB and utf8mb4 collation")
                description = connection.introspection.get_table_description(cursor, table)
                constraints = connection.introspection.get_constraints(cursor, table)
                errors.extend(inspect_model(model, description, constraints))
                for field in model._meta.local_fields:
                    if not isinstance(field, models.GeneratedField):
                        continue
                    expected, params = field.generated_sql(connection)
                    if connection.vendor == "mysql":
                        extra, expression = self.generated.get((table, field.column), ("", ""))
                        valid = "STORED GENERATED" in extra.upper() and normalized_expression(expression) == normalized_expression(expected)
                    else:
                        cursor.execute(f"PRAGMA table_xinfo({connection.ops.quote_name(table)})")
                        stored = {row[1] for row in cursor.fetchall() if row[6] == 3}
                        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=%s", [table])
                        definition = cursor.fetchone()[0]
                        valid = field.column in stored and normalized_expression(expected) in normalized_expression(definition)
                    if params or not valid:
                        errors.append(f"{table}.{field.column}: stored generation expression differs from model")
                self.stdout.write(f"Inspected {table}")
        if errors:
            raise CommandError("Schema verification failed:\n" + "\n".join(errors))
        engine_version = f"SQLite {version}" if connection.vendor == "sqlite" else f"MySQL {connection.mysql_server_info}"
        self.stdout.write(self.style.SUCCESS(
            f"Verified {table_count} tables on {engine_version}; "
            "migration history, columns, keys, relationships and indexes match; "
            "declared CHECK constraints are present and enforced. "
            "Behavior and concurrency tests must also pass."
        ))

    def inspect_mysql_options(self, cursor, errors):
            cursor.execute(
                "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE()"
            )
            self.table_options = {name: (engine, collation) for name, engine, collation in cursor.fetchall()}
            cursor.execute(
                "SELECT TABLE_NAME, COLUMN_NAME, EXTRA, GENERATION_EXPRESSION "
                "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
            )
            self.generated = {(table, column): (extra, expression) for table, column, extra, expression in cursor.fetchall()}
            cursor.execute(
                "SELECT TABLE_NAME, CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'CHECK' AND ENFORCED = 'NO'"
            )
            for table, name in cursor.fetchall():
                errors.append(f"{table}: check constraint {name} is not enforced")
