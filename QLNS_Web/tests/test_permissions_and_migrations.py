import ast
from pathlib import Path
import unittest

from permissions import can_assign_role, role_can
from migrate_db import _add_sql_error_context
from schema_migrations import (
    CURRENT_SCHEMA_VERSION,
    begin_migration,
    finish_migration,
    grant_web_read,
)


class RecordingDb:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))


class RolePermissionTests(unittest.TestCase):
    def test_role_scopes_keep_salary_export_and_team_access_separate(self):
        self.assertTrue(role_can("HR", "employees.view_salary"))
        self.assertTrue(role_can("HR", "employees.export_salary"))
        self.assertTrue(role_can("KeToan", "payroll.export"))
        self.assertFalse(role_can("KeToan", "employees.view"))
        self.assertTrue(role_can("QuanLy", "attendance.view_team"))
        self.assertFalse(role_can("QuanLy", "employees.view_salary"))
        self.assertTrue(role_can("NhanVien", "self.attendance"))
        self.assertFalse(role_can("NhanVien", "employees.view"))

    def test_only_super_admin_can_assign_elevated_roles(self):
        self.assertTrue(can_assign_role("QuanTri", "QuanTriHeThong"))
        self.assertFalse(can_assign_role("QuanTriHeThong", "QuanTri"))
        self.assertFalse(can_assign_role("HR", "QuanTriHeThong"))


class SchemaMigrationTests(unittest.TestCase):
    def test_migration_errors_include_sql_statement_context(self):
        class FailingDb:
            def execute(self, sql, params=()):
                raise ValueError("syntax error")

            query = execute

        db = FailingDb()
        _add_sql_error_context(db)

        with self.assertRaisesRegex(RuntimeError, "SQL starts with: ALTER TABLE"):
            db.execute("ALTER TABLE dbo.TableName ADD ColumnName INT")

    def test_request_readiness_check_does_not_run_schema_ddl(self):
        source = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        readiness = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_check_schema_readiness"
        )
        called_functions = {
            node.func.id
            for node in ast.walk(readiness)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        self.assertNotIn("ensure_schema", called_functions)

    def test_migration_is_marked_incomplete_until_finish(self):
        db = RecordingDb()

        begin_migration(db)
        finish_migration(db)

        self.assertIn("CREATE TABLE dbo.QlnsSchemaVersion", db.calls[0][0])
        self.assertEqual(db.calls[1][1], (CURRENT_SCHEMA_VERSION,) * 3)
        self.assertIn("SET IsComplete=0", db.calls[1][0])
        self.assertIn("SET IsComplete=1", db.calls[2][0])

    def test_web_schema_read_grant_escapes_principal_as_identifier(self):
        db = RecordingDb()

        grant_web_read(db, "web]login")

        self.assertIn("GRANT SELECT ON dbo.QlnsSchemaVersion TO [web]]login]", db.calls[0][0])
        self.assertEqual(db.calls[0][1], ("web]login",))

    def test_web_read_grant_is_skipped_without_a_separate_principal(self):
        db = RecordingDb()

        grant_web_read(db, None)

        self.assertEqual(db.calls, [])


if __name__ == "__main__":
    unittest.main()
