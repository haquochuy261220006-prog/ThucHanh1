import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FaceAttendanceContractTests(unittest.TestCase):
    def test_frontend_uses_scan_response_as_final_attendance_result(self):
        source = (ROOT / "static" / "face-attendance.js").read_text(encoding="utf-8")
        self.assertIn("post('/api/chamcong/face/scan'", source)
        self.assertNotIn("/api/chamcong/face/confirm", source)
        self.assertIn("showAttendanceSuccess(match.message", source)

    def test_backend_scan_route_records_attendance_directly(self):
        source = (ROOT / "routes" / "attendance.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        scan = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "face_scan"
        )
        calls = {
            node.func.id for node in ast.walk(scan)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("_record_attendance_cycle", calls)

    def test_face_apis_are_employee_self_service_only(self):
        source = (ROOT / "routes" / "attendance.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for function_name in ("face_delete", "face_enroll", "face_challenge", "face_scan"):
            with self.subTest(function=function_name):
                function = next(
                    node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == function_name
                )
                self.assertTrue(any(
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "admin"
                    for node in ast.walk(function)
                ))
        service = (ROOT / "services" / "attendance_service.py").read_text(encoding="utf-8")
        self.assertIn('session["user"].get("manv")', service)

    def test_only_employee_self_service_template_has_face_panel(self):
        template = (ROOT / "templates" / "attendance.html").read_text(encoding="utf-8")
        self.assertEqual(template.count('id="face-attendance"'), 1)
        self.assertIn('data-consent-version="{{ face_consent_version }}"', template)


if __name__ == "__main__":
    unittest.main()
