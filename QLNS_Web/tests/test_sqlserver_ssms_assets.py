from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SqlServerSsmsAssetsTests(unittest.TestCase):
    def test_database_bootstrap_never_drops_existing_database(self):
        sql = (ROOT / "database" / "migrations" / "00_create_database.sql").read_text(encoding="utf-8").upper()
        self.assertIn("IF DB_ID(N'NHANSU_PY') IS NULL", sql)
        self.assertIn("CREATE DATABASE [NHANSU_PY]", sql)
        self.assertNotIn("DROP DATABASE", sql)

    def test_inspection_script_checks_foreign_keys_and_migration_status(self):
        sql = (ROOT / "database" / "migrations" / "01_inspect_database.sql").read_text(encoding="utf-8").upper()
        self.assertIn("SYS.FOREIGN_KEYS", sql)
        self.assertIn("SYS.FOREIGN_KEY_COLUMNS", sql)
        self.assertIn("QLNSSCHEMAVERSION", sql)

    def test_ssms_guide_preserves_existing_database_data(self):
        guide = (ROOT / "docs" / "SQL_SERVER_SSMS_GUIDE.md").read_text(encoding="utf-8").lower()
        self.assertIn("không xóa dữ liệu", guide)
        self.assertIn("backup", guide)
        self.assertIn("windows authentication", guide)


if __name__ == "__main__":
    unittest.main()
