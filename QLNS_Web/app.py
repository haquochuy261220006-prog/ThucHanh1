import hmac
import os
import secrets
from flask import Flask, flash, jsonify, redirect, request, session, url_for

from database import db
from permissions import ROLE_LABELS
from contracts import bp as contracts_bp
from schema_migrations import CURRENT_SCHEMA_VERSION
from services.common_service import has_permission

app = Flask(__name__)
_app_env = os.environ.get("APP_ENV", "").lower()
_secret_key = os.environ.get("FLASK_SECRET_KEY")
if _app_env == "production" and not _secret_key:
    raise RuntimeError("Production requires FLASK_SECRET_KEY to be configured.")
app.secret_key = _secret_key or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower()
    in ("1", "true", "yes", "on")
    or os.environ.get("APP_ENV", "").lower() == "production",
    MAX_CONTENT_LENGTH=11 * 1024 * 1024,
)

app.register_blueprint(contracts_bp)

# shortcut: the initial cosine threshold and one face template need calibration before face matches are used as sole payroll evidence.












# Endpoint ghi dữ liệu nguồn của bảng lương; thay đổi thành công sẽ làm bảng lương nháp hết hiệu lực.
_PAYROLL_SOURCE_ENDPOINTS = frozenset(
    {
        "chamcong",
        "nghiphep",
        "overtime_requests",
        "workforce_shifts",
        "dieuchuyen",
        "face_enroll",
        "face_delete",
        "face_scan",
    }
)














@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(self), microphone=(), geolocation=()"
    )
    if request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# ---------------------------------------------------------------- CSRF
def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.context_processor
def _inject_csrf():
    return {
        "csrf_token": csrf_token,
        "has_permission": has_permission,
        "role_label": ROLE_LABELS.get(session.get("user", {}).get("role"), "Người dùng"),
    }


@app.before_request
def _csrf_protect():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    # API khuôn mặt đã có token riêng (X-Face-CSRF), được kiểm tra trong face_payload()
    if request.path.startswith("/api/chamcong/face/"):
        return None
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf_token", "")):
        if request.path.startswith("/api/") or request.headers.get("X-CSRF-Token"):
            return jsonify(ok=False, error="Phiên làm việc hết hạn. Hãy tải lại trang."), 400
        flash("Phiên làm việc hết hạn hoặc yêu cầu không hợp lệ. Hãy thử lại.", "error")
        return redirect(request.referrer or url_for("accounts.login"))
    return None


# ------------------------------------------- Giới hạn đăng nhập sai




# ----------------------------- OTP lưu phía máy chủ, gắn với nhân viên và quản trị viên


















































_schema_ok = False


@app.before_request
def _check_schema_readiness():
    global _schema_ok
    if _schema_ok or request.endpoint in (None, "static"):
        return
    try:
        rows = db.query(
            "SELECT 1 FROM dbo.QlnsSchemaVersion WHERE Version=? AND IsComplete=1",
            (CURRENT_SCHEMA_VERSION,),
        )[1]
        if not rows:
            return (
                "Database schema is not upgraded. Stop web workers, run python migrate_db.py "
                "with the migration account, then restart them.",
                503,
            )
        _schema_ok = True
    except Exception as e:
        app.logger.error(
            "Schema readiness check failed",
            exc_info=(type(e), e, e.__traceback__),
        )
        return (
            "Không thể kiểm tra trạng thái database schema. Hãy kiểm tra kết nối SQL Server "
            "và quyền SELECT của tài khoản ứng dụng trên dbo.QlnsSchemaVersion.",
            503,
        )


@app.after_request
def _invalidate_draft_payroll_after_source_change(response):
    endpoint = request.endpoint or ""
    endpoint_name = endpoint.rsplit(".", 1)[-1]
    module_key = (request.view_args or {}).get("key")
    source_changed = (
        request.method == "POST"
        and response.status_code < 400
        and (
            endpoint_name in _PAYROLL_SOURCE_ENDPOINTS
            or (endpoint_name == "module" and module_key == "nhanvien")
        )
    )
    if source_changed:
        try:
            db.execute(
                "UPDATE LuongKy SET TinhLuc=NULL,PhienBan=PhienBan+1 WHERE TrangThai=N'Nháp' AND TinhLuc IS NOT NULL AND EXISTS(SELECT 1 FROM Luong l WHERE l.Nam=LuongKy.Nam AND l.Thang=LuongKy.Thang)"
            )
        except Exception:
            app.logger.exception("Could not invalidate draft payroll after source-data update")
    return response


@app.before_request
def _validate_session_version():
    user = session.get("user")
    if not user or request.endpoint in (None, "static", "accounts.login"):
        return None
    try:
        rows = db.query(
            """SELECT t.SecurityVersion,t.VaiTro,t.MaNV,n.TrangThai
               FROM TaiKhoan t LEFT JOIN NhanVien n ON n.MaNV=t.MaNV
               WHERE t.TenDN=?""",
            (user.get("user"),),
        )[1]
    except Exception as e:
        app.logger.error(
            "Could not validate session account",
            exc_info=(type(e), e, e.__traceback__),
        )
        return "Không xác thực được phiên đăng nhập. Vui lòng thử lại.", 503
    if not rows:
        session.clear()
        flash("Tài khoản không còn hoạt động. Vui lòng đăng nhập lại.", "error")
        return redirect(url_for("accounts.login"))
    version, role, employee_id, employee_status = rows[0]
    if (
        user.get("security_version") != version
        or user.get("role") != role
        or user.get("manv") != employee_id
        or (employee_id is not None and employee_status != "Đang làm")
        or (role == "NhanVien" and employee_id is None)
    ):
        session.clear()
        flash("Phiên đăng nhập đã hết hiệu lực. Vui lòng đăng nhập lại.", "error")
        return redirect(url_for("accounts.login"))
    return None












_face_purge_day = None












































































# Route handlers and business services are isolated from this app factory module.
from routes.accounts import bp as accounts_bp
from routes.attendance import bp as attendance_bp
from routes.dashboard import bp as dashboard_bp
from routes.departments import bp as departments_bp
from routes.employees import bp as employees_bp
from routes.leave import bp as leave_bp
from routes.payroll import bp as payroll_bp
from routes.reports import bp as reports_bp

for _blueprint in (accounts_bp, dashboard_bp, departments_bp, employees_bp, attendance_bp, leave_bp, payroll_bp, reports_bp):
    app.register_blueprint(_blueprint)

from app_errors import register_error_handlers
register_error_handlers(app)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
