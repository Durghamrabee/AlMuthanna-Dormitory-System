"""Strict validation of our versioned SQLite schema before startup or restore."""
from collections import defaultdict
import re

from sqlalchemy import CheckConstraint, UniqueConstraint
from .models import Base


def _rows(connection, sql):
    if hasattr(connection, "exec_driver_sql"):
        return connection.exec_driver_sql(sql).fetchall()
    return connection.execute(sql).fetchall()


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _canonical(expression):
    """Normalize formatting outside string literals, keeping comparison values exact."""
    result, index, quoted = [], 0, False
    while index < len(expression):
        char = expression[index]
        if char == "'":
            result.append(char)
            if quoted and index + 1 < len(expression) and expression[index + 1] == "'":
                result.append("'")
                index += 2
                continue
            quoted = not quoted
        elif quoted:
            result.append(char)
        elif not char.isspace() and char not in '"`[]':
            result.append(char.lower())
        index += 1
    return "".join(result)


def _checks(sql):
    results, index = set(), 0
    while index < len(sql):
        char = sql[index]
        if char in "'\"`[":
            end = "]" if char == "[" else char
            index += 1
            while index < len(sql):
                if sql[index] == end:
                    index += 1
                    if index < len(sql) and sql[index] == end and char != "[":
                        index += 1
                    else:
                        break
                else:
                    index += 1
            continue
        if sql[index:index + 2] in {"--", "/*"}:
            raise ValueError("مخطط قاعدة البيانات غير متوافق مع الإصدار الموثوق.")
        match = re.match(r"\bCHECK\s*\(", sql[index:], re.IGNORECASE)
        if not match:
            index += 1
            continue
        index += match.end()
        start, depth, quoted = index, 1, False
        while index < len(sql) and depth:
            current = sql[index]
            if current == "'":
                if quoted and index + 1 < len(sql) and sql[index + 1] == "'":
                    index += 2
                    continue
                quoted = not quoted
            elif not quoted:
                if current == "(":
                    depth += 1
                elif current == ")":
                    depth -= 1
            index += 1
        if depth:
            raise ValueError("تعبير قيد قاعدة البيانات غير صالح.")
        results.add(_canonical(sql[start:index - 1]))
    return results


def _affinity(name):
    value = name.upper()
    if "INT" in value:
        return "INTEGER"
    if any(part in value for part in ("CHAR", "CLOB", "TEXT")):
        return "TEXT"
    if "BLOB" in value or not value:
        return "BLOB"
    if any(part in value for part in ("REAL", "FLOA", "DOUB")):
        return "REAL"
    return "NUMERIC"


def verify_schema(connection, triggers=(), metadata=None):
    for table in (metadata or Base.metadata).sorted_tables:
        table_name = _quoted(table.name)
        info = _rows(connection, f"PRAGMA table_info({table_name})")
        columns = {item[1]: item for item in info}
        if not set(table.columns.keys()) <= set(columns):
            raise ValueError("مخطط قاعدة البيانات يفتقد حقولاً مطلوبة؛ لم تتم الاستعادة.")
        actual_pk = tuple(item[1] for item in sorted(info, key=lambda item: item[5]) if item[5])
        if actual_pk != tuple(column.name for column in table.primary_key.columns):
            raise ValueError("مفتاح أحد جداول قاعدة البيانات غير متوافق.")
        for column in table.columns:
            actual = columns[column.name]
            if _affinity(str(column.type)) != _affinity(actual[2]):
                raise ValueError("نوع أحد حقول قاعدة البيانات غير متوافق.")
            if not column.nullable and not column.primary_key and not actual[3]:
                raise ValueError("قاعدة البيانات تفتقد قيد الحقول الإجبارية.")
        indexes, unique = set(), set()
        for item in _rows(connection, f"PRAGMA index_list({table_name})"):
            if item[4]:
                continue  # A partial index cannot replace a full uniqueness guarantee.
            fields = tuple(row[2] for row in _rows(connection, f"PRAGMA index_info({_quoted(item[1])})"))
            indexes.add(fields)
            if item[2]:
                unique.add(fields)
        expected_unique = {tuple(column.name for column in constraint.columns) for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}
        expected_indexes = {tuple(column.name for column in index.columns) for index in table.indexes}
        if not expected_unique <= unique or not expected_indexes <= indexes:
            raise ValueError("قاعدة البيانات تفتقد قيداً فريداً أو فهرساً مطلوباً.")
        foreign_groups = defaultdict(list)
        for item in _rows(connection, f"PRAGMA foreign_key_list({table_name})"):
            foreign_groups[item[0]].append(item)
        actual_foreign = set()
        for group in foreign_groups.values():
            group.sort(key=lambda item: item[1])
            actual_foreign.add((tuple(item[3] for item in group), group[0][2], tuple(item[4] for item in group), group[0][6].upper()))
        expected_foreign = set()
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            expected_foreign.add((tuple(item.parent.name for item in elements), elements[0].column.table.name,
                                  tuple(item.column.name for item in elements), (constraint.ondelete or "NO ACTION").upper()))
        if not expected_foreign <= actual_foreign:
            raise ValueError("قاعدة البيانات تفتقد علاقة مرجعية أو سلوك حذف آمناً.")
        sql_rows = _rows(connection, "SELECT sql FROM sqlite_master WHERE type='table' AND name='" + table.name + "'")
        if not sql_rows:
            raise ValueError("جدول مطلوب غير موجود في قاعدة البيانات.")
        checks = {_canonical(str(constraint.sqltext)) for constraint in table.constraints if isinstance(constraint, CheckConstraint)}
        if not checks <= _checks(sql_rows[0][0]):
            raise ValueError("قاعدة البيانات تفتقد أحد قيود التحقق المطلوبة؛ احتُفظ بالبيانات الحالية.")
    actual_triggers = {name: sql for name, sql in _rows(connection, "SELECT name,sql FROM sqlite_master WHERE type='trigger'")}
    for expected in triggers:
        match = re.search(r"TRIGGER\s+IF\s+NOT\s+EXISTS\s+(\w+)", expected, re.IGNORECASE)
        if match is None:
            raise ValueError("تعذر التحقق من مشغلات سلامة البيانات.")
        actual = actual_triggers.get(match.group(1), "")
        normalized = lambda sql: _canonical(re.sub(r"\bIF\s+NOT\s+EXISTS\s+", "", sql, flags=re.IGNORECASE))
        if normalized(expected) != normalized(actual):
            raise ValueError("قاعدة البيانات تفتقد مشغل حماية السعة أو الجنس أو الرقم الجامعي.")
