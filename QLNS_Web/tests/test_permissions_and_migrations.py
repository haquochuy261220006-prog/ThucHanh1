import unittest

from utils.permissions import role_can, module_permission
from migrate_db import _add_sql_error_context
from database.schema_migrations import (
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
    def test_role_scopes_match_current_permission_catalog(self):
        self.assertTrue(role_can("HR", "employees.view"))
        self.assertTrue(role_can("HR", "employees.create"))
        self.assertTrue(role_can("KeToan", "payroll.calculate"))
        # Legacy accounting accounts are migrated to HR_ACCOUNTANT and retain
        # the employee-management permissions of that combined role.
        self.assertTrue(role_can("KeToan", "employees.view"))
        # Legacy manager accounts normalize to the employee role. Team scope
        # requires a separately assigned permission, which is not in that role.
        self.assertFalse(role_can("QuanLy", "employees.team_view"))
        self.assertFalse(role_can("QuanLy", "employees.view_salary"))
        self.assertTrue(role_can("NhanVien", "self.attendance"))
        self.assertFalse(role_can("NhanVien", "employees.view"))

    def test_module_permission_maps_crud_actions(self):
        self.assertEqual(module_permission("nhanvien", "view"), "employees.view")
        self.assertEqual(module_permission("nhanvien", "add"), "employees.create")
        self.assertEqual(module_permission("hopdong", "update"), "contracts.edit")
        self.assertIsNone(module_permission("unknown", "view"))


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

    def test_migration_is_marked_incomplete_until_finish(self):
        db = RecordingDb()
        begin_migration(db)
        finish_migration(db)
        self.assertIn("CREATE TABLE dbo.QlnsSchemaVersion", db.calls[0][0])
        self.assertEqual(db.calls[1][1], (CURRENT_SCHEMA_VERSION,) * 3)
        self.assertIn("SET IsComplete=0", db.calls[1][0])
        self.assertIn("SET IsComplete=1", db.calls[2][0])

    def test_web_read_grant_escapes_principal_as_identifier(self):
        db = RecordingDb()
        grant_web_read(db, "web]login")
        self.assertIn("GRANT SELECT ON dbo.QlnsSchemaVersion TO [web]]login]", db.calls[0][0])
        self.assertEqual(db.calls[0][1], ("web]login",))

    def test_web_read_grant_is_skipped_without_a_separate_principal(self):
        db = RecordingDb()
        grant_web_read(db, None)
        self.assertEqual(db.calls, [])

    def test_migration_does_not_drop_existing_custom_profile_data(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        migration = (root / "database" / "migrate_db.py").read_text(encoding="utf-8")
        helpers = (root / "database" / "schema_migrations.py").read_text(encoding="utf-8")
        self.assertNotIn("drop_custom_profile_fields", migration)
        self.assertNotIn("DROP TABLE dbo.TruongMoRongNhanVien", helpers)
        self.assertNotIn("DROP TABLE dbo.GiaTriMoRongNhanVien", helpers)
        self.assertNotIn("DROP TABLE dbo.NhatKyTruongNhanVien", helpers)


if __name__ == "__main__":
    unittest.main()
