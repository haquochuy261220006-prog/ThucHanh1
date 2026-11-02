import base64
import csv
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import smtplib
import time
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from werkzeug.utils import secure_filename

from flask import (
    Flask,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError

import auth
import config
from cryptography.fernet import Fernet, InvalidToken
import db
import employee_profiles
import sensitive_audit
from permissions import ROLE_LABELS, module_permission, role_can
from contracts import bp as contracts_bp, sync_contract_statuses
from config import CONG_CHUAN, GIO_VAO_CHUAN
from payroll import apply_month_rules, approve_period, calculate_payroll, get_period_status, invalidate_period, lock_period, reopen_period, summarize_attendance, summarize_attendance_event_hours, touch_period
from payroll_engine import calculate_statutory_payroll, effective_salary_for_period, validate_policy
from web_auth import login_required

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
EMPLOYEE_SCAN_PREFILL = {}

app.register_blueprint(contracts_bp)

MODULES = {
    "nhanvien": {
        "title": "Nhân viên",
        "table": "NhanVien",
        "pk": "MaNV",
        "fields": [
            ("HoTen", "Họ tên", "text", True),
            ("NgaySinh", "Ngày sinh", "date", False),
            ("GioiTinh", "Giới tính", "choice:Nam|Nữ|Khác", False),
            ("DiaChi", "Địa chỉ", "text", False),
            ("SDT", "Số điện thoại", "text", False),
            ("Email", "Email", "email", False),
            ("CCCD", "CCCD", "text", False),
            ("NgayVaoLam", "Ngày vào làm", "date", False),
            ("MaPB", "Phòng ban", "department", False),
            ("MaCV", "Chức vụ", "position", False),
            ("MaViTri", "Vị trí công việc", "jobposition", False),
            ("LuongCoBan", "Lương cơ bản", "number", False),
            ("TrangThai", "Trạng thái", "choice:Đang làm|Đã nghỉ việc", True),
            ("AnhHoSo", "Ảnh hồ sơ", "image", False),
        ],
        "sql": "SELECT n.MaNV AS [_id],ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))) AS [Mã NV],n.HoTen AS [Họ tên],n.NgaySinh AS [Ngày sinh],n.GioiTinh AS [Giới tính],n.SDT AS [SĐT],n.Email,p.TenPB AS [Phòng ban],c.TenCV AS [Chức danh],v.TenViTri AS [Vị trí],n.NgayVaoLam AS [Ngày vào],n.LuongCoBan AS [Lương CB],n.TrangThai AS [Trạng thái] FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB LEFT JOIN ChucVu c ON c.MaCV=n.MaCV LEFT JOIN ViTriCongViec v ON v.MaViTri=n.MaViTri ORDER BY n.MaNV DESC",
    },
    "phongban": {
        "title": "Phòng ban",
        "table": "PhongBan",
        "pk": "MaPB",
        "fields": [
            ("TenPB", "Tên phòng ban", "text", True),
            ("KyHieu", "Ký hiệu (VD: KT)", "text", True),
            ("MaDonVi", "Đơn vị", "unit", False),
            ("MaPBCha", "Phòng ban cấp trên", "department_parent", False),
            ("NguoiPhuTrach", "Người phụ trách", "text", False),
            ("TrangThai", "Trạng thái", "choice:Hoạt động|Ngừng hoạt động", True),
        ],
        "sql": "SELECT p.MaPB AS [Mã PB],p.TenPB AS [Tên phòng ban],p.KyHieu AS [Ký hiệu],d.TenDonVi AS [Đơn vị],cha.TenPB AS [Cấp trên],p.NguoiPhuTrach AS [Người phụ trách],p.TrangThai AS [Trạng thái] FROM PhongBan p LEFT JOIN DonVi d ON d.MaDonVi=p.MaDonVi LEFT JOIN PhongBan cha ON cha.MaPB=p.MaPBCha ORDER BY p.MaPB DESC",
    },
    "donvi": {
        "title": "Đơn vị",
        "table": "DonVi",
        "pk": "MaDonVi",
        "fields": [("TenDonVi", "Tên đơn vị", "text", True), ("MaDonViCha", "Đơn vị cấp trên", "unit", False), ("TrangThai", "Trạng thái", "choice:Hoạt động|Ngừng hoạt động", True)],
        "sql": "SELECT d.MaDonVi AS [Mã đơn vị],d.TenDonVi AS [Tên đơn vị],cha.TenDonVi AS [Đơn vị cấp trên],d.TrangThai AS [Trạng thái] FROM DonVi d LEFT JOIN DonVi cha ON cha.MaDonVi=d.MaDonViCha ORDER BY d.TenDonVi",
    },
    "vitri": {
        "title": "Vị trí công việc",
        "table": "ViTriCongViec",
        "pk": "MaViTri",
        "fields": [("TenViTri", "Tên vị trí", "text", True), ("MaPB", "Phòng ban", "department", False), ("MoTa", "Mô tả", "text", False), ("TrangThai", "Trạng thái", "choice:Hoạt động|Ngừng hoạt động", True)],
        "sql": "SELECT v.MaViTri AS [Mã vị trí],v.TenViTri AS [Vị trí],p.TenPB AS [Phòng ban],v.MoTa AS [Mô tả],v.TrangThai AS [Trạng thái] FROM ViTriCongViec v LEFT JOIN PhongBan p ON p.MaPB=v.MaPB ORDER BY v.TenViTri",
    },
    "chucvu": {
        "title": "Chức vụ",
        "table": "ChucVu",
        "pk": "MaCV",
        "fields": [
            ("TenCV", "Tên chức vụ", "text", True),
            ("MoTa", "Mô tả", "text", False),
        ],
        "sql": "SELECT MaCV AS [Mã CV],TenCV AS [Tên chức vụ],MoTa AS [Mô tả] FROM ChucVu ORDER BY MaCV DESC",
    },
    "hopdong": {
        "title": "Hợp đồng",
        "table": "HopDong",
        "pk": "MaHD",
        "fields": [
            ("MaNV", "Nhân viên", "employee", True),
            (
                "LoaiHD",
                "Loại hợp đồng",
                "choice:Thử việc|Có thời hạn|Không thời hạn|Thời vụ|Bán thời gian|Học việc|Cộng tác viên|Đào tạo",
                True,
            ),
            ("NgayBatDau", "Ngày bắt đầu", "date", True),
            ("NgayKetThuc", "Ngày kết thúc", "date", False),
            ("LuongHD", "Lương hợp đồng", "number", False),
        ],
        "sql": "SELECT h.MaHD AS [Mã HĐ],n.HoTen AS [Nhân viên],h.LoaiHD AS [Loại],h.NgayBatDau AS [Bắt đầu],h.NgayKetThuc AS [Kết thúc],h.LuongHD AS [Lương HĐ],h.TrangThai AS [Trạng thái] FROM HopDong h JOIN NhanVien n ON n.MaNV=h.MaNV ORDER BY h.MaHD DESC",
    },
}
REPORTS = {
    "Tổng số nhân viên đang làm": (
        "SELECT COUNT(*) AS [Tổng nhân viên] FROM NhanVien WHERE TrangThai=N'Đang làm'",
        (),
    ),
    "Nhân viên theo phòng ban": (
        "SELECT ISNULL(p.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],COUNT(*) AS [Số nhân viên] FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB WHERE n.TrangThai=N'Đang làm' GROUP BY p.TenPB ORDER BY 2 DESC",
        (),
    ),
    "Nhân viên theo chức vụ": (
        "SELECT ISNULL(c.TenCV,N'(Chưa có chức vụ)') AS [Chức vụ],COUNT(*) AS [Số nhân viên] FROM NhanVien n LEFT JOIN ChucVu c ON c.MaCV=n.MaCV WHERE n.TrangThai=N'Đang làm' GROUP BY c.TenCV ORDER BY 2 DESC",
        (),
    ),
    "Nhân viên đã nghỉ việc": (
        "SELECT ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) AS [Mã NV],HoTen AS [Họ tên],NgayVaoLam AS [Ngày vào làm] FROM NhanVien WHERE TrangThai=N'Đã nghỉ việc'",
        (),
    ),
    "Đơn nghỉ phép theo trạng thái": (
        "SELECT TrangThai AS [Trạng thái],COUNT(*) AS [Số đơn],SUM(SoNgay) AS [Tổng ngày] FROM NghiPhep GROUP BY TrangThai",
        (),
    ),
    "Ngày công theo nhân viên": (None, ()),
    "Tỷ lệ nghỉ việc": (None, ()),
    "Tỷ lệ vắng mặt": (None, ()),
    "Chi phí nhân sự (kỳ lương đã khóa)": (None, ()),
    "Thời gian tuyển dụng": (None, ()),
    "Tỷ lệ hoàn thành KPI": (None, ()),
    "Dự báo nhu cầu nhân lực": (None, ()),
}
ATTENDANCE_PROGRESS_SQL = """WITH EffectiveEvents AS (
       SELECT e.MaNV,e.NgayCong,e.MaSuKien,e.ThoiDiem,e.LoaiSuKien
       FROM ChamCongSuKien e
       JOIN ChamCong c ON c.MaNV=e.MaNV AND c.Ngay=e.NgayCong
       WHERE e.NgayCong>=? AND e.NgayCong<DATEADD(month,1,?)
         AND e.LoaiSuKien IN (N'in',N'out')
         AND c.TrangThai IN (N'Đi làm',N'Đi muộn')
         AND e.MaSuKien>ISNULL((SELECT MAX(x.MaSuKien) FROM ChamCongSuKien x
             WHERE x.MaNV=e.MaNV AND x.NgayCong=e.NgayCong AND x.LoaiSuKien=N'delete'),0)
   ), AttendanceDays AS (
       SELECT DISTINCT MaNV,NgayCong FROM EffectiveEvents WHERE LoaiSuKien=N'in'
   ), OrderedEvents AS (
       SELECT MaNV,NgayCong,LoaiSuKien,ThoiDiem,
           LEAD(LoaiSuKien) OVER(PARTITION BY MaNV,NgayCong ORDER BY MaSuKien) AS NextType,
           LEAD(ThoiDiem) OVER(PARTITION BY MaNV,NgayCong ORDER BY MaSuKien) AS NextTime
       FROM EffectiveEvents
   ), EventHours AS (
       SELECT MaNV,NgayCong,SUM(DATEDIFF(SECOND,ThoiDiem,NextTime))/3600.0 AS HoursWorked
       FROM OrderedEvents
       WHERE LoaiSuKien=N'in' AND NextType=N'out' AND NextTime>=ThoiDiem
       GROUP BY MaNV,NgayCong
   ), EmployeeSummary AS (
       SELECT n.MaNV,n.HoTen,COUNT(a.NgayCong) AS WorkDays,
           CAST(ROUND(ISNULL(SUM(h.HoursWorked),0),2) AS DECIMAL(8,2)) AS HoursWorked
       FROM NhanVien n
       LEFT JOIN AttendanceDays a ON a.MaNV=n.MaNV
       LEFT JOIN EventHours h ON h.MaNV=a.MaNV AND h.NgayCong=a.NgayCong
       WHERE n.TrangThai=N'Đang làm'
       GROUP BY n.MaNV,n.HoTen
   )
   SELECT HoTen AS [Nhân viên],
       CAST(ROUND(WorkDays*100.0/?,1) AS DECIMAL(6,1)) AS [Tiến độ ngày công (%)],
       WorkDays AS [Ngày đi làm],? AS [Chuẩn ngày công],
       HoursWorked AS [Giờ ghi nhận]
   FROM EmployeeSummary ORDER BY HoTen"""
# shortcut: the initial cosine threshold and one face template need calibration before face matches are used as sole payroll evidence.
FACE_MATCH_THRESHOLD = config.FACE_MATCH_THRESHOLD


def admin():
    return session.get("user", {}).get("role") == "QuanTri"


def has_permission(permission):
    return role_can(session.get("user", {}).get("role"), permission)


def system_admin():
    return has_permission("accounts.manage")


def payroll_staff():
    return has_permission("payroll.view")


def is_manager():
    return session.get("user", {}).get("role") == "QuanLy"


def _safe_error(error, message="Không thể xử lý yêu cầu lúc này. Vui lòng thử lại."):
    if isinstance(error, ValueError):
        return str(error)
    app.logger.error(
        "Request failed",
        exc_info=(type(error), error, error.__traceback__),
    )
    return message


def _audit_profile_value(value, field_type):
    if value is None or value == "":
        return ""
    if field_type == "date":
        return str(value)[:10]
    if field_type == "number":
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except (InvalidOperation, ValueError):
            return str(value).strip()
    return str(value).strip()


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
            return jsonify(
                ok=False, error="Phiên làm việc hết hạn. Hãy tải lại trang."
            ), 400
        flash("Phiên làm việc hết hạn hoặc yêu cầu không hợp lệ. Hãy thử lại.", "error")
        return redirect(request.referrer or url_for("login"))
    return None


# ------------------------------------------- Giới hạn đăng nhập sai
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 300
_login_fails = {}  # (ip, tên đăng nhập) -> (số lần sai, thời điểm sai gần nhất)


def _login_locked(key):
    n, ts = _login_fails.get(key, (0, 0))
    if n >= LOGIN_MAX_FAILS and time.time() - ts < LOGIN_LOCK_SECONDS:
        return int(LOGIN_LOCK_SECONDS - (time.time() - ts)) + 1
    if n >= LOGIN_MAX_FAILS:
        _login_fails.pop(key, None)
    return 0


# ----------------------------- OTP lưu phía máy chủ, gắn với nhân viên và quản trị viên
def _otp_hash(code, manv, requester):
    payload = f"{requester}:{manv}:{code}".encode()
    return hmac.new(app.secret_key.encode(), payload, hashlib.sha256).hexdigest()


def _otp_can_send(manv):
    return not db.scalar(
        "SELECT COUNT(*) FROM TaiKhoanOTP WHERE MaNV=? AND SentAt>DATEADD(second,-30,SYSUTCDATETIME())",
        (manv,),
    )


def _otp_put(manv, code, channel):
    requester = session["user"]["user"]
    sent_at = datetime.utcnow()
    db.execute(
        "IF EXISTS(SELECT 1 FROM TaiKhoanOTP WHERE MaNV=?) UPDATE TaiKhoanOTP SET RequestedBy=?,Channel=?,CodeHash=?,SentAt=?,ExpiresAt=?,Attempts=0 WHERE MaNV=? ELSE INSERT INTO TaiKhoanOTP(MaNV,RequestedBy,Channel,CodeHash,SentAt,ExpiresAt,Attempts) VALUES(?,?,?,?,?,?,0)",
        (
            manv,
            requester,
            channel,
            _otp_hash(code, manv, requester),
            sent_at,
            sent_at + timedelta(minutes=5),
            manv,
            manv,
            requester,
            channel,
            _otp_hash(code, manv, requester),
            sent_at,
            sent_at + timedelta(minutes=5),
        ),
    )


def _otp_get(manv):
    rows = db.query(
        "SELECT RequestedBy,Channel,CodeHash,ExpiresAt,Attempts FROM TaiKhoanOTP WHERE MaNV=?",
        (manv,),
    )[1]
    if not rows or rows[0][0] != session["user"]["user"]:
        return None
    row = rows[0]
    return {
        "manv": str(manv),
        "channel": row[1],
        "hash": row[2].strip(),
        "expires": row[3],
        "attempts": row[4],
    }


def _otp_fail(manv):
    db.execute(
        "UPDATE TaiKhoanOTP SET Attempts=Attempts+1 WHERE MaNV=? AND RequestedBy=?",
        (manv, session["user"]["user"]),
    )


def _otp_clear(manv):
    db.execute(
        "DELETE FROM TaiKhoanOTP WHERE MaNV=? AND RequestedBy=?",
        (manv, session["user"]["user"]),
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        key = (request.remote_addr, username.lower())
        wait = _login_locked(key)
        if wait:
            flash(
                f"Đăng nhập sai quá {LOGIN_MAX_FAILS} lần. Vui lòng thử lại sau {wait} giây.",
                "error",
            )
            return render_template("login.html")
        try:
            u = auth.login(username, request.form.get("password", ""))
        except Exception:
            flash(
                "Không kết nối được SQL Server. Kiểm tra config.py và dịch vụ SQL Server.",
                "error",
            )
            return render_template("login.html")
        if u:
            _login_fails.pop(key, None)
            session.clear()  # cấp phiên mới sau khi đăng nhập
            session["user"] = u
            return redirect(url_for("dashboard"))
        n = _login_fails.get(key, (0, 0))[0] + 1
        _login_fails[key] = (n, time.time())
        flash("Tên đăng nhập hoặc mật khẩu không đúng.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/to-chuc")
@login_required
def to_chuc():
    if not has_permission("organization.manage"):
        return redirect(url_for("dashboard"))
    units = db.query("SELECT MaDonVi,TenDonVi,MaDonViCha FROM DonVi WHERE TrangThai=N'Hoạt động' ORDER BY TenDonVi")[1]
    departments = db.query("SELECT MaPB,TenPB,MaDonVi,MaPBCha FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB")[1]
    employees = db.query("SELECT n.MaNV,n.HoTen,n.MaPB,c.TenCV,v.TenViTri FROM NhanVien n LEFT JOIN ChucVu c ON c.MaCV=n.MaCV LEFT JOIN ViTriCongViec v ON v.MaViTri=n.MaViTri WHERE n.TrangThai=N'Đang làm' ORDER BY n.HoTen")[1]
    unit_nodes = {row[0]: {"label": row[1], "kind": "unit", "children": []} for row in units}
    dept_nodes = {row[0]: {"label": row[1], "kind": "department", "children": []} for row in departments}
    roots = []
    for unit_id, _, parent_id in units:
        node = unit_nodes[unit_id]
        if parent_id in unit_nodes:
            unit_nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)
    for dept_id, _, unit_id, parent_id in departments:
        node = dept_nodes[dept_id]
        if parent_id in dept_nodes:
            dept_nodes[parent_id]["children"].append(node)
        elif unit_id in unit_nodes:
            unit_nodes[unit_id]["children"].append(node)
        else:
            roots.append(node)
    for employee_id, name, dept_id, title, position in employees:
        item = {"label": name, "kind": "employee", "detail": " · ".join(x for x in (title, position) if x), "children": []}
        if dept_id in dept_nodes:
            dept_nodes[dept_id]["children"].append(item)
        else:
            roots.append(item)
    return render_template("organization.html", roots=roots, admin=admin())


@app.route("/nhanvien/<int:manv>/lich-su-cong-tac")
@login_required
def lich_su_cong_tac(manv):
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền xem lịch sử nhân sự này.", 403
    employee = db.query("SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE MaNV=?", (manv,))[1]
    if not employee:
        return "Không tìm thấy hồ sơ nhân viên.", 404
    rows = db.query("SELECT l.TuNgay,l.DenNgay,p.TenPB,c.TenCV,v.TenViTri,ql.HoTen,l.LuongCoBan,l.LyDo,l.NguoiCapNhat,l.TaoLuc FROM LichSuCongTac l LEFT JOIN PhongBan p ON p.MaPB=l.MaPB LEFT JOIN ChucVu c ON c.MaCV=l.MaCV LEFT JOIN ViTriCongViec v ON v.MaViTri=l.MaViTri LEFT JOIN NhanVien ql ON ql.MaNV=l.MaQuanLy WHERE l.MaNV=? ORDER BY l.TuNgay DESC,l.MaLichSu DESC", (manv,))[1]
    return render_template("employment_history.html", employee=employee[0], rows=rows, admin=admin())


@app.route("/nhanvien/<int:manv>/nhat-ky-ho-so")
@login_required
def employee_profile_audit(manv):
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền xem nhật ký hồ sơ này.", 403
    employee = db.query("SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE MaNV=?", (manv,))[1]
    if not employee:
        return "Không tìm thấy hồ sơ nhân viên.", 404
    rows = db.query("SELECT TOP 200 HanhDong,TruongDuLieu,NguoiThucHien,TaoLuc FROM NhatKyHoSoNhanVien WHERE MaNV=? ORDER BY MaNhatKy DESC", (manv,))[1]
    return render_template("employee_profile_audit.html", employee=employee[0], rows=rows, admin=admin())


def _employee_record_cipher():
    key = os.environ.get("HR_DOCUMENT_ENCRYPTION_KEY", "")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise RuntimeError("Cần cấu hình HR_DOCUMENT_ENCRYPTION_KEY bằng khóa Fernet để mã hóa hồ sơ tải lên.")


def _can_access_employee_records(manv):
    return admin() or has_permission("employees.view") or int(session.get("user", {}).get("manv") or 0) == int(manv)


def _start_employee_lifecycle(manv, phase, actor, start_date, reason=None, end_date=None):
    if phase not in ("Onboarding", "Offboarding"):
        raise ValueError("Giai đoạn nhân sự không hợp lệ.")
    if db.scalar("SELECT COUNT(*) FROM VongDoiNhanVien WHERE MaNV=? AND GiaiDoan=? AND TrangThai=N'Đang xử lý'", (manv, phase)):
        raise ValueError("Nhân viên đã có quy trình cùng giai đoạn đang xử lý.")
    rows = db.query("SET NOCOUNT ON; SET XACT_ABORT ON; BEGIN TRAN; DECLARE @Created TABLE(MaVongDoi BIGINT); INSERT INTO VongDoiNhanVien(MaNV,GiaiDoan,NgayBatDau,NgayHieuLucKetThuc,LyDo,NguoiTao) OUTPUT INSERTED.MaVongDoi INTO @Created VALUES(?,?,?,?,?,?); DECLARE @MaVongDoi BIGINT=(SELECT TOP 1 MaVongDoi FROM @Created); INSERT INTO ChecklistNhanVien(MaVongDoi,MaNV,TenViec,BoPhanPhuTrach,HanHoanThanh) SELECT @MaVongDoi,?,TenViec,BoPhanPhuTrach,DATEADD(day,SoNgayHan,?) FROM MauChecklistNhanSu WHERE GiaiDoan=? AND TrangThai=1; COMMIT; SELECT @MaVongDoi AS MaVongDoi;", (manv, phase, start_date, end_date, (reason or "")[:500] or None, actor, manv, start_date, phase))[1]
    return rows[0][0]


@app.route("/nhanvien/<int:manv>/tai-lieu", methods=["GET", "POST"])
@login_required
def employee_records(manv):
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền truy cập hồ sơ nhân viên này.", 403
    employee = db.query("SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE MaNV=?", (manv,))[1]
    if not employee:
        return "Không tìm thấy hồ sơ nhân viên.", 404
    if request.method == "POST":
        try:
            uploaded = request.files.get("file")
            category = request.form.get("LoaiTaiLieu", "").strip()
            allowed_categories = {"CCCD", "Bằng cấp", "Chứng chỉ", "Quyết định", "Hồ sơ cá nhân", "Khác"}
            if category not in allowed_categories or not uploaded or not uploaded.filename:
                raise ValueError("Chọn loại tài liệu và tệp cần tải lên.")
            extension = os.path.splitext(secure_filename(uploaded.filename))[1].lower()
            mime_types = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
            if extension not in mime_types:
                raise ValueError("Chỉ nhận PDF, DOCX, JPEG hoặc PNG.")
            raw = uploaded.read(8 * 1024 * 1024 + 1)
            if not raw or len(raw) > 8 * 1024 * 1024:
                raise ValueError("Tài liệu phải có dung lượng từ 1 byte đến 8 MB.")
            signatures = {".pdf": raw.startswith(b"%PDF-"), ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"), ".jpg": raw.startswith(b"\xff\xd8\xff"), ".jpeg": raw.startswith(b"\xff\xd8\xff"), ".docx": raw.startswith(b"PK\x03\x04")}
            if not signatures[extension]:
                raise ValueError("Nội dung tệp không khớp với định dạng phần mở rộng.")
            effective = date.fromisoformat(request.form["NgayHieuLuc"]) if request.form.get("NgayHieuLuc") else None
            retention = date.fromisoformat(request.form["HanLuuDen"]) if has_permission("records.manage") and request.form.get("HanLuuDen") else None
            if retention and effective and retention < effective:
                raise ValueError("Hạn lưu không được trước ngày hiệu lực.")
            filename = secure_filename(uploaded.filename)[:180] or ("tai-lieu" + extension)
            encrypted = _employee_record_cipher().encrypt(raw)
            new_id = db.query("INSERT INTO HoSoTepNhanVien(MaNV,LoaiTaiLieu,TenTep,DinhDang,DuLieu,NgayHieuLuc,HanLuuDen,NguoiTai) OUTPUT INSERTED.MaTep VALUES(?,?,?,?,?,?,?,?)", (manv, category, filename, extension, encrypted, effective, retention, session["user"]["user"]))[1][0][0]
            db.execute("INSERT INTO NhatKyHoSoTep(MaTep,MaNV,ThaoTac,NguoiThucHien) VALUES(?,?,N'upload',?)", (new_id, manv, session["user"]["user"]))
            flash("Đã mã hóa và lưu tài liệu hồ sơ.", "success")
            return redirect(url_for("employee_records", manv=manv))
        except Exception as error:
            flash(_safe_error(error, "Không thể lưu tài liệu. Kiểm tra khóa mã hóa và thông tin tệp."), "error")
    documents = db.query("SELECT MaTep,LoaiTaiLieu,TenTep,DinhDang,NgayHieuLuc,HanLuuDen,NguoiTai,TaoLuc FROM HoSoTepNhanVien WHERE MaNV=? ORDER BY TaoLuc DESC", (manv,))[1]
    db.execute("INSERT INTO NhatKyHoSoTep(MaNV,ThaoTac,NguoiThucHien) VALUES(?,N'view_list',?)", (manv, session["user"]["user"]))
    sensitive_audit.record(manv, "HoSoDienTu", "list", session["user"]["user"])
    return render_template("employee_records.html", employee=employee[0], documents=documents, admin=admin() or has_permission("records.manage"), today=date.today())


@app.route("/nhanvien/tai-lieu/han-luu")
@login_required
def employee_record_retention():
    if not has_permission("records.manage"):
        return "Chỉ quản trị viên được xem danh sách hạn lưu tài liệu.", 403
    today = date.today()
    _, rows = db.query(
        """SELECT TOP 500 t.MaTep,n.MaNV,n.HoTen,t.LoaiTaiLieu,t.TenTep,
                  t.NgayHieuLuc,t.HanLuuDen,t.NguoiTai,t.TaoLuc
           FROM HoSoTepNhanVien t JOIN NhanVien n ON n.MaNV=t.MaNV
           WHERE t.HanLuuDen IS NOT NULL AND t.HanLuuDen<=?
           ORDER BY CASE WHEN t.HanLuuDen<? THEN 0 ELSE 1 END,
                    t.HanLuuDen,n.HoTen,t.MaTep DESC""",
        (today + timedelta(days=90), today),
    )
    sensitive_audit.record_many(
        [row[1] for row in rows], "HoSoDienTu", "list", session["user"]["user"]
    )
    return render_template("employee_record_retention.html", rows=rows, today=today)


@app.route("/nhanvien/tai-lieu/<int:ma_tep>/tai-xuong")
@login_required
def download_employee_record(ma_tep):
    rows = db.query("SELECT MaNV,TenTep,DinhDang,DuLieu FROM HoSoTepNhanVien WHERE MaTep=?", (ma_tep,))[1]
    if not rows:
        return "Không tìm thấy tài liệu.", 404
    manv, filename, extension, encrypted = rows[0]
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền tải tài liệu này.", 403
    try:
        content = _employee_record_cipher().decrypt(bytes(encrypted))
    except (InvalidToken, RuntimeError):
        app.logger.exception("Employee document decryption failed")
        return "Không thể giải mã tài liệu. Hãy liên hệ quản trị viên.", 503
    db.execute("INSERT INTO NhatKyHoSoTep(MaTep,MaNV,ThaoTac,NguoiThucHien) VALUES(?,?,N'download',?)", (ma_tep, manv, session["user"]["user"]))
    sensitive_audit.record(manv, "HoSoDienTu", "download", session["user"]["user"])
    mime_types = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
    return send_file(io.BytesIO(content), mimetype=mime_types.get(extension, "application/octet-stream"), as_attachment=True, download_name=filename)


@app.route("/nhat-ky-truy-cap")
@login_required
def sensitive_access_audit():
    if not has_permission("audit.view"):
        return "Chỉ quản trị viên được xem nhật ký truy cập.", 403
    _, rows = db.query(
        "SELECT TOP 500 a.MaNhatKy,a.MaNV,ISNULL(n.HoTen,N'(Hồ sơ đã xóa)'),a.LoaiDuLieu,a.ThaoTac,a.NguoiThucHien,a.TaoLuc "
        "FROM NhatKyTruyCapNhanSu a LEFT JOIN NhanVien n ON n.MaNV=a.MaNV ORDER BY a.TaoLuc DESC,a.MaNhatKy DESC"
    )
    return render_template("sensitive_access_audit.html", rows=rows)


@app.route("/truong-mo-rong", methods=["GET", "POST"])
@login_required
def employee_custom_fields():
    if not has_permission("profile_fields.manage"):
        return "Chỉ quản trị viên được định nghĩa trường hồ sơ.", 403
    if request.method == "POST":
        try:
            action = request.form.get("action")
            field_id = int(request.form.get("MaTruong") or 0)
            if action == "add":
                name = request.form.get("TenTruong", "").strip()
                kind = request.form.get("KieuDuLieu", "")
                if not name or len(name) > 80 or kind not in ("text", "number", "date", "boolean", "email"):
                    raise ValueError("Tên trường hoặc kiểu dữ liệu không hợp lệ.")
                db.execute("INSERT INTO TruongMoRongNhanVien(TenTruong,KieuDuLieu,BatBuoc,NhayCam,NguoiTao) VALUES(?,?,?,?,?)", (name, kind, bool(request.form.get("BatBuoc")), bool(request.form.get("NhayCam")), session["user"]["user"]))
                flash("Đã tạo trường hồ sơ tùy chỉnh.", "success")
            elif action == "toggle":
                db.execute("UPDATE TruongMoRongNhanVien SET TrangThai=CASE WHEN TrangThai=1 THEN 0 ELSE 1 END WHERE MaTruong=?", (field_id,))
                flash("Đã cập nhật trạng thái trường.", "success")
            elif action == "delete":
                if db.scalar("SELECT COUNT(*) FROM GiaTriMoRongNhanVien WHERE MaTruong=?", (field_id,)):
                    raise ValueError("Trường đã có dữ liệu. Hãy ngừng sử dụng thay vì xóa để giữ hồ sơ.")
                db.execute("DELETE FROM TruongMoRongNhanVien WHERE MaTruong=?", (field_id,))
                flash("Đã xóa trường chưa có dữ liệu.", "success")
            else:
                raise ValueError("Thao tác không hợp lệ.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("employee_custom_fields"))
    fields = db.query("SELECT f.MaTruong,f.TenTruong,f.KieuDuLieu,f.BatBuoc,f.NhayCam,f.TrangThai,f.NguoiTao,f.TaoLuc,(SELECT COUNT(*) FROM GiaTriMoRongNhanVien v WHERE v.MaTruong=f.MaTruong) FROM TruongMoRongNhanVien f ORDER BY f.MaTruong DESC")[1]
    return render_template("custom_fields.html", fields=fields, admin=True)


@app.route("/nhanvien/<int:manv>/truong-mo-rong", methods=["GET", "POST"])
@login_required
def employee_custom_values(manv):
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền sửa hồ sơ nhân viên này.", 403
    employee = db.query("SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE MaNV=?", (manv,))[1]
    if not employee:
        return "Không tìm thấy hồ sơ nhân viên.", 404
    visibility = "" if has_permission("profile_fields.manage") else " AND f.NhayCam=0"
    fields = db.query("SELECT f.MaTruong,f.TenTruong,f.KieuDuLieu,f.BatBuoc,f.NhayCam,ISNULL(v.GiaTri,N'') FROM TruongMoRongNhanVien f LEFT JOIN GiaTriMoRongNhanVien v ON v.MaTruong=f.MaTruong AND v.MaNV=? WHERE f.TrangThai=1" + visibility + " ORDER BY f.MaTruong", (manv,))[1]
    if request.method == "POST":
        try:
            updates = []
            for field_id, name, kind, required, sensitive, old_value in fields:
                value = request.form.get(f"field_{field_id}", "").strip()
                if kind == "boolean" and value not in ("0", "1", ""):
                    raise ValueError(f"Giá trị {name} không hợp lệ.")
                if required and not value:
                    raise ValueError(f"Vui lòng nhập {name}.")
                if len(value) > 1000:
                    raise ValueError(f"{name} vượt quá 1000 ký tự.")
                if value and kind == "number":
                    try:
                        number = float(value)
                    except ValueError:
                        raise ValueError(f"{name} phải là số.")
                    if not math.isfinite(number):
                        raise ValueError(f"{name} phải là số hữu hạn.")
                if value and kind == "date":
                    try:
                        date.fromisoformat(value)
                    except ValueError:
                        raise ValueError(f"{name} phải là ngày hợp lệ.")
                if value and kind == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
                    raise ValueError(f"{name} phải là địa chỉ email hợp lệ.")
                stored_value = (value or "0") if kind == "boolean" else value
                if stored_value != (old_value or ""):
                    updates.append((field_id, stored_value))
            if updates:
                statements, params = ["SET XACT_ABORT ON; BEGIN TRAN;"], []
                for field_id, value in updates:
                    statements.append("IF EXISTS(SELECT 1 FROM GiaTriMoRongNhanVien WHERE MaNV=? AND MaTruong=?) UPDATE GiaTriMoRongNhanVien SET GiaTri=?,CapNhatBoi=?,CapNhatLuc=SYSUTCDATETIME() WHERE MaNV=? AND MaTruong=? ELSE INSERT INTO GiaTriMoRongNhanVien(MaNV,MaTruong,GiaTri,CapNhatBoi) VALUES(?,?,?,?);")
                    params.extend([manv, field_id, value, session["user"]["user"], manv, field_id, manv, field_id, value, session["user"]["user"]])
                    statements.append("INSERT INTO NhatKyTruongNhanVien(MaNV,MaTruong,NguoiThucHien) VALUES(?,?,?);")
                    params.extend([manv, field_id, session["user"]["user"]])
                statements.append("COMMIT;")
                db.execute(" ".join(statements), params)
            flash("Đã lưu thông tin mở rộng.", "success")
            return redirect(url_for("employee_custom_values", manv=manv))
        except Exception as error:
            flash(_safe_error(error), "error")
    return render_template("custom_values.html", employee=employee[0], fields=fields, admin=admin())


@app.route("/lich-ca", methods=["GET", "POST"])
@login_required
def workforce_shifts():
    if request.method == "POST":
        actor = session["user"]["user"]
        try:
            action = request.form.get("action")
            if action == "swap_request":
                own_id = int(session.get("user", {}).get("manv") or 0)
                assignment_a, assignment_b = int(request.form["CaCuaToi"]), int(request.form["CaDoi"])
                rows = db.query("SELECT p.MaPhanCa,p.MaNV,p.Ngay,p.MaCa,COALESCE(p.GioBatDauOverride,c.GioBatDau),COALESCE(p.GioKetThucOverride,c.GioKetThuc),c.QuaDem,n.MaPB FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa JOIN NhanVien n ON n.MaNV=p.MaNV WHERE p.MaPhanCa IN (?,?)", (assignment_a, assignment_b))[1]
                by_id = {int(row[0]): row for row in rows}
                first, second = by_id.get(assignment_a), by_id.get(assignment_b)
                if not own_id or not first or not second or first[1] == second[1] or first[2] != second[2] or first[2] < date.today():
                    raise ValueError("Chỉ yêu cầu đổi hai ca sắp tới trong cùng ngày.")
                if own_id not in (first[1], second[1]) or first[7] != second[7]:
                    raise ValueError("Bạn chỉ có thể đổi ca với nhân viên cùng phòng ban.")
                if db.scalar("SELECT COUNT(*) FROM YeuCauDoiCa WHERE TrangThai IN (N'Chờ xác nhận',N'Chờ duyệt') AND (MaPhanCaA IN (?,?) OR MaPhanCaB IN (?,?))", (assignment_a, assignment_b, assignment_a, assignment_b)):
                    raise ValueError("Một trong hai ca đã có yêu cầu đổi đang xử lý.")
                swap_id = db.query("INSERT INTO YeuCauDoiCa(MaPhanCaA,MaPhanCaB,MaNVCau) OUTPUT INSERTED.MaYeuCau VALUES(?,?,?)", (assignment_a, assignment_b, own_id))[1][0][0]
                db.execute("INSERT INTO NhatKyDoiCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'submit',NULL,N'Chờ xác nhận',?,?)", (swap_id, actor, request.form.get("LyDo", "").strip()[:500] or None))
                flash("Đã gửi đề nghị đổi ca cho đồng nghiệp xác nhận.", "success")
            elif action in ("swap_accept", "swap_reject"):
                swap_id = int(request.form["MaYeuCau"])
                own_id = int(session.get("user", {}).get("manv") or 0)
                swap = db.query("SELECT s.MaPhanCaA,s.MaPhanCaB,s.TrangThai,s.MaNVCau,a.MaNV,b.MaNV FROM YeuCauDoiCa s JOIN PhanCaNhanVien a ON a.MaPhanCa=s.MaPhanCaA JOIN PhanCaNhanVien b ON b.MaPhanCa=s.MaPhanCaB WHERE s.MaYeuCau=?", (swap_id,))[1]
                if not swap or swap[0][2] != "Chờ xác nhận" or own_id not in (swap[0][4], swap[0][5]) or own_id == swap[0][3]:
                    raise ValueError("Yêu cầu đổi ca không còn chờ bạn xác nhận.")
                status = "Chờ duyệt" if action == "swap_accept" else "Từ chối"
                reason = request.form.get("LyDo", "").strip()[:500]
                if action == "swap_reject" and not reason:
                    raise ValueError("Hãy ghi lý do từ chối đổi ca.")
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE YeuCauDoiCa SET TrangThai=?,XacNhanBoi=?,XacNhanLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Chờ xác nhận'; IF @@ROWCOUNT<>1 THROW 51030,'Swap request has already changed.',1; INSERT INTO NhatKyDoiCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,?,?,?,?,?); COMMIT;", (status, actor, reason or None, swap_id, swap_id, action, "Chờ xác nhận", status, actor, reason or None))
                flash("Đã xác nhận đề nghị đổi ca." if status == "Chờ duyệt" else "Đã từ chối đề nghị đổi ca.", "success")
            elif action in ("swap_approve", "swap_admin_reject") and admin():
                swap_id = int(request.form["MaYeuCau"])
                swap = db.query("SELECT s.MaPhanCaA,s.MaPhanCaB,s.TrangThai,a.MaNV,a.Ngay,a.MaCa,COALESCE(a.GioBatDauOverride,ca.GioBatDau),COALESCE(a.GioKetThucOverride,ca.GioKetThuc),CASE WHEN a.GioBatDauOverride IS NOT NULL OR a.GioKetThucOverride IS NOT NULL THEN CASE WHEN COALESCE(a.GioKetThucOverride,ca.GioKetThuc)<COALESCE(a.GioBatDauOverride,ca.GioBatDau) THEN 1 ELSE 0 END ELSE ca.QuaDem END,b.MaNV,b.MaCa,COALESCE(b.GioBatDauOverride,cb.GioBatDau),COALESCE(b.GioKetThucOverride,cb.GioKetThuc),CASE WHEN b.GioBatDauOverride IS NOT NULL OR b.GioKetThucOverride IS NOT NULL THEN CASE WHEN COALESCE(b.GioKetThucOverride,cb.GioKetThuc)<COALESCE(b.GioBatDauOverride,cb.GioBatDau) THEN 1 ELSE 0 END ELSE cb.QuaDem END FROM YeuCauDoiCa s JOIN PhanCaNhanVien a ON a.MaPhanCa=s.MaPhanCaA JOIN CaLamViec ca ON ca.MaCa=a.MaCa JOIN PhanCaNhanVien b ON b.MaPhanCa=s.MaPhanCaB JOIN CaLamViec cb ON cb.MaCa=b.MaCa WHERE s.MaYeuCau=? AND s.TrangThai=N'Chờ duyệt'", (swap_id,))[1]
                if not swap or swap[0][4] < date.today():
                    raise ValueError("Yêu cầu không còn hợp lệ hoặc ca đã qua ngày làm.")
                row = swap[0]
                reason = request.form.get("LyDo", "").strip()[:500]
                if action == "swap_admin_reject" and not reason:
                    raise ValueError("Hãy ghi lý do từ chối đổi ca.")
                if action == "swap_approve":
                    _validate_employee_shift_assignment(row[3], row[4], row[11], row[12], bool(row[13]), (row[0], row[1]))
                    _validate_employee_shift_assignment(row[9], row[4], row[6], row[7], bool(row[8]), (row[0], row[1]))
                    db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE PhanCaNhanVien SET MaCa=CASE WHEN MaPhanCa=? THEN ? ELSE ? END,GioBatDauOverride=CASE WHEN MaPhanCa=? THEN ? ELSE ? END,GioKetThucOverride=CASE WHEN MaPhanCa=? THEN ? ELSE ? END WHERE MaPhanCa IN (?,?) AND ((MaPhanCa=? AND MaNV=?) OR (MaPhanCa=? AND MaNV=?)); IF @@ROWCOUNT<>2 THROW 51031,'Shift assignments changed after approval.',1; UPDATE YeuCauDoiCa SET TrangThai=N'Đã đổi',NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Chờ duyệt'; IF @@ROWCOUNT<>1 THROW 51032,'Swap request has already changed.',1; INSERT INTO NhatKyDoiCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'approve',N'Chờ duyệt',N'Đã đổi',?,?); COMMIT;", (row[0], row[10], row[5], row[0], row[11], row[6], row[0], row[12], row[7], row[0], row[1], row[0], row[3], row[1], row[9], actor, reason or "Quản trị viên duyệt đổi ca", swap_id, swap_id, actor, reason or None))
                else:
                    db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE YeuCauDoiCa SET TrangThai=N'Từ chối',NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Chờ duyệt'; IF @@ROWCOUNT<>1 THROW 51032,'Swap request has already changed.',1; INSERT INTO NhatKyDoiCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'reject',N'Chờ duyệt',N'Từ chối',?,?); COMMIT;", (actor, reason, swap_id, swap_id, actor, reason))
                flash("Đã xử lý yêu cầu đổi ca.", "success")
            elif action in ("shift", "toggle_shift", "assign", "assign_group", "holiday") and admin():
                if action == "shift":
                    name = request.form.get("TenCa", "").strip()
                    start = datetime.strptime(request.form.get("GioBatDau", ""), "%H:%M").time()
                    end = datetime.strptime(request.form.get("GioKetThuc", ""), "%H:%M").time()
                    overnight, grace = bool(request.form.get("QuaDem")), int(request.form.get("PhutAnHan") or 0)
                    if not name or len(name) > 80 or start == end or (end < start) != overnight or grace not in range(241):
                        raise ValueError("Tên ca, giờ qua đêm hoặc số phút ân hạn không hợp lệ.")
                    db.execute("INSERT INTO CaLamViec(TenCa,GioBatDau,GioKetThuc,QuaDem,PhutAnHan) VALUES(?,?,?,?,?)", (name, start, end, overnight, grace))
                    flash("Đã thêm ca làm việc.", "success")
                elif action == "toggle_shift":
                    db.execute("UPDATE CaLamViec SET TrangThai=CASE WHEN TrangThai=1 THEN 0 ELSE 1 END WHERE MaCa=?", (int(request.form["MaCa"]),))
                    flash("Đã cập nhật trạng thái ca.", "success")
                elif action in ("assign", "assign_group"):
                    shift_id, work_date = int(request.form["MaCa"]), date.fromisoformat(request.form["Ngay"])
                    shift = db.query("SELECT GioBatDau,GioKetThuc FROM CaLamViec WHERE MaCa=? AND TrangThai=1", (shift_id,))[1]
                    if not shift:
                        raise ValueError("Ca không tồn tại hoặc đã ngừng hoạt động.")
                    start = _parse_optional_shift_time(request.form.get("GioBatDau")) or shift[0][0]
                    end = _parse_optional_shift_time(request.form.get("GioKetThuc")) or shift[0][1]
                    overnight = end < start
                    if action == "assign":
                        employee_ids = [int(request.form["MaNV"])]
                    else:
                        department_id = int(request.form["MaPB"])
                        employee_ids = [row[0] for row in db.query("SELECT MaNV FROM NhanVien WHERE MaPB=? AND TrangThai=N'Đang làm'", (department_id,))[1]]
                        if not employee_ids:
                            raise ValueError("Phòng ban chưa có nhân viên đang làm.")
                    for employee_id in employee_ids:
                        if not db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'", (employee_id,)):
                            raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
                        _validate_employee_shift_assignment(employee_id, work_date, start, end, overnight)
                    db.execute_batches([("INSERT INTO PhanCaNhanVien(MaNV,MaCa,Ngay,NguoiPhan,GioBatDauOverride,GioKetThucOverride) VALUES(?,?,?,?,?,?)", [(employee_id, shift_id, work_date, actor, start, end) for employee_id in employee_ids])])
                    flash(f"Đã phân ca cho {len(employee_ids)} nhân viên.", "success")
                else:
                    holiday = date.fromisoformat(request.form.get("Ngay", ""))
                    name = request.form.get("TenNgay", "").strip()
                    if not name or len(name) > 120:
                        raise ValueError("Tên ngày lễ bắt buộc, tối đa 120 ký tự.")
                    db.execute("INSERT INTO LichNgayLe(Ngay,TenNgay,HuongLuong,NguoiTao) VALUES(?,?,?,?)", (holiday, name, bool(request.form.get("HuongLuong")), actor))
                    flash("Đã thêm ngày lễ vào lịch.", "success")
            else:
                raise ValueError("Thao tác lịch ca không hợp lệ hoặc không đủ quyền.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("workforce_shifts"))

    own_id = int(session.get("user", {}).get("manv") or 0)
    assignment_sql = "SELECT p.MaPhanCa,n.HoTen,c.TenCa,p.Ngay,COALESCE(p.GioBatDauOverride,c.GioBatDau),COALESCE(p.GioKetThucOverride,c.GioKetThuc),CASE WHEN p.GioBatDauOverride IS NOT NULL OR p.GioKetThucOverride IS NOT NULL THEN CASE WHEN COALESCE(p.GioKetThucOverride,c.GioKetThuc)<COALESCE(p.GioBatDauOverride,c.GioBatDau) THEN 1 ELSE 0 END ELSE c.QuaDem END,p.NguoiPhan,p.MaNV,p.MaCa FROM PhanCaNhanVien p JOIN NhanVien n ON n.MaNV=p.MaNV JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.Ngay>=DATEADD(day,-1,CAST(GETDATE() AS DATE))"
    if admin():
        shifts = db.query("SELECT MaCa,TenCa,GioBatDau,GioKetThuc,QuaDem,PhutAnHan,TrangThai FROM CaLamViec ORDER BY TenCa")[1]
        people = db.query("SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
        assignments = db.query(assignment_sql + " ORDER BY p.Ngay DESC,n.HoTen")[1]
        departments = db.query("SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB")[1]
        swap_requests = db.query("SELECT s.MaYeuCau,a.Ngay,na.HoTen,ca.TenCa,nb.HoTen,cb.TenCa,s.TrangThai,s.PhanHoi,s.MaNVCau,b.MaNV FROM YeuCauDoiCa s JOIN PhanCaNhanVien a ON a.MaPhanCa=s.MaPhanCaA JOIN NhanVien na ON na.MaNV=a.MaNV JOIN CaLamViec ca ON ca.MaCa=a.MaCa JOIN PhanCaNhanVien b ON b.MaPhanCa=s.MaPhanCaB JOIN NhanVien nb ON nb.MaNV=b.MaNV JOIN CaLamViec cb ON cb.MaCa=b.MaCa WHERE s.TrangThai=N'Chờ duyệt' ORDER BY s.TaoLuc DESC", ())[1]
        swap_mine, swap_targets = [], []
    else:
        shifts, people, departments = [], [], []
        assignments = db.query(assignment_sql + " AND p.MaNV=? ORDER BY p.Ngay DESC", (own_id,))[1]
        swap_mine = [row for row in assignments if row[3] >= date.today()]
        swap_targets = db.query(assignment_sql + " AND p.MaNV<>? AND n.MaPB=(SELECT MaPB FROM NhanVien WHERE MaNV=?) ORDER BY p.Ngay,n.HoTen", (own_id, own_id))[1]
        swap_requests = db.query("SELECT s.MaYeuCau,a.Ngay,na.HoTen,ca.TenCa,nb.HoTen,cb.TenCa,s.TrangThai,s.PhanHoi,s.MaNVCau,CASE WHEN s.MaNVCau=a.MaNV THEN b.MaNV ELSE a.MaNV END AS MaNVXacNhan FROM YeuCauDoiCa s JOIN PhanCaNhanVien a ON a.MaPhanCa=s.MaPhanCaA JOIN NhanVien na ON na.MaNV=a.MaNV JOIN CaLamViec ca ON ca.MaCa=a.MaCa JOIN PhanCaNhanVien b ON b.MaPhanCa=s.MaPhanCaB JOIN NhanVien nb ON nb.MaNV=b.MaNV JOIN CaLamViec cb ON cb.MaCa=b.MaCa WHERE (s.MaNVCau=? OR a.MaNV=? OR b.MaNV=?) AND s.TrangThai IN (N'Chờ xác nhận',N'Chờ duyệt') ORDER BY s.TaoLuc DESC", (own_id, own_id, own_id))[1]
    holidays = db.query("SELECT Ngay,TenNgay,HuongLuong FROM LichNgayLe WHERE Ngay>=DATEADD(day,-30,CAST(GETDATE() AS DATE)) ORDER BY Ngay")[1]
    return render_template("workforce_shifts.html", shifts=shifts, people=people, assignments=assignments, holidays=holidays, departments=departments, swap_requests=swap_requests, swap_mine=swap_mine, swap_targets=swap_targets, own_id=own_id, admin=admin(), today=date.today().isoformat())


def _parse_optional_shift_time(value):
    value = (value or "").strip()
    return datetime.strptime(value, "%H:%M").time() if value else None


def _validate_employee_shift_assignment(employee_id, work_date, start, end, overnight, exclude_ids=()):
    if start == end or (end < start) != bool(overnight):
        raise ValueError("Giờ bắt đầu/kết thúc của ca không hợp lệ.")
    rows = db.query("SELECT p.MaPhanCa,p.Ngay,COALESCE(p.GioBatDauOverride,c.GioBatDau),COALESCE(p.GioKetThucOverride,c.GioKetThuc),CASE WHEN p.GioBatDauOverride IS NOT NULL OR p.GioKetThucOverride IS NOT NULL THEN CASE WHEN COALESCE(p.GioKetThucOverride,c.GioKetThuc)<COALESCE(p.GioBatDauOverride,c.GioBatDau) THEN 1 ELSE 0 END ELSE c.QuaDem END FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.MaNV=? AND p.Ngay BETWEEN DATEADD(day,-1,?) AND DATEADD(day,1,?)", (employee_id, work_date, work_date))[1]
    start_min = start.hour * 60 + start.minute
    end_min = end.hour * 60 + end.minute + (1440 if overnight else 0)
    excluded = {int(value) for value in exclude_ids}
    for assignment_id, old_day, old_start, old_end, old_overnight in rows:
        if int(assignment_id) in excluded:
            continue
        offset = (old_day - work_date).days * 1440
        old_start_min = offset + old_start.hour * 60 + old_start.minute
        old_end_min = offset + old_end.hour * 60 + old_end.minute + (1440 if old_overnight else 0)
        if max(start_min, old_start_min) < min(end_min, old_end_min):
            raise ValueError("Ca bị trùng giờ với một ca đã phân cho nhân viên.")

@app.route("/tang-ca", methods=["GET", "POST"])
@login_required
def overtime_requests():
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            if action == "request":
                employee_id = int(request.form["MaNV"]) if admin() else int(session["user"].get("manv") or 0)
                start = datetime.fromisoformat(request.form.get("BatDau", ""))
                end = datetime.fromisoformat(request.form.get("KetThuc", ""))
                reason = request.form.get("LyDo", "").strip()
                hours = (end - start).total_seconds() / 3600
                if not employee_id or hours <= 0 or hours > 24 or not reason or len(reason) > 500:
                    raise ValueError("Khoảng tăng ca hoặc lý do không hợp lệ; tối đa 24 giờ mỗi yêu cầu.")
                if not db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'", (employee_id,)):
                    raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
                if db.scalar("SELECT COUNT(*) FROM TangCaYeuCau WHERE MaNV=? AND TrangThai IN (N'Chờ duyệt',N'Đã duyệt',N'Đã xác nhận') AND BatDau<? AND KetThuc>?", (employee_id, end, start)):
                    raise ValueError("Thời gian trùng với một yêu cầu tăng ca đang chờ hoặc đã duyệt.")
                overtime_id = db.query("INSERT INTO TangCaYeuCau(MaNV,BatDau,KetThuc,SoGio,LyDo) OUTPUT INSERTED.MaYeuCau VALUES(?,?,?,?,?)", (employee_id, start, end, round(hours, 2), reason))[1][0][0]
                db.execute("INSERT INTO NhatKyTangCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'submit',NULL,N'Chờ duyệt',?,?)", (overtime_id, actor, reason))
                flash("Đã gửi yêu cầu tăng ca để quản trị viên phê duyệt.", "success")
            elif action in ("approve", "reject") and admin():
                overtime_id = int(request.form["MaYeuCau"])
                response = request.form.get("PhanHoi", "").strip()[:500]
                status = "Đã duyệt" if action == "approve" else "Từ chối"
                if action == "reject" and not response:
                    raise ValueError("Hãy nhập lý do từ chối yêu cầu tăng ca.")
                current = db.query("SELECT TrangThai FROM TangCaYeuCau WHERE MaYeuCau=?", (overtime_id,))[1]
                if not current or current[0][0] != "Chờ duyệt":
                    raise ValueError("Yêu cầu không còn ở trạng thái chờ duyệt.")
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE TangCaYeuCau SET TrangThai=?,NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Chờ duyệt'; IF @@ROWCOUNT<>1 THROW 50011,'Yêu cầu đã được xử lý.',1; INSERT INTO NhatKyTangCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,?,N'Chờ duyệt',?,?,?); COMMIT;", (status, actor, response or None, overtime_id, action, status, actor, response or None))
                flash("Đã cập nhật kết quả yêu cầu tăng ca.", "success")
            elif action == "confirm" and admin():
                overtime_id = int(request.form["MaYeuCau"])
                request_row = db.query("SELECT MaNV,BatDau,KetThuc,SoGio,TrangThai FROM TangCaYeuCau WHERE MaYeuCau=?", (overtime_id,))[1]
                if not request_row or request_row[0][4] != "Đã duyệt" or request_row[0][2] > datetime.now():
                    raise ValueError("Chỉ xác nhận tăng ca đã duyệt sau khi thời gian làm việc kết thúc.")
                employee_id, interval_start, interval_end, approved_hours, _ = request_row[0]
                observed_hours = _observed_overtime_hours(employee_id, interval_start, interval_end)
                requested_hours = request.form.get("SoGioThucTe", "").strip()
                actual_hours = float(requested_hours) if requested_hours else observed_hours
                reason = request.form.get("PhanHoi", "").strip()[:500]
                if not math.isfinite(actual_hours) or actual_hours < 0 or actual_hours > float(approved_hours):
                    raise ValueError("Giờ thực tế phải nằm trong khoảng 0 đến số giờ đã duyệt.")
                if not observed_hours and not reason:
                    raise ValueError("Không có cặp sự kiện vào/ra trong giờ tăng ca; cần lý do xác nhận ngoại lệ.")
                if abs(actual_hours-observed_hours) >= 0.01 and not reason:
                    raise ValueError("Giờ xác nhận khác giờ đối soát sự kiện; hãy ghi lý do.")
                detail = reason or f"Đối soát sự kiện: {observed_hours:g} giờ; xác nhận: {actual_hours:g} giờ."
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE TangCaYeuCau SET TrangThai=N'Đã xác nhận',SoGioThucTe=?,XacNhanBoi=?,XacNhanLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Đã duyệt'; IF @@ROWCOUNT<>1 THROW 50012,'Yêu cầu tăng ca đã thay đổi.',1; INSERT INTO NhatKyTangCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'confirm',N'Đã duyệt',N'Đã xác nhận',?,?); COMMIT;", (actual_hours, actor, detail, overtime_id, overtime_id, actor, detail))
                flash("Đã xác nhận giờ tăng ca sau khi đối soát sự kiện chấm công.", "success")
            else:
                raise ValueError("Thao tác tăng ca không hợp lệ hoặc không đủ quyền.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("overtime_requests"))
    if admin():
        rows = db.query("SELECT t.MaYeuCau,n.HoTen,t.BatDau,t.KetThuc,t.SoGio,t.SoGioThucTe,t.LyDo,t.TrangThai,t.NguoiDuyet,t.PhanHoi,t.MaNV FROM TangCaYeuCau t JOIN NhanVien n ON n.MaNV=t.MaNV ORDER BY CASE WHEN t.TrangThai=N'Chờ duyệt' THEN 0 WHEN t.TrangThai=N'Đã duyệt' THEN 1 ELSE 2 END,t.BatDau DESC")[1]
        people = db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
    else:
        manv = session["user"].get("manv") or -1
        rows = db.query("SELECT t.MaYeuCau,n.HoTen,t.BatDau,t.KetThuc,t.SoGio,t.SoGioThucTe,t.LyDo,t.TrangThai,t.NguoiDuyet,t.PhanHoi,t.MaNV FROM TangCaYeuCau t JOIN NhanVien n ON n.MaNV=t.MaNV WHERE t.MaNV=? ORDER BY t.BatDau DESC", (manv,))[1]
        people = []
    rows = [tuple(row) + (_observed_overtime_hours(row[10], row[2], row[3]),) for row in rows]
    return render_template("overtime.html", rows=rows, people=people, admin=admin(), own_id=session["user"].get("manv"), now=datetime.now())


@app.route("/tuyen-dung", methods=["GET", "POST"])
@login_required
def recruiting():
    if not has_permission("recruitment.view"):
        return "Chỉ quản trị viên được truy cập dữ liệu tuyển dụng.", 403
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            if action == "request":
                title = request.form.get("TieuDe", "").strip()
                count = int(request.form.get("SoLuong") or 0)
                if not title or len(title) > 120 or count not in range(1, 501):
                    raise ValueError("Tên vị trí hoặc số lượng cần tuyển không hợp lệ.")
                department = request.form.get("MaPB") or None
                job_title = request.form.get("MaCV") or None
                job_position = request.form.get("MaViTri") or None
                db.execute("INSERT INTO YeuCauTuyenDung(TieuDe,MaPB,MaCV,MaViTri,SoLuong,MoTa,NguoiTao) VALUES(?,?,?,?,?,?,?)", (title, department, job_title, job_position, count, request.form.get("MoTa", "").strip()[:2000] or None, actor))
                flash("Đã tạo yêu cầu tuyển dụng.", "success")
            elif action == "close_request":
                db.execute("UPDATE YeuCauTuyenDung SET TrangThai=N'Đã đóng' WHERE MaYeuCau=? AND TrangThai=N'Đang tuyển'", (int(request.form["MaYeuCau"]),))
                flash("Đã đóng yêu cầu tuyển dụng.", "success")
            elif action == "candidate":
                request_id = int(request.form["MaYeuCau"])
                name = request.form.get("HoTen", "").strip()
                email = request.form.get("Email", "").strip().lower() or None
                phone = request.form.get("SDT", "").strip() or None
                if not name or len(name) > 100 or not db.scalar("SELECT COUNT(*) FROM YeuCauTuyenDung WHERE MaYeuCau=? AND TrangThai=N'Đang tuyển'", (request_id,)):
                    raise ValueError("Yêu cầu tuyển dụng không mở hoặc họ tên ứng viên không hợp lệ.")
                if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                    raise ValueError("Email ứng viên không hợp lệ.")
                db.execute("INSERT INTO UngVien(MaYeuCau,HoTen,Email,SDT,KenhNguon,NguoiTao) VALUES(?,?,?,?,?,?)", (request_id, name, email, phone, request.form.get("KenhNguon", "").strip()[:80] or None, actor))
                flash("Đã thêm ứng viên vào pipeline.", "success")
            elif action == "stage":
                candidate_id = int(request.form["MaUngVien"])
                stage = request.form.get("TrangThai", "")
                if stage not in ("Mới", "Sàng lọc", "Phỏng vấn", "Offer", "Từ chối"):
                    raise ValueError("Trạng thái pipeline không hợp lệ.")
                if stage == "Offer" and not db.scalar("SELECT COUNT(*) FROM OfferUngVien WHERE MaUngVien=?", (candidate_id,)):
                    raise ValueError("Cần tạo offer trước khi chuyển ứng viên sang bước Offer.")
                db.execute("UPDATE UngVien SET TrangThai=? WHERE MaUngVien=? AND MaNV IS NULL", (stage, candidate_id))
                flash("Đã cập nhật pipeline ứng viên.", "success")
            elif action == "interview":
                candidate_id = int(request.form["MaUngVien"])
                when = datetime.fromisoformat(request.form.get("ThoiDiem", ""))
                mode = request.form.get("HinhThuc", "").strip()
                interviewer = request.form.get("NguoiPhongVan", "").strip()
                if not db.scalar("SELECT COUNT(*) FROM UngVien WHERE MaUngVien=? AND MaNV IS NULL", (candidate_id,)) or mode not in ("Trực tiếp", "Trực tuyến", "Điện thoại") or not interviewer or len(interviewer) > 100:
                    raise ValueError("Ứng viên, hình thức hoặc người phỏng vấn không hợp lệ.")
                db.execute("INSERT INTO PhongVanUngVien(MaUngVien,ThoiDiem,HinhThuc,NguoiPhongVan,NguoiTao) VALUES(?,?,?,?,?)", (candidate_id, when, mode, interviewer, actor))
                db.execute("UPDATE UngVien SET TrangThai=N'Phỏng vấn' WHERE MaUngVien=? AND TrangThai NOT IN (N'Từ chối',N'Nhận việc')", (candidate_id,))
                flash("Đã lên lịch phỏng vấn.", "success")
            elif action == "evaluate":
                interview_id = int(request.form["MaPhongVan"])
                score = int(request.form.get("Diem") or 0)
                review = request.form.get("NhanXet", "").strip()
                if score not in range(1, 6) or not review or len(review) > 2000:
                    raise ValueError("Điểm đánh giá từ 1 đến 5 và nhận xét là bắt buộc.")
                db.execute("INSERT INTO DanhGiaUngVien(MaPhongVan,Diem,NhanXet,NguoiDanhGia) VALUES(?,?,?,?)", (interview_id, score, review, actor))
                flash("Đã lưu đánh giá phỏng vấn.", "success")
            elif action == "offer":
                candidate_id = int(request.form["MaUngVien"])
                salary = float(request.form.get("LuongDeXuat") or -1)
                start = date.fromisoformat(request.form.get("NgayBatDau", ""))
                expires = date.fromisoformat(request.form["HanPhanHoi"]) if request.form.get("HanPhanHoi") else None
                if not math.isfinite(salary) or salary < 0 or not db.scalar("SELECT COUNT(*) FROM UngVien WHERE MaUngVien=? AND MaNV IS NULL AND TrangThai<>N'Từ chối'", (candidate_id,)) or (expires and expires < date.today()):
                    raise ValueError("Ứng viên hoặc thông tin offer không hợp lệ.")
                db.execute("INSERT INTO OfferUngVien(MaUngVien,LuongDeXuat,NgayBatDau,HanPhanHoi,NguoiTao) VALUES(?,?,?,?,?)", (candidate_id, salary, start, expires, actor))
                db.execute("UPDATE UngVien SET TrangThai=N'Offer' WHERE MaUngVien=?", (candidate_id,))
                flash("Đã lập bản nháp offer; cần đánh dấu gửi sau khi HR phê duyệt.", "success")
            elif action == "send_offer":
                offer_id = int(request.form["MaOffer"])
                db.execute("UPDATE OfferUngVien SET TrangThai=N'Đã gửi' WHERE MaOffer=? AND TrangThai=N'Bản nháp'", (offer_id,))
                flash("Đã ghi nhận offer được gửi cho ứng viên.", "success")
            elif action == "accept_offer":
                offer_id = int(request.form["MaOffer"])
                offer = db.query("SELECT o.MaUngVien,o.LuongDeXuat,o.NgayBatDau,o.HanPhanHoi,c.HoTen,c.Email,c.SDT,r.MaPB,r.MaCV,r.MaViTri FROM OfferUngVien o JOIN UngVien c ON c.MaUngVien=o.MaUngVien JOIN YeuCauTuyenDung r ON r.MaYeuCau=c.MaYeuCau WHERE o.MaOffer=? AND o.TrangThai=N'Đã gửi' AND c.MaNV IS NULL", (offer_id,))[1]
                if not offer:
                    raise ValueError("Offer không còn chờ phản hồi hoặc ứng viên đã được liên kết nhân viên.")
                candidate_id, salary, start, expiry, name, email, phone, department, job_title, position = offer[0]
                if expiry and expiry < date.today():
                    raise ValueError("Offer đã quá hạn phản hồi.")
                values = {"HoTen": name, "Email": email, "SDT": phone, "NgayVaoLam": start, "MaPB": department, "MaCV": job_title, "MaViTri": position, "LuongCoBan": salary, "TrangThai": "Đang làm"}
                employee_id = employee_profiles.create_employee("recruitment", str(candidate_id), values, actor)
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE OfferUngVien SET TrangThai=N'Đã nhận',MaNV=? WHERE MaOffer=? AND TrangThai=N'Đã gửi'; UPDATE UngVien SET TrangThai=N'Nhận việc',MaNV=? WHERE MaUngVien=? AND MaNV IS NULL; IF @@ROWCOUNT<>1 THROW 50021,'Ứng viên đã được liên kết.',1; IF NOT EXISTS(SELECT 1 FROM LichSuCongTac WHERE MaNV=? AND DenNgay IS NULL) INSERT INTO LichSuCongTac(MaNV,TuNgay,MaPB,MaCV,MaViTri,LuongCoBan,NguoiCapNhat,LyDo) VALUES(?,?,?,?,?,?,?,N'Tạo hồ sơ từ offer tuyển dụng'); COMMIT;", (employee_id, offer_id, employee_id, candidate_id, employee_id, start, department, job_title, position, salary, actor))
                db.execute("INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'tao',N'*',?)", (employee_id, actor))
                if not db.scalar("SELECT COUNT(*) FROM VongDoiNhanVien WHERE MaNV=? AND GiaiDoan=N'Onboarding' AND TrangThai=N'Đang xử lý'", (employee_id,)):
                    _start_employee_lifecycle(employee_id, "Onboarding", actor, start, "Nhận việc từ offer tuyển dụng")
                assign_codes()
                flash(f"Đã chấp nhận offer và liên kết ứng viên với mã nhân viên {employee_id}.", "success")
            else:
                raise ValueError("Thao tác tuyển dụng không hợp lệ.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("recruiting"))
    requests = db.query("SELECT r.MaYeuCau,r.TieuDe,p.TenPB,c.TenCV,v.TenViTri,r.SoLuong,r.TrangThai,r.MoTa FROM YeuCauTuyenDung r LEFT JOIN PhongBan p ON p.MaPB=r.MaPB LEFT JOIN ChucVu c ON c.MaCV=r.MaCV LEFT JOIN ViTriCongViec v ON v.MaViTri=r.MaViTri ORDER BY r.TaoLuc DESC")[1]
    candidates = db.query("SELECT c.MaUngVien,r.TieuDe,c.HoTen,c.Email,c.SDT,c.KenhNguon,c.TrangThai,c.MaNV,c.MaYeuCau,o.MaOffer,o.TrangThai,o.LuongDeXuat,o.NgayBatDau,o.HanPhanHoi FROM UngVien c JOIN YeuCauTuyenDung r ON r.MaYeuCau=c.MaYeuCau LEFT JOIN OfferUngVien o ON o.MaUngVien=c.MaUngVien ORDER BY c.TaoLuc DESC")[1]
    interviews = db.query("SELECT i.MaPhongVan,c.HoTen,i.ThoiDiem,i.HinhThuc,i.NguoiPhongVan,i.TrangThai,i.MaUngVien FROM PhongVanUngVien i JOIN UngVien c ON c.MaUngVien=i.MaUngVien ORDER BY i.ThoiDiem DESC")[1]
    reviews = db.query("SELECT d.MaPhongVan,d.Diem,d.NhanXet,d.NguoiDanhGia,d.TaoLuc FROM DanhGiaUngVien d ORDER BY d.TaoLuc DESC")[1]
    departments = db.query("SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB")[1]
    titles = db.query("SELECT MaCV,TenCV FROM ChucVu ORDER BY TenCV")[1]
    positions = db.query("SELECT MaViTri,TenViTri FROM ViTriCongViec WHERE TrangThai=1 ORDER BY TenViTri")[1]
    return render_template("recruiting.html", requests=requests, candidates=candidates, interviews=interviews, reviews=reviews, departments=departments, titles=titles, positions=positions, admin=True)


@app.route("/tai-san-nhan-vien", methods=["GET", "POST"])
@login_required
def employee_assets():
    if not has_permission("onboarding.manage"):
        return "Chỉ quản trị viên được quản lý tài sản nhân viên.", 403
    if request.method == "POST":
        actor = session["user"]["user"]
        try:
            action = request.form.get("action")
            if action == "assign":
                employee_id = int(request.form.get("MaNV", ""))
                name = request.form.get("TenTaiSan", "").strip()
                internal_code = request.form.get("MaNoiBo", "").strip()[:60] or None
                serial = request.form.get("Serial", "").strip()[:100] or None
                assigned = date.fromisoformat(request.form.get("NgayCap", ""))
                if not name or len(name) > 120 or assigned > date.today():
                    raise ValueError("Thông tin cấp tài sản không hợp lệ.")
                if not db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'", (employee_id,)):
                    raise ValueError("Chỉ có thể cấp tài sản cho nhân viên đang làm.")
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; INSERT INTO TaiSanNhanVien(MaNV,TenTaiSan,MaNoiBo,Serial,NgayCap,NguoiCap) VALUES(?,?,?,?,?,?); DECLARE @asset BIGINT=SCOPE_IDENTITY(); INSERT INTO NhatKyTaiSanNhanVien(MaTaiSan,ThaoTac,NguoiThucHien,ChiTiet) VALUES(@asset,N'cấp',?,N'Cấp tài sản cho nhân viên'); COMMIT;", (employee_id, name, internal_code, serial, assigned, actor, actor))
                flash("Đã ghi nhận tài sản cấp cho nhân viên.", "success")
            elif action == "return":
                asset_id = int(request.form.get("MaTaiSan", ""))
                returned = date.fromisoformat(request.form.get("NgayThuHoi", ""))
                condition = request.form.get("TinhTrangThuHoi", "").strip()[:200] or None
                if returned > date.today():
                    raise ValueError("Ngày thu hồi không được ở tương lai.")
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; DECLARE @employee INT,@assigned DATE; SELECT @employee=MaNV,@assigned=NgayCap FROM TaiSanNhanVien WITH (UPDLOCK,ROWLOCK) WHERE MaTaiSan=? AND TrangThai=N'Đang sử dụng'; IF @employee IS NULL THROW 50041,'Tài sản không còn được ghi nhận đang sử dụng.',1; IF @assigned>@returned THROW 50042,'Ngày thu hồi không được trước ngày cấp.',1; UPDATE TaiSanNhanVien SET TrangThai=N'Đã thu hồi',NgayThuHoi=?,TinhTrangThuHoi=?,NguoiThuHoi=? WHERE MaTaiSan=? AND TrangThai=N'Đang sử dụng'; IF @@ROWCOUNT<>1 THROW 50043,'Tài sản đã được cập nhật bởi người khác.',1; INSERT INTO NhatKyTaiSanNhanVien(MaTaiSan,ThaoTac,NguoiThucHien,ChiTiet) VALUES(?,N'thu hồi',?,?); COMMIT;", (asset_id, returned, condition, actor, asset_id, asset_id, actor, condition or "Thu hồi tài sản"))
                flash("Đã ghi nhận thu hồi tài sản.", "success")
            else:
                raise ValueError("Thao tác tài sản không hợp lệ.")
        except Exception as error:
            flash(_safe_error(error, "Không thể cập nhật tài sản. Vui lòng thử lại."), "error")
        return redirect(url_for("employee_assets"))
    people = db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
    assets = db.query("SELECT a.MaTaiSan,a.MaNV,n.HoTen,a.TenTaiSan,a.MaNoiBo,a.Serial,a.NgayCap,a.TrangThai,a.NgayThuHoi,a.TinhTrangThuHoi FROM TaiSanNhanVien a JOIN NhanVien n ON n.MaNV=a.MaNV ORDER BY CASE WHEN a.TrangThai=N'Đang sử dụng' THEN 0 ELSE 1 END,a.NgayCap DESC,a.MaTaiSan DESC")[1]
    history = db.query("SELECT l.MaTaiSan,n.HoTen,a.TenTaiSan,l.ThaoTac,l.NguoiThucHien,l.ChiTiet,l.TaoLuc FROM NhatKyTaiSanNhanVien l JOIN TaiSanNhanVien a ON a.MaTaiSan=l.MaTaiSan JOIN NhanVien n ON n.MaNV=a.MaNV ORDER BY l.TaoLuc DESC,l.MaNhatKy DESC")[1]
    return render_template("employee_assets.html", people=people, assets=assets, history=history, admin=True, today=date.today().isoformat())


@app.route("/vong-doi-nhan-vien", methods=["GET", "POST"])
@login_required
def employee_lifecycle():
    if not has_permission("onboarding.manage"):
        return "Chỉ quản trị viên được xử lý quy trình nhận việc/nghỉ việc.", 403
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            if action in ("onboarding", "offboarding"):
                manv = int(request.form["MaNV"])
                phase = "Onboarding" if action == "onboarding" else "Offboarding"
                if not db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=?", (manv, "Đang làm")):
                    raise ValueError("Chỉ nhân viên đang làm mới có thể mở quy trình.")
                start_date = date.fromisoformat(request.form.get("NgayBatDau", ""))
                end_date = date.fromisoformat(request.form["NgayHieuLucKetThuc"]) if phase == "Offboarding" and request.form.get("NgayHieuLucKetThuc") else (start_date if phase == "Offboarding" else None)
                if phase == "Offboarding" and end_date < start_date:
                    raise ValueError("Ngày nghỉ việc hiệu lực không được trước ngày bắt đầu bàn giao.")
                _start_employee_lifecycle(manv, phase, actor, start_date, request.form.get("LyDo"), end_date)
                flash("Đã tạo checklist " + ("onboarding" if phase == "Onboarding" else "offboarding") + ".", "success")
            elif action == "complete_task":
                task_id = int(request.form["MaChecklist"])
                note = request.form.get("GhiChu", "").strip()[:500]
                task = db.query("SELECT c.MaNV,c.TenViec,w.GiaiDoan FROM ChecklistNhanVien c JOIN VongDoiNhanVien w ON w.MaVongDoi=c.MaVongDoi WHERE c.MaChecklist=?", (task_id,))[1]
                if task and task[0][1] == "Thu hồi tài sản" and task[0][2] == "Offboarding" and db.scalar("SELECT COUNT(*) FROM TaiSanNhanVien WHERE MaNV=? AND TrangThai=N'Đang sử dụng'", (task[0][0],)):
                    raise ValueError("Hãy thu hồi các tài sản đang giao trong trang Tài sản nhân viên trước khi hoàn thành đầu việc này.")
                if not db.execute("UPDATE ChecklistNhanVien SET TrangThai=N'Hoàn thành',HoanThanhBoi=?,HoanThanhLuc=SYSUTCDATETIME(),GhiChu=? WHERE MaChecklist=? AND TrangThai=N'Chưa làm'", (actor, note or None, task_id)):
                    raise ValueError("Đầu việc không còn ở trạng thái chưa làm.")
                flash("Đã hoàn thành đầu việc.", "success")
            elif action == "add_template":
                phase = request.form.get("GiaiDoan", "")
                title = request.form.get("TenViec", "").strip()
                department = request.form.get("BoPhanPhuTrach", "").strip()
                due_offset = int(request.form.get("SoNgayHan") or 0)
                if phase not in ("Onboarding", "Offboarding") or not title or len(title) > 160 or not department or len(department) > 80 or due_offset not in range(-365, 366):
                    raise ValueError("Mẫu đầu việc không hợp lệ.")
                db.execute("INSERT INTO MauChecklistNhanSu(GiaiDoan,TenViec,BoPhanPhuTrach,SoNgayHan) VALUES(?,?,?,?)", (phase, title, department, due_offset))
                flash("Đã thêm mẫu checklist cho các quy trình mới.", "success")
            elif action == "toggle_template":
                db.execute("UPDATE MauChecklistNhanSu SET TrangThai=CASE WHEN TrangThai=1 THEN 0 ELSE 1 END WHERE MaMau=?", (int(request.form["MaMau"]),))
                flash("Đã cập nhật trạng thái mẫu checklist.", "success")
            elif action == "finalize_offboarding":
                workflow_id = int(request.form["MaVongDoi"])
                row = db.query("SELECT MaNV,NgayHieuLucKetThuc,TrangThai FROM VongDoiNhanVien WHERE MaVongDoi=? AND GiaiDoan=N'Offboarding'", (workflow_id,))[1]
                if not row or row[0][2] != "Đang xử lý":
                    raise ValueError("Quy trình nghỉ việc không còn đang xử lý.")
                manv, end_date, _ = row[0]
                if end_date and end_date > date.today():
                    raise ValueError("Chỉ có thể hoàn tất offboarding từ ngày nghỉ việc hiệu lực trở đi.")
                if db.scalar("SELECT COUNT(*) FROM ChecklistNhanVien WHERE MaVongDoi=? AND TrangThai<>N'Hoàn thành'", (workflow_id,)):
                    raise ValueError("Cần hoàn thành toàn bộ checklist trước khi kết thúc hồ sơ.")
                if db.scalar("SELECT COUNT(*) FROM TaiSanNhanVien WHERE MaNV=? AND TrangThai=N'Đang sử dụng'", (manv,)):
                    raise ValueError("Cần thu hồi các tài sản đang giao cho nhân viên trước khi kết thúc hồ sơ.")
                if db.scalar("SELECT COUNT(*) FROM QuanLyTrucTiep WHERE MaQuanLy=?", (manv,)):
                    raise ValueError("Hãy gán lại nhân viên thuộc quyền trước khi cho quản lý này nghỉ việc.")
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE VongDoiNhanVien SET TrangThai=N'Hoàn tất' WHERE MaVongDoi=? AND TrangThai=N'Đang xử lý'; IF @@ROWCOUNT<>1 THROW 50031,'Quy trình nghỉ việc đã thay đổi.',1; UPDATE NhanVien SET TrangThai=N'Đã nghỉ việc' WHERE MaNV=? AND TrangThai=N'Đang làm'; IF @@ROWCOUNT<>1 THROW 50032,'Hồ sơ nhân viên không còn hoạt động.',1; UPDATE TaiKhoan SET SecurityVersion=SecurityVersion+1 WHERE MaNV=?; DELETE FROM QuanLyTrucTiep WHERE MaNV=?; INSERT INTO NhatKyChamCong(MaNV,Nguon,ThaoTac,KetQua,NguoiThucHien,ChiTiet) SELECT MaNV,N'system',N'offboarding_face_delete',N'deleted',?,N'Xóa mẫu sinh trắc học khi hoàn tất nghỉ việc' FROM NhanVienKhuonMat WHERE MaNV=?; DELETE FROM NhanVienKhuonMat WHERE MaNV=?; COMMIT;", (workflow_id, manv, manv, manv, actor, manv, manv))
                flash("Đã kết thúc hồ sơ nhân viên, thu hồi phiên và xóa mẫu khuôn mặt.", "success")
            else:
                raise ValueError("Thao tác vòng đời không hợp lệ.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("employee_lifecycle"))
    workflows = db.query("SELECT w.MaVongDoi,w.MaNV,n.HoTen,w.GiaiDoan,w.NgayBatDau,w.NgayHieuLucKetThuc,w.LyDo,w.TrangThai,w.NguoiTao,(SELECT COUNT(*) FROM ChecklistNhanVien c WHERE c.MaVongDoi=w.MaVongDoi AND c.TrangThai=N'Hoàn thành'),(SELECT COUNT(*) FROM ChecklistNhanVien c WHERE c.MaVongDoi=w.MaVongDoi) FROM VongDoiNhanVien w JOIN NhanVien n ON n.MaNV=w.MaNV ORDER BY w.TaoLuc DESC")[1]
    tasks = db.query("SELECT c.MaVongDoi,c.MaChecklist,n.HoTen,w.GiaiDoan,c.TenViec,c.BoPhanPhuTrach,c.HanHoanThanh,c.TrangThai,c.HoanThanhBoi,c.GhiChu FROM ChecklistNhanVien c JOIN NhanVien n ON n.MaNV=c.MaNV JOIN VongDoiNhanVien w ON w.MaVongDoi=c.MaVongDoi ORDER BY c.HanHoanThanh,c.MaChecklist")[1]
    people = db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
    templates = db.query("SELECT MaMau,GiaiDoan,TenViec,BoPhanPhuTrach,SoNgayHan,TrangThai FROM MauChecklistNhanSu ORDER BY GiaiDoan,MaMau")[1]
    return render_template("employee_lifecycle.html", workflows=workflows, tasks=tasks, people=people, templates=templates, admin=True, today=date.today().isoformat())


@app.route("/danh-gia-kpi", methods=["GET", "POST"])
@login_required
def performance_kpi():
    own_id = int(session.get("user", {}).get("manv") or 0)
    if request.method == "POST":
        try:
            kpi_manage = admin() or has_permission("kpi.manage")
            action = request.form.get("action")
            actor = session["user"]["user"]
            if action == "cycle" and kpi_manage:
                name = request.form.get("TenChuKy", "").strip()
                start, end = date.fromisoformat(request.form.get("TuNgay", "")), date.fromisoformat(request.form.get("DenNgay", ""))
                if not name or len(name) > 120 or end < start:
                    raise ValueError("Tên hoặc ngày chu kỳ KPI không hợp lệ.")
                db.execute("INSERT INTO ChuKyKPI(TenChuKy,TuNgay,DenNgay,NguoiTao) VALUES(?,?,?,?)", (name, start, end, actor))
                flash("Đã tạo chu kỳ đánh giá.", "success")
            elif action == "goal" and kpi_manage:
                cycle_id = int(request.form["MaChuKy"])
                employee_id = request.form.get("MaNV") or None
                department_id = request.form.get("MaPB") or None
                title = request.form.get("TenMucTieu", "").strip()
                target = float(request.form.get("GiaTriMucTieu") or -1)
                weight = float(request.form.get("TrongSo") or 0)
                unit = request.form.get("DonVi", "").strip()
                if bool(employee_id) == bool(department_id) or not title or len(title) > 160 or not math.isfinite(target) or target <= 0 or not math.isfinite(weight) or not 0 <= weight <= 100 or not unit or len(unit) > 40:
                    raise ValueError("Mục tiêu phải gắn với đúng một nhân viên hoặc phòng ban; các giá trị KPI chưa hợp lệ.")
                if db.scalar("SELECT COUNT(*) FROM DanhGiaKPIChuKy WHERE MaChuKy=? AND TrangThai<>N'Nháp'", (cycle_id,)):
                    raise ValueError("Không thể thêm mục tiêu sau khi chu kỳ đã có bản tự đánh giá được gửi.")
                if not db.scalar("SELECT COUNT(*) FROM ChuKyKPI WHERE MaChuKy=? AND TrangThai=N'Đang mở'", (cycle_id,)):
                    raise ValueError("Chu kỳ KPI đã đóng hoặc không tồn tại.")
                db.execute("INSERT INTO MucTieuKPI(MaChuKy,MaNV,MaPB,TenMucTieu,MoTa,GiaTriMucTieu,DonVi,TrongSo,NguoiTao) VALUES(?,?,?,?,?,?,?,?,?)", (cycle_id, employee_id, department_id, title, request.form.get("MoTa", "").strip()[:1000] or None, target, unit, weight, actor))
                flash("Đã tạo mục tiêu KPI.", "success")
            elif action == "close_cycle" and kpi_manage:
                db.execute("UPDATE ChuKyKPI SET TrangThai=N'Đã đóng' WHERE MaChuKy=? AND TrangThai=N'Đang mở'", (int(request.form["MaChuKy"]),))
                flash("Đã đóng chu kỳ KPI.", "success")
            elif action == "result":
                goal_id = int(request.form["MaMucTieu"])
                actual = float(request.form.get("GiaTriThucTe") or -1)
                comment = request.form.get("NhanXet", "").strip()[:1000]
                goal = db.query("SELECT g.MaNV,g.MaPB,g.GiaTriMucTieu,c.TrangThai FROM MucTieuKPI g JOIN ChuKyKPI c ON c.MaChuKy=g.MaChuKy WHERE g.MaMucTieu=?", (goal_id,))[1]
                if not goal or goal[0][3] != "Đang mở" or not math.isfinite(actual) or actual < 0:
                    raise ValueError("Mục tiêu không còn mở hoặc kết quả không hợp lệ.")
                goal_employee, goal_department, target = goal[0][:3]
                employee_id = int(request.form.get("MaNV")) if kpi_manage and request.form.get("MaNV") else own_id
                if not kpi_manage and not employee_id:
                    raise ValueError("Tài khoản chưa liên kết hồ sơ nhân viên.")
                if goal_employee and employee_id != goal_employee:
                    raise ValueError("Mục tiêu này thuộc nhân viên khác.")
                if goal_department and not db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND MaPB=?", (employee_id, goal_department)):
                    raise ValueError("Nhân viên không thuộc phòng ban gắn với mục tiêu.")
                if db.scalar("SELECT COUNT(*) FROM DanhGiaKPIChuKy e JOIN MucTieuKPI g ON g.MaChuKy=e.MaChuKy WHERE e.MaNV=? AND g.MaMucTieu=? AND e.TrangThai<>N'Nháp'", (employee_id, goal_id)):
                    raise ValueError("Kết quả đã được chốt tự đánh giá; không thể sửa trong lúc duyệt hoặc sau khi duyệt.")
                progress = min(100, round(actual * 100 / float(target), 2))
                db.execute("IF EXISTS(SELECT 1 FROM KetQuaKPI WHERE MaMucTieu=? AND MaNV=?) UPDATE KetQuaKPI SET GiaTriThucTe=?,TienDo=?,NhanXet=?,TrangThai=N'Đã gửi',NguoiCapNhat=?,CapNhatLuc=SYSUTCDATETIME(),NguoiDuyet=NULL,DuyetLuc=NULL WHERE MaMucTieu=? AND MaNV=? ELSE INSERT INTO KetQuaKPI(MaMucTieu,MaNV,GiaTriThucTe,TienDo,NhanXet,TrangThai,NguoiCapNhat) VALUES(?,?,?,?,?,N'Đã gửi',?)", (goal_id, employee_id, actual, progress, comment or None, actor, goal_id, employee_id, goal_id, employee_id, actual, progress, comment or None, actor))
                db.execute("INSERT INTO NhatKyKetQuaKPI(MaMucTieu,MaNV,GiaTriThucTe,TienDo,NhanXet,NguoiCapNhat) VALUES(?,?,?,?,?,?)", (goal_id, employee_id, actual, progress, comment or None, actor))
                flash("Đã gửi kết quả KPI.", "success")
            elif action == "review":
                raise ValueError("Duyệt theo từng mục tiêu đã được thay bằng quy trình tự đánh giá → quản lý → HR theo chu kỳ.")
            elif action == "self_submit":
                cycle_id = int(request.form["MaChuKy"])
                if not own_id or not db.scalar("SELECT COUNT(*) FROM ChuKyKPI WHERE MaChuKy=? AND TrangThai=N'Đang mở'", (cycle_id,)):
                    raise ValueError("Tài khoản hoặc chu kỳ KPI không hợp lệ.")
                existing = db.query("SELECT TrangThai FROM DanhGiaKPIChuKy WHERE MaChuKy=? AND MaNV=?", (cycle_id, own_id))[1]
                if existing and existing[0][0] != "Nháp":
                    raise ValueError("Bản tự đánh giá đã gửi và đang trong quy trình duyệt.")
                goal_rows = db.query("SELECT g.GiaTriMucTieu,g.TrongSo,r.GiaTriThucTe,r.TrangThai FROM MucTieuKPI g LEFT JOIN NhanVien n ON n.MaNV=? LEFT JOIN KetQuaKPI r ON r.MaMucTieu=g.MaMucTieu AND r.MaNV=? WHERE g.MaChuKy=? AND (g.MaNV=? OR g.MaPB=n.MaPB)", (own_id, own_id, cycle_id, own_id))[1]
                if not goal_rows or any(row[0] <= 0 or row[2] is None or row[3] not in ("Đã gửi", "Đã duyệt") for row in goal_rows):
                    raise ValueError("Hãy gửi kết quả cho tất cả mục tiêu trong chu kỳ trước khi tự đánh giá.")
                total_weight = sum(float(row[1] or 0) for row in goal_rows)
                if abs(total_weight - 100) > 0.01:
                    raise ValueError(f"Tổng trọng số mục tiêu phải bằng 100% (hiện là {total_weight:g}%).")
                self_score = round(sum(min(float(row[2]) / float(row[0]), 1) * float(row[1]) for row in goal_rows if float(row[0]) > 0), 2)
                comment = request.form.get("NhanXetTuDanhGia", "").strip()[:2000]
                missing = db.scalar("SELECT COUNT(*) FROM KhungNangLuc n WHERE n.TrangThai=1 AND NOT EXISTS(SELECT 1 FROM DanhGiaNangLuc d WHERE d.MaChuKy=? AND d.MaNV=? AND d.MaNangLuc=n.MaNangLuc AND d.DiemTuDanhGia IS NOT NULL)", (cycle_id, own_id))
                if missing:
                    raise ValueError("Hãy tự đánh giá đủ năng lực trong khung trước khi gửi.")
                if existing:
                    db.execute("UPDATE DanhGiaKPIChuKy SET DiemTuDanhGia=?,NhanXetTuDanhGia=?,TrangThai=N'Chờ quản lý',TuDanhGiaLuc=SYSUTCDATETIME() WHERE MaChuKy=? AND MaNV=? AND TrangThai=N'Nháp'", (self_score, comment or None, cycle_id, own_id))
                else:
                    db.execute("INSERT INTO DanhGiaKPIChuKy(MaChuKy,MaNV,DiemTuDanhGia,NhanXetTuDanhGia,TrangThai,TuDanhGiaLuc) VALUES(?,?,?,?,N'Chờ quản lý',SYSUTCDATETIME())", (cycle_id, own_id, self_score, comment or None))
                db.execute("INSERT INTO NhatKyDanhGiaKPI(MaChuKy,MaNV,ThaoTac,ChiTiet,NguoiThucHien) VALUES(?,?,N'Tự đánh giá',?,?)", (cycle_id, own_id, json.dumps({"score": self_score, "weight_total": total_weight, "comment": comment}, ensure_ascii=False), actor))
                flash("Đã gửi tự đánh giá KPI; hồ sơ đang chờ quản lý trực tiếp.", "success")
            elif action == "competency_self":
                cycle_id, competency_id = int(request.form["MaChuKy"]), int(request.form["MaNangLuc"])
                level = int(request.form.get("DiemTuDanhGia") or 0)
                comment = request.form.get("NhanXetTuDanhGia", "").strip()[:1000]
                if not own_id or level not in range(1, 6) or not db.scalar("SELECT COUNT(*) FROM ChuKyKPI WHERE MaChuKy=? AND TrangThai=N'Đang mở'", (cycle_id,)) or not db.scalar("SELECT COUNT(*) FROM KhungNangLuc WHERE MaNangLuc=? AND TrangThai=1", (competency_id,)):
                    raise ValueError("Chu kỳ/năng lực không hợp lệ; cấp độ phải từ 1 đến 5.")
                if db.scalar("SELECT COUNT(*) FROM DanhGiaKPIChuKy WHERE MaChuKy=? AND MaNV=? AND TrangThai<>N'Nháp'", (cycle_id, own_id)):
                    raise ValueError("Đã gửi tự đánh giá; không thể sửa năng lực trong khi đang duyệt.")
                db.execute("IF EXISTS(SELECT 1 FROM DanhGiaNangLuc WHERE MaChuKy=? AND MaNV=? AND MaNangLuc=?) UPDATE DanhGiaNangLuc SET DiemTuDanhGia=?,NhanXetTuDanhGia=?,CapNhatLuc=SYSUTCDATETIME() WHERE MaChuKy=? AND MaNV=? AND MaNangLuc=? ELSE INSERT INTO DanhGiaNangLuc(MaChuKy,MaNV,MaNangLuc,DiemTuDanhGia,NhanXetTuDanhGia) VALUES(?,?,?,?,?)", (cycle_id, own_id, competency_id, level, comment or None, cycle_id, own_id, competency_id, cycle_id, own_id, competency_id, level, comment or None))
                db.execute("INSERT INTO NhatKyDanhGiaKPI(MaChuKy,MaNV,ThaoTac,ChiTiet,NguoiThucHien) VALUES(?,?,N'Tự đánh giá năng lực',?,?)", (cycle_id, own_id, json.dumps({"competency_id": competency_id, "level": level, "comment": comment}, ensure_ascii=False), actor))
                flash("Đã lưu tự đánh giá năng lực.", "success")
            elif action == "manager_review" and is_manager():
                evaluation_id = int(request.form["MaDanhGia"])
                manager_score = float(request.form.get("DiemQuanLy") or -1)
                comment = request.form.get("NhanXetQuanLy", "").strip()[:2000]
                evaluation = db.query("SELECT e.MaChuKy,e.MaNV,e.DiemTuDanhGia FROM DanhGiaKPIChuKy e JOIN QuanLyTrucTiep q ON q.MaNV=e.MaNV WHERE e.MaDanhGia=? AND e.TrangThai=N'Chờ quản lý' AND q.MaQuanLy=?", (evaluation_id, own_id))[1]
                if not evaluation or not math.isfinite(manager_score) or not 0 <= manager_score <= 100 or not comment:
                    raise ValueError("Chỉ quản lý trực tiếp được đánh giá hồ sơ đang chờ; cần điểm 0–100 và nhận xét.")
                cycle_id, employee_id, self_score = evaluation[0]
                if db.scalar("SELECT COUNT(*) FROM KhungNangLuc n WHERE n.TrangThai=1 AND NOT EXISTS(SELECT 1 FROM DanhGiaNangLuc d WHERE d.MaChuKy=? AND d.MaNV=? AND d.MaNangLuc=n.MaNangLuc AND d.DiemQuanLy IS NOT NULL)", (cycle_id, employee_id)):
                    raise ValueError("Quản lý cần chấm đủ các năng lực trước khi gửi HR.")
                total_score = round(float(self_score) * 0.7 + manager_score * 0.3, 2)
                if not db.execute("UPDATE DanhGiaKPIChuKy SET DiemQuanLy=?,DiemTongHop=?,NhanXetQuanLy=?,TrangThai=N'Chờ HR',QuanLyBoi=?,QuanLyLuc=SYSUTCDATETIME() WHERE MaDanhGia=? AND TrangThai=N'Chờ quản lý'", (manager_score, total_score, comment, actor, evaluation_id)):
                    raise ValueError("Bản đánh giá vừa được người khác xử lý; hãy tải lại trang.")
                db.execute("UPDATE DanhGiaNangLuc SET TrangThai=N'Chờ HR' WHERE MaChuKy=? AND MaNV=? AND DiemQuanLy IS NOT NULL", (cycle_id, employee_id))
                db.execute("INSERT INTO NhatKyDanhGiaKPI(MaChuKy,MaNV,ThaoTac,ChiTiet,NguoiThucHien) VALUES(?,?,N'Quản lý đánh giá',?,?)", (cycle_id, employee_id, json.dumps({"manager_score": manager_score, "total_score": total_score, "comment": comment}, ensure_ascii=False), actor))
                flash("Đã gửi đánh giá quản lý lên HR phê duyệt.", "success")
            elif action == "competency_manager" and is_manager():
                evaluation_id, competency_id = int(request.form["MaDanhGia"]), int(request.form["MaNangLuc"])
                employee_id = int(request.form["MaNV"])
                level = int(request.form.get("DiemQuanLy") or 0)
                comment = request.form.get("NhanXetQuanLy", "").strip()[:1000]
                allowed = db.scalar("SELECT COUNT(*) FROM DanhGiaKPIChuKy e JOIN QuanLyTrucTiep q ON q.MaNV=e.MaNV JOIN DanhGiaNangLuc d ON d.MaChuKy=e.MaChuKy AND d.MaNV=e.MaNV WHERE e.MaDanhGia=? AND e.MaNV=? AND e.TrangThai=N'Chờ quản lý' AND q.MaQuanLy=? AND d.MaNangLuc=? AND d.DiemTuDanhGia IS NOT NULL", (evaluation_id, employee_id, own_id, competency_id))
                if not allowed or level not in range(1, 6) or not comment:
                    raise ValueError("Chỉ quản lý trực tiếp được chấm năng lực 1–5; cần nhận xét.")
                db.execute("UPDATE DanhGiaNangLuc SET DiemQuanLy=?,NhanXetQuanLy=?,QuanLyBoi=?,QuanLyLuc=SYSUTCDATETIME(),CapNhatLuc=SYSUTCDATETIME() WHERE MaChuKy=(SELECT MaChuKy FROM DanhGiaKPIChuKy WHERE MaDanhGia=?) AND MaNV=? AND MaNangLuc=?", (level, comment, actor, evaluation_id, employee_id, competency_id))
                cycle_id = int(db.scalar("SELECT MaChuKy FROM DanhGiaKPIChuKy WHERE MaDanhGia=?", (evaluation_id,)))
                db.execute("INSERT INTO NhatKyDanhGiaKPI(MaChuKy,MaNV,ThaoTac,ChiTiet,NguoiThucHien) VALUES(?,?,N'Quản lý đánh giá năng lực',?,?)", (cycle_id, employee_id, json.dumps({"competency_id": competency_id, "level": level, "comment": comment}, ensure_ascii=False), actor))
                flash("Đã lưu đánh giá năng lực của quản lý.", "success")
            elif action == "hr_approve" and has_permission("kpi.approve"):
                evaluation_id = int(request.form["MaDanhGia"])
                evaluation = db.query("SELECT MaChuKy,MaNV,DiemTuDanhGia,DiemQuanLy,DiemTongHop FROM DanhGiaKPIChuKy WHERE MaDanhGia=? AND TrangThai=N'Chờ HR'", (evaluation_id,))[1]
                if not evaluation:
                    raise ValueError("Chỉ có thể phê duyệt đánh giá đang chờ HR.")
                cycle_id, employee_id, self_score, manager_score, total_score = evaluation[0]
                if not db.execute("UPDATE DanhGiaKPIChuKy SET TrangThai=N'Đã duyệt',HRBoi=?,HRLuc=SYSUTCDATETIME() WHERE MaDanhGia=? AND TrangThai=N'Chờ HR'", (actor, evaluation_id)):
                    raise ValueError("Bản đánh giá vừa được người khác xử lý; hãy tải lại trang.")
                db.execute("UPDATE DanhGiaNangLuc SET TrangThai=N'Đã duyệt',HRBoi=?,HRLuc=SYSUTCDATETIME() WHERE MaChuKy=? AND MaNV=? AND TrangThai=N'Chờ HR'", (actor, cycle_id, employee_id))
                db.execute("UPDATE KetQuaKPI SET TrangThai=N'Đã duyệt',NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME() WHERE MaNV=? AND MaMucTieu IN (SELECT g.MaMucTieu FROM MucTieuKPI g JOIN NhanVien n ON n.MaNV=? WHERE g.MaChuKy=? AND (g.MaNV=? OR g.MaPB=n.MaPB))", (actor, employee_id, employee_id, cycle_id, employee_id))
                db.execute("INSERT INTO NhatKyDanhGiaKPI(MaChuKy,MaNV,ThaoTac,ChiTiet,NguoiThucHien) VALUES(?,?,N'HR phê duyệt',?,?)", (cycle_id, employee_id, json.dumps({"self_score": self_score, "manager_score": manager_score, "total_score": total_score}, ensure_ascii=False), actor))
                flash("HR đã phê duyệt và chốt kết quả chu kỳ.", "success")
            elif action == "competency_add" and has_permission("kpi.approve"):
                name = request.form.get("TenNangLuc", "").strip()
                level = int(request.form.get("CapDoChuan") or 0)
                if db.scalar("SELECT COUNT(*) FROM DanhGiaKPIChuKy e JOIN ChuKyKPI c ON c.MaChuKy=e.MaChuKy WHERE c.TrangThai=N'Đang mở' AND e.TrangThai<>N'Nháp'"):
                    raise ValueError("Không thể đổi khung năng lực khi chu kỳ đã có hồ sơ đang duyệt.")
                if not name or len(name) > 120 or level not in range(1, 6):
                    raise ValueError("Tên năng lực bắt buộc; cấp độ chuẩn phải từ 1 đến 5.")
                db.execute("INSERT INTO KhungNangLuc(TenNangLuc,NhomNangLuc,MoTa,CapDoChuan) VALUES(?,?,?,?)", (name, request.form.get("NhomNangLuc", "").strip()[:80] or None, request.form.get("MoTa", "").strip()[:1000] or None, level))
                flash("Đã thêm năng lực vào khung.", "success")
            elif action == "career_plan":
                employee_id = int(request.form["MaNV"]) if has_permission("kpi.approve") and request.form.get("MaNV") else own_id
                cycle_id = int(request.form["MaChuKy"]) if request.form.get("MaChuKy") else None
                target_role = request.form.get("TenVaiTroMucTieu", "").strip()[:120]
                skills = request.form.get("KyNangCanPhatTrien", "").strip()[:1000]
                due = date.fromisoformat(request.form["HanMucTieu"]) if request.form.get("HanMucTieu") else None
                if not employee_id or not target_role or not skills:
                    raise ValueError("Kế hoạch cần nhân viên, vai trò mục tiêu và nội dung phát triển.")
                if cycle_id and not db.scalar("SELECT COUNT(*) FROM ChuKyKPI WHERE MaChuKy=?", (cycle_id,)):
                    raise ValueError("Chu kỳ đánh giá không tồn tại.")
                db.execute("INSERT INTO KeHoachPhatTrien(MaNV,MaChuKy,TenVaiTroMucTieu,KyNangCanPhatTrien,HanMucTieu,NguoiTao,TrangThai) VALUES(?,?,?,?,?,?,N'Chờ quản lý')", (employee_id, cycle_id, target_role, skills, due, actor))
                flash("Đã gửi kế hoạch phát triển nghề nghiệp để quản lý xem xét.", "success")
            elif action == "career_manager" and is_manager():
                plan_id = int(request.form["MaKeHoach"])
                if not db.scalar("SELECT COUNT(*) FROM KeHoachPhatTrien p JOIN QuanLyTrucTiep q ON q.MaNV=p.MaNV WHERE p.MaKeHoach=? AND q.MaQuanLy=? AND p.TrangThai=N'Chờ quản lý'", (plan_id, own_id)):
                    raise ValueError("Kế hoạch không thuộc phạm vi quản lý hoặc đã được xử lý.")
                db.execute("UPDATE KeHoachPhatTrien SET TrangThai=N'Chờ HR',QuanLyDuyetBoi=?,QuanLyDuyetLuc=SYSUTCDATETIME() WHERE MaKeHoach=? AND TrangThai=N'Chờ quản lý'", (actor, plan_id))
                flash("Đã chuyển kế hoạch phát triển lên HR.", "success")
            elif action == "career_hr" and has_permission("kpi.approve"):
                plan_id = int(request.form["MaKeHoach"])
                status = request.form.get("TrangThai")
                if status not in ("Đang thực hiện", "Từ chối") or not db.execute("UPDATE KeHoachPhatTrien SET TrangThai=?,HRDuyetBoi=?,HRDuyetLuc=SYSUTCDATETIME() WHERE MaKeHoach=? AND TrangThai=N'Chờ HR'", (status, actor, plan_id)):
                    raise ValueError("Kế hoạch không còn chờ HR hoặc trạng thái không hợp lệ.")
                flash("Đã xử lý kế hoạch phát triển.", "success")
            elif action == "feedback":
                employee_id = int(request.form["MaNV"]) if kpi_manage else own_id
                cycle_id = int(request.form["MaChuKy"]) if request.form.get("MaChuKy") else None
                kind = request.form.get("LoaiPhanHoi", "").strip()
                content = request.form.get("NoiDung", "").strip()
                if not employee_id or not kind or len(kind) > 30 or not content or len(content) > 2000:
                    raise ValueError("Phản hồi cần có loại và nội dung, tối đa 2000 ký tự.")
                db.execute("INSERT INTO PhanHoiKPI(MaNV,MaChuKy,NguoiGui,LoaiPhanHoi,NoiDung) VALUES(?,?,?,?,?)", (employee_id, cycle_id, actor, kind, content))
                flash("Đã lưu phản hồi.", "success")
            else:
                raise ValueError("Thao tác KPI không hợp lệ hoặc không đủ quyền.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("performance_kpi"))
    cycles = db.query("SELECT MaChuKy,TenChuKy,TuNgay,DenNgay,TrangThai FROM ChuKyKPI ORDER BY TuNgay DESC")[1]
    open_cycle_ids = {cycle[0] for cycle in cycles if cycle[4] == "Đang mở"}
    kpi_manage = admin() or has_permission("kpi.manage")
    departments = db.query("SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB")[1] if kpi_manage else []
    people = db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1] if kpi_manage else []
    if kpi_manage:
        goals = db.query("SELECT g.MaMucTieu,g.MaChuKy,c.TenChuKy,g.MaNV,g.MaPB,g.TenMucTieu,g.MoTa,g.GiaTriMucTieu,g.DonVi,g.TrongSo FROM MucTieuKPI g JOIN ChuKyKPI c ON c.MaChuKy=g.MaChuKy ORDER BY c.TuNgay DESC,g.MaMucTieu")[1]
        evaluations = db.query("SELECT e.MaDanhGia,e.MaChuKy,c.TenChuKy,e.MaNV,n.HoTen,e.DiemTuDanhGia,e.DiemQuanLy,e.DiemTongHop,e.TrangThai,e.NhanXetTuDanhGia,e.NhanXetQuanLy FROM DanhGiaKPIChuKy e JOIN ChuKyKPI c ON c.MaChuKy=e.MaChuKy JOIN NhanVien n ON n.MaNV=e.MaNV ORDER BY c.TuNgay DESC,n.HoTen")[1]
        plans = db.query("SELECT p.MaKeHoach,p.MaNV,n.HoTen,c.TenChuKy,p.TenVaiTroMucTieu,p.KyNangCanPhatTrien,p.HanMucTieu,p.TrangThai FROM KeHoachPhatTrien p JOIN NhanVien n ON n.MaNV=p.MaNV LEFT JOIN ChuKyKPI c ON c.MaChuKy=p.MaChuKy ORDER BY p.TaoLuc DESC")[1]
        feedback = db.query("SELECT p.MaPhanHoi,n.HoTen,p.MaChuKy,p.NguoiGui,p.LoaiPhanHoi,p.NoiDung,p.TaoLuc FROM PhanHoiKPI p JOIN NhanVien n ON n.MaNV=p.MaNV ORDER BY p.TaoLuc DESC")[1]
        competency_scores = db.query("SELECT d.MaChuKy,d.MaNV,d.MaNangLuc,k.TenNangLuc,k.CapDoChuan,d.DiemTuDanhGia,d.DiemQuanLy,d.NhanXetTuDanhGia,d.NhanXetQuanLy,d.TrangThai FROM DanhGiaNangLuc d JOIN KhungNangLuc k ON k.MaNangLuc=d.MaNangLuc ORDER BY d.MaChuKy,d.MaNV,k.TenNangLuc")[1]
        history = db.query("SELECT n.HoTen,c.TenChuKy,h.ThaoTac,h.ChiTiet,h.NguoiThucHien,h.TaoLuc FROM NhatKyDanhGiaKPI h JOIN NhanVien n ON n.MaNV=h.MaNV JOIN ChuKyKPI c ON c.MaChuKy=h.MaChuKy ORDER BY h.TaoLuc DESC")[1]
    elif is_manager() and own_id:
        goals = db.query("SELECT g.MaMucTieu,g.MaChuKy,c.TenChuKy,g.MaNV,g.MaPB,g.TenMucTieu,g.MoTa,g.GiaTriMucTieu,g.DonVi,g.TrongSo,ISNULL(r.GiaTriThucTe,0),ISNULL(r.TienDo,0),ISNULL(r.TrangThai,N'Chưa cập nhật'),r.MaKetQua FROM MucTieuKPI g JOIN ChuKyKPI c ON c.MaChuKy=g.MaChuKy LEFT JOIN NhanVien n ON n.MaNV=? LEFT JOIN KetQuaKPI r ON r.MaMucTieu=g.MaMucTieu AND r.MaNV=? WHERE g.MaNV=? OR g.MaNV IN (SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?) OR g.MaPB=n.MaPB ORDER BY c.TuNgay DESC,g.MaMucTieu", (own_id, own_id, own_id, own_id))[1]
        evaluations = db.query("SELECT e.MaDanhGia,e.MaChuKy,c.TenChuKy,e.MaNV,n.HoTen,e.DiemTuDanhGia,e.DiemQuanLy,e.DiemTongHop,e.TrangThai,e.NhanXetTuDanhGia,e.NhanXetQuanLy FROM DanhGiaKPIChuKy e JOIN ChuKyKPI c ON c.MaChuKy=e.MaChuKy JOIN NhanVien n ON n.MaNV=e.MaNV WHERE e.MaNV=? OR e.MaNV IN (SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?) ORDER BY c.TuNgay DESC,n.HoTen", (own_id, own_id))[1]
        plans = db.query("SELECT p.MaKeHoach,p.MaNV,n.HoTen,c.TenChuKy,p.TenVaiTroMucTieu,p.KyNangCanPhatTrien,p.HanMucTieu,p.TrangThai FROM KeHoachPhatTrien p JOIN NhanVien n ON n.MaNV=p.MaNV LEFT JOIN ChuKyKPI c ON c.MaChuKy=p.MaChuKy WHERE (p.MaNV=? OR p.MaNV IN (SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?)) ORDER BY p.TaoLuc DESC", (own_id, own_id))[1]
        feedback = db.query("SELECT p.MaPhanHoi,n.HoTen,p.MaChuKy,p.NguoiGui,p.LoaiPhanHoi,p.NoiDung,p.TaoLuc FROM PhanHoiKPI p JOIN NhanVien n ON n.MaNV=p.MaNV WHERE p.MaNV=? OR p.MaNV IN (SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?) ORDER BY p.TaoLuc DESC", (own_id, own_id))[1]
        competency_scores = db.query("SELECT d.MaChuKy,d.MaNV,d.MaNangLuc,k.TenNangLuc,k.CapDoChuan,d.DiemTuDanhGia,d.DiemQuanLy,d.NhanXetTuDanhGia,d.NhanXetQuanLy,d.TrangThai FROM DanhGiaNangLuc d JOIN KhungNangLuc k ON k.MaNangLuc=d.MaNangLuc WHERE d.MaNV=? OR d.MaNV IN (SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?) ORDER BY d.MaChuKy,d.MaNV,k.TenNangLuc", (own_id, own_id))[1]
        history = db.query("SELECT n.HoTen,c.TenChuKy,h.ThaoTac,h.ChiTiet,h.NguoiThucHien,h.TaoLuc FROM NhatKyDanhGiaKPI h JOIN NhanVien n ON n.MaNV=h.MaNV JOIN ChuKyKPI c ON c.MaChuKy=h.MaChuKy WHERE h.MaNV=? OR h.MaNV IN (SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?) ORDER BY h.TaoLuc DESC", (own_id, own_id))[1]
    else:
        goals = db.query("SELECT g.MaMucTieu,g.MaChuKy,c.TenChuKy,g.MaNV,g.MaPB,g.TenMucTieu,g.MoTa,g.GiaTriMucTieu,g.DonVi,g.TrongSo,ISNULL(r.GiaTriThucTe,0),ISNULL(r.TienDo,0),ISNULL(r.TrangThai,N'Chưa cập nhật'),r.MaKetQua FROM MucTieuKPI g JOIN ChuKyKPI c ON c.MaChuKy=g.MaChuKy LEFT JOIN NhanVien n ON n.MaNV=? LEFT JOIN KetQuaKPI r ON r.MaMucTieu=g.MaMucTieu AND r.MaNV=? WHERE (g.MaNV=? OR g.MaPB=n.MaPB) ORDER BY c.TuNgay DESC,g.MaMucTieu", (own_id, own_id, own_id))[1]
        evaluations = db.query("SELECT e.MaDanhGia,e.MaChuKy,c.TenChuKy,e.MaNV,n.HoTen,e.DiemTuDanhGia,e.DiemQuanLy,e.DiemTongHop,e.TrangThai,e.NhanXetTuDanhGia,e.NhanXetQuanLy FROM DanhGiaKPIChuKy e JOIN ChuKyKPI c ON c.MaChuKy=e.MaChuKy JOIN NhanVien n ON n.MaNV=e.MaNV WHERE e.MaNV=? ORDER BY c.TuNgay DESC", (own_id,))[1]
        plans = db.query("SELECT p.MaKeHoach,p.MaNV,n.HoTen,c.TenChuKy,p.TenVaiTroMucTieu,p.KyNangCanPhatTrien,p.HanMucTieu,p.TrangThai FROM KeHoachPhatTrien p JOIN NhanVien n ON n.MaNV=p.MaNV LEFT JOIN ChuKyKPI c ON c.MaChuKy=p.MaChuKy WHERE p.MaNV=? ORDER BY p.TaoLuc DESC", (own_id,))[1]
        feedback = db.query("SELECT p.MaPhanHoi,n.HoTen,p.MaChuKy,p.NguoiGui,p.LoaiPhanHoi,p.NoiDung,p.TaoLuc FROM PhanHoiKPI p JOIN NhanVien n ON n.MaNV=p.MaNV WHERE p.MaNV=? ORDER BY p.TaoLuc DESC", (own_id,))[1]
        competency_scores = db.query("SELECT d.MaChuKy,d.MaNV,d.MaNangLuc,k.TenNangLuc,k.CapDoChuan,d.DiemTuDanhGia,d.DiemQuanLy,d.NhanXetTuDanhGia,d.NhanXetQuanLy,d.TrangThai FROM DanhGiaNangLuc d JOIN KhungNangLuc k ON k.MaNangLuc=d.MaNangLuc WHERE d.MaNV=? ORDER BY d.MaChuKy,k.TenNangLuc", (own_id,))[1]
        history = db.query("SELECT n.HoTen,c.TenChuKy,h.ThaoTac,h.ChiTiet,h.NguoiThucHien,h.TaoLuc FROM NhatKyDanhGiaKPI h JOIN NhanVien n ON n.MaNV=h.MaNV JOIN ChuKyKPI c ON c.MaChuKy=h.MaChuKy WHERE h.MaNV=? ORDER BY h.TaoLuc DESC", (own_id,))[1]
    competencies = db.query("SELECT MaNangLuc,TenNangLuc,NhomNangLuc,MoTa,CapDoChuan FROM KhungNangLuc WHERE TrangThai=1 ORDER BY NhomNangLuc,TenNangLuc")[1]
    if kpi_manage:
        goal_history = db.query("SELECT n.HoTen,c.TenChuKy,g.TenMucTieu,h.GiaTriThucTe,h.TienDo,h.NhanXet,h.NguoiCapNhat,h.TaoLuc FROM NhatKyKetQuaKPI h JOIN NhanVien n ON n.MaNV=h.MaNV JOIN MucTieuKPI g ON g.MaMucTieu=h.MaMucTieu JOIN ChuKyKPI c ON c.MaChuKy=g.MaChuKy ORDER BY h.TaoLuc DESC")[1]
    elif is_manager() and own_id:
        goal_history = db.query("SELECT n.HoTen,c.TenChuKy,g.TenMucTieu,h.GiaTriThucTe,h.TienDo,h.NhanXet,h.NguoiCapNhat,h.TaoLuc FROM NhatKyKetQuaKPI h JOIN NhanVien n ON n.MaNV=h.MaNV JOIN MucTieuKPI g ON g.MaMucTieu=h.MaMucTieu JOIN ChuKyKPI c ON c.MaChuKy=g.MaChuKy WHERE h.MaNV=? OR h.MaNV IN (SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?) ORDER BY h.TaoLuc DESC", (own_id, own_id))[1]
    else:
        goal_history = db.query("SELECT n.HoTen,c.TenChuKy,g.TenMucTieu,h.GiaTriThucTe,h.TienDo,h.NhanXet,h.NguoiCapNhat,h.TaoLuc FROM NhatKyKetQuaKPI h JOIN NhanVien n ON n.MaNV=h.MaNV JOIN MucTieuKPI g ON g.MaMucTieu=h.MaMucTieu JOIN ChuKyKPI c ON c.MaChuKy=g.MaChuKy WHERE h.MaNV=? ORDER BY h.TaoLuc DESC", (own_id,))[1]
    return render_template("performance.html", cycles=cycles, open_cycle_ids=open_cycle_ids, departments=departments, people=people, goals=goals, evaluations=evaluations, plans=plans, competencies=competencies, competency_scores=competency_scores, history=history, goal_history=goal_history, feedback=feedback, admin=kpi_manage, can_approve=has_permission("kpi.approve"), is_manager=is_manager(), today=date.today().isoformat(), own_id=own_id)

@app.route("/dao-tao-ky-nang", methods=["GET", "POST"])
@login_required
def training_skills():
    own_id = int(session.get("user", {}).get("manv") or 0)
    manage = has_permission("training.manage")
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            if action == "course" and manage:
                title = request.form.get("TenKhoa", "").strip()
                hours, validity = float(request.form.get("SoGio") or 0), request.form.get("HieuLucChungChiThang") or None
                if not title or len(title) > 160 or not math.isfinite(hours) or hours < 0 or (validity and int(validity) not in range(1, 601)):
                    raise ValueError("Thông tin khóa học không hợp lệ.")
                db.execute("INSERT INTO KhoaDaoTao(TenKhoa,NhaCungCap,MoTa,SoGio,HieuLucChungChiThang,NguoiTao) VALUES(?,?,?,?,?,?)", (title, request.form.get("NhaCungCap", "").strip()[:120] or None, request.form.get("MoTa", "").strip()[:1000] or None, hours, validity, actor))
                flash("Đã tạo khóa đào tạo.", "success")
            elif action == "toggle_course" and manage:
                db.execute("UPDATE KhoaDaoTao SET TrangThai=CASE WHEN TrangThai=1 THEN 0 ELSE 1 END WHERE MaKhoa=?", (int(request.form["MaKhoa"]),))
                flash("Đã cập nhật trạng thái khóa học.", "success")
            elif action == "enroll":
                employee_id = int(request.form["MaNV"]) if manage and request.form.get("MaNV") else own_id
                course_id = int(request.form["MaKhoa"])
                if not employee_id or not db.scalar("SELECT COUNT(*) FROM KhoaDaoTao WHERE MaKhoa=? AND TrangThai=1", (course_id,)):
                    raise ValueError("Khóa đào tạo hoặc nhân viên không hợp lệ.")
                db.execute("IF EXISTS(SELECT 1 FROM DangKyDaoTao WHERE MaNV=? AND MaKhoa=? AND TrangThai IN (N'Từ chối',N'Đã hủy')) UPDATE DangKyDaoTao SET TrangThai=N'Chờ duyệt',NgayDangKy=CAST(GETDATE() AS DATE),GhiChu=NULL,NguoiDuyet=NULL,DuyetLuc=NULL WHERE MaNV=? AND MaKhoa=? ELSE IF NOT EXISTS(SELECT 1 FROM DangKyDaoTao WHERE MaNV=? AND MaKhoa=?) INSERT INTO DangKyDaoTao(MaNV,MaKhoa) VALUES(?,?)", (employee_id, course_id, employee_id, course_id, employee_id, course_id, employee_id, course_id))
                flash("Đã gửi đăng ký khóa học.", "success")
            elif action == "training_update" and manage:
                registration_id = int(request.form["MaDangKy"])
                status = request.form.get("TrangThai", "")
                if status not in ("Đang học", "Hoàn thành", "Từ chối", "Đã hủy"):
                    raise ValueError("Trạng thái đào tạo không hợp lệ.")
                completed = date.fromisoformat(request.form["NgayHoanThanh"]) if request.form.get("NgayHoanThanh") else None
                expiry = date.fromisoformat(request.form["HanChungChi"]) if request.form.get("HanChungChi") else None
                certificate = request.form.get("TenChungChi", "").strip()[:160] or None
                if status == "Hoàn thành" and not completed:
                    raise ValueError("Nhập ngày hoàn thành trước khi xác nhận khóa học.")
                db.execute("UPDATE DangKyDaoTao SET TrangThai=?,NgayBatDau=COALESCE(NgayBatDau,CAST(GETDATE() AS DATE)),NgayHoanThanh=?,TenChungChi=?,HanChungChi=?,NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME() WHERE MaDangKy=?", (status, completed, certificate, expiry, actor, registration_id))
                flash("Đã cập nhật hồ sơ đào tạo.", "success")
            elif action == "skill_catalog" and manage:
                name = request.form.get("TenKyNang", "").strip()
                if not name or len(name) > 100:
                    raise ValueError("Tên kỹ năng bắt buộc, tối đa 100 ký tự.")
                db.execute("INSERT INTO KyNang(TenKyNang,LinhVuc) VALUES(?,?)", (name, request.form.get("LinhVuc", "").strip()[:80] or None))
                flash("Đã thêm kỹ năng vào danh mục.", "success")
            elif action == "skill":
                employee_id = int(request.form["MaNV"]) if manage and request.form.get("MaNV") else own_id
                skill_id, level = int(request.form["MaKyNang"]), int(request.form.get("CapDo") or 0)
                target_level = int(request.form["MucTieuCapDo"]) if request.form.get("MucTieuCapDo") else None
                if not employee_id or level not in range(1, 6) or (target_level is not None and target_level not in range(1, 6)):
                    raise ValueError("Cấp độ kỹ năng phải từ 1 đến 5.")
                verified = actor if manage else None
                db.execute("IF EXISTS(SELECT 1 FROM NhanVienKyNang WHERE MaNV=? AND MaKyNang=?) UPDATE NhanVienKyNang SET CapDo=?,MucTieuCapDo=?,DuocXacNhanBoi=?,CapNhatLuc=SYSUTCDATETIME() WHERE MaNV=? AND MaKyNang=? ELSE INSERT INTO NhanVienKyNang(MaNV,MaKyNang,CapDo,MucTieuCapDo,DuocXacNhanBoi) VALUES(?,?,?,?,?)", (employee_id, skill_id, level, target_level, verified, employee_id, skill_id, employee_id, skill_id, level, target_level, verified))
                flash("Đã lưu kỹ năng và cấp độ.", "success")
            elif action == "development_plan":
                employee_id = int(request.form["MaNV"]) if manage and request.form.get("MaNV") else own_id
                skills = request.form.get("KyNangCanPhatTrien", "").strip()
                due = date.fromisoformat(request.form["HanMucTieu"]) if request.form.get("HanMucTieu") else None
                if not employee_id or not skills or len(skills) > 1000:
                    raise ValueError("Nhập kỹ năng cần phát triển, tối đa 1000 ký tự.")
                db.execute("INSERT INTO KeHoachPhatTrien(MaNV,TenVaiTroMucTieu,KyNangCanPhatTrien,HanMucTieu,NguoiTao,TrangThai) VALUES(?,?,?,?,?,N'Chờ quản lý')", (employee_id, request.form.get("TenVaiTroMucTieu", "").strip()[:120] or None, skills, due, actor))
                flash("Đã tạo kế hoạch phát triển.", "success")
            else:
                raise ValueError("Thao tác đào tạo không hợp lệ hoặc không đủ quyền.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("training_skills"))
    courses = db.query("SELECT MaKhoa,TenKhoa,NhaCungCap,MoTa,SoGio,HieuLucChungChiThang,TrangThai FROM KhoaDaoTao ORDER BY TenKhoa")[1]
    if manage:
        registrations = db.query("SELECT d.MaDangKy,n.HoTen,k.TenKhoa,d.TrangThai,d.NgayDangKy,d.NgayBatDau,d.NgayHoanThanh,d.TenChungChi,d.HanChungChi,d.GhiChu FROM DangKyDaoTao d JOIN NhanVien n ON n.MaNV=d.MaNV JOIN KhoaDaoTao k ON k.MaKhoa=d.MaKhoa ORDER BY d.NgayDangKy DESC")[1]
        skill_rows = db.query("SELECT n.MaNV,n.HoTen,k.TenKyNang,s.CapDo,s.MucTieuCapDo,s.DuocXacNhanBoi,s.MaKyNang FROM NhanVienKyNang s JOIN NhanVien n ON n.MaNV=s.MaNV JOIN KyNang k ON k.MaKyNang=s.MaKyNang ORDER BY n.HoTen,k.TenKyNang")[1]
        plans = db.query("SELECT p.MaKeHoach,n.HoTen,p.TenVaiTroMucTieu,p.KyNangCanPhatTrien,p.HanMucTieu,p.TrangThai FROM KeHoachPhatTrien p JOIN NhanVien n ON n.MaNV=p.MaNV ORDER BY p.HanMucTieu")[1]
        people = db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
    else:
        registrations = db.query("SELECT d.MaDangKy,n.HoTen,k.TenKhoa,d.TrangThai,d.NgayDangKy,d.NgayBatDau,d.NgayHoanThanh,d.TenChungChi,d.HanChungChi,d.GhiChu FROM DangKyDaoTao d JOIN NhanVien n ON n.MaNV=d.MaNV JOIN KhoaDaoTao k ON k.MaKhoa=d.MaKhoa WHERE d.MaNV=? ORDER BY d.NgayDangKy DESC", (own_id,))[1]
        skill_rows = db.query("SELECT n.MaNV,n.HoTen,k.TenKyNang,s.CapDo,s.MucTieuCapDo,s.DuocXacNhanBoi,s.MaKyNang FROM NhanVienKyNang s JOIN NhanVien n ON n.MaNV=s.MaNV JOIN KyNang k ON k.MaKyNang=s.MaKyNang WHERE s.MaNV=? ORDER BY k.TenKyNang", (own_id,))[1]
        plans = db.query("SELECT p.MaKeHoach,n.HoTen,p.TenVaiTroMucTieu,p.KyNangCanPhatTrien,p.HanMucTieu,p.TrangThai FROM KeHoachPhatTrien p JOIN NhanVien n ON n.MaNV=p.MaNV WHERE p.MaNV=? ORDER BY p.HanMucTieu", (own_id,))[1]
        people = []
    skills = db.query("SELECT MaKyNang,TenKyNang,LinhVuc FROM KyNang WHERE TrangThai=1 ORDER BY TenKyNang")[1]
    return render_template("training.html", courses=courses, registrations=registrations, skills=skills, skill_rows=skill_rows, plans=plans, people=people, admin=manage, own_id=own_id)


@app.route("/phuc-loi", methods=["GET", "POST"])
@login_required
def benefits():
    own_id = int(session.get("user", {}).get("manv") or 0)
    manage = has_permission("benefits.manage")
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            if action == "benefit" and manage:
                name = request.form.get("TenPhucLoi", "").strip()
                if not name or len(name) > 120:
                    raise ValueError("Tên quyền lợi bắt buộc, tối đa 120 ký tự.")
                db.execute("INSERT INTO PhucLoi(TenPhucLoi,MoTa,DieuKienHuong,NguoiTao) VALUES(?,?,?,?)", (name, request.form.get("MoTa", "").strip()[:1000] or None, request.form.get("DieuKienHuong", "").strip()[:1000] or None, actor))
                flash("Đã thêm quyền lợi.", "success")
            elif action == "toggle" and manage:
                db.execute("UPDATE PhucLoi SET TrangThai=CASE WHEN TrangThai=1 THEN 0 ELSE 1 END WHERE MaPhucLoi=?", (int(request.form["MaPhucLoi"]),))
                flash("Đã cập nhật trạng thái quyền lợi.", "success")
            elif action == "enroll":
                employee_id = int(request.form["MaNV"]) if manage and request.form.get("MaNV") else own_id
                benefit_id = int(request.form["MaPhucLoi"])
                if not employee_id or not db.scalar("SELECT COUNT(*) FROM PhucLoi WHERE MaPhucLoi=? AND TrangThai=1", (benefit_id,)):
                    raise ValueError("Quyền lợi không còn khả dụng hoặc nhân viên không hợp lệ.")
                db.execute("IF EXISTS(SELECT 1 FROM DangKyPhucLoi WHERE MaNV=? AND MaPhucLoi=? AND TrangThai IN (N'Từ chối',N'Đã hủy')) UPDATE DangKyPhucLoi SET TrangThai=N'Chờ duyệt',NgayDangKy=CAST(GETDATE() AS DATE),GhiChu=?,NguoiDuyet=NULL,DuyetLuc=NULL WHERE MaNV=? AND MaPhucLoi=? ELSE IF NOT EXISTS(SELECT 1 FROM DangKyPhucLoi WHERE MaNV=? AND MaPhucLoi=?) INSERT INTO DangKyPhucLoi(MaNV,MaPhucLoi,GhiChu) VALUES(?,?,?)", (employee_id, benefit_id, request.form.get("GhiChu", "").strip()[:500] or None, employee_id, benefit_id, employee_id, benefit_id, employee_id, benefit_id, request.form.get("GhiChu", "").strip()[:500] or None))
                flash("Đã gửi đăng ký quyền lợi để HR xác minh điều kiện.", "success")
            elif action == "review" and manage:
                registration_id = int(request.form["MaDangKy"])
                status = request.form.get("TrangThai")
                if status not in ("Đã duyệt", "Từ chối", "Đã hủy"):
                    raise ValueError("Trạng thái đăng ký quyền lợi không hợp lệ.")
                db.execute("UPDATE DangKyPhucLoi SET TrangThai=?,NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME() WHERE MaDangKy=? AND TrangThai=N'Chờ duyệt'", (status, actor, registration_id))
                flash("Đã cập nhật đăng ký quyền lợi.", "success")
            else:
                raise ValueError("Thao tác phúc lợi không hợp lệ hoặc không đủ quyền.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("benefits"))
    catalog = db.query("SELECT MaPhucLoi,TenPhucLoi,MoTa,DieuKienHuong,TrangThai FROM PhucLoi ORDER BY TenPhucLoi")[1]
    query = "SELECT d.MaDangKy,n.HoTen,b.TenPhucLoi,d.TrangThai,d.NgayDangKy,d.GhiChu,d.NguoiDuyet,d.MaNV FROM DangKyPhucLoi d JOIN NhanVien n ON n.MaNV=d.MaNV JOIN PhucLoi b ON b.MaPhucLoi=d.MaPhucLoi"
    rows = db.query(query + (" ORDER BY d.NgayDangKy DESC" if manage else " WHERE d.MaNV=? ORDER BY d.NgayDangKy DESC"), (() if manage else (own_id,)))[1]
    people = db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1] if manage else []
    return render_template("benefits.html", catalog=catalog, rows=rows, people=people, admin=manage)


@app.route("/hoach-dinh-nhan-luc", methods=["GET", "POST"])
@login_required
def workforce_planning():
    if not has_permission("headcount.manage"):
        return "Chỉ quản trị viên được xem kế hoạch nhân lực.", 403
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            if action == "headcount":
                year, department = int(request.form.get("Nam") or 0), int(request.form.get("MaPB") or 0)
                position = request.form.get("MaViTri") or None
                count = int(request.form.get("SoLuongKeHoach") or -1)
                cost = float(request.form.get("ChiPhiDuKien") or -1)
                if year not in range(2000, 2101) or not department or count not in range(0, 50001) or not math.isfinite(cost) or cost < 0:
                    raise ValueError("Năm, đơn vị, số lượng hoặc ngân sách dự kiến không hợp lệ.")
                if position and not db.scalar("SELECT COUNT(*) FROM ViTriCongViec WHERE MaViTri=? AND (MaPB IS NULL OR MaPB=?)", (position, department)):
                    raise ValueError("Vị trí công việc không thuộc phòng ban đã chọn.")
                db.execute("INSERT INTO KeHoachDinhBien(Nam,MaPB,MaViTri,SoLuongKeHoach,ChiPhiDuKien,LyDo,NguoiTao) VALUES(?,?,?,?,?,?,?)", (year, department, position, count, cost, request.form.get("LyDo", "").strip()[:500] or None, actor))
                flash("Đã tạo bản ghi kế hoạch headcount/chi phí.", "success")
            elif action == "plan_status":
                status = request.form.get("TrangThai", "")
                if status not in ("Nháp", "Đề xuất", "Đã duyệt", "Đã đóng"):
                    raise ValueError("Trạng thái kế hoạch không hợp lệ.")
                db.execute("UPDATE KeHoachDinhBien SET TrangThai=? WHERE MaKeHoach=?", (status, int(request.form["MaKeHoach"])))
                flash("Đã cập nhật trạng thái kế hoạch.", "success")
            elif action == "succession":
                position, employee_id = int(request.form["MaViTri"]), int(request.form["MaNV"])
                readiness = request.form.get("MucDoSanSang", "")
                if readiness not in ("Sẵn sàng", "6-12 tháng", "12-24 tháng", "Cần phát triển") or not db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'", (employee_id,)):
                    raise ValueError("Nhân viên kế nhiệm hoặc mức độ sẵn sàng không hợp lệ.")
                db.execute("INSERT INTO KeHoachKeNhiem(MaViTri,MaNV,MucDoSanSang,KhoangTrongKyNang,GhiChu,NguoiTao) VALUES(?,?,?,?,?,?)", (position, employee_id, readiness, request.form.get("KhoangTrongKyNang", "").strip()[:1000] or None, request.form.get("GhiChu", "").strip()[:500] or None, actor))
                flash("Đã ghi nhận ứng viên kế nhiệm.", "success")
            else:
                raise ValueError("Thao tác hoạch định nhân lực không hợp lệ.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("workforce_planning"))
    plans = db.query("SELECT p.MaKeHoach,p.Nam,b.TenPB,v.TenViTri,p.SoLuongKeHoach,p.ChiPhiDuKien,p.TrangThai,p.LyDo,COUNT(n.MaNV),ISNULL(SUM(n.LuongCoBan),0) FROM KeHoachDinhBien p JOIN PhongBan b ON b.MaPB=p.MaPB LEFT JOIN ViTriCongViec v ON v.MaViTri=p.MaViTri LEFT JOIN NhanVien n ON n.MaPB=p.MaPB AND n.TrangThai=N'Đang làm' AND (p.MaViTri IS NULL OR n.MaViTri=p.MaViTri) GROUP BY p.MaKeHoach,p.Nam,b.TenPB,v.TenViTri,p.SoLuongKeHoach,p.ChiPhiDuKien,p.TrangThai,p.LyDo ORDER BY p.Nam DESC,b.TenPB")[1]
    successors = db.query("SELECT k.MaKeNhiem,v.TenViTri,n.MaNV,n.HoTen,k.MucDoSanSang,k.KhoangTrongKyNang,k.GhiChu FROM KeHoachKeNhiem k JOIN ViTriCongViec v ON v.MaViTri=k.MaViTri JOIN NhanVien n ON n.MaNV=k.MaNV ORDER BY v.TenViTri,n.HoTen")[1]
    candidate_skills = {}
    for manv, skill, level in db.query("SELECT s.MaNV,k.TenKyNang,s.CapDo FROM NhanVienKyNang s JOIN KyNang k ON k.MaKyNang=s.MaKyNang", ())[1]:
        candidate_skills.setdefault(manv, []).append(f"{skill} ({level}/5)")
    departments = db.query("SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB")[1]
    positions = db.query("SELECT MaViTri,TenViTri FROM ViTriCongViec WHERE TrangThai=1 ORDER BY TenViTri")[1]
    people = db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1]
    return render_template("workforce_planning.html", plans=plans, successors=successors, candidate_skills=candidate_skills, departments=departments, positions=positions, people=people, admin=True, year=date.today().year)


@app.route("/phan-tich-nhan-su")
@login_required
def hr_analytics():
    if not has_permission("reports.hr"):
        return "Chỉ quản trị viên được xem phân tích nhân sự tổng hợp.", 403
    current = date.today().replace(day=1)
    month_starts = []
    year, month = current.year, current.month
    for _ in range(12):
        month_starts.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    month_starts.reverse()
    first_month, after_last = month_starts[0], date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    hires = {(row[0], row[1]): row[2] for row in db.query("SELECT YEAR(NgayVaoLam),MONTH(NgayVaoLam),COUNT(*) FROM NhanVien WHERE NgayVaoLam>=? AND NgayVaoLam<? GROUP BY YEAR(NgayVaoLam),MONTH(NgayVaoLam)", (first_month, after_last))[1]}
    exits = {(row[0], row[1]): row[2] for row in db.query("SELECT YEAR(NgayHieuLucKetThuc),MONTH(NgayHieuLucKetThuc),COUNT(*) FROM VongDoiNhanVien WHERE GiaiDoan=N'Offboarding' AND TrangThai=N'Hoàn tất' AND NgayHieuLucKetThuc>=? AND NgayHieuLucKetThuc<? GROUP BY YEAR(NgayHieuLucKetThuc),MONTH(NgayHieuLucKetThuc)", (first_month, after_last))[1]}
    trend = [{"month": item.strftime("%m/%Y"), "hires": hires.get((item.year, item.month), 0), "exits": exits.get((item.year, item.month), 0)} for item in month_starts]
    departments = db.query("SELECT ISNULL(p.TenPB,N'(Chưa phân phòng)'),COUNT(*),ISNULL(SUM(n.LuongCoBan),0) FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB WHERE n.TrangThai=N'Đang làm' GROUP BY p.TenPB ORDER BY 2 DESC")[1]
    skills = db.query("SELECT k.TenKyNang,COUNT(DISTINCT n.MaNV),AVG(CASE WHEN n.MaNV IS NOT NULL THEN CAST(s.CapDo AS DECIMAL(5,2)) END) FROM KyNang k LEFT JOIN NhanVienKyNang s ON s.MaKyNang=k.MaKyNang LEFT JOIN NhanVien n ON n.MaNV=s.MaNV AND n.TrangThai=N'Đang làm' WHERE k.TrangThai=1 GROUP BY k.TenKyNang ORDER BY 2 DESC,k.TenKyNang")[1]
    training = db.query("SELECT TrangThai,COUNT(*) FROM DangKyDaoTao GROUP BY TrangThai ORDER BY TrangThai")[1]
    stats = {
        "active": db.scalar("SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm'") or 0,
        "new_12m": sum(item["hires"] for item in trend),
        "exits_12m": sum(item["exits"] for item in trend),
        "leave_pending": db.scalar("SELECT COUNT(*) FROM NghiPhep WHERE TrangThai LIKE N'Chờ%'") or 0,
    }
    peak = max([1] + [max(item["hires"], item["exits"]) for item in trend])
    return render_template("hr_analytics.html", trend=trend, peak=peak, departments=departments, skills=skills, training=training, stats=stats, admin=True)


@app.route("/")
@login_required
def dashboard():
    if not admin():
        return redirect(url_for("chamcong"))
    stats = {}
    try:
        stat_columns, stat_rows = db.query(
            """SELECT
                (SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm') AS staff,
                (SELECT COUNT(*) FROM PhongBan) AS departments,
                (SELECT COUNT(*) FROM HopDong WHERE TrangThai IN (N'Còn hiệu lực',N'Đã ký') AND NgayBatDau<=CAST(GETDATE() AS DATE) AND (NgayKetThuc IS NULL OR NgayKetThuc>=CAST(GETDATE() AS DATE))) AS contracts,
                (SELECT COUNT(*) FROM NghiPhep WHERE TrangThai LIKE N'Chờ%') AS leaves"""
        )
        stats = dict(zip(stat_columns, stat_rows[0]))
        cols, rows = db.query(
            "SELECT TOP 8 ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) AS [Mã NV],HoTen AS [Họ tên],Email,TrangThai AS [Trạng thái] FROM NhanVien ORDER BY MaNV DESC"
        )
    except Exception as e:
        stats["error"] = _safe_error(e, "Không tải được số liệu tổng quan.")
        cols, rows = [], []
    return render_template(
        "dashboard.html",
        stats=stats,
        cols=cols,
        rows=rows,
        admin=admin(),
        now=date.today().strftime("%d/%m/%Y"),
    )


def friendly_delete_error(e):
    s = str(e)
    if "REFERENCE constraint" in s or "FOREIGN KEY" in s:
        return "Không thể xóa vì bản ghi này đang được dùng ở dữ liệu khác (ví dụ phòng ban/chức vụ còn nhân viên). Hãy chuyển hoặc xóa dữ liệu liên quan trước."
    return _safe_error(e, "Không thể xóa dữ liệu lúc này.")


def delete_record(key, m, id_):
    if key == "nhanvien":
        if str(session["user"].get("manv") or "") == str(id_):
            raise ValueError(
                "Không thể xóa nhân viên đang gắn với tài khoản bạn đang đăng nhập."
            )
        # Giữ lại toàn bộ hồ sơ đã tham gia nghiệp vụ để bảo toàn lịch sử.
        if db.scalar(
            "SELECT COUNT(*) FROM QuanLyTrucTiep WHERE MaQuanLy=? OR MaNV=?",
            (id_, id_),
        ):
            raise ValueError(
                "Hồ sơ này đang có liên kết quản lý trực tiếp. Hãy xử lý liên kết trước khi xóa."
            )
        if db.scalar(
            "SELECT COUNT(*) FROM NhanVienNguon WHERE MaNV=? AND LoaiNguon<>N'manual'",
            (id_,),
        ):
            raise ValueError(
                "Hồ sơ này đang được liên kết với nguồn nghiệp vụ khác. Hãy chuyển trạng thái nhân viên thay vì xóa."
            )
        if db.scalar(
            "SELECT (SELECT COUNT(*) FROM Luong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM ChamCong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM NghiPhep WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM HopDong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM NhatKyChamCong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM KhieuNaiChamCong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM NhatKyNghiPhep WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM NhatKyLuong WHERE MaNV=?)",
            (id_,) * 8,
        ):
            raise ValueError(
                "Nhân viên này đã có lịch sử nghiệp vụ nên không xóa để tránh mất dữ liệu. "
                "Hãy sửa hồ sơ và chuyển Trạng thái sang “Đã nghỉ việc”."
            )
        if db.scalar("SELECT COUNT(*) FROM LichSuCongTac WHERE MaNV=?", (id_,)) > 1:
            raise ValueError("Hồ sơ có nhiều giai đoạn công tác. Hãy chuyển trạng thái sang Đã nghỉ việc để giữ lịch sử.")
        if db.scalar("SELECT COUNT(*) FROM HoSoTepNhanVien WHERE MaNV=?", (id_,)) or db.scalar("SELECT COUNT(*) FROM GiaTriMoRongNhanVien WHERE MaNV=?", (id_,)):
            raise ValueError("Hồ sơ có tài liệu hoặc dữ liệu mở rộng. Hãy chuyển trạng thái sang Đã nghỉ việc để bảo toàn hồ sơ.")
        # Nhân viên chưa có lịch sử nghiệp vụ: xóa cùng dữ liệu phụ trong 1 giao dịch.
        if db.scalar("SELECT OBJECT_ID('LichSuDieuChuyen','U')") and db.scalar(
            "SELECT COUNT(*) FROM LichSuDieuChuyen WHERE MaNV=?", (id_,)
        ):
            raise ValueError(
                "Nhân viên đã có lịch sử điều chuyển. Hãy chuyển trạng thái sang Đã nghỉ việc để giữ lịch sử."
            )
        db.execute(
            "SET NOCOUNT ON; SET XACT_ABORT ON; BEGIN TRAN; "
            "INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'xoa',N'*',?); "
            "IF OBJECT_ID('LichSuDieuChuyen','U') IS NOT NULL DELETE FROM LichSuDieuChuyen WHERE MaNV=?; "
            "DELETE FROM NghiPhep WHERE MaNV=?; DELETE FROM LichSuCongTac WHERE MaNV=?; DELETE FROM NhatKyHoSoTep WHERE MaNV=?; DELETE FROM NhatKyTruongNhanVien WHERE MaNV=?; DELETE FROM QuanLyTrucTiep WHERE MaQuanLy=?; "
            "DELETE FROM QuanLyTrucTiep WHERE MaNV=?; DELETE FROM HopDong WHERE MaNV=?; "
            "DELETE FROM TaiKhoan WHERE MaNV=?; "
            "DELETE FROM NhanVienNguon WHERE MaNV=? AND LoaiNguon=N'manual'; "
            "DELETE FROM NhanVien WHERE MaNV=?; COMMIT;",
            (id_, session["user"]["user"]) + (id_,) * 11,
        )
    elif key == "hopdong":
        status = db.scalar("SELECT TrangThai FROM HopDong WHERE MaHD=?", (id_,))
        if status != "Bản nháp" or db.scalar("SELECT COUNT(*) FROM TepHopDong WHERE MaHD=?", (id_,)) or db.scalar("SELECT COUNT(*) FROM LichSuHopDong WHERE MaHD=?", (id_,)):
            raise ValueError("Hợp đồng đã có tài liệu hoặc lịch sử; không thể xóa để bảo toàn vòng đời.")
        db.execute("DELETE FROM HopDong WHERE MaHD=?", (id_,))
    else:
        db.execute(f"DELETE FROM {m['table']} WHERE {m['pk']}=?", (id_,))


_KY_MAC_DINH = {
    "nhan su": "NS",
    "ke toan": "KTO",
    "kinh doanh": "KD",
    "ky thuat": "KT",
    "marketing": "MKT",
}


def _bo_dau(t):
    t = unicodedata.normalize("NFD", t.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def assign_codes():
    """Cấp Mã NV hiển thị = NV + số thứ tự chung 2 chữ số + ký hiệu phòng ở cuối (NV01KT, NV02NS...)."""
    rows = db.query(
        "SELECT n.MaNV,p.KyHieu FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB WHERE n.MaNVHT IS NULL ORDER BY n.MaNV"
    )[1]
    if not rows:
        return
    mx = 0
    for (code,) in db.query("SELECT MaNVHT FROM NhanVien WHERE MaNVHT IS NOT NULL")[1]:
        m = re.fullmatch(r"NV(\d+)[A-Z]*", code or "")
        if m:
            mx = max(mx, int(m.group(1)))
    for manv, ky in rows:
        mx += 1
        db.execute(
            "UPDATE NhanVien SET MaNVHT=? WHERE MaNV=?",
            ("NV%02d%s" % (mx, (ky or "").upper()), manv),
        )


def ensure_schema():
    db.execute(
        "IF OBJECT_ID('DonVi','U') IS NULL CREATE TABLE DonVi(MaDonVi INT IDENTITY PRIMARY KEY,TenDonVi NVARCHAR(120) NOT NULL UNIQUE,MaDonViCha INT NULL REFERENCES DonVi(MaDonVi),TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Hoạt động')"
    )
    db.execute(
        "IF COL_LENGTH('PhongBan','MaDonVi') IS NULL ALTER TABLE PhongBan ADD MaDonVi INT NULL REFERENCES DonVi(MaDonVi)"
    )
    db.execute(
        "IF COL_LENGTH('PhongBan','MaPBCha') IS NULL ALTER TABLE PhongBan ADD MaPBCha INT NULL REFERENCES PhongBan(MaPB)"
    )
    db.execute(
        "IF OBJECT_ID('ViTriCongViec','U') IS NULL CREATE TABLE ViTriCongViec(MaViTri INT IDENTITY PRIMARY KEY,TenViTri NVARCHAR(120) NOT NULL,MaPB INT NULL REFERENCES PhongBan(MaPB),MoTa NVARCHAR(255) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Hoạt động',CONSTRAINT UQ_ViTriCongViec UNIQUE(TenViTri,MaPB))"
    )
    db.execute(
        "IF COL_LENGTH('NhanVien','MaViTri') IS NULL ALTER TABLE NhanVien ADD MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri)"
    )
    db.execute(
        "IF OBJECT_ID('LichSuCongTac','U') IS NULL CREATE TABLE LichSuCongTac(MaLichSu BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),TuNgay DATE NOT NULL,DenNgay DATE NULL,MaPB INT NULL REFERENCES PhongBan(MaPB),MaCV INT NULL REFERENCES ChucVu(MaCV),MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri),MaQuanLy INT NULL REFERENCES NhanVien(MaNV),LuongCoBan DECIMAL(18,0) NOT NULL DEFAULT 0,NguoiCapNhat NVARCHAR(50) NOT NULL,LyDo NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CONSTRAINT CK_LichSuCongTac_Ngay CHECK(DenNgay IS NULL OR DenNgay>=TuNgay))"
    )
    db.execute("IF OBJECT_ID('NhatKyHoSoNhanVien','U') IS NULL CREATE TABLE NhatKyHoSoNhanVien(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL,HanhDong NVARCHAR(20) NOT NULL,TruongDuLieu NVARCHAR(80) NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('NhatKyTruyCapNhanSu','U') IS NULL CREATE TABLE NhatKyTruyCapNhanSu(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaNV INT NULL,LoaiDuLieu NVARCHAR(30) NOT NULL CHECK(LoaiDuLieu IN (N'CCCD',N'LienHe',N'Luong',N'HopDong',N'HoSoDienTu')),ThaoTac NVARCHAR(12) NOT NULL CHECK(ThaoTac IN (N'view',N'list',N'download',N'export')),NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF COL_LENGTH('LichSuCongTac','MaQuanLy') IS NULL ALTER TABLE LichSuCongTac ADD MaQuanLy INT NULL REFERENCES NhanVien(MaNV)")
    db.execute(
        "INSERT INTO LichSuCongTac(MaNV,TuNgay,MaPB,MaCV,MaViTri,MaQuanLy,LuongCoBan,NguoiCapNhat,LyDo) SELECT n.MaNV,CAST(GETDATE() AS DATE),n.MaPB,n.MaCV,n.MaViTri,NULL,n.LuongCoBan,N'system',N'Khởi tạo mốc hiện trạng khi nâng cấp' FROM NhanVien n WHERE NOT EXISTS(SELECT 1 FROM LichSuCongTac l WHERE l.MaNV=n.MaNV AND l.DenNgay IS NULL)"
    )
    db.execute(
        "IF OBJECT_ID('HoSoTepNhanVien','U') IS NULL CREATE TABLE HoSoTepNhanVien(MaTep BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),LoaiTaiLieu NVARCHAR(60) NOT NULL,TenTep NVARCHAR(180) NOT NULL,DinhDang NVARCHAR(20) NOT NULL,DuLieu VARBINARY(MAX) NOT NULL,NgayHieuLuc DATE NULL,HanLuuDen DATE NULL,NguoiTai NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyHoSoTep','U') IS NULL CREATE TABLE NhatKyHoSoTep(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaTep BIGINT NULL,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),ThaoTac NVARCHAR(30) NOT NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute("IF OBJECT_ID('TaiSanNhanVien','U') IS NULL CREATE TABLE TaiSanNhanVien(MaTaiSan BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),TenTaiSan NVARCHAR(120) NOT NULL,MaNoiBo NVARCHAR(60) NULL,Serial NVARCHAR(100) NULL,NgayCap DATE NOT NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang sử dụng' CHECK(TrangThai IN (N'Đang sử dụng',N'Đã thu hồi')),NgayThuHoi DATE NULL,TinhTrangThuHoi NVARCHAR(200) NULL,NguoiCap NVARCHAR(50) NOT NULL,NguoiThuHoi NVARCHAR(50) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('NhatKyTaiSanNhanVien','U') IS NULL CREATE TABLE NhatKyTaiSanNhanVien(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaTaiSan BIGINT NOT NULL REFERENCES TaiSanNhanVien(MaTaiSan),ThaoTac NVARCHAR(20) NOT NULL CHECK(ThaoTac IN (N'cấp',N'thu hồi')),NguoiThucHien NVARCHAR(50) NOT NULL,ChiTiet NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('TruongMoRongNhanVien','U') IS NULL CREATE TABLE TruongMoRongNhanVien(MaTruong INT IDENTITY PRIMARY KEY,TenTruong NVARCHAR(80) NOT NULL UNIQUE,KieuDuLieu NVARCHAR(12) NOT NULL CHECK(KieuDuLieu IN (N'text',N'number',N'date',N'boolean',N'email')),BatBuoc BIT NOT NULL DEFAULT 0,NhayCam BIT NOT NULL DEFAULT 0,TrangThai BIT NOT NULL DEFAULT 1,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('GiaTriMoRongNhanVien','U') IS NULL CREATE TABLE GiaTriMoRongNhanVien(MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaTruong INT NOT NULL REFERENCES TruongMoRongNhanVien(MaTruong),GiaTri NVARCHAR(1000) NOT NULL,CapNhatBoi NVARCHAR(50) NOT NULL,CapNhatLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CONSTRAINT PK_GiaTriMoRongNhanVien PRIMARY KEY(MaNV,MaTruong))")
    db.execute("IF OBJECT_ID('NhatKyTruongNhanVien','U') IS NULL CREATE TABLE NhatKyTruongNhanVien(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaTruong INT NOT NULL REFERENCES TruongMoRongNhanVien(MaTruong),NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute(
        "IF COL_LENGTH('PhongBan','KyHieu') IS NULL ALTER TABLE PhongBan ADD KyHieu NVARCHAR(10) NULL"
    )
    db.execute(
        "IF COL_LENGTH('NhanVien','MaNVHT') IS NULL ALTER TABLE NhanVien ADD MaNVHT NVARCHAR(20) NULL"
    )
    db.execute(
        "IF COL_LENGTH('NhanVien','AnhHoSo') IS NULL ALTER TABLE NhanVien ADD AnhHoSo VARBINARY(MAX) NULL"
    )
    db.execute(
        "IF OBJECT_ID('NhanVienNguon','U') IS NULL CREATE TABLE NhanVienNguon("
        "MaNguon BIGINT IDENTITY PRIMARY KEY,LoaiNguon NVARCHAR(30) NOT NULL,"
        "MaNguonNgoai NVARCHAR(100) NOT NULL,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),"
        "NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),"
        "CONSTRAINT UQ_NhanVienNguon UNIQUE(LoaiNguon,MaNguonNgoai))"
    )
    db.execute("IF OBJECT_ID('YeuCauTuyenDung','U') IS NULL CREATE TABLE YeuCauTuyenDung(MaYeuCau INT IDENTITY PRIMARY KEY,TieuDe NVARCHAR(120) NOT NULL,MaPB INT NULL REFERENCES PhongBan(MaPB),MaCV INT NULL REFERENCES ChucVu(MaCV),MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri),SoLuong SMALLINT NOT NULL DEFAULT 1,MoTa NVARCHAR(2000) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang tuyển',NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(SoLuong BETWEEN 1 AND 500))")
    db.execute("IF OBJECT_ID('UngVien','U') IS NULL CREATE TABLE UngVien(MaUngVien BIGINT IDENTITY PRIMARY KEY,MaYeuCau INT NOT NULL REFERENCES YeuCauTuyenDung(MaYeuCau),HoTen NVARCHAR(100) NOT NULL,Email NVARCHAR(100) NULL,SDT NVARCHAR(20) NULL,KenhNguon NVARCHAR(80) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Mới',MaNV INT NULL UNIQUE REFERENCES NhanVien(MaNV),NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('PhongVanUngVien','U') IS NULL CREATE TABLE PhongVanUngVien(MaPhongVan BIGINT IDENTITY PRIMARY KEY,MaUngVien BIGINT NOT NULL REFERENCES UngVien(MaUngVien),ThoiDiem DATETIME2 NOT NULL,HinhThuc NVARCHAR(40) NOT NULL,NguoiPhongVan NVARCHAR(100) NOT NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đã lên lịch',GhiChu NVARCHAR(1000) NULL,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('DanhGiaUngVien','U') IS NULL CREATE TABLE DanhGiaUngVien(MaDanhGia BIGINT IDENTITY PRIMARY KEY,MaPhongVan BIGINT NOT NULL REFERENCES PhongVanUngVien(MaPhongVan),Diem TINYINT NOT NULL CHECK(Diem BETWEEN 1 AND 5),NhanXet NVARCHAR(2000) NOT NULL,NguoiDanhGia NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('OfferUngVien','U') IS NULL CREATE TABLE OfferUngVien(MaOffer BIGINT IDENTITY PRIMARY KEY,MaUngVien BIGINT NOT NULL REFERENCES UngVien(MaUngVien),LuongDeXuat DECIMAL(18,0) NOT NULL,NgayBatDau DATE NOT NULL,HanPhanHoi DATE NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Bản nháp',MaNV INT NULL REFERENCES NhanVien(MaNV),NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(LuongDeXuat>=0),UNIQUE(MaUngVien))")
    db.execute("IF OBJECT_ID('MauChecklistNhanSu','U') IS NULL CREATE TABLE MauChecklistNhanSu(MaMau INT IDENTITY PRIMARY KEY,GiaiDoan NVARCHAR(20) NOT NULL CHECK(GiaiDoan IN (N'Onboarding',N'Offboarding')),TenViec NVARCHAR(160) NOT NULL,BoPhanPhuTrach NVARCHAR(80) NOT NULL,SoNgayHan SMALLINT NOT NULL DEFAULT 0,TrangThai BIT NOT NULL DEFAULT 1,UNIQUE(GiaiDoan,TenViec))")
    db.execute("IF OBJECT_ID('VongDoiNhanVien','U') IS NULL CREATE TABLE VongDoiNhanVien(MaVongDoi BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),GiaiDoan NVARCHAR(20) NOT NULL,NgayBatDau DATE NOT NULL,NgayHieuLucKetThuc DATE NULL,LyDo NVARCHAR(500) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang xử lý',NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(GiaiDoan IN (N'Onboarding',N'Offboarding'))) ")
    db.execute("IF OBJECT_ID('ChecklistNhanVien','U') IS NULL CREATE TABLE ChecklistNhanVien(MaChecklist BIGINT IDENTITY PRIMARY KEY,MaVongDoi BIGINT NOT NULL REFERENCES VongDoiNhanVien(MaVongDoi),MaNV INT NOT NULL REFERENCES NhanVien(MaNV),TenViec NVARCHAR(160) NOT NULL,BoPhanPhuTrach NVARCHAR(80) NOT NULL,HanHoanThanh DATE NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chưa làm',HoanThanhBoi NVARCHAR(50) NULL,HoanThanhLuc DATETIME2 NULL,GhiChu NVARCHAR(500) NULL)")
    db.execute("IF OBJECT_ID('ChuKyKPI','U') IS NULL CREATE TABLE ChuKyKPI(MaChuKy INT IDENTITY PRIMARY KEY,TenChuKy NVARCHAR(120) NOT NULL,TuNgay DATE NOT NULL,DenNgay DATE NOT NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang mở',NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(DenNgay>=TuNgay))")
    db.execute("IF OBJECT_ID('MucTieuKPI','U') IS NULL CREATE TABLE MucTieuKPI(MaMucTieu BIGINT IDENTITY PRIMARY KEY,MaChuKy INT NOT NULL REFERENCES ChuKyKPI(MaChuKy),MaNV INT NULL REFERENCES NhanVien(MaNV),MaPB INT NULL REFERENCES PhongBan(MaPB),TenMucTieu NVARCHAR(160) NOT NULL,MoTa NVARCHAR(1000) NULL,GiaTriMucTieu DECIMAL(18,2) NOT NULL,DonVi NVARCHAR(40) NOT NULL,TrongSo DECIMAL(5,2) NOT NULL DEFAULT 0,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(GiaTriMucTieu>=0),CHECK(TrongSo BETWEEN 0 AND 100),CHECK((MaNV IS NOT NULL AND MaPB IS NULL) OR (MaNV IS NULL AND MaPB IS NOT NULL)))")
    db.execute("IF OBJECT_ID('KetQuaKPI','U') IS NULL CREATE TABLE KetQuaKPI(MaKetQua BIGINT IDENTITY PRIMARY KEY,MaMucTieu BIGINT NOT NULL REFERENCES MucTieuKPI(MaMucTieu),MaNV INT NOT NULL REFERENCES NhanVien(MaNV),GiaTriThucTe DECIMAL(18,2) NOT NULL DEFAULT 0,TienDo DECIMAL(5,2) NOT NULL DEFAULT 0,NhanXet NVARCHAR(1000) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp',NguoiCapNhat NVARCHAR(50) NOT NULL,CapNhatLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,UNIQUE(MaMucTieu,MaNV),CHECK(GiaTriThucTe>=0),CHECK(TienDo BETWEEN 0 AND 100))")
    db.execute("IF OBJECT_ID('PhanHoiKPI','U') IS NULL CREATE TABLE PhanHoiKPI(MaPhanHoi BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaChuKy INT NULL REFERENCES ChuKyKPI(MaChuKy),NguoiGui NVARCHAR(50) NOT NULL,LoaiPhanHoi NVARCHAR(30) NOT NULL,NoiDung NVARCHAR(2000) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('NhatKyKetQuaKPI','U') IS NULL CREATE TABLE NhatKyKetQuaKPI(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaMucTieu BIGINT NOT NULL REFERENCES MucTieuKPI(MaMucTieu),MaNV INT NOT NULL REFERENCES NhanVien(MaNV),GiaTriThucTe DECIMAL(18,2) NOT NULL,TienDo DECIMAL(5,2) NOT NULL,NhanXet NVARCHAR(1000) NULL,NguoiCapNhat NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('DanhGiaKPIChuKy','U') IS NULL CREATE TABLE DanhGiaKPIChuKy(MaDanhGia BIGINT IDENTITY PRIMARY KEY,MaChuKy INT NOT NULL REFERENCES ChuKyKPI(MaChuKy),MaNV INT NOT NULL REFERENCES NhanVien(MaNV),DiemTuDanhGia DECIMAL(5,2) NULL,DiemQuanLy DECIMAL(5,2) NULL,DiemTongHop DECIMAL(5,2) NULL,NhanXetTuDanhGia NVARCHAR(2000) NULL,NhanXetQuanLy NVARCHAR(2000) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp',TuDanhGiaLuc DATETIME2 NULL,QuanLyBoi NVARCHAR(50) NULL,QuanLyLuc DATETIME2 NULL,HRBoi NVARCHAR(50) NULL,HRLuc DATETIME2 NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),UNIQUE(MaChuKy,MaNV),CHECK(DiemTuDanhGia IS NULL OR DiemTuDanhGia BETWEEN 0 AND 100),CHECK(DiemQuanLy IS NULL OR DiemQuanLy BETWEEN 0 AND 100),CHECK(DiemTongHop IS NULL OR DiemTongHop BETWEEN 0 AND 100))")
    db.execute("IF OBJECT_ID('NhatKyDanhGiaKPI','U') IS NULL CREATE TABLE NhatKyDanhGiaKPI(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaChuKy INT NOT NULL REFERENCES ChuKyKPI(MaChuKy),MaNV INT NOT NULL REFERENCES NhanVien(MaNV),ThaoTac NVARCHAR(40) NOT NULL,ChiTiet NVARCHAR(MAX) NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('KhungNangLuc','U') IS NULL CREATE TABLE KhungNangLuc(MaNangLuc INT IDENTITY PRIMARY KEY,TenNangLuc NVARCHAR(120) NOT NULL UNIQUE,NhomNangLuc NVARCHAR(80) NULL,MoTa NVARCHAR(1000) NULL,CapDoChuan TINYINT NOT NULL DEFAULT 3,TrangThai BIT NOT NULL DEFAULT 1,CHECK(CapDoChuan BETWEEN 1 AND 5))")
    db.execute("IF OBJECT_ID('DanhGiaNangLuc','U') IS NULL CREATE TABLE DanhGiaNangLuc(MaDanhGiaNangLuc BIGINT IDENTITY PRIMARY KEY,MaChuKy INT NOT NULL REFERENCES ChuKyKPI(MaChuKy),MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaNangLuc INT NOT NULL REFERENCES KhungNangLuc(MaNangLuc),DiemTuDanhGia TINYINT NULL,NhanXetTuDanhGia NVARCHAR(1000) NULL,DiemQuanLy TINYINT NULL,NhanXetQuanLy NVARCHAR(1000) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp',QuanLyBoi NVARCHAR(50) NULL,QuanLyLuc DATETIME2 NULL,HRBoi NVARCHAR(50) NULL,HRLuc DATETIME2 NULL,CapNhatLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),UNIQUE(MaChuKy,MaNV,MaNangLuc),CHECK(DiemTuDanhGia IS NULL OR DiemTuDanhGia BETWEEN 1 AND 5),CHECK(DiemQuanLy IS NULL OR DiemQuanLy BETWEEN 1 AND 5))")
    db.execute("IF OBJECT_ID('KhoaDaoTao','U') IS NULL CREATE TABLE KhoaDaoTao(MaKhoa INT IDENTITY PRIMARY KEY,TenKhoa NVARCHAR(160) NOT NULL,NhaCungCap NVARCHAR(120) NULL,MoTa NVARCHAR(1000) NULL,SoGio DECIMAL(6,2) NOT NULL DEFAULT 0,HieuLucChungChiThang SMALLINT NULL,TrangThai BIT NOT NULL DEFAULT 1,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(SoGio>=0),CHECK(HieuLucChungChiThang IS NULL OR HieuLucChungChiThang BETWEEN 1 AND 600))")
    db.execute("IF OBJECT_ID('DangKyDaoTao','U') IS NULL CREATE TABLE DangKyDaoTao(MaDangKy BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaKhoa INT NOT NULL REFERENCES KhoaDaoTao(MaKhoa),TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt',NgayDangKy DATE NOT NULL DEFAULT CAST(GETDATE() AS DATE),NgayBatDau DATE NULL,NgayHoanThanh DATE NULL,TenChungChi NVARCHAR(160) NULL,HanChungChi DATE NULL,GhiChu NVARCHAR(500) NULL,NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,UNIQUE(MaNV,MaKhoa))")
    db.execute("IF OBJECT_ID('KyNang','U') IS NULL CREATE TABLE KyNang(MaKyNang INT IDENTITY PRIMARY KEY,TenKyNang NVARCHAR(100) NOT NULL UNIQUE,LinhVuc NVARCHAR(80) NULL,TrangThai BIT NOT NULL DEFAULT 1)")
    db.execute("IF OBJECT_ID('NhanVienKyNang','U') IS NULL CREATE TABLE NhanVienKyNang(MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaKyNang INT NOT NULL REFERENCES KyNang(MaKyNang),CapDo TINYINT NOT NULL CHECK(CapDo BETWEEN 1 AND 5),MucTieuCapDo TINYINT NULL CHECK(MucTieuCapDo IS NULL OR MucTieuCapDo BETWEEN 1 AND 5),DuocXacNhanBoi NVARCHAR(50) NULL,CapNhatLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),PRIMARY KEY(MaNV,MaKyNang))")
    db.execute("IF OBJECT_ID('KeHoachPhatTrien','U') IS NULL CREATE TABLE KeHoachPhatTrien(MaKeHoach BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),TenVaiTroMucTieu NVARCHAR(120) NULL,KyNangCanPhatTrien NVARCHAR(1000) NOT NULL,HanMucTieu DATE NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang thực hiện',NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF COL_LENGTH('KeHoachPhatTrien','MaChuKy') IS NULL ALTER TABLE KeHoachPhatTrien ADD MaChuKy INT NULL REFERENCES ChuKyKPI(MaChuKy); IF COL_LENGTH('KeHoachPhatTrien','QuanLyDuyetBoi') IS NULL ALTER TABLE KeHoachPhatTrien ADD QuanLyDuyetBoi NVARCHAR(50) NULL,QuanLyDuyetLuc DATETIME2 NULL; IF COL_LENGTH('KeHoachPhatTrien','HRDuyetBoi') IS NULL ALTER TABLE KeHoachPhatTrien ADD HRDuyetBoi NVARCHAR(50) NULL,HRDuyetLuc DATETIME2 NULL")
    db.execute("IF OBJECT_ID('PhucLoi','U') IS NULL CREATE TABLE PhucLoi(MaPhucLoi INT IDENTITY PRIMARY KEY,TenPhucLoi NVARCHAR(120) NOT NULL UNIQUE,MoTa NVARCHAR(1000) NULL,DieuKienHuong NVARCHAR(1000) NULL,TrangThai BIT NOT NULL DEFAULT 1,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('DangKyPhucLoi','U') IS NULL CREATE TABLE DangKyPhucLoi(MaDangKy BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaPhucLoi INT NOT NULL REFERENCES PhucLoi(MaPhucLoi),TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt',NgayDangKy DATE NOT NULL DEFAULT CAST(GETDATE() AS DATE),GhiChu NVARCHAR(500) NULL,NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,UNIQUE(MaNV,MaPhucLoi))")
    db.execute("IF OBJECT_ID('KeHoachDinhBien','U') IS NULL CREATE TABLE KeHoachDinhBien(MaKeHoach INT IDENTITY PRIMARY KEY,Nam SMALLINT NOT NULL,MaPB INT NOT NULL REFERENCES PhongBan(MaPB),MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri),SoLuongKeHoach SMALLINT NOT NULL,ChiPhiDuKien DECIMAL(18,0) NOT NULL DEFAULT 0,LyDo NVARCHAR(500) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp',NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(Nam BETWEEN 2000 AND 2100),CHECK(SoLuongKeHoach BETWEEN 0 AND 50000),CHECK(ChiPhiDuKien>=0))")
    db.execute("IF OBJECT_ID('KeHoachKeNhiem','U') IS NULL CREATE TABLE KeHoachKeNhiem(MaKeNhiem BIGINT IDENTITY PRIMARY KEY,MaViTri INT NOT NULL REFERENCES ViTriCongViec(MaViTri),MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MucDoSanSang NVARCHAR(20) NOT NULL,KhoangTrongKyNang NVARCHAR(1000) NULL,GhiChu NVARCHAR(500) NULL,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(MucDoSanSang IN (N'Sẵn sàng',N'6-12 tháng',N'12-24 tháng',N'Cần phát triển')))")
    db.execute("INSERT INTO MauChecklistNhanSu(GiaiDoan,TenViec,BoPhanPhuTrach,SoNgayHan) SELECT v.GiaiDoan,v.TenViec,v.BoPhanPhuTrach,v.SoNgayHan FROM (VALUES (N'Onboarding',N'Hoàn tất và lưu hợp đồng',N'Nhân sự',2),(N'Onboarding',N'Tạo tài khoản và cấp quyền cần thiết',N'Công nghệ thông tin',0),(N'Onboarding',N'Cấp thiết bị làm việc',N'Công nghệ thông tin',1),(N'Onboarding',N'Giới thiệu nội quy và quy trình',N'Nhân sự',2),(N'Offboarding',N'Bàn giao công việc',N'Quản lý trực tiếp',0),(N'Offboarding',N'Thu hồi tài sản',N'Công nghệ thông tin',0),(N'Offboarding',N'Thu hồi hoặc khóa tài khoản',N'Công nghệ thông tin',0),(N'Offboarding',N'Đối soát công và quyền lợi',N'Nhân sự',0)) v(GiaiDoan,TenViec,BoPhanPhuTrach,SoNgayHan) WHERE NOT EXISTS(SELECT 1 FROM MauChecklistNhanSu m WHERE m.GiaiDoan=v.GiaiDoan AND m.TenViec=v.TenViec)")
    db.execute(
        "IF COL_LENGTH('TaiKhoan','SecurityVersion') IS NULL ALTER TABLE TaiKhoan ADD SecurityVersion INT NOT NULL CONSTRAINT DF_TaiKhoan_SecurityVersion DEFAULT 1"
    )
    db.execute("IF OBJECT_ID('CK_TaiKhoan_VaiTro','C') IS NULL BEGIN DECLARE @roleCheck SYSNAME; SELECT TOP (1) @roleCheck=name FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID('dbo.TaiKhoan') AND definition LIKE '%VaiTro%'; IF @roleCheck IS NOT NULL EXEC(N'ALTER TABLE dbo.TaiKhoan DROP CONSTRAINT '+QUOTENAME(@roleCheck)); ALTER TABLE dbo.TaiKhoan ADD CONSTRAINT CK_TaiKhoan_VaiTro CHECK(VaiTro IN (N'QuanTri',N'QuanTriHeThong',N'HR',N'KeToan',N'QuanLy',N'NhanVien')); END")
    db.execute("IF OBJECT_ID('NhatKyPhanQuyen','U') IS NULL CREATE TABLE NhatKyPhanQuyen(MaNhatKy BIGINT IDENTITY PRIMARY KEY,TenDN NVARCHAR(50) NOT NULL,VaiTroCu NVARCHAR(20) NULL,VaiTroMoi NVARCHAR(20) NULL,ThaoTac NVARCHAR(20) NOT NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute(
        "IF OBJECT_ID('MauHopDong','U') IS NULL CREATE TABLE MauHopDong(MaMau INT IDENTITY(1,1) PRIMARY KEY,TenMau NVARCHAR(120) NOT NULL,FileName NVARCHAR(180) NOT NULL,NoiDung NVARCHAR(MAX) NOT NULL,TepDocx VARBINARY(MAX) NOT NULL,NgayTai DATETIME2 NOT NULL DEFAULT SYSDATETIME())"
    )
    for col, typ in [
        ("ThuongCC", "DECIMAL(18,0)"),
        ("ThuongThem", "DECIMAL(18,0)"),
        ("GioTangCa", "DECIMAL(7,2)"),
        ("TienTangCa", "DECIMAL(18,0)"),
        ("SoLanMuon", "INT"),
        ("TruMuon", "DECIMAL(18,0)"),
        ("SoNgayNghiKP", "INT"),
        ("TruNghiKP", "DECIMAL(18,0)"),
    ]:
        db.execute(
            f"IF COL_LENGTH('Luong','{col}') IS NULL ALTER TABLE Luong ADD {col} {typ} NOT NULL DEFAULT 0"
        )
    db.execute(
        "IF COL_LENGTH('Luong','GioGhiNhan') IS NULL ALTER TABLE Luong ADD GioGhiNhan DECIMAL(8,2) NULL"
    )
    db.execute(
        "IF COL_LENGTH('Luong','LuongDieuChinh') IS NULL ALTER TABLE Luong ADD LuongDieuChinh DECIMAL(18,0) NULL"
    )
    db.execute(
        "IF OBJECT_ID('LuongCauHinhThang','U') IS NULL CREATE TABLE LuongCauHinhThang(Nam INT NOT NULL,Thang INT NOT NULL,TyLeThuongCC DECIMAL(6,4) NOT NULL,HeSoTangCa DECIMAL(5,2) NOT NULL,CONSTRAINT PK_LuongCauHinhThang PRIMARY KEY(Nam,Thang))"
    )
    pbs = db.query("SELECT MaPB,TenPB,KyHieu FROM PhongBan ORDER BY MaPB")[1]
    used = {r[2] for r in pbs if r[2]}
    for mapb, ten, ky in pbs:
        if ky:
            continue
        base = _bo_dau(re.sub(r"(?i)^(phòng|ban)\s+", "", ten.strip())).lower()
        cand = (
            _KY_MAC_DINH.get(base)
            or "".join(w[0] for w in base.split() if w[:1].isalpha()).upper()[:5]
            or "PB"
        )
        cand = re.sub("[^A-Z]", "", cand.upper()) or "PB"
        k = cand
        i = 2
        while k in used:
            k = cand[:4] + chr(64 + i)
            i += 1
        used.add(k)
        db.execute("UPDATE PhongBan SET KyHieu=? WHERE MaPB=?", (k, mapb))
    # đổi từ định dạng mã cũ (vd KT01) sang định dạng mới: cấp lại toàn bộ 1 lần
    if db.scalar(
        "SELECT COUNT(*) FROM NhanVien WHERE MaNVHT IS NOT NULL AND MaNVHT NOT LIKE 'NV[0-9]%'"
    ):
        db.execute("UPDATE NhanVien SET MaNVHT=NULL")
    assign_codes()
    db.execute(
        "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_PhongBan_KyHieu') CREATE UNIQUE INDEX UX_PhongBan_KyHieu ON PhongBan(KyHieu) WHERE KyHieu IS NOT NULL"
    )
    db.execute(
        "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_NhanVien_MaNVHT') CREATE UNIQUE INDEX UX_NhanVien_MaNVHT ON NhanVien(MaNVHT) WHERE MaNVHT IS NOT NULL"
    )
    db.execute(
        "IF OBJECT_ID('NhanVienKhuonMat','U') IS NULL CREATE TABLE NhanVienKhuonMat(MaNV INT NOT NULL PRIMARY KEY REFERENCES NhanVien(MaNV) ON DELETE CASCADE, Embedding NVARCHAR(MAX) NOT NULL, ConsentAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), ConsentVersion NVARCHAR(40) NOT NULL DEFAULT N'2026-10-v1', UpdatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF COL_LENGTH('NhanVienKhuonMat','ConsentVersion') IS NULL ALTER TABLE NhanVienKhuonMat ADD ConsentVersion NVARCHAR(40) NOT NULL DEFAULT N'2026-10-v1'"
    )
    db.execute(
        "IF OBJECT_ID('TaiKhoanOTP','U') IS NULL CREATE TABLE TaiKhoanOTP(MaNV INT NOT NULL PRIMARY KEY REFERENCES NhanVien(MaNV) ON DELETE CASCADE, RequestedBy NVARCHAR(50) NOT NULL, Channel NVARCHAR(10) NOT NULL, CodeHash CHAR(64) NOT NULL, SentAt DATETIME2 NOT NULL, ExpiresAt DATETIME2 NOT NULL, Attempts INT NOT NULL DEFAULT 0)"
    )
    db.execute(
        "IF OBJECT_ID('TepHopDong','U') IS NULL CREATE TABLE TepHopDong(MaTep INT IDENTITY(1,1) PRIMARY KEY, MaHD INT NOT NULL REFERENCES HopDong(MaHD) ON DELETE CASCADE, TenTep NVARCHAR(255) NOT NULL, DinhDang VARCHAR(10) NOT NULL, TepData VARBINARY(MAX) NOT NULL, NoiDung NVARCHAR(MAX) NOT NULL, NguoiTao NVARCHAR(50) NOT NULL, NgayTao DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    for col, typ in [
        ("NguoiLap", "NVARCHAR(50) NULL"),
        ("NguoiDuyet", "NVARCHAR(50) NULL"),
        ("NgayDuyet", "DATETIME2 NULL"),
        ("NgayKy", "DATE NULL"),
        ("NguoiKy", "NVARCHAR(50) NULL"),
        ("PhienBan", "INT NOT NULL DEFAULT 1"),
        ("HopDongGoc", "INT NULL"),
        ("LyDoChamDut", "NVARCHAR(1000) NULL"),
    ]:
        db.execute(f"IF COL_LENGTH('HopDong','{col}') IS NULL ALTER TABLE HopDong ADD {col} {typ}")
    db.execute(
        "DECLARE @df sysname, @sql nvarchar(max); "
        "SELECT @df=dc.name FROM sys.default_constraints dc "
        "JOIN sys.columns c ON c.default_object_id=dc.object_id "
        "WHERE dc.parent_object_id=OBJECT_ID(N'dbo.HopDong') AND c.name=N'TrangThai'; "
        "IF @df IS NOT NULL BEGIN "
        "SET @sql=N'ALTER TABLE dbo.HopDong DROP CONSTRAINT '+QUOTENAME(@df); "
        "EXEC sys.sp_executesql @sql; END; "
        "ALTER TABLE dbo.HopDong ADD CONSTRAINT DF_HopDong_TrangThai "
        "DEFAULT N'Bản nháp' FOR TrangThai"
    )
    for col, typ in [
        ("LoaiTaiLieu", "NVARCHAR(40) NOT NULL DEFAULT N'Bản nháp AI'"),
        ("TrangThai", "NVARCHAR(30) NOT NULL DEFAULT N'Bản nháp'"),
        ("PhienBan", "INT NOT NULL DEFAULT 1"),
        ("NguoiDuyet", "NVARCHAR(50) NULL"),
        ("NgayDuyet", "DATETIME2 NULL"),
        ("NgayKy", "DATE NULL"),
        ("GhiChu", "NVARCHAR(1000) NULL"),
    ]:
        db.execute(f"IF COL_LENGTH('TepHopDong','{col}') IS NULL ALTER TABLE TepHopDong ADD {col} {typ}")
    db.execute("IF OBJECT_ID('LichSuHopDong','U') IS NULL CREATE TABLE LichSuHopDong(MaLichSu BIGINT IDENTITY(1,1) PRIMARY KEY,MaHD INT NOT NULL REFERENCES HopDong(MaHD),HanhDong NVARCHAR(40) NOT NULL,TrangThaiCu NVARCHAR(30) NULL,TrangThaiMoi NVARCHAR(30) NULL,ChiTiet NVARCHAR(1000) NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("UPDATE HopDong SET TrangThai=N'Hết hạn' WHERE TrangThai IN (N'Còn hiệu lực',N'Đã ký') AND NgayKetThuc IS NOT NULL AND NgayKetThuc<CAST(GETDATE() AS DATE)")
    db.execute("UPDATE HopDong SET TrangThai=N'Còn hiệu lực' WHERE TrangThai=N'Đã ký' AND NgayBatDau<=CAST(GETDATE() AS DATE) AND (NgayKetThuc IS NULL OR NgayKetThuc>=CAST(GETDATE() AS DATE))")
    db.execute(
        "IF OBJECT_ID('NhatKyChamCong','U') IS NULL CREATE TABLE NhatKyChamCong(MaNhatKy BIGINT IDENTITY(1,1) PRIMARY KEY, MaCC INT NULL, MaNV INT NOT NULL, Nguon NVARCHAR(20) NOT NULL, ThaoTac NVARCHAR(30) NOT NULL, KetQua NVARCHAR(30) NOT NULL, Similarity DECIMAL(7,5) NULL, ThoiDiem DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), NguoiThucHien NVARCHAR(50) NULL, ChiTiet NVARCHAR(500) NULL)"
    )
    db.execute(
        "IF OBJECT_ID('ChamCongSuKien','U') IS NULL CREATE TABLE ChamCongSuKien(MaSuKien BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),NgayCong DATE NOT NULL,MaCC INT NULL REFERENCES ChamCong(MaCC),ThoiDiem DATETIME2 NOT NULL,LoaiSuKien NVARCHAR(20) NOT NULL,Nguon NVARCHAR(20) NOT NULL,KetQua NVARCHAR(30) NOT NULL,Similarity DECIMAL(7,5) NULL,NguoiThucHien NVARCHAR(50) NULL,ChiTiet NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute("IF COL_LENGTH('ChamCongSuKien','NgayCong') IS NULL ALTER TABLE ChamCongSuKien ADD NgayCong DATE NULL; UPDATE e SET NgayCong=COALESCE(c.Ngay,CAST(e.ThoiDiem AS DATE)) FROM ChamCongSuKien e LEFT JOIN ChamCong c ON c.MaCC=e.MaCC WHERE e.NgayCong IS NULL; IF EXISTS(SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('ChamCongSuKien') AND name='NgayCong' AND is_nullable=1) ALTER TABLE ChamCongSuKien ALTER COLUMN NgayCong DATE NOT NULL")
    db.execute("IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_ChamCongSuKien_Employee_WorkDate') CREATE INDEX IX_ChamCongSuKien_Employee_WorkDate ON ChamCongSuKien(MaNV,NgayCong,MaSuKien)")
    db.execute("INSERT INTO ChamCongSuKien(MaNV,NgayCong,MaCC,ThoiDiem,LoaiSuKien,Nguon,KetQua,NguoiThucHien,ChiTiet) SELECT c.MaNV,c.Ngay,c.MaCC,DATEADD(SECOND,DATEDIFF(SECOND,CAST('00:00:00' AS TIME),c.GioVao),CAST(c.Ngay AS DATETIME2)),N'in',N'legacy',N'imported',N'system',N'Migrated from daily attendance summary' FROM ChamCong c WHERE c.GioVao IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ChamCongSuKien e WHERE e.MaCC=c.MaCC AND e.LoaiSuKien=N'in' AND e.Nguon=N'legacy')")
    db.execute("INSERT INTO ChamCongSuKien(MaNV,NgayCong,MaCC,ThoiDiem,LoaiSuKien,Nguon,KetQua,NguoiThucHien,ChiTiet) SELECT c.MaNV,c.Ngay,c.MaCC,DATEADD(SECOND,DATEDIFF(SECOND,CAST('00:00:00' AS TIME),c.GioRa),CAST(c.Ngay AS DATETIME2)),N'out',N'legacy',N'imported',N'system',N'Migrated from daily attendance summary' FROM ChamCong c WHERE c.GioRa IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ChamCongSuKien e WHERE e.MaCC=c.MaCC AND e.LoaiSuKien=N'out' AND e.Nguon=N'legacy')")
    db.execute("IF OBJECT_ID('CaLamViec','U') IS NULL CREATE TABLE CaLamViec(MaCa INT IDENTITY PRIMARY KEY,TenCa NVARCHAR(80) NOT NULL UNIQUE,GioBatDau TIME NOT NULL,GioKetThuc TIME NOT NULL,QuaDem BIT NOT NULL DEFAULT 0,PhutAnHan SMALLINT NOT NULL DEFAULT 0,TrangThai BIT NOT NULL DEFAULT 1,CHECK(GioBatDau<>GioKetThuc),CHECK(PhutAnHan BETWEEN 0 AND 240))")
    db.execute("IF OBJECT_ID('PhanCaNhanVien','U') IS NULL CREATE TABLE PhanCaNhanVien(MaPhanCa BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaCa INT NOT NULL REFERENCES CaLamViec(MaCa),Ngay DATE NOT NULL,NguoiPhan NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CONSTRAINT UQ_PhanCaNhanVien UNIQUE(MaNV,MaCa,Ngay))")
    db.execute("IF COL_LENGTH('PhanCaNhanVien','GioBatDauOverride') IS NULL ALTER TABLE PhanCaNhanVien ADD GioBatDauOverride TIME NULL; IF COL_LENGTH('PhanCaNhanVien','GioKetThucOverride') IS NULL ALTER TABLE PhanCaNhanVien ADD GioKetThucOverride TIME NULL")
    db.execute("IF EXISTS(SELECT 1 FROM sys.key_constraints WHERE parent_object_id=OBJECT_ID('PhanCaNhanVien') AND name='UQ_PhanCaNhanVien') ALTER TABLE PhanCaNhanVien DROP CONSTRAINT UQ_PhanCaNhanVien")
    db.execute("IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_PhanCaNhanVien_Ngay') CREATE INDEX IX_PhanCaNhanVien_Ngay ON PhanCaNhanVien(Ngay,MaNV)")
    db.execute("IF OBJECT_ID('YeuCauDoiCa','U') IS NULL CREATE TABLE YeuCauDoiCa(MaYeuCau BIGINT IDENTITY PRIMARY KEY,MaPhanCaA BIGINT NOT NULL REFERENCES PhanCaNhanVien(MaPhanCa),MaPhanCaB BIGINT NOT NULL REFERENCES PhanCaNhanVien(MaPhanCa),MaNVCau INT NOT NULL REFERENCES NhanVien(MaNV),TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ xác nhận',XacNhanBoi NVARCHAR(50) NULL,XacNhanLuc DATETIME2 NULL,NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,PhanHoi NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(MaPhanCaA<>MaPhanCaB),CHECK(TrangThai IN (N'Chờ xác nhận',N'Chờ duyệt',N'Đã đổi',N'Từ chối')))")
    db.execute("IF OBJECT_ID('NhatKyDoiCa','U') IS NULL CREATE TABLE NhatKyDoiCa(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaYeuCau BIGINT NOT NULL REFERENCES YeuCauDoiCa(MaYeuCau),ThaoTac NVARCHAR(30) NOT NULL,TrangThaiCu NVARCHAR(20) NULL,TrangThaiMoi NVARCHAR(20) NOT NULL,NguoiThucHien NVARCHAR(50) NOT NULL,LyDo NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('LichNgayLe','U') IS NULL CREATE TABLE LichNgayLe(MaNgayLe INT IDENTITY PRIMARY KEY,Ngay DATE NOT NULL UNIQUE,TenNgay NVARCHAR(120) NOT NULL,HuongLuong BIT NOT NULL DEFAULT 1,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute("IF OBJECT_ID('TangCaYeuCau','U') IS NULL CREATE TABLE TangCaYeuCau(MaYeuCau BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),BatDau DATETIME2 NOT NULL,KetThuc DATETIME2 NOT NULL,SoGio DECIMAL(5,2) NOT NULL,SoGioThucTe DECIMAL(5,2) NULL,LyDo NVARCHAR(500) NOT NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt',NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,XacNhanBoi NVARCHAR(50) NULL,XacNhanLuc DATETIME2 NULL,PhanHoi NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(KetThuc>BatDau),CHECK(SoGio>0 AND SoGio<=24),CHECK(SoGioThucTe IS NULL OR (SoGioThucTe>=0 AND SoGioThucTe<=24)))")
    db.execute("IF COL_LENGTH('TangCaYeuCau','SoGioThucTe') IS NULL ALTER TABLE TangCaYeuCau ADD SoGioThucTe DECIMAL(5,2) NULL")
    db.execute("IF COL_LENGTH('TangCaYeuCau','XacNhanBoi') IS NULL ALTER TABLE TangCaYeuCau ADD XacNhanBoi NVARCHAR(50) NULL")
    db.execute("IF COL_LENGTH('TangCaYeuCau','XacNhanLuc') IS NULL ALTER TABLE TangCaYeuCau ADD XacNhanLuc DATETIME2 NULL")
    db.execute("IF OBJECT_ID('NhatKyTangCa','U') IS NULL CREATE TABLE NhatKyTangCa(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaYeuCau BIGINT NOT NULL REFERENCES TangCaYeuCau(MaYeuCau),ThaoTac NVARCHAR(30) NOT NULL,TrangThaiCu NVARCHAR(20) NULL,TrangThaiMoi NVARCHAR(20) NOT NULL,NguoiThucHien NVARCHAR(50) NOT NULL,LyDo NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute(
        "IF OBJECT_ID('KhieuNaiChamCong','U') IS NULL CREATE TABLE KhieuNaiChamCong(MaKN INT IDENTITY(1,1) PRIMARY KEY, MaNV INT NOT NULL, Ngay DATE NOT NULL, NoiDung NVARCHAR(1000) NOT NULL, TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ xử lý', PhanHoi NVARCHAR(1000) NULL, NguoiXuLy NVARCHAR(50) NULL, TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), XuLyLuc DATETIME2 NULL)"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyLuong','U') IS NULL CREATE TABLE NhatKyLuong(MaNhatKy BIGINT IDENTITY(1,1) PRIMARY KEY, MaNV INT NULL, Thang INT NOT NULL, Nam INT NOT NULL, HanhDong NVARCHAR(40) NOT NULL, GiaTriCu NVARCHAR(MAX) NULL, GiaTriMoi NVARCHAR(MAX) NULL, LyDo NVARCHAR(500) NOT NULL, NguoiThucHien NVARCHAR(50) NOT NULL, ThoiDiem DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute("IF COL_LENGTH('NghiPhep','LoaiNghi') IS NULL ALTER TABLE NghiPhep ADD LoaiNghi NVARCHAR(40) NOT NULL CONSTRAINT DF_NghiPhep_LoaiNghi DEFAULT N'Khác'")
    db.execute("IF COL_LENGTH('NghiPhep','PhanHoi') IS NULL ALTER TABLE NghiPhep ADD PhanHoi NVARCHAR(1000) NULL")
    db.execute("IF COL_LENGTH('NghiPhep','TaoLuc') IS NULL ALTER TABLE NghiPhep ADD TaoLuc DATETIME2 NOT NULL CONSTRAINT DF_NghiPhep_TaoLuc DEFAULT SYSUTCDATETIME()")
    db.execute("IF COL_LENGTH('NghiPhep','NgayCuTu') IS NULL ALTER TABLE NghiPhep ADD NgayCuTu DATE NULL, NgayCuDen DATE NULL, SoNgayCu INT NULL, LoaiCu NVARCHAR(40) NULL")
    db.execute("UPDATE NghiPhep SET TrangThai=N'Chờ nhân sự' WHERE TrangThai=N'Chờ duyệt'")
    db.execute("IF OBJECT_ID('QuyPhepNam','U') IS NULL CREATE TABLE QuyPhepNam(MaNV INT NOT NULL REFERENCES NhanVien(MaNV) ON DELETE CASCADE,Nam INT NOT NULL,SoNgayCap DECIMAL(6,2) NOT NULL DEFAULT 0,SoNgayChuyen DECIMAL(6,2) NOT NULL DEFAULT 0,CONSTRAINT PK_QuyPhepNam PRIMARY KEY(MaNV,Nam))")
    db.execute("IF OBJECT_ID('LichLamViecNhanVien','U') IS NULL CREATE TABLE LichLamViecNhanVien(MaNV INT NOT NULL REFERENCES NhanVien(MaNV) ON DELETE CASCADE,Thu TINYINT NOT NULL CHECK(Thu BETWEEN 0 AND 6),CONSTRAINT PK_LichLamViecNhanVien PRIMARY KEY(MaNV,Thu))")
    db.execute("IF OBJECT_ID('QuanLyTrucTiep','U') IS NULL CREATE TABLE QuanLyTrucTiep(MaNV INT NOT NULL PRIMARY KEY REFERENCES NhanVien(MaNV) ON DELETE CASCADE,MaQuanLy INT NOT NULL REFERENCES NhanVien(MaNV))")
    db.execute("UPDATE l SET MaQuanLy=q.MaQuanLy FROM LichSuCongTac l JOIN QuanLyTrucTiep q ON q.MaNV=l.MaNV WHERE l.DenNgay IS NULL AND l.MaQuanLy IS NULL")
    db.execute("IF OBJECT_ID('CauHinhNghiPhep','U') IS NULL CREATE TABLE CauHinhNghiPhep(Id TINYINT NOT NULL PRIMARY KEY CHECK(Id=1),YeuCauQuanLy BIT NOT NULL DEFAULT 0,YeuCauNhanSu BIT NOT NULL DEFAULT 1)")
    db.execute("IF NOT EXISTS(SELECT 1 FROM CauHinhNghiPhep WHERE Id=1) INSERT INTO CauHinhNghiPhep(Id,YeuCauQuanLy,YeuCauNhanSu) VALUES(1,0,1)")
    db.execute("IF OBJECT_ID('ThongBaoNghiPhep','U') IS NULL CREATE TABLE ThongBaoNghiPhep(MaTB BIGINT IDENTITY(1,1) PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV) ON DELETE CASCADE,MaNP INT NULL,NoiDung NVARCHAR(500) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),DaDoc BIT NOT NULL DEFAULT 0)")
    db.execute("IF OBJECT_ID('NhatKyNghiPhep','U') IS NULL CREATE TABLE NhatKyNghiPhep(MaNK BIGINT IDENTITY(1,1) PRIMARY KEY,MaNP INT NOT NULL,MaNV INT NOT NULL,ThaoTac NVARCHAR(40) NOT NULL,TrangThaiCu NVARCHAR(40) NULL,TrangThaiMoi NVARCHAR(40) NULL,ChiTiet NVARCHAR(1000) NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())")
    db.execute(
        "IF OBJECT_ID('LuongKy','U') IS NULL CREATE TABLE LuongKy(Nam INT NOT NULL, Thang INT NOT NULL, TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp', TinhLuc DATETIME2 NULL, TinhBoi NVARCHAR(50) NULL, DuyetLuc DATETIME2 NULL, DuyetBoi NVARCHAR(50) NULL, KhoaLuc DATETIME2 NULL, KhoaBoi NVARCHAR(50) NULL, PhienBan INT NOT NULL DEFAULT 0, CONSTRAINT PK_LuongKy PRIMARY KEY(Nam,Thang))"
    )
    db.execute("IF OBJECT_ID('PayrollPolicyVersion','U') IS NULL CREATE TABLE PayrollPolicyVersion(MaChinhSach BIGINT IDENTITY PRIMARY KEY,Ten NVARCHAR(120) NOT NULL,NgayHieuLuc DATE NOT NULL,QuyTacJson NVARCHAR(MAX) NOT NULL,CanCu NVARCHAR(1000) NOT NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp',NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,CHECK(ISJSON(QuyTacJson)=1),CHECK(TrangThai IN (N'Nháp',N'Đã duyệt',N'Ngừng áp dụng')))" )
    db.execute("IF OBJECT_ID('PayrollEmployeeTaxProfile','U') IS NULL CREATE TABLE PayrollEmployeeTaxProfile(MaNV INT NOT NULL REFERENCES NhanVien(MaNV) ON DELETE CASCADE,TuNgay DATE NOT NULL,LaCuTru BIT NULL,NguoiPhuThuoc INT NULL,ThamGiaBaoHiem BIT NULL,LuongTinhBaoHiem DECIMAL(18,0) NULL,NguoiCapNhat NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CONSTRAINT PK_PayrollEmployeeTaxProfile PRIMARY KEY(MaNV,TuNgay),CHECK(NguoiPhuThuoc IS NULL OR NguoiPhuThuoc>=0),CHECK(LuongTinhBaoHiem IS NULL OR LuongTinhBaoHiem>=0))")
    db.execute("IF OBJECT_ID('PayrollItem','U') IS NULL CREATE TABLE PayrollItem(MaKhoan BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),Nam INT NOT NULL,Thang INT NOT NULL,Loai NVARCHAR(20) NOT NULL,Ten NVARCHAR(120) NOT NULL,SoTien DECIMAL(18,0) NOT NULL,ChiuThue BIT NOT NULL DEFAULT 0,CanCuBaoHiem BIT NOT NULL DEFAULT 0,DuocTruThue BIT NOT NULL DEFAULT 0,LyDo NVARCHAR(500) NOT NULL,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(Thang BETWEEN 1 AND 12),CHECK(Loai IN (N'earning',N'reduction',N'deduction')),CHECK(SoTien>=0))")
    db.execute("IF OBJECT_ID('PayrollItem','U') IS NOT NULL AND (EXISTS(SELECT 1 FROM PayrollItem WHERE Loai=N'penalty') OR NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID('PayrollItem') AND name=N'CK_PayrollItem_Loai')) BEGIN DECLARE @c sysname,@sql nvarchar(max); DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT name FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID('PayrollItem') AND definition LIKE '%Loai%'; OPEN c; FETCH NEXT FROM c INTO @c; WHILE @@FETCH_STATUS=0 BEGIN SET @sql=N'ALTER TABLE PayrollItem DROP CONSTRAINT '+QUOTENAME(@c); EXEC sp_executesql @sql; FETCH NEXT FROM c INTO @c; END; CLOSE c; DEALLOCATE c; UPDATE PayrollItem SET Loai=N'reduction' WHERE Loai=N'penalty'; ALTER TABLE PayrollItem ADD CONSTRAINT CK_PayrollItem_Loai CHECK(Loai IN (N'earning',N'reduction',N'deduction')); END")
    db.execute("IF OBJECT_ID('PayrollResultSnapshot','U') IS NULL CREATE TABLE PayrollResultSnapshot(MaLuong INT NOT NULL PRIMARY KEY REFERENCES Luong(MaLuong) ON DELETE CASCADE,MaChinhSach BIGINT NOT NULL REFERENCES PayrollPolicyVersion(MaChinhSach),QuyTacJson NVARCHAR(MAX) NOT NULL,DuLieuDauVaoJson NVARCHAR(MAX) NOT NULL,ChiTietTinhJson NVARCHAR(MAX) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(ISJSON(QuyTacJson)=1),CHECK(ISJSON(DuLieuDauVaoJson)=1),CHECK(ISJSON(ChiTietTinhJson)=1))")
    for col, typ in [
        ("ThueTNCN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHXH_NLD", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHYT_NLD", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHTN_NLD", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHXHDN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHYTDN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHTNDN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BH_TNLDBNN_DN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("LuongThucLinh", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
    ]:
        db.execute(f"IF COL_LENGTH('Luong','{col}') IS NULL ALTER TABLE Luong ADD [{col}] {typ}")


_schema_ok = False


@app.before_request
def _auto_schema():
    global _schema_ok
    if _schema_ok or request.endpoint in (None, "static"):
        return
    try:
        ensure_schema()
        _schema_ok = True
    except Exception as e:
        app.logger.error(
            "Schema initialization failed",
            exc_info=(type(e), e, e.__traceback__),
        )


@app.after_request
def _invalidate_draft_payroll_after_source_change(response):
    endpoint = request.endpoint or ""
    module_key = (request.view_args or {}).get("key")
    source_changed = request.method == "POST" and response.status_code < 400 and (
        endpoint in {"chamcong", "nghiphep", "overtime_requests", "workforce_shifts", "dieuchuyen"}
        or endpoint.startswith("api_chamcong_face_")
        or (endpoint == "module" and module_key in {"nhanvien", "lichngayle"})
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
    if not user or request.endpoint in (None, "static", "login"):
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
        return redirect(url_for("login"))
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
        return redirect(url_for("login"))
    return None


def ensure_pbcv():
    db.execute(
        "IF OBJECT_ID('PhongBan_ChucVu','U') IS NULL CREATE TABLE PhongBan_ChucVu(MaPB INT NOT NULL REFERENCES PhongBan(MaPB) ON DELETE CASCADE, MaCV INT NOT NULL REFERENCES ChucVu(MaCV) ON DELETE CASCADE, PRIMARY KEY(MaPB,MaCV))"
    )


@app.route("/api/chucvu-nhanh", methods=["POST"])
@login_required
def chucvu_nhanh():
    if not admin():
        return jsonify(ok=False, error="Chức năng này dành cho quản trị viên."), 403
    data = request.get_json(silent=True) or {}
    ten = (data.get("TenCV") or "").strip()
    try:
        if not ten:
            raise ValueError("Vui lòng nhập tên chức vụ.")
        if len(ten) > 100:
            raise ValueError("Tên chức vụ tối đa 100 ký tự.")
        try:
            mapb = int(data.get("MaPB"))
        except (TypeError, ValueError):
            raise ValueError("Vui lòng chọn phòng ban trước.")
        if not db.scalar("SELECT COUNT(*) FROM PhongBan WHERE MaPB=?", (mapb,)):
            raise ValueError("Phòng ban không tồn tại.")
        ensure_pbcv()
        row = db.query("SELECT MaCV,TenCV FROM ChucVu WHERE TenCV=?", (ten,))[1]
        if not row:
            db.execute("INSERT INTO ChucVu(TenCV) VALUES(?)", (ten,))
            row = db.query("SELECT MaCV,TenCV FROM ChucVu WHERE TenCV=?", (ten,))[1]
            db.execute(
                "INSERT INTO PhongBan_ChucVu(MaPB,MaCV) VALUES(?,?)", (mapb, row[0][0])
            )
        else:
            macv = row[0][0]
            # chức vụ chung (chưa gắn phòng nào) đã dùng được cho mọi phòng -> không gắn thêm để khỏi làm mất ở phòng khác
            if db.scalar(
                "SELECT COUNT(*) FROM PhongBan_ChucVu WHERE MaCV=?", (macv,)
            ) and not db.scalar(
                "SELECT COUNT(*) FROM PhongBan_ChucVu WHERE MaPB=? AND MaCV=?",
                (mapb, macv),
            ):
                db.execute(
                    "INSERT INTO PhongBan_ChucVu(MaPB,MaCV) VALUES(?,?)", (mapb, macv)
                )
        return jsonify(ok=True, id=row[0][0], name=row[0][1])
    except Exception as e:
        status = 400 if isinstance(e, ValueError) else 500
        return jsonify(ok=False, error=_safe_error(e, "Không thể tạo chức vụ lúc này.")), status


@app.route("/<key>", methods=["GET", "POST"])
@login_required
def module(key):
    if key not in MODULES:
        return redirect(url_for("dashboard"))
    view_permission = "employees.team_view" if key == "nhanvien" and is_manager() else module_permission(key, "view")
    if not view_permission or not has_permission(view_permission):
        return "Bạn không có quyền xem dữ liệu này.", 403
    if key == "hopdong":
        sync_contract_statuses()
    m = MODULES[key]
    edit_id = request.args.get("edit")
    can_manage = bool(module_permission(key, "edit") and has_permission(module_permission(key, "edit")))
    can_export = bool(module_permission(key, "export") and has_permission(module_permission(key, "export")))
    if edit_id and not can_manage:
        return "Bạn không có quyền sửa dữ liệu này.", 403
    employee_source_key = (
        secrets.token_urlsafe(32)
        if key == "nhanvien" and not edit_id
        else None
    )
    if request.method == "POST":
        action = request.form.get("action")
        action_permission = module_permission(key, action)
        if not action_permission or not has_permission(action_permission):
            return "Bạn không có quyền thực hiện thao tác này.", 403
        source_key = (
            request.form.get("employee_source_key", "")
            if key == "nhanvien" and action == "add"
            else None
        )
        vals = []
        write_fields = []
        photo_changed = False
        try:
            if key == "nhanvien" and action == "add":
                if not source_key:
                    raise ValueError("Biểu mẫu đã hết hạn. Hãy tải lại trang thêm nhân viên.")
                existing_employee = employee_profiles.find_source_employee(
                    "manual", source_key
                )
                if existing_employee:
                    assign_codes()
                    flash(
                        f"Hồ sơ đã được tạo trước đó với mã nhân viên {existing_employee}.",
                        "success",
                    )
                    return redirect(url_for("module", key=key))
            if key == "hopdong" and action == "update":
                status = db.scalar("SELECT TrangThai FROM HopDong WHERE MaHD=?", (request.form.get("id"),))
                if status != "Bản nháp" or db.scalar("SELECT COUNT(*) FROM TepHopDong WHERE MaHD=?", (request.form.get("id"),)):
                    raise ValueError("Chỉ sửa hợp đồng nháp chưa có tệp phiên bản; dùng chức năng soạn/vòng đời để tạo phiên bản mới.")
            if action in ("add", "update"):
                for col, label, typ, req in m["fields"]:
                    if typ == "image":
                        uploaded = request.files.get(col)
                        if not uploaded or not uploaded.filename:
                            if action == "add":
                                write_fields.append((col, label, typ, req))
                                vals.append(None)
                            continue
                        raw = uploaded.read(5 * 1024 * 1024 + 1)
                        if len(raw) > 5 * 1024 * 1024:
                            raise ValueError("Ảnh hồ sơ tối đa 5 MB.")
                        try:
                            with Image.open(io.BytesIO(raw)) as im:
                                if im.format not in ("JPEG", "PNG", "WEBP"):
                                    raise ValueError(
                                        "Chỉ nhận ảnh JPEG, PNG hoặc WEBP."
                                    )
                                if im.width * im.height > 20_000_000:
                                    raise ValueError(
                                        "Ảnh có kích thước điểm ảnh quá lớn."
                                    )
                                im = ImageOps.exif_transpose(im).convert("RGB")
                                im.thumbnail((1600, 1600))
                                output = io.BytesIO()
                                im.save(
                                    output, format="JPEG", quality=88, optimize=True
                                )
                                value = output.getvalue()
                        except (UnidentifiedImageError, OSError):
                            raise ValueError("Tệp tải lên không phải ảnh hợp lệ.")
                        write_fields.append((col, label, typ, req))
                        vals.append(value)
                        photo_changed = True
                        continue
                    value = request.form.get(col, "").strip()
                    if typ in ("unit", "department", "department_parent", "jobposition") and value:
                        try:
                            value = str(int(value))
                        except ValueError:
                            raise ValueError(label + " không hợp lệ.")
                        table, pk = {
                            "unit": ("DonVi", "MaDonVi"),
                            "department": ("PhongBan", "MaPB"),
                            "department_parent": ("PhongBan", "MaPB"),
                            "jobposition": ("ViTriCongViec", "MaViTri"),
                        }[typ]
                        if not db.scalar(f"SELECT COUNT(*) FROM {table} WHERE {pk}=?", (value,)):
                            raise ValueError(label + " không tồn tại.")
                        if key == "donvi" and col == "MaDonViCha" and action == "update" and value == request.form.get("id"):
                            raise ValueError("Đơn vị không thể là cấp trên của chính nó.")
                        if key == "phongban" and col == "MaPBCha" and action == "update" and value == request.form.get("id"):
                            raise ValueError("Phòng ban không thể là cấp trên của chính nó.")
                        if key in ("donvi", "phongban") and col in ("MaDonViCha", "MaPBCha"):
                            table_name, id_col, parent_col = (
                                ("DonVi", "MaDonVi", "MaDonViCha")
                                if key == "donvi"
                                else ("PhongBan", "MaPB", "MaPBCha")
                            )
                            ancestors = dict(db.query(f"SELECT {id_col},{parent_col} FROM {table_name}")[1])
                            node = int(value)
                            visited = set()
                            while node and node not in visited:
                                if action == "update" and node == int(request.form.get("id") or 0):
                                    raise ValueError("Không thể chuyển nút xuống dưới một nút con của nó.")
                                visited.add(node)
                                node = ancestors.get(node) or 0
                    if key == "nhanvien" and col == "Email" and value:
                        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
                            raise ValueError("Địa chỉ email không hợp lệ.")
                        if action == "update" and db.scalar(
                            "SELECT COUNT(*) FROM NhanVien WHERE Email=? AND MaNV<>?",
                            (value, request.form.get("id") or -1),
                        ):
                            raise ValueError("Email này đã được hồ sơ nhân viên khác sử dụng.")
                    if key == "nhanvien" and col == "CCCD" and value:
                        digits = re.sub(r"\D", "", value)
                        if len(digits) not in (9, 12):
                            raise ValueError("CCCD phải có 9 hoặc 12 chữ số.")
                        if action == "update" and db.scalar(
                            "SELECT COUNT(*) FROM NhanVien WHERE REPLACE(REPLACE(REPLACE(CCCD,' ',''),'.',''),'-','')=? AND MaNV<>?",
                            (digits, request.form.get("id") or -1),
                        ):
                            raise ValueError("Số CCCD này đã được hồ sơ khác sử dụng.")
                        value = digits
                    if key == "nhanvien" and col == "SDT" and value:
                        phone_digits = re.sub(r"\D", "", value)
                        if not re.fullmatch(r"\+?[0-9][0-9 .()-]{6,18}", value) or not 8 <= len(phone_digits) <= 15:
                            raise ValueError("Số điện thoại không hợp lệ.")
                    if typ == "number" and value:
                        try:
                            number = float(value)
                        except ValueError:
                            raise ValueError(label + " phải là số.")
                        if not math.isfinite(number) or number < 0:
                            raise ValueError(label + " phải là số không âm hợp lệ.")
                    if col == "KyHieu":
                        value = value.upper()
                        if not re.fullmatch("[A-Z]{1,5}", value):
                            raise ValueError(
                                "Ký hiệu phòng ban gồm 1-5 chữ cái không dấu, ví dụ KT."
                            )
                        if db.scalar(
                            "SELECT COUNT(*) FROM PhongBan WHERE KyHieu=? AND MaPB<>?",
                            (value, request.form.get("id") or -1),
                        ):
                            raise ValueError(
                                "Ký hiệu " + value + " đã được phòng ban khác dùng."
                            )
                    if req and not value:
                        raise ValueError("Vui lòng nhập " + label + ".")
                    write_fields.append((col, label, typ, req))
                    vals.append(value or None)
            if key == "nhanvien" and action in ("add", "update"):
                submitted = dict(zip((field[0] for field in write_fields), vals))
                if action == "update" and submitted.get("TrangThai") == "Đã nghỉ việc" and db.scalar("SELECT TrangThai FROM NhanVien WHERE MaNV=?", (request.form.get("id"),)) == "Đang làm":
                    lifecycle_done = db.scalar("SELECT COUNT(*) FROM VongDoiNhanVien WHERE MaNV=? AND GiaiDoan=N'Offboarding' AND TrangThai=N'Hoàn tất'", (request.form.get("id"),))
                    if not lifecycle_done:
                        raise ValueError("Hãy hoàn tất quy trình offboarding trước khi chuyển nhân viên sang Đã nghỉ việc.")
                selected_department = submitted.get("MaPB")
                selected_position = submitted.get("MaViTri")
                if action == "update":
                    current_assignment = db.query("SELECT MaPB,MaViTri FROM NhanVien WHERE MaNV=?", (request.form.get("id"),))[1]
                    if current_assignment:
                        selected_department = submitted.get("MaPB", current_assignment[0][0])
                        selected_position = submitted.get("MaViTri", current_assignment[0][1])
                if selected_position:
                    position_department = db.scalar("SELECT MaPB FROM ViTriCongViec WHERE MaViTri=?", (selected_position,))
                    if position_department is not None and str(position_department) != str(selected_department):
                        raise ValueError("Vị trí công việc này thuộc phòng ban khác với phòng ban đã chọn.")
            if action == "add":
                cols = [f[0] for f in write_fields]
                if key == "hopdong":
                    contract_id = db.query(
                        f"INSERT INTO HopDong ({','.join(cols)},TrangThai,NguoiLap,PhienBan) OUTPUT INSERTED.MaHD VALUES ({','.join(['?'] * len(cols))},N'Bản nháp',?,1)",
                        vals + [session["user"]["user"]],
                    )[1][0][0]
                    db.execute("INSERT INTO LichSuHopDong(MaHD,HanhDong,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien) VALUES(?,N'tao_ban_nhap',NULL,N'Bản nháp',N'Tạo từ màn hình quản lý hợp đồng',?)", (contract_id, session["user"]["user"]))
                elif key == "nhanvien":
                    created_id = employee_profiles.create_employee(
                        "manual",
                        source_key,
                        dict(zip(cols, vals)),
                        session["user"]["user"],
                    )
                    db.execute("INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'tao',N'*',?)", (created_id, session["user"]["user"]))
                    db.execute(
                        "INSERT INTO LichSuCongTac(MaNV,TuNgay,MaPB,MaCV,MaViTri,MaQuanLy,LuongCoBan,NguoiCapNhat,LyDo) VALUES(?,?,?,?,?,NULL,?,?,N'Tạo hồ sơ nhân viên')",
                        (created_id, date.today(), dict(zip(cols, vals)).get("MaPB"), dict(zip(cols, vals)).get("MaCV"), dict(zip(cols, vals)).get("MaViTri"), dict(zip(cols, vals)).get("LuongCoBan") or 0, session["user"]["user"]),
                    )
                else:
                    db.execute(
                        f"INSERT INTO {m['table']} ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
                        vals,
                    )
                if key == "nhanvien":
                    assign_codes()
                flash("Đã thêm dữ liệu.", "success")
            elif action == "update":
                sets = ",".join(f"{f[0]}=?" for f in write_fields)
                if sets and key == "nhanvien":
                    employee_id = int(request.form["id"])
                    current = db.query("SELECT MaPB,MaCV,MaViTri,LuongCoBan,(SELECT MaQuanLy FROM QuanLyTrucTiep q WHERE q.MaNV=NhanVien.MaNV) FROM NhanVien WHERE MaNV=?", (employee_id,))[1]
                    if not current:
                        raise ValueError("Không tìm thấy hồ sơ nhân viên.")
                    audit_fields = [field for field in m["fields"] if field[2] != "image"]
                    audit_columns = [field[0] for field in audit_fields]
                    old_profile_rows = db.query(f"SELECT {','.join(audit_columns)} FROM NhanVien WHERE MaNV=?", (employee_id,))[1]
                    old_profile = dict(zip(audit_columns, old_profile_rows[0]))
                    submitted_profile = dict(zip((field[0] for field in write_fields), vals))
                    changed_profile_fields = [
                        field[0]
                        for field in audit_fields
                        if field[0] in submitted_profile
                        and _audit_profile_value(old_profile.get(field[0]), field[2])
                        != _audit_profile_value(submitted_profile.get(field[0]), field[2])
                    ]
                    if photo_changed:
                        changed_profile_fields.append("AnhHoSo")
                    audit_sql = "".join(
                        " INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'cap_nhat',?,?);"
                        for _ in changed_profile_fields
                    )
                    audit_params = [value for field in changed_profile_fields for value in (employee_id, field, session["user"]["user"])]
                    tracked = ("MaPB", "MaCV", "MaViTri", "LuongCoBan", "MaQuanLy")
                    current_values = dict(zip(tracked, current[0]))
                    new_values = dict(current_values)
                    submitted = dict(zip((field[0] for field in write_fields), vals))
                    new_values.update({field: submitted[field] for field in tracked if field in submitted})
                    changed = any(str(current_values[field] or "") != str(new_values[field] or "") for field in tracked)
                    update_sql = f"UPDATE NhanVien SET {sets} WHERE MaNV=?;"
                    update_params = vals + [employee_id]
                    if photo_changed:
                        update_sql += " DELETE FROM NhanVienKhuonMat WHERE MaNV=?;"
                        update_params.append(employee_id)
                    update_sql += audit_sql
                    if changed:
                        try:
                            effective = datetime.strptime(request.form.get("NgayHieuLuc", ""), "%Y-%m-%d").date()
                        except ValueError:
                            raise ValueError("Ngày hiệu lực phải hợp lệ.")
                        current_start = db.scalar("SELECT MAX(TuNgay) FROM LichSuCongTac WHERE MaNV=? AND DenNgay IS NULL", (employee_id,))
                        if current_start and effective < current_start:
                            raise ValueError("Ngày hiệu lực không được trước mốc lịch sử hiện tại.")
                        snapshot = [new_values[field] for field in tracked]
                        reason = request.form.get("LyDoDieuChinh", "").strip()[:500] or "Cập nhật hồ sơ công tác"
                        if current_start and effective == current_start:
                            history_sql = "UPDATE LichSuCongTac SET MaPB=?,MaCV=?,MaViTri=?,LuongCoBan=?,MaQuanLy=?,NguoiCapNhat=?,LyDo=? WHERE MaNV=? AND DenNgay IS NULL;"
                            history_params = snapshot + [session["user"]["user"], reason, employee_id]
                        else:
                            history_sql = "UPDATE LichSuCongTac SET DenNgay=DATEADD(day,-1,?) WHERE MaNV=? AND DenNgay IS NULL; INSERT INTO LichSuCongTac(MaNV,TuNgay,MaPB,MaCV,MaViTri,MaQuanLy,LuongCoBan,NguoiCapNhat,LyDo) VALUES(?,?,?,?,?,?,?,?,?);"
                            history_params = [effective, employee_id, employee_id, effective] + snapshot + [session["user"]["user"], reason]
                        db.execute("SET XACT_ABORT ON; BEGIN TRAN; " + history_sql + " " + update_sql + " COMMIT;", history_params + update_params + audit_params)
                    else:
                        db.execute("SET XACT_ABORT ON; BEGIN TRAN; " + update_sql + " COMMIT;", update_params + audit_params)
                elif sets and key == "nhanvien" and photo_changed:
                    db.execute(
                        f"SET XACT_ABORT ON; BEGIN TRAN; UPDATE {m['table']} SET {sets} WHERE {m['pk']}=?; DELETE FROM NhanVienKhuonMat WHERE MaNV=?; COMMIT",
                        vals + [request.form["id"], request.form["id"]],
                    )
                elif sets:
                    db.execute(
                        f"UPDATE {m['table']} SET {sets} WHERE {m['pk']}=?",
                        vals + [request.form["id"]],
                    )
                    if key == "hopdong":
                        db.execute("INSERT INTO LichSuHopDong(MaHD,HanhDong,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien) VALUES(?,N'sua_ban_nhap',N'Bản nháp',N'Bản nháp',N'Cập nhật thông tin hợp đồng nháp',?)", (request.form["id"], session["user"]["user"]))
                flash("Đã cập nhật dữ liệu.", "success")
            elif action == "delete":
                delete_record(key, m, request.form["id"])
                flash("Đã xóa dữ liệu.", "success")
            return redirect(url_for("module", key=key))
        except Exception as e:
            flash(friendly_delete_error(e) if action == "delete" else _safe_error(e), "error")
    edit = None
    if edit_id:
        edit = db.query(
            f"SELECT {','.join('CASE WHEN AnhHoSo IS NULL THEN 0 ELSE 1 END AS AnhHoSo' if f[0] == 'AnhHoSo' else f[0] for f in m['fields'])} FROM {m['table']} WHERE {m['pk']}=?",
            (edit_id,),
        )[1]
        edit = dict(zip([f[0] for f in m["fields"]], edit[0])) if edit else None
    try:
        cols, rows = db.query(m["sql"])
        if key == "nhanvien" and is_manager():
            own_id = int(session.get("user", {}).get("manv") or 0)
            team_ids = {row[0] for row in db.query("SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?", (own_id,))[1]}
            if own_id:
                team_ids.add(own_id)
            rows = [row for row in rows if row and row[0] in team_ids]
            hidden_columns = {"Email", "SĐT", "CCCD", "Lương CB"}
            visible = [index for index, col in enumerate(cols) if col not in hidden_columns]
            cols = [cols[index] for index in visible]
            rows = [[row[index] for index in visible] for row in rows]
        search = request.args.get("q", "").strip()
        if search:
            if key == "nhanvien":
                q_ = search.casefold()
                rows = [
                    r
                    for r in rows
                    if q_
                    in (
                        str(r[1]).casefold(),
                        re.sub("[a-z]+$", "", str(r[1]).casefold()),
                    )
                ]  # tìm nhanh nhân viên: chỉ theo Mã NV
            else:
                rows = [
                    r
                    for r in rows
                    if search.casefold()
                    in " ".join("" if x is None else str(x) for x in r).casefold()
                ]
    except Exception as e:
        cols, rows = [], []
        flash(_safe_error(e, "Không tải được dữ liệu. Vui lòng thử lại."), "error")
    if has_permission("employees.view_cccd") and key == "nhanvien":
        actor = session["user"]["user"]
        employee_ids = [row[0] for row in rows if row and row[0] is not None]
        sensitive_audit.record_many(employee_ids, "LienHe", "list", actor)
        sensitive_audit.record_many(employee_ids, "CCCD", "list", actor)
        sensitive_audit.record_many(employee_ids, "Luong", "list", actor)
        if edit:
            employee_id = int(edit_id)
            for data_type in ("CCCD", "LienHe", "Luong"):
                sensitive_audit.record(employee_id, data_type, "view", actor)
    elif has_permission("contracts.view") and key == "hopdong" and rows:
        contract_ids = [int(row[0]) for row in rows if row and row[0] is not None]
        if contract_ids:
            placeholders = ",".join("?" for _ in contract_ids)
            employee_ids = [row[0] for row in db.query(
                f"SELECT MaNV FROM HopDong WHERE MaHD IN ({placeholders})", contract_ids
            )[1]]
            sensitive_audit.record_many(employee_ids, "HopDong", "list", session["user"]["user"])
    options = {}
    if key == "nhanvien":
        try:
            options["MaPB"] = db.query(
                "SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB"
            )[1]
            options["MaCV"] = db.query("SELECT MaCV,TenCV FROM ChucVu ORDER BY TenCV")[
                1
            ]
            options["MaViTri"] = db.query("SELECT MaViTri,TenViTri FROM ViTriCongViec WHERE TrangThai=N'Hoạt động' ORDER BY TenViTri")[1]
            ensure_pbcv()
            links = db.query("SELECT MaPB,MaCV FROM PhongBan_ChucVu")[1]
            dm = {}
            for pb_, cv_ in links:
                dm.setdefault(cv_, []).append(pb_)
            options["cv_data"] = [
                {"id": c[0], "name": c[1], "depts": dm.get(c[0], [])}
                for c in options["MaCV"]
            ]
        except Exception as e:
            flash(_safe_error(e, "Không tải được danh sách phòng ban/chức vụ."), "error")
    if key in ("donvi", "phongban", "vitri"):
        try:
            options["MaDonViCha"] = db.query("SELECT MaDonVi,TenDonVi FROM DonVi WHERE TrangThai=N'Hoạt động' ORDER BY TenDonVi")[1]
            options["MaDonVi"] = options["MaDonViCha"]
            options["MaPBCha"] = db.query("SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB")[1]
            options["MaPB"] = options["MaPBCha"]
        except Exception as e:
            flash(_safe_error(e, "Không tải được cấu trúc tổ chức."), "error")
    if key == "hopdong":
        try:
            options["MaNV"] = [
                [r[0], (r[2] or str(r[0])) + " - " + r[1]]
                for r in db.query(
                    "SELECT MaNV,HoTen,MaNVHT FROM NhanVien ORDER BY HoTen"
                )[1]
            ]
        except Exception as e:
            flash(_safe_error(e, "Không tải được danh sách nhân viên."), "error")
    prefill = {}
    if key == "nhanvien" and request.args.get("prefill") == "1" and not edit:
        token = request.args.get("token", "")
        item = EMPLOYEE_SCAN_PREFILL.pop(token, None)
        if (
            item
            and item["expires"] >= time.time()
            and item.get("user") == session["user"]["user"]
        ):
            prefill = item["fields"]
    contract_templates = []
    if key == "hopdong":
        try:
            contract_templates = db.query(
                "SELECT MaMau,TenMau,FileName,NgayTai,NoiDung FROM MauHopDong ORDER BY MaMau DESC"
            )[1]
        except Exception as e:
            flash(_safe_error(e, "Không tải được danh sách hợp đồng mẫu."), "error")
    contract_documents = []
    contract_expiry_alerts = []
    if key == "hopdong":
        try:
            contract_documents = db.query(
                "SELECT t.MaTep,n.HoTen,h.MaHD,t.TenTep,t.DinhDang,t.LoaiTaiLieu,t.PhienBan,t.TrangThai,t.NgayTao FROM TepHopDong t JOIN HopDong h ON h.MaHD=t.MaHD JOIN NhanVien n ON n.MaNV=h.MaNV ORDER BY t.MaTep DESC"
            )[1]
        except Exception as e:
            flash(_safe_error(e, "Không tải được tệp hợp đồng đã lưu."), "error")
        try:
            contract_expiry_alerts = db.query(
                "SELECT h.MaHD,n.HoTen,h.LoaiHD,h.NgayKetThuc,DATEDIFF(day,CAST(GETDATE() AS DATE),h.NgayKetThuc) AS SoNgay FROM HopDong h JOIN NhanVien n ON n.MaNV=h.MaNV WHERE h.TrangThai IN (N'Còn hiệu lực',N'Đã ký') AND h.NgayKetThuc>=CAST(GETDATE() AS DATE) AND h.NgayKetThuc<=DATEADD(day,90,CAST(GETDATE() AS DATE)) ORDER BY h.NgayKetThuc"
            )[1]
        except Exception as e:
            flash(_safe_error(e, "Không tải được cảnh báo hết hạn hợp đồng."), "error")
    return render_template(
        "module.html",
        m=m,
        key=key,
        cols=cols,
        rows=rows,
        edit=edit,
        edit_id=edit_id,
        options=options,
        prefill=prefill,
        admin=admin(),
        can_manage=can_manage,
        can_export=can_export,
        contract_templates=contract_templates,
        contract_documents=contract_documents,
        contract_expiry_alerts=contract_expiry_alerts,
        employee_source_key=employee_source_key,
        today=date.today().isoformat(),
    )


@app.route("/chamcong", methods=["GET", "POST"])
@login_required
def chamcong():
    _purge_expired_face_templates()
    today = date.today()
    try:
        selected_day = date.fromisoformat(request.args.get("date", today.isoformat()))
    except ValueError:
        selected_day = today
        flash("Ngày xem chấm công không hợp lệ.", "error")
    face_csrf = session.setdefault("face_csrf", secrets.token_urlsafe(32))
    if request.method == "POST":
        manv = request.form.get("MaNV") if admin() else session["user"].get("manv")
        action = request.form.get("action")
        source = "admin" if admin() else "manual"
        try:
            if action in ("in", "out") and not manv:
                raise ValueError(
                    "Tài khoản chưa gắn với nhân viên nào, hãy liên hệ quản trị viên."
                )
            if action == "update_status":
                if not admin():
                    raise ValueError(
                        "Chỉ quản trị viên mới được sửa trạng thái chấm công."
                    )
                status = request.form.get("TrangThai", "").strip()
                if status not in ("Đi làm", "Đi muộn", "Nghỉ phép", "Nghỉ không phép"):
                    raise ValueError("Trạng thái chấm công không hợp lệ.")
                existing = db.query(
                    "SELECT MaNV,Ngay,TrangThai FROM ChamCong WHERE MaCC=?",
                    (request.form.get("id"),),
                )[1]
                if not existing:
                    raise ValueError("Không tìm thấy bản ghi chấm công.")
                if not db.execute(
                    "UPDATE ChamCong SET TrangThai=? WHERE MaCC=?",
                    (status, request.form.get("id")),
                ):
                    raise ValueError("Không tìm thấy bản ghi chấm công.")
                manv_, work_date, old_status = existing[0]
                _audit_attendance(manv_, "admin", "edit_status", "updated", int(request.form.get("id")), actor=session["user"]["user"], detail=f"{old_status} -> {status}")
                _record_attendance_event(manv_, int(request.form.get("id")), "correction", "admin", "updated", session["user"]["user"], f"Trạng thái: {old_status} -> {status}", work_date=work_date)
                flash("Đã cập nhật trạng thái chấm công.", "success")
                manv_, work_date = existing[0][:2]
                if db.scalar(
                    "SELECT COUNT(*) FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?",
                    (manv_, work_date.month, work_date.year),
                ):
                    flash("Kỳ lương tương ứng đã được tính trước đó; hãy tính lại kỳ lương để áp dụng thay đổi.", "error")
                return redirect(
                    url_for("chamcong", date=request.form.get("date", today.isoformat()))
                )
            if action == "delete":
                if not admin():
                    raise ValueError(
                        "Chỉ quản trị viên mới được xóa bản ghi chấm công."
                    )
                existing = db.query(
                    "SELECT MaNV,Ngay,TrangThai FROM ChamCong WHERE MaCC=?",
                    (request.form["id"],),
                )[1]
                if not existing:
                    raise ValueError("Không tìm thấy bản ghi chấm công.")
                db.execute("UPDATE ChamCongSuKien SET MaCC=NULL WHERE MaCC=?; DELETE FROM ChamCong WHERE MaCC=?", (request.form["id"], request.form["id"]))
                _audit_attendance(existing[0][0], "admin", "delete", "deleted", int(request.form["id"]), actor=session["user"]["user"], detail="Quản trị viên xóa bản ghi")
                _record_attendance_event(existing[0][0], None, "delete", "admin", "deleted", session["user"]["user"], f"Xóa dòng tổng hợp ngày {existing[0][1]}", work_date=existing[0][1])
                flash("Đã xóa bản ghi chấm công.", "success")
                manv_, work_date = existing[0][:2]
                if db.scalar(
                    "SELECT COUNT(*) FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?",
                    (manv_, work_date.month, work_date.year),
                ):
                    flash("Kỳ lương tương ứng đã được tính trước đó; hãy tính lại kỳ lương để áp dụng thay đổi.", "error")
                return redirect(
                    url_for("chamcong", date=request.form.get("date", today.isoformat()))
                )
            if action == "resolve_complaint":
                if not admin():
                    raise ValueError("Chỉ quản trị viên được xử lý khiếu nại.")
                complaint_id = int(request.form.get("MaKN", ""))
                resolution = request.form.get("PhanHoi", "").strip()
                status = request.form.get("TrangThai", "").strip()
                if status not in ("Đi làm", "Đi muộn", "Nghỉ phép", "Nghỉ không phép") or not resolution:
                    raise ValueError("Cần chọn trạng thái hợp lệ và ghi phản hồi xử lý.")
                record = db.query("SELECT MaNV,Ngay,TrangThai FROM KhieuNaiChamCong WHERE MaKN=? AND TrangThai=N'Chờ xử lý'", (complaint_id,))[1]
                if not record:
                    raise ValueError("Không tìm thấy khiếu nại đang chờ xử lý.")
                employee_id, complaint_day, _ = record[0]
                clock_in = request.form.get("GioVao", "").strip() or None
                clock_out = request.form.get("GioRa", "").strip() or None
                old_times = db.query("SELECT GioVao,GioRa FROM ChamCong WHERE MaNV=? AND Ngay=?", (employee_id, complaint_day))[1]
                if old_times:
                    clock_in = clock_in or (old_times[0][0].strftime("%H:%M") if old_times[0][0] else None)
                    clock_out = clock_out or (old_times[0][1].strftime("%H:%M") if old_times[0][1] else None)
                for clock_value in (clock_in, clock_out):
                    if clock_value and not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", clock_value):
                        raise ValueError("Giờ vào/ra phải theo định dạng HH:MM.")
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; IF EXISTS(SELECT 1 FROM ChamCong WHERE MaNV=? AND Ngay=?) UPDATE ChamCong SET GioVao=?,GioRa=?,TrangThai=? WHERE MaNV=? AND Ngay=? ELSE INSERT INTO ChamCong(MaNV,Ngay,GioVao,GioRa,TrangThai) VALUES(?,?,?,?,?); UPDATE KhieuNaiChamCong SET TrangThai=N'Đã xử lý',PhanHoi=?,NguoiXuLy=?,XuLyLuc=SYSUTCDATETIME() WHERE MaKN=?; COMMIT;", (employee_id, complaint_day, clock_in, clock_out, status, employee_id, complaint_day, employee_id, complaint_day, clock_in, clock_out, status, resolution, session["user"]["user"], complaint_id))
                _audit_attendance(employee_id, "admin", "resolve_complaint", "updated", actor=session["user"]["user"], detail=f"KN {complaint_id}: {resolution}")
                _record_attendance_event(employee_id, None, "delete", "admin", "replaced", session["user"]["user"], f"Đặt lại luồng sự kiện theo khiếu nại {complaint_id}", work_date=complaint_day)
                if clock_in:
                    event_time = datetime.combine(complaint_day, datetime.strptime(clock_in, "%H:%M").time())
                    _record_attendance_event(employee_id, None, "in", "admin", "corrected", session["user"]["user"], f"Giờ vào đã xác minh theo khiếu nại {complaint_id}", happened_at=event_time, work_date=complaint_day)
                if clock_out:
                    event_day = complaint_day + timedelta(days=1) if clock_in and clock_out < clock_in else complaint_day
                    event_time = datetime.combine(event_day, datetime.strptime(clock_out, "%H:%M").time())
                    _record_attendance_event(employee_id, None, "out", "admin", "corrected", session["user"]["user"], f"Giờ ra đã xác minh theo khiếu nại {complaint_id}", happened_at=event_time, work_date=complaint_day)
                _record_attendance_event(employee_id, None, "correction", "admin", "updated", session["user"]["user"], f"KN {complaint_id}: {resolution}", work_date=complaint_day)
                flash("Đã cập nhật giờ công và xử lý khiếu nại.", "success")
                if db.scalar("SELECT COUNT(*) FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?", (employee_id, complaint_day.month, complaint_day.year)):
                    flash("Kỳ lương đã tính trước đó; hãy mở lại và tính lại kỳ để áp dụng thay đổi.", "error")
                return redirect(url_for("chamcong", date=complaint_day.isoformat()))
            if action == "complaint":
                if admin():
                    raise ValueError("Nhân viên gửi khiếu nại bằng tài khoản của mình.")
                exception_type = request.form.get("LoaiNgoaiLe", "")
                detail = request.form.get("NoiDung", "").strip()
                if exception_type not in ("Quên chấm vào/ra", "Máy chấm công lỗi", "Sai giờ ghi nhận", "Khác"):
                    raise ValueError("Loại ngoại lệ chấm công không hợp lệ.")
                reason = f"[{exception_type}] {detail}"
                complaint_day = date.fromisoformat(request.form.get("Ngay", ""))
                if not detail or len(reason) > 1000:
                    raise ValueError("Nội dung khiếu nại bắt buộc và tối đa 1000 ký tự.")
                db.execute("INSERT INTO KhieuNaiChamCong(MaNV,Ngay,NoiDung) VALUES(?,?,?)", (manv, complaint_day, reason))
                _audit_attendance(manv, "manual", "complaint", "submitted", actor=session["user"]["user"], detail=reason)
                flash("Đã gửi khiếu nại chấm công để quản trị viên xem xét.", "success")
                return redirect(url_for("chamcong", date=complaint_day.isoformat()))
            if action not in ("in", "out"):
                raise ValueError("Thao tác chấm công không hợp lệ.")
            if not admin() and (not request.form.get("LyDo") or len(request.form.get("LyDo", "").strip()) < 5):
                raise ValueError("Hãy nhập lý do khi dùng chấm công dự phòng.")
            occurred_at = datetime.now()
            actor = session["user"]["user"]
            detail = request.form.get("LyDo", "")
            work_date = _attendance_work_date(int(manv), occurred_at)
            _record_attendance_cycle(
                int(manv), work_date, action, source, "recorded", actor,
                detail=detail, occurred_at=occurred_at,
            )
            flash("Đã ghi nhận chấm công.", "success")
        except Exception as e:
            flash(_safe_error(e), "error")
        return redirect(url_for("chamcong"))
    flt = "" if admin() else " AND MaNV=%d" % int(session["user"].get("manv") or -1)
    try:
        people = db.query(
            "SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm'"
            + flt
            + " ORDER BY HoTen"
        )[1]
        cols, rows = db.query(
            "SELECT c.MaCC AS [Mã CC],n.HoTen AS [Nhân viên],c.Ngay AS [Ngày],c.GioVao AS [Giờ vào],c.GioRa AS [Giờ ra],c.TrangThai AS [Trạng thái] FROM ChamCong c JOIN NhanVien n ON n.MaNV=c.MaNV WHERE c.Ngay=?"
            + flt.replace("MaNV", "c.MaNV")
            + " ORDER BY c.MaCC DESC",
            (selected_day,),
        )
    except Exception as e:
        people = []
        cols, rows = [], []
        flash(_safe_error(e, "Không tải được dữ liệu chấm công."), "error")
    has_photo = False
    has_face = False
    has_current_face = False
    if not admin():
        manv = session["user"].get("manv")
        if manv:
            has_photo = bool(db.scalar("SELECT CASE WHEN AnhHoSo IS NULL THEN 0 ELSE 1 END FROM NhanVien WHERE MaNV=?", (manv,)) or 0)
            has_face = bool(db.scalar("SELECT COUNT(*) FROM NhanVienKhuonMat WHERE MaNV=?", (manv,)) or 0)
            has_current_face = bool(db.scalar("SELECT COUNT(*) FROM NhanVienKhuonMat WHERE MaNV=? AND ConsentVersion=?", (manv, config.FACE_CONSENT_VERSION)) or 0)
    return render_template(
        "attendance.html",
        people=people,
        cols=cols,
        rows=rows,
        today=today,
        selected_day=selected_day,
        admin=admin(),
        face_csrf=face_csrf,
        has_photo=has_photo,
        has_face=has_face,
        has_current_face=has_current_face,
        face_logs=db.query("SELECT TOP 200 n.HoTen,j.Nguon,j.ThaoTac,j.KetQua,j.Similarity,j.ThoiDiem,j.NguoiThucHien,j.ChiTiet FROM NhatKyChamCong j JOIN NhanVien n ON n.MaNV=j.MaNV ORDER BY j.MaNhatKy DESC", ())[1] if admin() else [],
        attendance_events=(db.query("SELECT TOP 300 n.HoTen,e.NgayCong,e.ThoiDiem,e.LoaiSuKien,e.Nguon,e.KetQua,e.Similarity,e.NguoiThucHien,e.ChiTiet FROM ChamCongSuKien e JOIN NhanVien n ON n.MaNV=e.MaNV ORDER BY e.ThoiDiem DESC", ())[1] if admin() else db.query("SELECT TOP 100 n.HoTen,e.NgayCong,e.ThoiDiem,e.LoaiSuKien,e.Nguon,e.KetQua,e.Similarity,e.NguoiThucHien,e.ChiTiet FROM ChamCongSuKien e JOIN NhanVien n ON n.MaNV=e.MaNV WHERE e.MaNV=? ORDER BY e.ThoiDiem DESC", (session["user"].get("manv") or -1,))[1]),
        complaints=db.query("SELECT k.MaKN,k.MaNV,n.HoTen,k.Ngay,k.NoiDung,k.TaoLuc FROM KhieuNaiChamCong k JOIN NhanVien n ON n.MaNV=k.MaNV WHERE k.TrangThai=N'Chờ xử lý' ORDER BY k.TaoLuc", ())[1] if admin() else [],
        face_retention_days=config.FACE_RETENTION_DAYS,
        face_consent_version=config.FACE_CONSENT_VERSION,
        my_complaints=db.query("SELECT Ngay,NoiDung,TrangThai,PhanHoi FROM KhieuNaiChamCong WHERE MaNV=? ORDER BY TaoLuc DESC", (session["user"].get("manv") or -1,))[1] if not admin() else [],
    )


@app.route("/api/nhanvien/<int:manv>/anh")
@login_required
def nhanvien_anh(manv):
    if not admin() and str(session["user"].get("manv") or "") != str(manv):
        return "", 403
    blob = db.scalar("SELECT AnhHoSo FROM NhanVien WHERE MaNV=?", (manv,))
    if not blob:
        return "", 404
    response = make_response(bytes(blob))
    response.headers["Content-Type"] = "image/jpeg"
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


_face_purge_day = None

def _purge_expired_face_templates():
    global _face_purge_day
    today = date.today()
    if _face_purge_day == today:
        return
    db.execute(
        "SET XACT_ABORT ON; BEGIN TRAN; INSERT INTO NhatKyChamCong(MaNV,Nguon,ThaoTac,KetQua,ChiTiet) SELECT MaNV,N'system',N'retention_delete',N'deleted',N'Mẫu khuôn mặt hết thời hạn lưu' FROM NhanVienKhuonMat WHERE ConsentAt<DATEADD(day,-?,SYSUTCDATETIME()); DELETE FROM NhanVienKhuonMat WHERE ConsentAt<DATEADD(day,-?,SYSUTCDATETIME()); COMMIT;",
        (config.FACE_RETENTION_DAYS, config.FACE_RETENTION_DAYS),
    )
    _face_purge_day = today


def _face_cipher():
    if not config.FACE_ENCRYPTION_KEY:
        raise RuntimeError("Quản trị viên cần cấu hình FACE_ENCRYPTION_KEY trước khi dùng nhận diện khuôn mặt.")
    try:
        return Fernet(config.FACE_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, TypeError):
        raise RuntimeError("FACE_ENCRYPTION_KEY không hợp lệ; hãy tạo khóa Fernet mới.")


def _audit_attendance(manv, source, action, result, attendance_id=None, similarity=None, actor=None, detail=None):
    db.execute(
        "INSERT INTO NhatKyChamCong(MaCC,MaNV,Nguon,ThaoTac,KetQua,Similarity,NguoiThucHien,ChiTiet) VALUES(?,?,?,?,?,?,?,?)",
        (attendance_id, manv, source, action, result, similarity, actor, (detail or "")[:500] or None),
    )


def _record_attendance_event(manv, attendance_id, action, source, result, actor, detail=None, similarity=None, happened_at=None, work_date=None):
    """Append an event while retaining its business date and legacy summary link."""
    happened_at = happened_at or datetime.now()
    db.execute(
        "INSERT INTO ChamCongSuKien(MaNV,NgayCong,MaCC,ThoiDiem,LoaiSuKien,Nguon,KetQua,Similarity,NguoiThucHien,ChiTiet) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (manv, work_date or happened_at.date(), attendance_id, happened_at, action, source, result, similarity, actor, (detail or "")[:500]),
    )


def _attendance_status(manv, work_date, occurred_at):
    shifts = db.query(
        "SELECT COALESCE(p.GioBatDauOverride,c.GioBatDau),c.PhutAnHan FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.MaNV=? AND p.Ngay=? ORDER BY COALESCE(p.GioBatDauOverride,c.GioBatDau)",
        (manv, work_date),
    )[1]
    actual_minutes = occurred_at.hour * 60 + occurred_at.minute
    if shifts:
        start, grace = shifts[0]
        cutoff = (start.hour * 60 + start.minute + grace) % 1440
    else:
        cutoff_time = datetime.strptime(GIO_VAO_CHUAN, "%H:%M").time()
        cutoff = cutoff_time.hour * 60 + cutoff_time.minute
    return "Đi muộn" if actual_minutes > cutoff else "Đi làm"


def _attendance_work_date(manv, occurred_at):
    work_date = occurred_at.date()
    previous_day = work_date - timedelta(days=1)
    overnight_shifts = db.query(
        "SELECT COALESCE(p.GioKetThucOverride,c.GioKetThuc) FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.MaNV=? AND p.Ngay=? AND ((p.GioBatDauOverride IS NOT NULL OR p.GioKetThucOverride IS NOT NULL) AND COALESCE(p.GioKetThucOverride,c.GioKetThuc)<COALESCE(p.GioBatDauOverride,c.GioBatDau) OR p.GioBatDauOverride IS NULL AND p.GioKetThucOverride IS NULL AND c.QuaDem=1)",
        (manv, previous_day),
    )[1]
    return previous_day if any(occurred_at.time() <= shift_end for (shift_end,) in overnight_shifts) else work_date


def _record_attendance_cycle(manv, work_date, action, source, result, actor, detail=None, similarity=None, occurred_at=None):
    """Atomically append an in/out event and update the compatible daily summary."""
    occurred_at = occurred_at or datetime.now()
    status = _attendance_status(manv, work_date, occurred_at)
    sql = """
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    DECLARE @action NVARCHAR(20)=?, @employee_id INT=?, @work_date DATE=?,
            @event_at DATETIME2=?, @status NVARCHAR(20)=?, @source NVARCHAR(20)=?,
            @result NVARCHAR(30)=?, @similarity DECIMAL(7,5)=?,
            @actor NVARCHAR(50)=?, @detail NVARCHAR(500)=?, @attendance_id INT,
            @last_action NVARCHAR(20), @lock_result INT, @resource NVARCHAR(255);
    SET @resource=CONCAT(N'attendance:',@employee_id,N':',CONVERT(NVARCHAR(10),@work_date,23));
    EXEC @lock_result=sys.sp_getapplock
        @Resource=@resource,
        @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000,@DbPrincipal='public';
    IF @lock_result<0 THROW 51010,'Attendance record is busy.',1;
    SELECT TOP (1) @last_action=LoaiSuKien
      FROM ChamCongSuKien WITH (UPDLOCK,HOLDLOCK)
     WHERE MaNV=@employee_id AND NgayCong=@work_date
       AND LoaiSuKien IN (N'in',N'out',N'delete')
     ORDER BY MaSuKien DESC;
    IF @last_action=N'delete' SET @last_action=NULL;
    IF @action=N'in' AND @last_action=N'in' THROW 51011,'An in event is already open.',1;
    IF @action=N'out' AND ISNULL(@last_action,N'')<>N'in' THROW 51012,'There is no open in event.',1;
    SELECT @attendance_id=MaCC FROM ChamCong WITH (UPDLOCK,HOLDLOCK)
     WHERE MaNV=@employee_id AND Ngay=@work_date;
    IF @action=N'in'
    BEGIN
        IF @attendance_id IS NULL
            INSERT INTO ChamCong(MaNV,Ngay,GioVao,TrangThai)
            VALUES(@employee_id,@work_date,CAST(@event_at AS TIME),@status);
        ELSE
            UPDATE ChamCong SET GioVao=COALESCE(GioVao,CAST(@event_at AS TIME)),
                GioRa=NULL,TrangThai=CASE WHEN GioVao IS NULL THEN @status ELSE TrangThai END
             WHERE MaCC=@attendance_id;
    END
    ELSE
    BEGIN
        IF @attendance_id IS NULL THROW 51012,'There is no daily summary for this event.',1;
        UPDATE ChamCong SET GioRa=CAST(@event_at AS TIME) WHERE MaCC=@attendance_id;
    END;
    SELECT @attendance_id=MaCC FROM ChamCong WHERE MaNV=@employee_id AND Ngay=@work_date;
    INSERT INTO ChamCongSuKien(MaNV,NgayCong,MaCC,ThoiDiem,LoaiSuKien,Nguon,KetQua,Similarity,NguoiThucHien,ChiTiet)
    VALUES(@employee_id,@work_date,@attendance_id,@event_at,@action,@source,@result,@similarity,@actor,@detail);
    INSERT INTO NhatKyChamCong(MaCC,MaNV,Nguon,ThaoTac,KetQua,Similarity,NguoiThucHien,ChiTiet)
    VALUES(@attendance_id,@employee_id,@source,@action,@result,@similarity,@actor,@detail);
    COMMIT;
    """
    try:
        db.execute(sql, (action, manv, work_date, occurred_at, status, source, result, similarity, actor, (detail or "")[:500]))
    except Exception as error:
        message = str(error)
        if "51010" in message:
            raise ValueError("Đang ghi nhận chấm công khác cho ngày này. Hãy thử lại.") from error
        if "51011" in message:
            raise ValueError("Chưa chấm ra khỏi lượt làm trước đó.") from error
        if "51012" in message:
            raise ValueError("Cần chấm vào trước khi chấm ra.") from error
        raise
def _attendance_intervals(employee_id, start_at, end_at):
    rows = db.query(
        "SELECT e.ThoiDiem,e.LoaiSuKien FROM ChamCongSuKien e WHERE e.MaNV=? AND e.ThoiDiem>=? AND e.ThoiDiem<=? AND e.LoaiSuKien IN (N'in',N'out') AND e.MaSuKien>ISNULL((SELECT MAX(x.MaSuKien) FROM ChamCongSuKien x WHERE x.MaNV=e.MaNV AND x.NgayCong=e.NgayCong AND x.LoaiSuKien=N'delete'),0) ORDER BY e.ThoiDiem,e.MaSuKien",
        (employee_id, start_at - timedelta(hours=24), end_at),
    )[1]
    intervals, opened = [], None
    for occurred_at, action in rows:
        if action == "delete":
            opened = None
        elif action == "in" and opened is None:
            opened = occurred_at
        elif action == "out" and opened is not None and occurred_at >= opened:
            intervals.append((opened, occurred_at))
            opened = None
    return intervals


def _observed_overtime_hours(employee_id, start_at, end_at):
    seconds = sum(
        (min(end, end_at) - max(start, start_at)).total_seconds()
        for start, end in _attendance_intervals(employee_id, start_at, end_at)
        if min(end, end_at) > max(start, start_at)
    )
    return round(seconds / 3600, 2)


def face_payload():
    if not hmac.compare_digest(
        request.headers.get("X-Face-CSRF", ""), session.get("face_csrf", "")
    ):
        return None, (jsonify(error="Phiên làm việc hết hạn. Hãy tải lại trang."), 400)
    if request.content_length and request.content_length > 65536:
        return None, (jsonify(error="Dữ liệu quét quá lớn. Hãy thử lại."), 413)
    data = request.get_json(silent=True) or {}
    embedding = data.get("embedding")
    if (
        not isinstance(embedding, list)
        or len(embedding) != 1024
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or abs(v) > 10
            for v in embedding
        )
    ):
        return None, (jsonify(error="Mẫu khuôn mặt không hợp lệ. Hãy quét lại."), 400)
    return data, None


def face_employee_id(data):
    if admin():
        raise ValueError("Chấm công bằng khuôn mặt chỉ dành cho tài khoản nhân viên.")
    try:
        manv = int(session["user"].get("manv") or 0)
    except (TypeError, ValueError):
        manv = 0
    if not manv:
        raise ValueError(
            "Tài khoản chưa gắn với nhân viên nào hoặc chưa chọn nhân viên."
        )
    if not db.scalar(
        "SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'", (manv,)
    ):
        raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
    return manv


@app.route("/api/chamcong/face/enroll", methods=["POST"])
@login_required
def face_enroll():
    data, error = face_payload()
    if error:
        return error
    try:
        if data.get("consent") is not True:
            raise ValueError(
                "Cần xác nhận đã có sự đồng ý trước khi lưu dữ liệu khuôn mặt."
            )
        manv = face_employee_id(data)
        if not data.get("consent_purpose") or data.get("consent_version") != config.FACE_CONSENT_VERSION:
            raise ValueError("Cần xác nhận rõ mục đích và phiên bản thông báo xử lý dữ liệu khuôn mặt.")
        cipher = _face_cipher()
        embedding = cipher.encrypt(json.dumps(data["embedding"], separators=(",", ":")).encode()).decode("ascii")
        db.execute(
            "IF EXISTS(SELECT 1 FROM NhanVienKhuonMat WHERE MaNV=?) UPDATE NhanVienKhuonMat SET Embedding=?,ConsentAt=SYSUTCDATETIME(),ConsentVersion=?,UpdatedAt=SYSUTCDATETIME() WHERE MaNV=? ELSE INSERT INTO NhanVienKhuonMat(MaNV,Embedding,ConsentVersion) VALUES(?,?,?)",
            (manv, embedding, config.FACE_CONSENT_VERSION, manv, manv, embedding, config.FACE_CONSENT_VERSION),
        )
        _audit_attendance(manv, "face", "enroll", "success", actor=session["user"]["user"], detail="Đồng ý phiên bản " + config.FACE_CONSENT_VERSION)
        return jsonify(message="Đã đăng ký mẫu khuôn mặt đã mã hóa."), 200
    except Exception:
        app.logger.exception("Face enrollment failed")
        return jsonify(error="Không thể đăng ký dữ liệu khuôn mặt. Hãy thử lại hoặc liên hệ quản trị viên."), 400


@app.route("/api/chamcong/face/delete", methods=["POST"])
@login_required
def face_delete():
    data = request.get_json(silent=True) or {}
    if not hmac.compare_digest(
        request.headers.get("X-Face-CSRF", ""), session.get("face_csrf", "")
    ):
        return jsonify(error="Phiên làm việc hết hạn. Hãy tải lại trang."), 400
    try:
        manv = face_employee_id(data)
        db.execute("DELETE FROM NhanVienKhuonMat WHERE MaNV=?", (manv,))
        _audit_attendance(manv, "face", "delete_template", "success", actor=session["user"]["user"], detail="Nhân viên chủ động thu hồi đồng ý/xóa mẫu")
        return jsonify(message="Đã xóa dữ liệu khuôn mặt."), 200
    except Exception:
        app.logger.exception("Face template deletion failed")
        return jsonify(error="Không thể xóa dữ liệu khuôn mặt. Hãy thử lại hoặc liên hệ quản trị viên."), 400


@app.route("/api/chamcong/face/challenge", methods=["POST"])
@login_required
def face_challenge():
    if admin():
        return jsonify(error="Chấm công khuôn mặt chỉ dành cho tài khoản nhân viên."), 403
    if not hmac.compare_digest(request.headers.get("X-Face-CSRF", ""), session.get("face_csrf", "")):
        return jsonify(error="Phiên làm việc hết hạn. Hãy tải lại trang."), 400
    own_id = int(session.get("user", {}).get("manv") or 0)
    if not own_id or not db.scalar("SELECT COUNT(*) FROM NhanVienKhuonMat WHERE MaNV=?", (own_id,)):
        return jsonify(error="Tài khoản chưa có mẫu khuôn mặt. Hãy đăng ký mẫu trước."), 409
    sequence = ["left", "right"]
    secrets.SystemRandom().shuffle(sequence)
    nonce = secrets.token_urlsafe(24)
    session["face_live_challenge"] = {"nonce": nonce, "sequence": sequence, "expires": time.time() + 90}
    return jsonify(nonce=nonce, sequence=sequence, expires_in=90), 200


@app.route("/api/chamcong/face/scan", methods=["POST"])
@login_required
def face_scan():
    if admin():
        return jsonify(
            error="Chấm công bằng khuôn mặt chỉ dành cho tài khoản nhân viên."
        ), 403
    data, error = face_payload()
    if error:
        return error
    action = data.get("action")
    if action not in ("in", "out"):
        return jsonify(error="Vui lòng chọn chấm vào hoặc chấm ra."), 400
    challenge = session.pop("face_live_challenge", None)
    if not challenge or challenge["expires"] < time.time() or not hmac.compare_digest(str(data.get("nonce", "")), challenge["nonce"]):
        return jsonify(error="Thử thách camera đã hết hạn hoặc không hợp lệ. Hãy bắt đầu lại.", fallback=True), 409
    if data.get("sequence") != challenge["sequence"] or data.get("blinked") is not True:
        return jsonify(error="Chưa hoàn thành thử thách chuyển động và chớp mắt.", fallback=True), 409
    try:
        real_score = float(data.get("real_score"))
        live_score = float(data.get("live_score"))
    except (TypeError, ValueError):
        return jsonify(error="Không có điểm xác minh người thật hợp lệ.", fallback=True), 400
    if (
        not math.isfinite(real_score) or not math.isfinite(live_score)
        or not 0 <= real_score <= 1 or not 0 <= live_score <= 1
        or real_score < config.FACE_ANTISPOOF_THRESHOLD
        or live_score < config.FACE_LIVENESS_THRESHOLD
    ):
        _audit_attendance(int(session["user"].get("manv") or 0), "face", action, "rejected", actor=session["user"]["user"], detail=f"Liveness rejected; real={real_score if 'real_score' in locals() else 'invalid'}; live={live_score if 'live_score' in locals() else 'invalid'}")
        return jsonify(error="Không vượt qua kiểm tra chống giả mạo. Hãy thử lại bằng camera hoặc dùng chấm công dự phòng.", fallback=True), 409
    try:
        own_id = int(session["user"].get("manv") or 0)
        candidates = db.query(
            "SELECT f.MaNV,f.Embedding,n.HoTen,ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))),f.ConsentVersion FROM NhanVienKhuonMat f JOIN NhanVien n ON n.MaNV=f.MaNV WHERE n.TrangThai=N'Đang làm' AND f.MaNV=?",
            (own_id,),
        )[1]
        probe = data["embedding"]
        probe_norm = math.sqrt(sum(v * v for v in probe))
        best = None
        best_score = -1
        for manv, stored, name, code, consent_version in candidates:
            if consent_version != config.FACE_CONSENT_VERSION:
                _audit_attendance(own_id, "face", action, "rejected", actor=session["user"]["user"], detail="Phiên bản đồng ý đã thay đổi; cần đăng ký lại")
                return jsonify(error="Thông báo về dữ liệu khuôn mặt đã thay đổi. Hãy đọc và đồng ý lại bằng cách đăng ký lại mẫu.", fallback=True), 409
            try:
                known = json.loads(_face_cipher().decrypt(stored.encode("ascii")))
            except (TypeError, ValueError, InvalidToken):
                continue
            if not isinstance(known, list) or len(known) != len(probe):
                continue
            known_norm = math.sqrt(sum(v * v for v in known))
            if not probe_norm or not known_norm:
                continue
            score = sum(a * b for a, b in zip(probe, known)) / (probe_norm * known_norm)
            if score > best_score:
                best = (manv, name, code)
                best_score = score
        if best is None or best_score < FACE_MATCH_THRESHOLD:
            _audit_attendance(own_id, "face", action, "rejected", similarity=max(0, best_score), actor=session["user"]["user"], detail="Không đạt ngưỡng; ngưỡng cấu hình=" + str(FACE_MATCH_THRESHOLD))
            return jsonify(
                error="Không nhận diện được khuôn mặt đã đăng ký. Hãy chọn ảnh rõ hơn hoặc dùng chấm công dự phòng.", fallback=True
            ), 404
        manv, name, code = best
        now = datetime.now()
        work_date = _attendance_work_date(manv, now)
        _record_attendance_cycle(
            manv, work_date, action, "face", "matched", session["user"]["user"],
            detail=f"Live camera challenge; real={real_score:.3f}; live={live_score:.3f}",
            similarity=best_score, occurred_at=now,
        )
        return jsonify(
            message="Đã ghi nhận chấm công.",
            employee=name,
            code=code,
            similarity=round(best_score, 3),
            action=action,
        ), 200
    except ValueError as error:
        return jsonify(error=str(error), fallback=True), 409
    except Exception:
        app.logger.exception("Face attendance processing failed")
        return jsonify(error="Không thể ghi nhận chấm công. Hãy dùng phương thức dự phòng hoặc liên hệ quản trị viên."), 400


LEAVE_TYPES = ("Phép năm", "Không lương", "Nghỉ ốm", "Việc riêng có lương", "Khác")
def _leave_days(employee_id, start, end):
    scheduled = db.query("SELECT Thu FROM LichLamViecNhanVien WHERE MaNV=?", (employee_id,))[1]
    work_days = {row[0] for row in scheduled} if scheduled else set(range(7)) - set(config.NGAY_NGHI_TUAN)
    holidays = {row[0] for row in db.query("SELECT Ngay FROM LichNgayLe WHERE Ngay>=? AND Ngay<=?", (start, end))[1]}
    assigned_days = {row[0] for row in db.query("SELECT DISTINCT Ngay FROM PhanCaNhanVien WHERE MaNV=? AND Ngay>=? AND Ngay<=?", (employee_id, start, end))[1]}
    if assigned_days:
        return sum(day not in holidays for day in assigned_days)
    return sum(
        1
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() in work_days
        and start + timedelta(days=offset) not in holidays
    )


def _leave_audit(leave_id, employee_id, action, old_status, new_status, detail, actor):
    db.execute("INSERT INTO NhatKyNghiPhep(MaNP,MaNV,ThaoTac,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien) VALUES(?,?,?,?,?,?,?)", (leave_id, employee_id, action, old_status, new_status, (detail or "")[:1000], actor))


def _leave_notify(employee_id, leave_id, message):
    db.execute("INSERT INTO ThongBaoNghiPhep(MaNV,MaNP,NoiDung) VALUES(?,?,?)", (employee_id, leave_id, message[:500]))


_LEAVE_PENDING_DAYS = """ISNULL(SUM(CASE
    WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
         AND LoaiCu=N'Phép năm' AND SoNgayCu IS NOT NULL
    THEN CASE WHEN SoNgay>SoNgayCu THEN SoNgay-SoNgayCu ELSE 0 END
    ELSE SoNgay END),0)"""


def _leave_quota(employee_id, year):
    row = db.query("SELECT SoNgayCap,SoNgayChuyen FROM QuyPhepNam WHERE MaNV=? AND Nam=?", (employee_id, year))[1]
    allocated, carry = row[0] if row else (0, 0)
    used = db.scalar("SELECT ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0) FROM NghiPhep WHERE MaNV=? AND ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy')) OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL)) AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=?", (employee_id, year)) or 0
    pending = db.scalar(f"SELECT {_LEAVE_PENDING_DAYS} FROM NghiPhep WHERE MaNV=? AND LoaiNghi=N'Phép năm' AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND YEAR(TuNgay)=?", (employee_id, year)) or 0
    return float(allocated), float(carry), float(used), float(pending)


def _save_leave_quota(employee_id, year, allocated, carry):
    sql = f"""SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    DECLARE @employee_id INT=?, @year INT=?, @allocated DECIMAL(6,2)=?,
            @carry DECIMAL(6,2)=?, @resource NVARCHAR(255), @lock_result INT,
            @used DECIMAL(9,2)=0, @pending DECIMAL(9,2)=0;
    SET @resource=CONCAT(N'leave-quota:',@employee_id);
    EXEC @lock_result=sys.sp_getapplock @Resource=@resource,@LockMode='Exclusive',
         @LockOwner='Transaction',@LockTimeout=10000,@DbPrincipal='public';
    IF @lock_result<0 THROW 52030,'Leave quota lock unavailable.',1;
    SELECT @used=ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
           AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0)
    FROM NghiPhep WHERE MaNV=@employee_id AND
         ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy'))
          OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL))
      AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
                    AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=@year;
    SELECT @pending={_LEAVE_PENDING_DAYS}
    FROM NghiPhep WHERE MaNV=@employee_id AND LoaiNghi=N'Phép năm'
      AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
      AND YEAR(TuNgay)=@year;
    IF @allocated+@carry<@used+@pending
        THROW 52031,'Annual leave allocation is below reserved balance.',1;
    IF EXISTS(SELECT 1 FROM QuyPhepNam WITH(UPDLOCK,HOLDLOCK) WHERE MaNV=@employee_id AND Nam=@year)
        UPDATE QuyPhepNam SET SoNgayCap=@allocated,SoNgayChuyen=@carry WHERE MaNV=@employee_id AND Nam=@year;
    ELSE
        INSERT INTO QuyPhepNam(MaNV,Nam,SoNgayCap,SoNgayChuyen) VALUES(@employee_id,@year,@allocated,@carry);
    COMMIT;
    SELECT 1 AS Saved;"""
    try:
        result = db.query(sql, (employee_id, year, allocated, carry))[1]
    except Exception as error:
        message = str(error)
        if "52030" in message:
            raise ValueError("Đang cập nhật quỹ phép khác; vui lòng thử lại.") from error
        if "52031" in message:
            allocated, carry, used, pending = _leave_quota(employee_id, year)
            raise ValueError(f"Quỹ mới phải tối thiểu {used + pending:g} ngày để giữ đủ ngày đã dùng và các đơn đang chờ.") from error
        raise
    if not result:
        raise RuntimeError("SQL Server không xác nhận đã lưu quỹ phép.")


def _create_leave_request(employee_id, start, end, days, reason, leave_type, state, actor):
    sql = f"""SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    DECLARE @employee_id INT=?, @start DATE=?, @end DATE=?, @days INT=?,
            @reason NVARCHAR(255)=?, @leave_type NVARCHAR(40)=?, @state NVARCHAR(20)=?,
            @actor NVARCHAR(50)=?, @year INT=YEAR(?), @lock_result INT,
            @resource NVARCHAR(255), @allocated DECIMAL(6,2)=0, @carry DECIMAL(6,2)=0,
            @used DECIMAL(9,2)=0, @pending DECIMAL(9,2)=0, @leave_id INT;
    SET @resource=CONCAT(N'leave-quota:',@employee_id);
    EXEC @lock_result=sys.sp_getapplock @Resource=@resource,@LockMode='Exclusive',
         @LockOwner='Transaction',@LockTimeout=10000,@DbPrincipal='public';
    IF @lock_result<0 THROW 52010,'Leave request lock unavailable.',1;
    IF EXISTS(SELECT 1 FROM NghiPhep WITH(UPDLOCK,HOLDLOCK)
        WHERE MaNV=@employee_id AND TrangThai NOT IN (N'Từ chối',N'Đã rút',N'Đã hủy')
          AND ((TuNgay<=@end AND DenNgay>=@start) OR (NgayCuTu<=@end AND NgayCuDen>=@start)))
        THROW 52011,'Leave date overlaps another active request.',1;
    IF @leave_type=N'Phép năm'
    BEGIN
        SELECT @allocated=SoNgayCap,@carry=SoNgayChuyen
        FROM QuyPhepNam WITH(UPDLOCK,HOLDLOCK) WHERE MaNV=@employee_id AND Nam=@year;
        SELECT @used=ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
               AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0)
        FROM NghiPhep WHERE MaNV=@employee_id AND
             ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy'))
              OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL))
          AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
                        AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=@year;
        SELECT @pending={_LEAVE_PENDING_DAYS}
        FROM NghiPhep WHERE MaNV=@employee_id AND LoaiNghi=N'Phép năm'
          AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
          AND YEAR(TuNgay)=@year;
        IF @days>@allocated+@carry-@used-@pending
            THROW 52012,'Annual leave quota is insufficient.',1;
    END;
    INSERT INTO NghiPhep(MaNV,TuNgay,DenNgay,SoNgay,LyDo,LoaiNghi,TrangThai)
    VALUES(@employee_id,@start,@end,@days,@reason,@leave_type,@state);
    SET @leave_id=CONVERT(INT,SCOPE_IDENTITY());
    INSERT INTO NhatKyNghiPhep(MaNP,MaNV,ThaoTac,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien)
    VALUES(@leave_id,@employee_id,N'submit',NULL,@state,CONCAT(@leave_type,N'; ',@days,N' ngĂ y'),@actor);
    COMMIT;
    SELECT @leave_id AS MaNP;"""
    try:
        result = db.query(
            sql,
            (employee_id, start, end, days, reason, leave_type, state, actor, start),
        )[1]
    except Exception as error:
        message = str(error)
        if "52010" in message:
            raise ValueError("Đang xử lý yêu cầu nghỉ khác; vui lòng gửi lại.") from error
        if "52011" in message:
            raise ValueError("Khoảng ngày vừa trùng với một đơn nghỉ đang hoạt động.") from error
        if "52012" in message:
            allocated, carry, used, pending = _leave_quota(employee_id, start.year)
            available = max(0, allocated + carry - used - pending)
            raise ValueError(f"Quỹ phép năm còn {available:g} ngày, không đủ cho yêu cầu {days} ngày.") from error
        raise
    if not result:
        raise RuntimeError("SQL Server đã lưu đơn nhưng không trả mã đơn mới.")
    return result[0][0]


def _update_leave_request(leave_id, employee_id, start, end, days, reason, leave_type, state, expected_state, expected_start, expected_end, expected_days, expected_type, actor):
    sql = f"""SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    DECLARE @leave_id INT=?, @employee_id INT=?, @start DATE=?, @end DATE=?, @days INT=?,
            @reason NVARCHAR(255)=?, @leave_type NVARCHAR(40)=?, @state NVARCHAR(40)=?,
            @expected_state NVARCHAR(40)=?, @expected_start DATE=?, @expected_end DATE=?,
            @expected_days INT=?, @expected_type NVARCHAR(40)=?, @actor NVARCHAR(50)=?,
            @year INT=YEAR(?),
            @old_start DATE, @old_end DATE, @old_days INT, @old_type NVARCHAR(40),
            @old_state NVARCHAR(40), @save_old BIT=0, @lock_result INT,
            @resource NVARCHAR(255), @allocated DECIMAL(6,2)=0, @carry DECIMAL(6,2)=0,
            @used DECIMAL(9,2)=0, @pending DECIMAL(9,2)=0;
    SET @resource=CONCAT(N'leave-quota:',@employee_id);
    EXEC @lock_result=sys.sp_getapplock @Resource=@resource,@LockMode='Exclusive',
         @LockOwner='Transaction',@LockTimeout=10000,@DbPrincipal='public';
    IF @lock_result<0 THROW 52020,'Leave change lock unavailable.',1;
    SELECT @old_start=TuNgay,@old_end=DenNgay,@old_days=SoNgay,@old_type=LoaiNghi,@old_state=TrangThai
    FROM NghiPhep WITH(UPDLOCK,HOLDLOCK)
    WHERE MaNP=@leave_id AND MaNV=@employee_id;
    IF @old_state IS NULL OR @old_state<>@expected_state OR @old_start<>@expected_start
       OR @old_end<>@expected_end OR @old_days<>@expected_days OR @old_type<>@expected_type
        THROW 52021,'Leave request changed before update.',1;
    IF @old_state NOT IN (N'Chờ quản lý',N'Chờ nhân sự',N'Đã duyệt')
        THROW 52021,'Leave request is no longer editable.',1;
    IF EXISTS(SELECT 1 FROM NghiPhep WITH(UPDLOCK,HOLDLOCK)
        WHERE MaNV=@employee_id AND MaNP<>@leave_id
          AND TrangThai NOT IN (N'Từ chối',N'Đã rút',N'Đã hủy')
          AND ((TuNgay<=@end AND DenNgay>=@start) OR (NgayCuTu<=@end AND NgayCuDen>=@start)))
        THROW 52022,'Leave date overlaps another active request.',1;
    IF @leave_type=N'Phép năm'
    BEGIN
        SELECT @allocated=SoNgayCap,@carry=SoNgayChuyen
        FROM QuyPhepNam WITH(UPDLOCK,HOLDLOCK) WHERE MaNV=@employee_id AND Nam=@year;
        SELECT @used=ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
               AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0)
        FROM NghiPhep WHERE MaNV=@employee_id AND MaNP<>@leave_id AND
             ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy'))
              OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL))
          AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
                        AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=@year;
        SELECT @pending={_LEAVE_PENDING_DAYS}
        FROM NghiPhep WHERE MaNV=@employee_id AND MaNP<>@leave_id AND LoaiNghi=N'Phép năm'
          AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
          AND YEAR(TuNgay)=@year;
        IF @days>@allocated+@carry-@used-@pending
            THROW 52023,'Annual leave quota is insufficient.',1;
    END;
    SET @save_old=CASE WHEN @old_state=N'Đã duyệt' AND @state<>N'Đã duyệt' THEN 1 ELSE 0 END;
    UPDATE NghiPhep SET TuNgay=@start,DenNgay=@end,SoNgay=@days,LyDo=@reason,LoaiNghi=@leave_type,
        NgayCuTu=CASE WHEN @save_old=1 THEN @old_start ELSE NULL END,
        NgayCuDen=CASE WHEN @save_old=1 THEN @old_end ELSE NULL END,
        SoNgayCu=CASE WHEN @save_old=1 THEN @old_days ELSE NULL END,
        LoaiCu=CASE WHEN @save_old=1 THEN @old_type ELSE NULL END,TrangThai=@state
    WHERE MaNP=@leave_id AND MaNV=@employee_id;
    IF @@ROWCOUNT<>1 THROW 52021,'Leave request changed before update.',1;
    INSERT INTO NhatKyNghiPhep(MaNP,MaNV,ThaoTac,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien)
    VALUES(@leave_id,@employee_id,N'change',@old_state,@state,
        CONCAT(CONVERT(NVARCHAR(10),@old_start,23),N' -> ',CONVERT(NVARCHAR(10),@start,23)),@actor);
    COMMIT;
    SELECT 1 AS Updated;"""
    try:
        result = db.query(
            sql,
            (leave_id, employee_id, start, end, days, reason, leave_type, state,
             expected_state, expected_start, expected_end, expected_days, expected_type, actor, start),
        )[1]
    except Exception as error:
        message = str(error)
        if "52020" in message:
            raise ValueError("Đang xử lý yêu cầu nghỉ khác; vui lòng gửi lại.") from error
        if "52021" in message:
            raise ValueError("Đơn nghỉ đã được cập nhật hoặc không còn ở trạng thái có thể sửa.") from error
        if "52022" in message:
            raise ValueError("Khoảng ngày mới vừa trùng với một đơn nghỉ đang hoạt động.") from error
        if "52023" in message:
            allocated, carry, used, pending = _leave_quota(employee_id, start.year)
            available = max(0, allocated + carry - used - pending)
            raise ValueError(f"Quỹ phép năm còn {available:g} ngày, không đủ cho thay đổi này ({days} ngày).") from error
        raise
    if not result:
        raise RuntimeError("SQL Server không xác nhận đã cập nhật đơn nghỉ.")


@app.route("/nghiphep", methods=["GET", "POST"])
@login_required
def nghiphep():
    leave_admin = has_permission("leave.view_all")
    manager_role = is_manager()
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            own_id = int(session["user"].get("manv") or 0)
            policy = db.query("SELECT YeuCauQuanLy,YeuCauNhanSu FROM CauHinhNghiPhep WHERE Id=1")[1][0]
            require_manager, require_hr = bool(policy[0]), bool(policy[1])
            if action == "policy" and has_permission("leave.manage_policy"):
                db.execute("UPDATE CauHinhNghiPhep SET YeuCauQuanLy=?,YeuCauNhanSu=? WHERE Id=1", (1 if request.form.get("YeuCauQuanLy") else 0, 1 if request.form.get("YeuCauNhanSu") else 0))
                flash("Đã lưu luồng duyệt nghỉ phép.", "success")
            elif action == "manager" and has_permission("leave.manage_policy"):
                employee_id, manager_id = int(request.form["MaNV"]), int(request.form["MaQuanLy"])
                if employee_id == manager_id or not db.scalar("SELECT COUNT(*) FROM NhanVien n JOIN TaiKhoan t ON t.MaNV=n.MaNV AND t.VaiTro=N'QuanLy' WHERE n.MaNV=? AND n.TrangThai=N'Đang làm'", (manager_id,)):
                    raise ValueError("Quản lý phải có vai trò QuanLy, đang làm và khác với nhân viên được gán.")
                old_manager = db.scalar("SELECT MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (employee_id,))
                if old_manager != manager_id:
                    current_start = db.scalar("SELECT MAX(TuNgay) FROM LichSuCongTac WHERE MaNV=? AND DenNgay IS NULL", (employee_id,))
                    today = date.today()
                    if current_start and today < current_start:
                        raise ValueError("Ngày hiệu lực mới trước mốc lịch sử hiện tại.")
                    snapshot = db.query("SELECT MaPB,MaCV,MaViTri,LuongCoBan FROM NhanVien WHERE MaNV=?", (employee_id,))[1]
                    if not snapshot:
                        raise ValueError("Không tìm thấy hồ sơ nhân viên.")
                    snapshot = list(snapshot[0])
                    manager_sql = "IF EXISTS(SELECT 1 FROM QuanLyTrucTiep WHERE MaNV=?) UPDATE QuanLyTrucTiep SET MaQuanLy=? WHERE MaNV=? ELSE INSERT INTO QuanLyTrucTiep(MaNV,MaQuanLy) VALUES(?,?);"
                    manager_params = [employee_id, manager_id, employee_id, employee_id, manager_id]
                    if current_start == today:
                        history_sql = "UPDATE LichSuCongTac SET MaQuanLy=?,NguoiCapNhat=?,LyDo=N'Cập nhật quản lý trực tiếp' WHERE MaNV=? AND DenNgay IS NULL;"
                        history_params = [manager_id, actor, employee_id]
                    else:
                        history_sql = "UPDATE LichSuCongTac SET DenNgay=DATEADD(day,-1,?) WHERE MaNV=? AND DenNgay IS NULL; INSERT INTO LichSuCongTac(MaNV,TuNgay,MaPB,MaCV,MaViTri,MaQuanLy,LuongCoBan,NguoiCapNhat,LyDo) VALUES(?,?,?,?,?,?,?,?,N'Cập nhật quản lý trực tiếp');"
                        history_params = [today, employee_id, employee_id, today] + snapshot[:3] + [manager_id, snapshot[3], actor]
                    manager_audit_sql = "INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'cap_nhat',N'MaQuanLy',?);"
                    db.execute("SET XACT_ABORT ON; BEGIN TRAN; " + manager_sql + history_sql + manager_audit_sql + " COMMIT;", manager_params + history_params + [employee_id, actor])
                flash("Đã lưu quản lý trực tiếp.", "success")
            elif action == "quota" and has_permission("leave.manage_quota"):
                employee_id, quota_year = int(request.form["MaNV"]), int(request.form["Nam"])
                allocated, carry = float(request.form.get("SoNgayCap", 0)), float(request.form.get("SoNgayChuyen", 0))
                if not 2000 <= quota_year <= 2100 or not all(math.isfinite(v) and 0 <= v <= 366 for v in (allocated, carry)):
                    raise ValueError("Năm hoặc số ngày phép không hợp lệ.")
                _, _, used, pending = _leave_quota(employee_id, quota_year)
                if allocated + carry < used + pending:
                    raise ValueError(
                        f"Quỹ mới phải tối thiểu {used + pending:g} ngày để giữ đủ ngày đã dùng và các đơn đang chờ."
                    )
                _save_leave_quota(employee_id, quota_year, allocated, carry)
                flash("Đã cập nhật quỹ phép năm.", "success")
            elif action == "schedule" and has_permission("leave.manage_schedule"):
                employee_id = int(request.form["MaNV"])
                days = {int(value) for value in request.form.getlist("Thu")}
                if not days or any(value not in range(7) for value in days):
                    raise ValueError("Lịch cần có ít nhất một ngày làm việc.")
                db.execute_batches([
                    ("DELETE FROM LichLamViecNhanVien WHERE MaNV=?", [(employee_id,)]),
                    ("INSERT INTO LichLamViecNhanVien(MaNV,Thu) VALUES(?,?)", [(employee_id, day) for day in sorted(days)]),
                ])
                flash("Đã lưu lịch làm việc theo tuần.", "success")
            elif action == "read_notice" and not leave_admin:
                db.execute("UPDATE ThongBaoNghiPhep SET DaDoc=1 WHERE MaTB=? AND MaNV=?", (request.form["id"], own_id))
            elif action == "submit":
                employee_id = int(request.form["MaNV"] if leave_admin else own_id)
                start, end = date.fromisoformat(request.form["TuNgay"]), date.fromisoformat(request.form["DenNgay"])
                leave_type, reason = request.form.get("LoaiNghi", ""), request.form.get("LyDo", "").strip()
                if not employee_id or end < start or start.year != end.year:
                    raise ValueError("Tài khoản hoặc khoảng ngày nghỉ không hợp lệ; mỗi đơn chỉ thuộc một năm.")
                if leave_type not in LEAVE_TYPES or len(reason) > 255:
                    raise ValueError("Loại nghỉ không hợp lệ hoặc lý do vượt quá 255 ký tự.")
                if not db.scalar("SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'", (employee_id,)):
                    raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
                days = _leave_days(employee_id, start, end)
                if not days:
                    raise ValueError("Khoảng nghỉ không có ngày làm việc theo lịch nhân viên.")
                if db.scalar("SELECT COUNT(*) FROM NghiPhep WHERE MaNV=? AND TrangThai NOT IN (N'Từ chối',N'Đã rút',N'Đã hủy') AND ((TuNgay<=? AND DenNgay>=?) OR (NgayCuTu<=? AND NgayCuDen>=?))", (employee_id, end, start, end, start)):
                    raise ValueError("Khoảng ngày trùng với đơn đang chờ, đã duyệt hoặc đang yêu cầu hủy.")
                if leave_type == "Phép năm":
                    allocated, carry, used, pending = _leave_quota(employee_id, start.year)
                    available = allocated + carry - used - pending
                    if days > available:
                        raise ValueError(f"Quỹ phép năm còn {max(0, available):g} ngày, không đủ cho yêu cầu {days} ngày.")
                manager = db.scalar("SELECT MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (employee_id,))
                if require_manager and not manager:
                    raise ValueError("Chưa gán quản lý trực tiếp cho nhân viên; quản trị viên cần cấu hình trước khi gửi đơn.")
                state = "Chờ quản lý" if require_manager else ("Chờ nhân sự" if require_hr else "Đã duyệt")
                leave_id = _create_leave_request(
                    employee_id, start, end, days, reason, leave_type, state, actor
                )
                _leave_notify(employee_id, leave_id, f"Đơn nghỉ {start}–{end} đã được gửi; trạng thái: {state}.")
                if state == "Chờ quản lý":
                    _leave_notify(manager, leave_id, f"Có đơn nghỉ phép của nhân viên cần bạn xem xét ({start}–{end}).")
                flash("Đã gửi đơn nghỉ phép.", "success")
            elif action in ("approve", "reject"):
                leave_id = int(request.form["id"])
                item = db.query("SELECT p.MaNV,p.TrangThai,p.TuNgay,p.DenNgay,p.SoNgay,p.NgayCuTu,p.NgayCuDen,p.SoNgayCu,p.LoaiCu,q.MaQuanLy FROM NghiPhep p LEFT JOIN QuanLyTrucTiep q ON q.MaNV=p.MaNV WHERE p.MaNP=?", (leave_id,))[1]
                if not item:
                    raise ValueError("Không tìm thấy đơn nghỉ phép.")
                employee_id, old_state = item[0][0], item[0][1]
                if old_state not in ("Chờ quản lý", "Chờ nhân sự", "Chờ quản lý hủy", "Chờ nhân sự hủy", "Chờ quản lý thay đổi", "Chờ nhân sự thay đổi"):
                    raise ValueError("Đơn không còn ở trạng thái chờ duyệt.")
                is_manager = manager_role and own_id and item[0][9] == own_id
                is_hr_reviewer = has_permission("leave.approve_hr")
                if old_state.startswith("Chờ quản lý") and not is_manager:
                    raise ValueError("Chỉ quản lý trực tiếp được chỉ định mới xử lý bước này.")
                if old_state.startswith("Chờ nhân sự") and not is_hr_reviewer:
                    raise ValueError("Đơn đang chờ bước nhân sự.")
                if not (is_manager or is_hr_reviewer):
                    raise ValueError("Bạn không có quyền xử lý đơn này.")
                if action == "reject":
                    if "hủy" in old_state:
                        new_state = "Đã duyệt"
                        db.execute("UPDATE NghiPhep SET TrangThai=N'Đã duyệt',PhanHoi=? WHERE MaNP=?", (request.form.get("PhanHoi", "").strip()[:1000], leave_id))
                    elif "thay đổi" in old_state and item[0][5]:
                        db.execute("UPDATE NghiPhep SET TuNgay=?,DenNgay=?,SoNgay=?,LoaiNghi=?,TrangThai=N'Đã duyệt',NgayCuTu=NULL,NgayCuDen=NULL,SoNgayCu=NULL,LoaiCu=NULL WHERE MaNP=?", (item[0][5], item[0][6], item[0][7], item[0][8], leave_id))
                        new_state = "Đã duyệt"
                    else:
                        new_state = "Từ chối"
                        db.execute("UPDATE NghiPhep SET TrangThai=?,PhanHoi=? WHERE MaNP=?", (new_state, request.form.get("PhanHoi", "").strip()[:1000], leave_id))
                    _leave_notify(employee_id, leave_id, f"Đơn nghỉ {item[0][2]}–{item[0][3]} bị từ chối. {request.form.get('PhanHoi', '').strip()[:300]}")
                elif old_state.startswith("Chờ quản lý"):
                    stem = "hủy" if "hủy" in old_state else ("thay đổi" if "thay đổi" in old_state else "")
                    new_state = ("Chờ nhân sự " + stem).strip() if require_hr else ("Đã hủy" if stem == "hủy" else "Đã duyệt")
                    db.execute("UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id))
                    if new_state.startswith("Chờ nhân sự"):
                        _leave_notify(employee_id, leave_id, "Quản lý đã duyệt; đơn đang chờ nhân sự.")
                    else:
                        db.execute("UPDATE NghiPhep SET NgayCuTu=NULL,NgayCuDen=NULL,SoNgayCu=NULL,LoaiCu=NULL WHERE MaNP=?", (leave_id,))
                        _leave_notify(employee_id, leave_id, "Đơn nghỉ đã được hủy." if new_state == "Đã hủy" else "Đơn nghỉ đã được duyệt.")
                else:
                    new_state = "Đã hủy" if "hủy" in old_state else "Đã duyệt"
                    db.execute("UPDATE NghiPhep SET TrangThai=?,PhanHoi=?,NgayCuTu=NULL,NgayCuDen=NULL,SoNgayCu=NULL,LoaiCu=NULL WHERE MaNP=?", (new_state, request.form.get("PhanHoi", "").strip()[:1000], leave_id))
                    _leave_notify(employee_id, leave_id, "Đơn nghỉ đã được hủy." if new_state == "Đã hủy" else "Đơn nghỉ đã được nhân sự duyệt.")
                _leave_audit(leave_id, employee_id, action, old_state, new_state, request.form.get("PhanHoi", ""), actor)
                flash("Đã cập nhật trạng thái đơn nghỉ.", "success")
            elif action == "withdraw":
                leave_id = int(request.form["id"])
                item = db.query("SELECT MaNV,TrangThai,TuNgay,DenNgay FROM NghiPhep WHERE MaNP=?", (leave_id,))[1]
                if not item or item[0][0] != own_id:
                    raise ValueError("Không tìm thấy đơn của bạn.")
                employee_id, old_state, start, end = item[0]
                if old_state in ("Chờ quản lý", "Chờ nhân sự", "Chờ quản lý thay đổi", "Chờ nhân sự thay đổi"):
                    if old_state.endswith("thay đổi"):
                        change = db.query("SELECT NgayCuTu,NgayCuDen,SoNgayCu,LoaiCu FROM NghiPhep WHERE MaNP=?", (leave_id,))[1][0]
                        if change[0]:
                            db.execute("UPDATE NghiPhep SET TuNgay=?,DenNgay=?,SoNgay=?,LoaiNghi=?,TrangThai=N'Đã duyệt',NgayCuTu=NULL,NgayCuDen=NULL,SoNgayCu=NULL,LoaiCu=NULL WHERE MaNP=?", (*change, leave_id))
                            new_state = "Đã duyệt"
                        else:
                            new_state = "Đã rút"
                            db.execute("UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id))
                    else:
                        new_state = "Đã rút"
                        db.execute("UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id))
                elif old_state in ("Chờ quản lý hủy", "Chờ nhân sự hủy"):
                    new_state = "Đã duyệt"
                    db.execute("UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id))
                elif old_state == "Đã duyệt":
                    manager = db.scalar("SELECT MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (employee_id,))
                    new_state = "Chờ quản lý hủy" if require_manager and manager else "Chờ nhân sự hủy"
                else:
                    raise ValueError("Đơn này không thể rút hoặc hủy ở trạng thái hiện tại.")
                db.execute("UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id))
                _leave_audit(leave_id, employee_id, "withdraw", old_state, new_state, "Nhân viên yêu cầu rút/hủy đơn", actor)
                _leave_notify(employee_id, leave_id, f"Yêu cầu rút/hủy đơn đang ở trạng thái {new_state}.")
                if new_state == "Chờ quản lý hủy":
                    _leave_notify(manager, leave_id, f"Có yêu cầu hủy đơn đã duyệt ({start}–{end}) cần bạn xem xét.")
                flash("Đã ghi nhận yêu cầu rút/hủy đơn.", "success")
            elif action == "change":
                leave_id = int(request.form["id"])
                item = db.query("SELECT MaNV,TuNgay,DenNgay,SoNgay,LoaiNghi,TrangThai FROM NghiPhep WHERE MaNP=?", (leave_id,))[1]
                if not item or item[0][0] != own_id:
                    raise ValueError("Không tìm thấy đơn của bạn.")
                employee_id, old_start, old_end, old_days, old_type, old_state = item[0]
                if old_state not in ("Chờ quản lý", "Chờ nhân sự", "Đã duyệt"):
                    raise ValueError("Đơn ở trạng thái hiện tại không thể thay đổi.")
                start, end = date.fromisoformat(request.form["TuNgay"]), date.fromisoformat(request.form["DenNgay"])
                leave_type, reason = request.form.get("LoaiNghi", ""), request.form.get("LyDo", "").strip()
                days = _leave_days(employee_id, start, end)
                if end < start or start.year != end.year or not days or leave_type not in LEAVE_TYPES:
                    raise ValueError("Ngày, lịch làm việc hoặc loại nghỉ không hợp lệ.")
                if db.scalar("SELECT COUNT(*) FROM NghiPhep WHERE MaNV=? AND MaNP<>? AND TrangThai NOT IN (N'Từ chối',N'Đã rút',N'Đã hủy') AND ((TuNgay<=? AND DenNgay>=?) OR (NgayCuTu<=? AND NgayCuDen>=?))", (employee_id, leave_id, end, start, end, start)):
                    raise ValueError("Khoảng ngày mới bị trùng một đơn đang hiệu lực.")
                if leave_type == "Phép năm":
                    allocated, carry, used, pending = _leave_quota(employee_id, start.year)
                    reusable_days = old_days if old_type == "Phép năm" and old_start.year == start.year else 0
                    available = allocated + carry - used - pending + reusable_days
                    if days > available:
                        raise ValueError(f"Quỹ phép năm còn {max(0, available):g} ngày, không đủ cho thay đổi này.")
                if len(reason) > 255:
                    raise ValueError("Lý do nghỉ tối đa 255 ký tự.")
                manager = db.scalar("SELECT MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (employee_id,))
                if require_manager and not manager:
                    raise ValueError("Chưa gán quản lý trực tiếp cho nhân viên.")
                state = "Chờ quản lý thay đổi" if require_manager else ("Chờ nhân sự thay đổi" if require_hr else "Đã duyệt")
                _update_leave_request(
                    leave_id, employee_id, start, end, days, reason,
                    leave_type, state, old_state, old_start, old_end, old_days, old_type, actor
                )
                _leave_notify(employee_id, leave_id, f"Đã ghi nhận yêu cầu thay đổi ngày nghỉ; trạng thái: {state}.")
                if state.startswith("Chờ quản lý"):
                    _leave_notify(manager, leave_id, "Có yêu cầu thay đổi ngày nghỉ cần bạn xem xét.")
                flash("Đã gửi yêu cầu thay đổi ngày nghỉ.", "success")
            else:
                raise ValueError("Thao tác nghỉ phép không hợp lệ hoặc bạn không đủ quyền.")
        except Exception as e:
            flash(_safe_error(e), "error")
        return redirect(url_for("nghiphep"))

    own_id = int(session["user"].get("manv") or 0)
    flt = "" if leave_admin else " AND p.MaNV=%d" % own_id
    try:
        people = db.query(
            "SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm'"
            + (f" AND MaNV={own_id}" if not leave_admin else "")
            + " ORDER BY HoTen"
        )[1]
        cols, rows = db.query(
            "SELECT p.MaNP,n.HoTen,p.TuNgay,p.DenNgay,p.SoNgay,p.LoaiNghi,p.LyDo,p.TrangThai,p.PhanHoi FROM NghiPhep p JOIN NhanVien n ON n.MaNV=p.MaNV"
            + (" WHERE 1=1" + flt if flt else "")
            + " ORDER BY p.MaNP DESC"
        )
        manager_rows = db.query("SELECT p.MaNP,n.HoTen,p.TuNgay,p.DenNgay,p.SoNgay,p.LoaiNghi,p.LyDo,p.TrangThai,p.PhanHoi FROM NghiPhep p JOIN NhanVien n ON n.MaNV=p.MaNV JOIN QuanLyTrucTiep q ON q.MaNV=p.MaNV WHERE q.MaQuanLy=? AND p.TrangThai LIKE N'Chờ quản lý%' ORDER BY p.MaNP DESC", (own_id,))[1] if manager_role and own_id else []
        if leave_admin:
            manager_map = {row[0]: row[1] for row in db.query("SELECT MaNV,MaQuanLy FROM QuanLyTrucTiep", ())[1]}
        elif manager_role and own_id:
            manager_map = {row[0]: row[1] for row in db.query("SELECT MaNV,MaQuanLy FROM QuanLyTrucTiep WHERE MaQuanLy=? OR MaNV=?", (own_id, own_id))[1]}
        else:
            manager_map = {row[0]: row[1] for row in db.query("SELECT MaNV,MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (own_id,))[1]} if own_id else {}
        schedules, quotas = {}, {}
        if leave_admin:
            for employee, day in db.query("SELECT MaNV,Thu FROM LichLamViecNhanVien", ())[1]:
                schedules.setdefault(employee, set()).add(day)
            quota_base = {employee: (float(allocated), float(carry)) for employee, allocated, carry in db.query("SELECT MaNV,SoNgayCap,SoNgayChuyen FROM QuyPhepNam WHERE Nam=?", (date.today().year,))[1]}
            quota_used = {employee: float(days or 0) for employee, days in db.query("SELECT MaNV,ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0) FROM NghiPhep WHERE ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy')) OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL)) AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=? GROUP BY MaNV", (date.today().year,))[1]}
            quota_pending = {employee: float(days or 0) for employee, days in db.query(f"SELECT MaNV,{_LEAVE_PENDING_DAYS} FROM NghiPhep WHERE LoaiNghi=N'Phép năm' AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND YEAR(TuNgay)=? GROUP BY MaNV", (date.today().year,))[1]}
            quotas = {employee: (*quota_base.get(employee, (0, 0)), quota_used.get(employee, 0), quota_pending.get(employee, 0)) for employee, _, _ in people}
        elif own_id:
            quotas[own_id] = _leave_quota(own_id, date.today().year)
        notices = db.query("SELECT TOP 30 MaTB,MaNP,NoiDung,TaoLuc,DaDoc FROM ThongBaoNghiPhep WHERE MaNV=? ORDER BY MaTB DESC", (own_id,))[1] if own_id else []
    except Exception as e:
        people, manager_rows, manager_map, schedules, quotas, notices = [], [], {}, {}, {}, []
        cols, rows = [], []
        flash(_safe_error(e, "Không tải được dữ liệu nghỉ phép."), "error")
    policy = db.query("SELECT YeuCauQuanLy,YeuCauNhanSu FROM CauHinhNghiPhep WHERE Id=1")[1][0]
    available_managers = db.query("SELECT n.MaNV,n.HoTen FROM NhanVien n JOIN TaiKhoan t ON t.MaNV=n.MaNV AND t.VaiTro=N'QuanLy' WHERE n.TrangThai=N'Đang làm' ORDER BY n.HoTen")[1] if has_permission("leave.manage_policy") else []
    balance = quotas.get(own_id, (0, 0, 0, 0))
    current_year = date.today().year
    default_work_days = set(range(7)) - set(config.NGAY_NGHI_TUAN)
    return render_template(
        "leave.html", people=people, cols=cols, rows=rows, admin=leave_admin, manager_rows=manager_rows,
        manager_map=manager_map, schedules=schedules, quotas=quotas, notices=notices, policy=policy,
        available_managers=available_managers, leave_types=LEAVE_TYPES, own_id=own_id,
        balance=balance, current_year=current_year, default_work_days=default_work_days,
        leave_days=list(enumerate(("Thứ 2","Thứ 3","Thứ 4","Thứ 5","Thứ 6","Thứ 7","Chủ nhật"))),
    )


def _payroll_reason():
    reason = request.form.get("LyDo", "").strip()
    if not reason:
        raise ValueError("Vui lòng nhập lý do điều chỉnh lương.")
    if len(reason) > 500:
        raise ValueError("Lý do điều chỉnh tối đa 500 ký tự.")
    return reason


@app.route("/luong", methods=["GET", "POST"])
@login_required
def luong():
    if not payroll_staff():
        return "Bạn không có quyền xem hoặc xử lý bảng lương.", 403
    try:
        month = int(request.values.get("month", date.today().month))
        year = int(request.values.get("year", date.today().year))
    except (TypeError, ValueError):
        return "Tháng hoặc năm không hợp lệ.", 400
    if month not in range(1, 13) or year not in range(2000, 2101):
        return "Tháng hoặc năm không hợp lệ.", 400
    saved_rules = db.query(
        "SELECT TyLeThuongCC,HeSoTangCa FROM LuongCauHinhThang WHERE Nam=? AND Thang=?",
        (year, month),
    )[1]
    bonus_rate = float(saved_rules[0][0]) if saved_rules else config.CHUYEN_CAN_TY_LE
    overtime_factor = float(saved_rules[0][1]) if saved_rules else config.HE_SO_TANG_CA
    active_policy_rows = db.query(
        "SELECT TOP 1 MaChinhSach,Ten,NgayHieuLuc,QuyTacJson,CanCu FROM PayrollPolicyVersion WHERE TrangThai=N'Đã duyệt' AND NgayHieuLuc<=? ORDER BY NgayHieuLuc DESC,MaChinhSach DESC",
        (date(year, month, 1),),
    )[1]
    active_policy = active_policy_rows[0] if active_policy_rows else None
    active_policy_rules = json.loads(active_policy[3]) if active_policy else None
    if active_policy_rules:
        bonus_rate = float(active_policy_rules["attendance_bonus_rate"])
        overtime_factor = float(active_policy_rules["overtime_factor"])
    policy_rows = db.query(
        "SELECT MaChinhSach,Ten,NgayHieuLuc,TrangThai,CanCu,NguoiTao,DuyetLuc FROM PayrollPolicyVersion ORDER BY NgayHieuLuc DESC,MaChinhSach DESC"
    )[1]
    period_status = get_period_status(db, year, month)
    period_state_rows = db.query("SELECT TinhLuc FROM LuongKy WHERE Nam=? AND Thang=?", (year,month))[1]
    period_calculated_at = period_state_rows[0][0] if period_state_rows else None
    if request.method == "POST":
        try:
            action = request.form.get("action")
            action_permission = {
                "approve": "payroll.approve", "lock": "payroll.lock", "reopen": "payroll.reopen",
                "calculate": "payroll.calculate", "delete": "payroll.delete",
                "adjust": "payroll.edit", "adjust_common": "payroll.edit",
                "adjust_extra_bonus": "payroll.edit",
                "policy_draft": "payroll.edit", "policy_approve": "payroll.approve",
                "profile_save": "payroll.edit", "item_add": "payroll.edit",
                "item_delete": "payroll.edit",
            }.get(action)
            if not action_permission or not has_permission(action_permission):
                return "Bạn không có quyền thực hiện thao tác bảng lương này.", 403
            if active_policy and action in {"adjust_common", "adjust_extra_bonus", "adjust"}:
                raise ValueError("Kỳ này đã có chính sách lương phiên bản. Hãy sửa khoản đầu vào rồi tính lại kỳ nháp để đồng bộ thuế và bảo hiểm.")
            if action in {"delete", "adjust_common", "adjust_extra_bonus", "adjust", "calculate", "profile_save", "item_add", "item_delete"} and period_status != "Nháp":
                raise ValueError("Kỳ lương đã được duyệt hoặc khóa; không thể sửa hoặc tính lại.")
            if action == "policy_draft":
                policy_name = request.form.get("TenChinhSach", "").strip()
                source = request.form.get("CanCu", "").strip()
                effective = date.fromisoformat(request.form.get("NgayHieuLuc", ""))
                if not policy_name or len(policy_name) > 120 or not source or len(source) > 1000:
                    raise ValueError("Tên chính sách và căn cứ áp dụng là bắt buộc.")
                try:
                    raw_policy = request.form.get("QuyTacJson", "")
                    if len(raw_policy) > 30000:
                        raise ValueError("Cấu hình chính sách quá dài.")
                    policy_json = json.loads(raw_policy)
                    validate_policy(policy_json)
                except (json.JSONDecodeError, TypeError) as error:
                    raise ValueError("Cấu hình chính sách phải là JSON hợp lệ.") from error
                db.execute(
                    "INSERT INTO PayrollPolicyVersion(Ten,NgayHieuLuc,QuyTacJson,CanCu,NguoiTao) VALUES(?,?,?,?,?)",
                    (policy_name, effective, json.dumps(policy_json, ensure_ascii=False), source, session["user"]["user"]),
                )
                db.execute(
                    "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriMoi,LyDo,NguoiThucHien) VALUES(NULL,?,?,N'Tạo bản nháp chính sách lương',?,?,?)",
                    (effective.month,effective.year,json.dumps({"ten":policy_name,"hieu_luc":effective,"quy_tac":policy_json},ensure_ascii=False,default=str),source,session["user"]["user"]),
                )
                flash("Đã lưu bản nháp chính sách lương. Bản nháp chưa được dùng để tính lương.", "success")
            elif action == "policy_approve":
                policy_id = int(request.form.get("MaChinhSach", ""))
                draft = db.query(
                    "SELECT QuyTacJson FROM PayrollPolicyVersion WHERE MaChinhSach=? AND TrangThai=N'Nháp'",
                    (policy_id,),
                )[1]
                if not draft:
                    raise ValueError("Không tìm thấy bản nháp chính sách.")
                validate_policy(json.loads(draft[0][0]))
                existing = db.scalar(
                    "SELECT COUNT(*) FROM PayrollPolicyVersion WHERE NgayHieuLuc=(SELECT NgayHieuLuc FROM PayrollPolicyVersion WHERE MaChinhSach=?) AND TrangThai=N'Đã duyệt'",
                    (policy_id,),
                )
                if existing:
                    raise ValueError("Đã có chính sách được duyệt cùng ngày hiệu lực.")
                approval_reason = _payroll_reason()
                db.execute(
                    "UPDATE PayrollPolicyVersion SET TrangThai=N'Đã duyệt',NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME() WHERE MaChinhSach=? AND TrangThai=N'Nháp'",
                    (session["user"]["user"], policy_id),
                )
                db.execute(
                    "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriMoi,LyDo,NguoiThucHien) SELECT NULL,MONTH(NgayHieuLuc),YEAR(NgayHieuLuc),N'Duyệt chính sách lương',CONCAT(N'Mã chính sách ',MaChinhSach,N' · ',Ten),?,? FROM PayrollPolicyVersion WHERE MaChinhSach=?",
                    (approval_reason,session["user"]["user"],policy_id),
                )
                db.execute(
                    "UPDATE k SET TinhLuc=NULL,TinhBoi=?,PhienBan=PhienBan+1 FROM LuongKy k WHERE (k.Nam*100+k.Thang)>=(SELECT YEAR(NgayHieuLuc)*100+MONTH(NgayHieuLuc) FROM PayrollPolicyVersion WHERE MaChinhSach=?) AND k.TrangThai=N'Nháp' AND EXISTS(SELECT 1 FROM Luong l WHERE l.Nam=k.Nam AND l.Thang=k.Thang)",
                    (session["user"]["user"],policy_id),
                )
                flash("Đã duyệt chính sách. Chính sách chỉ áp dụng cho kỳ bắt đầu từ ngày hiệu lực.", "success")
            elif action == "profile_save":
                employee_id = int(request.form.get("MaNV", ""))
                effective = date.fromisoformat(request.form.get("TuNgay", ""))
                dependents = int(request.form.get("NguoiPhuThuoc", ""))
                if dependents < 0 or dependents > 50:
                    raise ValueError("Số người phụ thuộc phải từ 0 đến 50.")
                resident_value = request.form.get("LaCuTru")
                insurance_value = request.form.get("ThamGiaBaoHiem")
                if resident_value not in ("0", "1") or insurance_value not in ("0", "1"):
                    raise ValueError("Cần xác định tình trạng cư trú và tham gia bảo hiểm.")
                insurance_base = request.form.get("LuongTinhBaoHiem", "").strip()
                insurance_base = int(insurance_base) if insurance_base else None
                if insurance_base is not None and insurance_base < 0:
                    raise ValueError("Lương tính bảo hiểm không được âm.")
                db.execute(
                    "IF EXISTS(SELECT 1 FROM PayrollEmployeeTaxProfile WHERE MaNV=? AND TuNgay=?) UPDATE PayrollEmployeeTaxProfile SET LaCuTru=?,NguoiPhuThuoc=?,ThamGiaBaoHiem=?,LuongTinhBaoHiem=?,NguoiCapNhat=? WHERE MaNV=? AND TuNgay=? ELSE INSERT INTO PayrollEmployeeTaxProfile(MaNV,TuNgay,LaCuTru,NguoiPhuThuoc,ThamGiaBaoHiem,LuongTinhBaoHiem,NguoiCapNhat) VALUES(?,?,?,?,?,?,?)",
                    (employee_id,effective,int(resident_value),dependents,int(insurance_value),insurance_base,session["user"]["user"],employee_id,effective,employee_id,effective,int(resident_value),dependents,int(insurance_value),insurance_base,session["user"]["user"]),
                )
                db.execute(
                    "UPDATE k SET TinhLuc=NULL,TinhBoi=?,PhienBan=PhienBan+1 FROM LuongKy k WHERE (k.Nam*100+k.Thang)>=(YEAR(?)*100+MONTH(?)) AND k.TrangThai=N'Nháp' AND EXISTS(SELECT 1 FROM Luong l WHERE l.MaNV=? AND l.Nam=k.Nam AND l.Thang=k.Thang)",
                    (session["user"]["user"],effective,effective,employee_id),
                )
                db.execute(
                    "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,N'Cập nhật hồ sơ thuế/bảo hiểm',?,?,?)",
                    (employee_id,month,year,json.dumps({"hieu_luc":effective,"cu_tru":bool(int(resident_value)),"nguoi_phu_thuoc":dependents,"tham_gia_bao_hiem":bool(int(insurance_value)),"luong_tinh_bao_hiem":insurance_base},ensure_ascii=False,default=str),"Cập nhật hồ sơ người lao động",session["user"]["user"]),
                )
                flash("Đã lưu hồ sơ thuế/bảo hiểm có hiệu lực theo ngày đã chọn.", "success")
            elif action == "item_add":
                employee_id = int(request.form.get("MaNV", ""))
                amount = int(request.form.get("SoTien", ""))
                item_type = request.form.get("Loai", "")
                name = request.form.get("TenKhoan", "").strip()
                reason = _payroll_reason()
                if item_type not in ("earning", "reduction", "deduction") or amount < 0 or not name or len(name) > 120:
                    raise ValueError("Loại, tên hoặc số tiền khoản lương không hợp lệ.")
                db.execute(
                    "INSERT INTO PayrollItem(MaNV,Nam,Thang,Loai,Ten,SoTien,ChiuThue,CanCuBaoHiem,DuocTruThue,LyDo,NguoiTao) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (employee_id,year,month,item_type,name,amount,int(request.form.get("ChiuThue")=="on"),int(request.form.get("CanCuBaoHiem")=="on"),int(request.form.get("DuocTruThue")=="on"),reason,session["user"]["user"]),
                )
                db.execute(
                    "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,N'Thêm khoản lương',?,?,?)",
                    (employee_id,year,month,json.dumps({"loai":item_type,"ten":name,"so_tien":amount,"chiu_thue":request.form.get("ChiuThue")=="on","can_cu_bao_hiem":request.form.get("CanCuBaoHiem")=="on","duoc_tru_thue":request.form.get("DuocTruThue")=="on"},ensure_ascii=False),reason,session["user"]["user"]),
                )
                invalidate_period(db,year,month,session["user"]["user"])
                flash("Đã thêm khoản lương cho kỳ nháp.", "success")
            elif action == "item_delete":
                item_id = int(request.form.get("MaKhoan", ""))
                reason = _payroll_reason()
                old_item = db.query("SELECT MaNV,Loai,Ten,SoTien FROM PayrollItem WHERE MaKhoan=? AND Nam=? AND Thang=?", (item_id,year,month))[1]
                if not old_item:
                    raise ValueError("Không tìm thấy khoản lương trong kỳ đã chọn.")
                db.execute("DELETE FROM PayrollItem WHERE MaKhoan=? AND Nam=? AND Thang=?", (item_id,year,month))
                employee_id,old_type,old_name,old_amount = old_item[0]
                db.execute("INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,LyDo,NguoiThucHien) VALUES(?,?,?,N'Xóa khoản lương',?,?,?)", (employee_id,year,month,json.dumps({"loai":old_type,"ten":old_name,"so_tien":old_amount},ensure_ascii=False,default=str),reason,session["user"]["user"]))
                invalidate_period(db,year,month,session["user"]["user"])
                flash("Đã xóa khoản lương khỏi kỳ nháp.", "success")
            elif action == "approve":
                reason = _payroll_reason()
                approve_period(db, year, month, session["user"]["user"], reason)
                flash("Đã phê duyệt kỳ lương.", "success")
            elif action == "lock":
                reason = _payroll_reason()
                lock_period(db, year, month, session["user"]["user"], reason)
                flash("Đã khóa kỳ lương. Chỉ có thể xuất phiếu lương sau bước này.", "success")
            elif action == "reopen":
                reason = _payroll_reason()
                reopen_period(db, year, month, session["user"]["user"], reason)
                flash("Đã mở lại kỳ lương để điều chỉnh. Hãy tính lại và gửi duyệt lần nữa.", "success")
            elif action == "delete":
                payroll_id = int(request.form.get("id", ""))
                reason = _payroll_reason()
                old = db.query(
                    "SELECT MaNV,LuongCB,ThuongThem,TongLuong FROM Luong WHERE MaLuong=? AND Thang=? AND Nam=?",
                    (payroll_id, month, year),
                )[1]
                if not old:
                    raise ValueError("Không tìm thấy dòng lương trong kỳ đã chọn.")
                manv, old_base, old_bonus, old_total = old[0]
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; DELETE FROM Luong WHERE MaLuong=? AND Thang=? AND Nam=?; INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,?,?,?,?,?); COMMIT;",
                    (
                        payroll_id, month, year, manv, month, year, "Xóa dòng lương",
                        json.dumps({"LuongCB": old_base, "ThuongThem": old_bonus, "TongLuong": old_total}, ensure_ascii=False, default=str),
                        None, reason, session["user"]["user"],
                    ),
                )
                touch_period(db, year, month, session["user"]["user"])
                flash("Đã xóa dòng lương.", "success")
            elif action == "adjust_common":
                reason = _payroll_reason()
                old_rules = {"TyLeThuongCC": bonus_rate * 100, "HeSoTangCa": overtime_factor}
                try:
                    bonus_rate = float(request.form.get("TyLeThuongCC", "")) / 100
                    overtime_factor = float(request.form.get("HeSoTangCa", ""))
                except (TypeError, ValueError):
                    raise ValueError("Vui lòng nhập phần trăm thưởng chuyên cần và hệ số tăng ca hợp lệ.")
                if not math.isfinite(bonus_rate) or not 0 <= bonus_rate <= 1:
                    raise ValueError("Tỷ lệ thưởng chuyên cần phải từ 0% đến 100%.")
                if not math.isfinite(overtime_factor) or not 0 <= overtime_factor <= 10:
                    raise ValueError("Hệ số tăng ca phải từ 0 đến 10.")
                apply_month_rules(db, year, month, bonus_rate, overtime_factor, old_rules, reason, session["user"]["user"])
                flash("Đã áp dụng mức thưởng chuyên cần và hệ số tăng ca chung cho bảng lương tháng này.", "success")
            elif action == "adjust_extra_bonus":
                reason = _payroll_reason()
                try:
                    payroll_id = int(request.form.get("id", ""))
                    extra_bonus = int(request.form.get("ThuongThem", ""))
                except (TypeError, ValueError):
                    raise ValueError("Thưởng thêm phải là số nguyên không âm.")
                if extra_bonus < 0:
                    raise ValueError("Thưởng thêm không được âm.")
                row = db.query(
                    "SELECT MaNV,LuongCB,NgayCong,GioTangCa,SoLanMuon,SoNgayNghiKP,ISNULL(ThuongThem,0) FROM Luong WHERE MaLuong=? AND Thang=? AND Nam=?",
                    (payroll_id, month, year),
                )[1]
                if not row:
                    raise ValueError("Không tìm thấy dòng lương trong kỳ đã chọn.")
                manv, base_salary, days, overtime_hours, late_count, unpaid_days, old_bonus = row[0]
                total = calculate_payroll(
                    base_salary,
                    days,
                    overtime_hours,
                    late_count,
                    unpaid_days,
                    bonus_rate,
                    overtime_factor,
                    extra_bonus,
                )[-1]
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; UPDATE Luong SET ThuongThem=?,TongLuong=? WHERE MaLuong=? AND Thang=? AND Nam=?; INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,?,?,?,?,?); COMMIT;",
                    (
                        extra_bonus, total, payroll_id, month, year, manv, month, year,
                        "Điều chỉnh thưởng thêm", str(old_bonus), str(extra_bonus),
                        reason, session["user"]["user"],
                    ),
                )
                touch_period(db, year, month, session["user"]["user"])
                flash("Đã cập nhật thưởng thêm cho nhân viên trong kỳ lương.", "success")
            elif action == "adjust":
                reason = _payroll_reason()
                try:
                    base_salary = int(request.form.get("LuongCB", ""))
                    payroll_id = int(request.form.get("id", ""))
                except (TypeError, ValueError):
                    raise ValueError("Lương cơ bản phải là số nguyên không âm.")
                if base_salary < 0:
                    raise ValueError("Lương cơ bản không được âm.")
                row = db.query(
                    "SELECT MaNV,LuongCB,NgayCong,GioTangCa,SoLanMuon,SoNgayNghiKP,ThuongThem FROM Luong WHERE MaLuong=? AND Thang=? AND Nam=?",
                    (payroll_id, month, year),
                )[1]
                if not row:
                    raise ValueError(
                        "Không tìm thấy dòng lương cần điều chỉnh."
                    )
                manv, old_base_salary, days, overtime_hours, late_count, unpaid_days, extra_bonus = row[0]
                (
                    attendance_bonus,
                    overtime_pay,
                    late_deduction,
                    unpaid_deduction,
                    deductions,
                    total,
                ) = calculate_payroll(
                    base_salary,
                    days,
                    overtime_hours,
                    late_count,
                    unpaid_days,
                    bonus_rate,
                    overtime_factor,
                    extra_bonus,
                )
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; UPDATE Luong SET LuongCB=?,LuongDieuChinh=?,ThuongCC=?,TienTangCa=?,PhuCap=?,TruMuon=?,TruNghiKP=?,KhauTru=?,TongLuong=? WHERE MaLuong=? AND Thang=? AND Nam=?; INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,?,?,?,?,?); COMMIT;",
                    (
                        base_salary,
                        base_salary,
                        attendance_bonus,
                        overtime_pay,
                        attendance_bonus + overtime_pay,
                        late_deduction,
                        unpaid_deduction,
                        deductions,
                        total,
                        payroll_id,
                        month,
                        year,
                        manv,
                        month,
                        year,
                        "Điều chỉnh lương cơ bản",
                        str(old_base_salary),
                        str(base_salary),
                        reason,
                        session["user"]["user"],
                    ),
                )
                touch_period(db, year, month, session["user"]["user"])
                flash(
                    "Đã cập nhật lương cơ bản riêng cho nhân viên; các khoản chuyên cần và tăng ca dùng mức chung của tháng.",
                    "success",
                )
            elif action == "calculate":
                today = date.today()
                if (year, month) > (today.year, today.month):
                    raise ValueError("Chưa thể tính lương cho tháng trong tương lai.")
                first = date(year, month, 1)
                last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
                people = db.query(
                    "SELECT MaNV,LuongCoBan,NgayVaoLam FROM NhanVien WHERE TrangThai=N'Đang làm'"
                )[1]
                rules = json.loads(active_policy[3]) if active_policy else None
                salary_history = {}
                if rules:
                    for history_row in db.query(
                        "SELECT MaNV,TuNgay,DenNgay,LuongCoBan FROM LichSuCongTac WHERE TuNgay<=? AND (DenNgay IS NULL OR DenNgay>=?) ORDER BY MaNV,TuNgay",
                        (last, first),
                    )[1]:
                        salary_history.setdefault(int(history_row[0]), []).append(history_row[1:])
                payroll_items_by_employee = {}
                for item in db.query(
                    "SELECT MaNV,Loai,Ten,SoTien,ChiuThue,CanCuBaoHiem,DuocTruThue FROM PayrollItem WHERE Nam=? AND Thang=? ORDER BY MaKhoan",
                    (year, month),
                )[1]:
                    payroll_items_by_employee.setdefault(int(item[0]), []).append({
                        "kind": item[1], "name": item[2], "amount": item[3],
                        "taxable": bool(item[4]), "insurable": bool(item[5]),
                        "tax_deductible": bool(item[6]),
                    })
                employee_profiles_by_id = {}
                if rules:
                    profiles = db.query(
                        "WITH Ranked AS (SELECT MaNV,LaCuTru,NguoiPhuThuoc,ThamGiaBaoHiem,LuongTinhBaoHiem,ROW_NUMBER() OVER(PARTITION BY MaNV ORDER BY TuNgay DESC) AS rn FROM PayrollEmployeeTaxProfile WHERE TuNgay<=?) SELECT MaNV,LaCuTru,NguoiPhuThuoc,ThamGiaBaoHiem,LuongTinhBaoHiem FROM Ranked WHERE rn=1",
                        (first,),
                    )[1]
                    employee_profiles_by_id = {int(r[0]): r[1:] for r in profiles}
                event_hours_by_employee = summarize_attendance_event_hours(db, year, month)
                cc = {}
                nghi = {}
                for r in db.query(
                    "SELECT MaNV,Ngay,GioVao,GioRa,TrangThai FROM ChamCong WHERE Ngay>=? AND Ngay<=?",
                    (first, last),
                )[1]:
                    cc.setdefault(r[0], []).append(r[1:])
                leave_reconciliation_by_employee = {}
                for r in db.query(
                    "SELECT MaNV,TuNgay,DenNgay,SoNgay,LoaiNghi FROM NghiPhep WHERE TrangThai=N'Đã duyệt' AND TuNgay<=? AND DenNgay>=?",
                    (last, first),
                )[1]:
                    nghi.setdefault(r[0], []).append(r[1:3])
                    leave_reconciliation_by_employee.setdefault(int(r[0]), []).append({
                        "from": r[1], "to": r[2], "days_recorded": r[3], "type": r[4],
                    })
                shifts_by_employee = {}
                for employee_id, work_date, start_time, grace in db.query(
                    "SELECT p.MaNV,p.Ngay,COALESCE(p.GioBatDauOverride,c.GioBatDau),c.PhutAnHan FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.Ngay>=? AND p.Ngay<?",
                    (first, date(year + (month == 12), month % 12 + 1, 1)),
                )[1]:
                    shifts_by_employee.setdefault(employee_id, {}).setdefault(work_date, []).append((start_time, grace))
                weekdays_by_employee = {}
                for employee_id, weekday in db.query("SELECT MaNV,Thu FROM LichLamViecNhanVien")[1]:
                    weekdays_by_employee.setdefault(employee_id, set()).add(weekday)
                holidays = {row[0] for row in db.query("SELECT Ngay FROM LichNgayLe WHERE Ngay>=? AND Ngay<?", (first, date(year + (month == 12), month % 12 + 1, 1)))[1]}
                existing_payroll = {
                    row[0]: (row[1], row[2])
                    for row in db.query(
                        "SELECT MaNV,LuongDieuChinh,ThuongThem FROM Luong WHERE Thang=? AND Nam=?",
                        (month, year),
                    )[1]
                }
                updates = []
                inserts = []
                statutory_snapshots = []
                for manv, luong_cb, ngay_vao in people:
                    previous = existing_payroll.get(manv)
                    salary_override = previous[0] if previous else None
                    if rules:
                        effective_salary_rows = salary_history.get(int(manv), [])
                        if not effective_salary_rows and ngay_vao:
                            effective_salary_rows = [(ngay_vao, None, luong_cb)]
                        luong_cb = effective_salary_for_period(
                            luong_cb, effective_salary_rows, first, last
                        )
                    if salary_override is not None:
                        luong_cb = salary_override
                    r = summarize_attendance(
                        ngay_vao,
                        cc.get(manv, []),
                        nghi.get(manv, []),
                        year,
                        month,
                        today,
                        work_weekdays=weekdays_by_employee.get(manv),
                        scheduled_shifts=shifts_by_employee.get(manv),
                        holidays=holidays,
                    )
                    next_month = date(year + (month == 12), month % 12 + 1, 1)
                    r["gio_tang_ca"] = float(db.scalar(
                        "SELECT ISNULL(SUM(SoGioThucTe),0) FROM TangCaYeuCau WHERE MaNV=? AND TrangThai=N'Đã xác nhận' AND XacNhanLuc IS NOT NULL AND BatDau>=CAST(? AS DATETIME2) AND BatDau<CAST(? AS DATETIME2)",
                        (manv, first, next_month),
                    ) or 0)
                    extra_bonus = previous[1] if previous and previous[1] is not None else 0
                    (
                        attendance_bonus,
                        overtime_pay,
                        late_deduction,
                        unpaid_deduction,
                        deductions,
                        total,
                    ) = calculate_payroll(
                        luong_cb,
                        r["ngay_di_lam"],
                        r["gio_tang_ca"],
                        r["so_lan_muon"],
                        r["so_ngay_nghi_kp"],
                        bonus_rate,
                        overtime_factor,
                        extra_bonus,
                        standard_workdays=active_policy_rules["standard_workdays_per_month"] if active_policy_rules else None,
                        hours_per_workday=active_policy_rules["hours_per_workday"] if active_policy_rules else None,
                        attendance_bonus_min_days=active_policy_rules["attendance_bonus_min_days"] if active_policy_rules else None,
                    )
                    vals = (
                        r["ngay_di_lam"],
                        luong_cb or 0,
                        attendance_bonus + overtime_pay,
                        deductions,
                        total,
                        attendance_bonus,
                        r["gio_tang_ca"],
                        overtime_pay,
                        r["so_lan_muon"],
                        late_deduction,
                        r["so_ngay_nghi_kp"],
                        unpaid_deduction,
                        event_hours_by_employee.get(manv, 0),
                    )
                    additional_items = payroll_items_by_employee.get(int(manv), [])
                    if rules:
                        profile = employee_profiles_by_id.get(int(manv))
                        if not profile or any(value is None for value in profile[:3]):
                            raise ValueError(f"Nhân viên mã {manv} chưa có hồ sơ cư trú, người phụ thuộc và bảo hiểm có hiệu lực từ {first:%d/%m/%Y}.")
                        resident, dependents, insurance_subject, insurance_base = profile
                        vals = list(vals)
                        vals[2] = int(vals[2] + sum(int(item["amount"]) * (-1 if item["kind"] == "reduction" else 1) for item in additional_items if item["kind"] != "deduction"))
                        vals[3] = int(vals[3] + sum(int(item["amount"]) for item in additional_items if item["kind"] == "deduction"))
                        component_items = []
                        for component_name, amount in (
                            ("attendance_bonus", attendance_bonus),
                            ("overtime", overtime_pay),
                            ("extra_bonus", extra_bonus or 0),
                        ):
                            flags = rules["components"][component_name]
                            component_items.append({"kind": "earning", "amount": amount, "taxable": flags["taxable"], "insurable": flags["insurable"]})
                        deduction_flags = rules["components"]["payroll_deductions"]
                        component_items.append({"kind": "reduction", "amount": deductions, "taxable": deduction_flags["taxable"], "insurable": deduction_flags["insurable"]})
                        component_items.extend(additional_items)
                        statutory = calculate_statutory_payroll(
                            base_salary=luong_cb, items=component_items, policy=rules,
                            tax_resident=bool(resident), dependents=dependents,
                            insurance_subject=bool(insurance_subject), insurance_base=insurance_base,
                        )
                        vals[4] = int(statutory["gross"])
                        vals.extend((int(statutory["personal_income_tax"]),
                                     int(statutory["employee_contributions"].get("bhxh", 0)),
                                     int(statutory["employee_contributions"].get("bhyt", 0)),
                                     int(statutory["employee_contributions"].get("bhtn", 0)),
                                     int(statutory["employer_contributions"].get("bhxh", 0)),
                                     int(statutory["employer_contributions"].get("bhyt", 0)),
                                     int(statutory["employer_contributions"].get("bhtn", 0)),
                                     int(statutory["employer_contributions"].get("tnld_bnn", 0)),
                                     int(statutory["net"])))
                        vals = tuple(vals)
                        statutory_snapshots.append((int(manv), json.dumps({
                            "base_salary": luong_cb, "attendance_days": r["ngay_di_lam"],
                            "scheduled_shifts": [{"date": work_day, "start": shift_start, "grace_minutes": grace} for work_day, shifts in shifts_by_employee.get(int(manv), {}).items() for shift_start, grace in shifts],
                            "holiday_dates": sorted(holidays),
                            "overtime_approved_hours": r["gio_tang_ca"], "event_hours_reconciliation": event_hours_by_employee.get(manv, 0),
                            "attendance_bonus": attendance_bonus, "overtime_pay": overtime_pay,
                            "unpaid_and_late_deductions": deductions, "extra_bonus": extra_bonus or 0,
                            "approved_leave_entries": leave_reconciliation_by_employee.get(int(manv), []),
                            "profile": {"tax_resident": bool(resident), "dependents": dependents, "insurance_subject": bool(insurance_subject), "insurance_base": insurance_base},
                            "additional_items": payroll_items_by_employee.get(int(manv), []),
                        }, ensure_ascii=False, default=str), json.dumps({key: (dict(value) if isinstance(value, dict) else value) for key, value in statutory.items()}, ensure_ascii=False, default=str)))
                    else:
                        vals = list(vals)
                        vals[2] = int(vals[2] + sum(int(item["amount"]) * (-1 if item["kind"] == "reduction" else 1) for item in additional_items if item["kind"] != "deduction"))
                        vals[3] = int(vals[3] + sum(int(item["amount"]) for item in additional_items if item["kind"] == "deduction"))
                        vals[4] = int(vals[4] + sum(int(item["amount"]) * (-1 if item["kind"] == "reduction" else 1) for item in additional_items if item["kind"] != "deduction"))
                        vals = tuple(vals) + (0, 0, 0, 0, 0, 0, 0, 0, 0)
                    if previous:
                        updates.append(vals + (manv, month, year))
                    else:
                        inserts.append(vals + (manv, month, year))
                db.execute_batches(
                    [
                        (
                            "UPDATE Luong SET NgayCong=?,LuongCB=?,PhuCap=?,KhauTru=?,TongLuong=?,ThuongCC=?,GioTangCa=?,TienTangCa=?,SoLanMuon=?,TruMuon=?,SoNgayNghiKP=?,TruNghiKP=?,GioGhiNhan=?,ThueTNCN=?,BHXH_NLD=?,BHYT_NLD=?,BHTN_NLD=?,BHXHDN=?,BHYTDN=?,BHTNDN=?,BH_TNLDBNN_DN=?,LuongThucLinh=? WHERE MaNV=? AND Thang=? AND Nam=?",
                            updates,
                        ),
                        (
                            "INSERT INTO Luong(NgayCong,LuongCB,PhuCap,KhauTru,TongLuong,ThuongCC,GioTangCa,TienTangCa,SoLanMuon,TruMuon,SoNgayNghiKP,TruNghiKP,GioGhiNhan,ThueTNCN,BHXH_NLD,BHYT_NLD,BHTN_NLD,BHXHDN,BHYTDN,BHTNDN,BH_TNLDBNN_DN,LuongThucLinh,MaNV,Thang,Nam) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            inserts,
                        ),
                        (
                            "IF NOT EXISTS(SELECT 1 FROM LuongKy WITH(UPDLOCK,HOLDLOCK) WHERE Nam=? AND Thang=?) INSERT INTO LuongKy(Nam,Thang,TrangThai) VALUES(?, ?, N'Nháp'); UPDATE LuongKy SET TinhLuc=SYSUTCDATETIME(),TinhBoi=?,PhienBan=PhienBan+1 WHERE Nam=? AND Thang=? AND TrangThai=N'Nháp'; IF @@ROWCOUNT<>1 THROW 50004,'Kỳ lương không còn ở trạng thái nháp.',1",
                            [(year, month, year, month, session["user"]["user"], year, month)],
                        ),
                    ]
                )
                if rules and statutory_snapshots:
                    line_ids = {int(row[0]): int(row[1]) for row in db.query(
                        "SELECT MaNV,MaLuong FROM Luong WHERE Nam=? AND Thang=?", (year, month)
                    )[1]}
                    snapshot_batches = []
                    for employee_id, inputs_json, result_json in statutory_snapshots:
                        payroll_row_id = line_ids[employee_id]
                        snapshot_batches.append((payroll_row_id, active_policy[0], active_policy[3], inputs_json, result_json))
                    db.execute_batches([(
                        "IF EXISTS(SELECT 1 FROM PayrollResultSnapshot WHERE MaLuong=?) UPDATE PayrollResultSnapshot SET MaChinhSach=?,QuyTacJson=?,DuLieuDauVaoJson=?,ChiTietTinhJson=?,TaoLuc=SYSUTCDATETIME() WHERE MaLuong=? ELSE INSERT INTO PayrollResultSnapshot(MaLuong,MaChinhSach,QuyTacJson,DuLieuDauVaoJson,ChiTietTinhJson) VALUES(?,?,?,?,?)",
                        [(row[0], row[1], row[2], row[3], row[4], row[0], row[0], row[1], row[2], row[3], row[4]) for row in snapshot_batches],
                    )])
                flash(
                    f"Đã tính lương tháng {month}/{year} cho {len(people)} nhân viên."
                    + (
                        " Tháng chưa kết thúc: ngày nghỉ không phép chỉ tính đến hôm qua."
                        if last >= today
                        else ""
                    ),
                    "success",
                )
            return redirect(url_for("luong", month=month, year=year))
        except Exception as e:
            flash(_safe_error(e, "Không thể xử lý bảng lương lúc này."), "error")
        return redirect(url_for("luong", month=month, year=year))
    history_cols, history_rows = [], []
    try:
        cols, rows = db.query(
            """SELECT l.MaLuong AS [Mã],n.HoTen AS [Nhân viên],l.NgayCong AS [Ngày đi làm],l.GioGhiNhan AS [Giờ ghi nhận],l.LuongCB AS [Lương cơ bản],
    CAST(ROUND(l.LuongCB / CAST(? AS DECIMAL(10,2)),0) AS DECIMAL(18,0)) AS [Lương/ngày],l.ThuongCC AS [Thưởng chuyên cần],
    CAST(CAST(l.GioTangCa AS DECIMAL(7,1)) AS VARCHAR(10)) AS [Giờ tăng ca],l.TienTangCa AS [Tiền tăng ca],
    l.SoLanMuon AS [Số lần muộn],l.TruMuon AS [Trừ đi muộn],l.SoNgayNghiKP AS [Ngày nghỉ KP],l.TruNghiKP AS [Trừ nghỉ KP],
    l.TongLuong AS [Tổng trước thuế/BHXH],l.ThueTNCN AS [Thuế TNCN],l.BHXH_NLD AS [BHXH NLĐ],l.BHYT_NLD AS [BHYT NLĐ],l.BHTN_NLD AS [BHTN NLĐ],l.BHXHDN AS [BHXH DN],l.BHYTDN AS [BHYT DN],l.BHTNDN AS [BHTN DN],l.BH_TNLDBNN_DN AS [TNLĐ-BNN DN],l.LuongThucLinh AS [Thực lĩnh] FROM Luong l JOIN NhanVien n ON n.MaNV=l.MaNV
    WHERE l.Thang=? AND l.Nam=? ORDER BY n.HoTen""",
            (CONG_CHUAN, month, year),
        )
        bonus_rows = db.query(
            "SELECT MaLuong,ThuongThem FROM Luong WHERE Thang=? AND Nam=?",
            (month, year),
        )[1]
        extra_bonuses = {r[0]: r[1] for r in bonus_rows}
        cols.append("Thưởng thêm")
        rows = [r + [extra_bonuses.get(r[0], 0)] for r in rows]
        snapshot_ids = {int(r[0]) for r in db.query(
            "SELECT s.MaLuong FROM PayrollResultSnapshot s JOIN Luong l ON l.MaLuong=s.MaLuong WHERE l.Thang=? AND l.Nam=?",
            (month,year),
        )[1]}
        cols.append("Đã lưu snapshot")
        rows = [r + ["Có" if int(r[0]) in snapshot_ids else "Chưa"] for r in rows]
        history_cols, history_rows = db.query(
            "SELECT CASE WHEN j.MaNV IS NULL THEN N'(Điều chỉnh chung)' ELSE ISNULL(n.HoTen,N'(Hồ sơ đã xóa)') END AS [Nhân viên],j.ThoiDiem AS [Thời điểm UTC],j.NguoiThucHien AS [Người thực hiện],j.HanhDong AS [Thao tác],j.GiaTriCu AS [Giá trị cũ],j.GiaTriMoi AS [Giá trị mới],j.LyDo AS [Lý do] FROM NhatKyLuong j LEFT JOIN NhanVien n ON n.MaNV=j.MaNV WHERE j.Thang=? AND j.Nam=? ORDER BY j.MaNhatKy DESC",
            (month, year),
        )
    except Exception as e:
        cols, rows = [], []
        flash(_safe_error(e, "Không tải được dữ liệu bảng lương."), "error")
    if rows:
        payroll_employee_ids = [
            row[0]
            for row in db.query("SELECT MaNV FROM Luong WHERE Thang=? AND Nam=?", (month, year))[1]
        ]
        sensitive_audit.record_many(payroll_employee_ids, "Luong", "list", session["user"]["user"])
    slip_people = []
    if period_status == "Đã khóa":
        slip_people = db.query(
            "SELECT l.MaNV,n.HoTen FROM Luong l JOIN NhanVien n ON n.MaNV=l.MaNV WHERE l.Thang=? AND l.Nam=? ORDER BY n.HoTen",
            (month, year),
        )[1]
    return render_template(
        "salary.html",
        cols=cols,
        rows=rows,
        month=month,
        year=year,
        standard=active_policy_rules["standard_workdays_per_month"] if active_policy_rules else CONG_CHUAN,
        cfg=config,
        attendance_bonus_percent=bonus_rate * 100,
        overtime_factor=overtime_factor,
        history_cols=history_cols,
        history_rows=history_rows,
        period_status=period_status,
        period_calculated_at=period_calculated_at,
        has_payroll=bool(rows),
        slip_people=slip_people,
        active_policy=active_policy,
        policy_rows=policy_rows,
        policy_json=active_policy[3] if active_policy else "",
        policy_employees=db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1],
        profile_rows=db.query("SELECT p.MaNV,n.HoTen,p.TuNgay,p.LaCuTru,p.NguoiPhuThuoc,p.ThamGiaBaoHiem,p.LuongTinhBaoHiem FROM PayrollEmployeeTaxProfile p JOIN NhanVien n ON n.MaNV=p.MaNV WHERE p.TuNgay=(SELECT MAX(p2.TuNgay) FROM PayrollEmployeeTaxProfile p2 WHERE p2.MaNV=p.MaNV AND p2.TuNgay<=?) ORDER BY n.HoTen", (date(year,month,1),))[1],
        pay_items=db.query("SELECT i.MaKhoan,n.HoTen,i.Loai,i.Ten,i.SoTien,i.ChiuThue,i.CanCuBaoHiem,i.DuocTruThue,i.LyDo FROM PayrollItem i JOIN NhanVien n ON n.MaNV=i.MaNV WHERE i.Nam=? AND i.Thang=? ORDER BY n.HoTen,i.MaKhoan", (year,month))[1],
        admin=payroll_staff(),
    )


def _salary_slip_response(manv, year, month):
    if month not in range(1, 13) or year not in range(2000, 2101):
        return "Tháng hoặc năm không hợp lệ.", 400
    state = db.query(
        "SELECT TrangThai FROM LuongKy WHERE Nam=? AND Thang=?", (year, month)
    )[1]
    if not state or state[0][0] != "Đã khóa":
        return "Phiếu lương chỉ được xem sau khi kỳ lương đã khóa.", 403
    rows = db.query(
        "SELECT n.HoTen,n.MaNV,l.Thang,l.Nam,l.NgayCong,l.LuongCB,l.ThuongCC,l.GioTangCa,l.TienTangCa,l.SoLanMuon,l.TruMuon,l.SoNgayNghiKP,l.TruNghiKP,l.ThuongThem,l.TongLuong,l.GioGhiNhan,l.ThueTNCN,l.BHXH_NLD,l.BHYT_NLD,l.BHTN_NLD,l.BHXHDN,l.BHYTDN,l.BHTNDN,l.BH_TNLDBNN_DN,l.LuongThucLinh FROM Luong l JOIN NhanVien n ON n.MaNV=l.MaNV WHERE l.MaNV=? AND l.Thang=? AND l.Nam=?",
        (manv, month, year),
    )[1]
    if not rows:
        return "Không tìm thấy phiếu lương.", 404
    snapshot = db.query("SELECT MaChinhSach,QuyTacJson,DuLieuDauVaoJson,ChiTietTinhJson,TaoLuc FROM PayrollResultSnapshot WHERE MaLuong=(SELECT MaLuong FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?)", (manv,month,year))[1]
    calculation_detail = json.loads(snapshot[0][3]) if snapshot else None
    taxable_income_display = f"{int(calculation_detail['taxable_income']):,}" if calculation_detail else None
    return render_template("salary_slip.html", row=rows[0], calculation_snapshot=snapshot[0] if snapshot else None, calculation_detail=calculation_detail, taxable_income_display=taxable_income_display)

@app.route("/luong/phieu/<int:manv>/<int:year>/<int:month>")
@login_required
def salary_slip(manv, year, month):
    if not has_permission("payroll.view") and (session["user"].get("manv") or -1) != manv:
        return "Bạn không có quyền xem phiếu lương này.", 403
    return _salary_slip_response(manv, year, month)

@app.route("/luong/phieu-cua-toi")
@login_required
def my_salary_slip():
    manv = session["user"].get("manv") or -1
    if manv < 0:
        return "Tài khoản chưa gắn với hồ sơ nhân viên.", 403
    if request.args.get("month") and request.args.get("year"):
        try:
            month = int(request.args["month"])
            year = int(request.args["year"])
        except (TypeError, ValueError):
            return "Tháng hoặc năm không hợp lệ.", 400
        return _salary_slip_response(manv, year, month)
    periods = db.query(
        "SELECT k.Nam,k.Thang FROM LuongKy k JOIN Luong l ON l.Nam=k.Nam AND l.Thang=k.Thang WHERE l.MaNV=? AND k.TrangThai=N'Đã khóa' ORDER BY k.Nam DESC,k.Thang DESC",
        (manv,),
    )[1]
    return render_template("my_salary_slips.html", periods=periods, manv=manv)


@app.route("/dieuchuyen", methods=["GET", "POST"])
@login_required
def dieuchuyen():
    if not admin():
        return redirect(url_for("dashboard"))
    try:
        db.execute("""IF OBJECT_ID('LichSuDieuChuyen','U') IS NULL
    CREATE TABLE LichSuDieuChuyen(
      MaDieuChuyen INT IDENTITY(1,1) PRIMARY KEY,
      MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
      MaPB_Cu INT NULL REFERENCES PhongBan(MaPB),
      MaPB_Moi INT NOT NULL REFERENCES PhongBan(MaPB),
      ThoiDiemChuyen DATETIME2(0) NOT NULL,
      LyDo NVARCHAR(500) NULL,
      NguoiThucHien NVARCHAR(100) NULL)""")
    except Exception as e:
        flash(_safe_error(e, "Không tạo được bảng lịch sử điều chuyển."), "error")
    if request.method == "POST":
        try:
            manv = int(request.form["MaNV"])
            pb_moi = int(request.form["MaPB_Moi"])
            thoi_diem = datetime.fromisoformat(request.form["ThoiDiemChuyen"])
            current = db.query("SELECT MaPB FROM NhanVien WHERE MaNV=?", (manv,))[1]
            if not current:
                raise ValueError("Không tìm thấy nhân viên.")
            pb_cu = current[0][0]
            if pb_cu is not None and int(pb_cu) == pb_moi:
                raise ValueError("Nhân viên hiện đã thuộc phòng ban này.")
            if not db.scalar(
                "SELECT COUNT(*) FROM PhongBan WHERE MaPB=? AND TrangThai=N'Hoạt động'",
                (pb_moi,),
            ):
                raise ValueError("Phòng ban mới không tồn tại hoặc đã ngừng hoạt động.")
            db.execute(
                """SET XACT_ABORT ON; BEGIN TRAN;
      INSERT INTO LichSuDieuChuyen(MaNV,MaPB_Cu,MaPB_Moi,ThoiDiemChuyen,LyDo,NguoiThucHien)
      VALUES(?,?,?,?,?,?);
      UPDATE NhanVien SET MaPB=? WHERE MaNV=?;
      COMMIT;""",
                (
                    manv,
                    pb_cu,
                    pb_moi,
                    thoi_diem,
                    request.form.get("LyDo", "").strip() or None,
                    session["user"]["user"],
                    pb_moi,
                    manv,
                ),
            )
            flash("Đã điều chuyển nhân viên và lưu ngày giờ chuyển.", "success")
        except Exception as e:
            flash(_safe_error(e, "Không thể hoàn tất điều chuyển lúc này."), "error")
        return redirect(url_for("dieuchuyen"))
    try:
        people = db.query(
            "SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen"
        )[1]
        departments = db.query(
            "SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB"
        )[1]
        cols, rows = db.query("""SELECT ls.MaDieuChuyen AS [Mã],n.HoTen AS [Nhân viên],
    ISNULL(cu.TenPB,N'(Chưa phân phòng)') AS [Phòng ban cũ],moi.TenPB AS [Phòng ban mới],
    ls.ThoiDiemChuyen AS [Ngày giờ chuyển],ls.LyDo AS [Lý do],ls.NguoiThucHien AS [Người thực hiện]
    FROM LichSuDieuChuyen ls JOIN NhanVien n ON n.MaNV=ls.MaNV
    LEFT JOIN PhongBan cu ON cu.MaPB=ls.MaPB_Cu JOIN PhongBan moi ON moi.MaPB=ls.MaPB_Moi
    ORDER BY ls.ThoiDiemChuyen DESC""")
    except Exception as e:
        people = []
        departments = []
        cols, rows = [], []
        flash(_safe_error(e, "Không tải được lịch sử điều chuyển."), "error")
    return render_template(
        "transfer.html",
        people=people,
        departments=departments,
        cols=cols,
        rows=rows,
        admin=admin(),
    )


EXTENDED_REPORTS = {
    "Tỷ lệ nghỉ việc",
    "Tỷ lệ vắng mặt",
    "Chi phí nhân sự (kỳ lương đã khóa)",
    "Thời gian tuyển dụng",
    "Tỷ lệ hoàn thành KPI",
    "Dự báo nhu cầu nhân lực",
}


def _extended_report_query(name, year, month):
    if name == "Tỷ lệ nghỉ việc":
        return ("""DECLARE @start DATE=?,@end DATE=DATEFROMPARTS(?,12,31); WITH Counts AS (SELECT (SELECT COUNT(*) FROM NhanVien n WHERE n.NgayVaoLam<@start AND NOT EXISTS(SELECT 1 FROM VongDoiNhanVien v WHERE v.MaNV=n.MaNV AND v.GiaiDoan=N'Offboarding' AND v.NgayHieuLucKetThuc<@start)) AS Opening,(SELECT COUNT(*) FROM NhanVien n WHERE n.NgayVaoLam<=@end AND NOT EXISTS(SELECT 1 FROM VongDoiNhanVien v WHERE v.MaNV=n.MaNV AND v.GiaiDoan=N'Offboarding' AND v.NgayHieuLucKetThuc<=@end)) AS Closing,(SELECT COUNT(DISTINCT MaNV) FROM VongDoiNhanVien WHERE GiaiDoan=N'Offboarding' AND NgayHieuLucKetThuc>=@start AND NgayHieuLucKetThuc<=@end) AS Leavers) SELECT Leavers AS [Số nhân viên nghỉ việc],Opening AS [Đầu kỳ],Closing AS [Cuối kỳ],CAST(CASE WHEN Opening+Closing=0 THEN 0 ELSE ROUND(Leavers*200.0/(Opening+Closing),2) END AS DECIMAL(7,2)) AS [Tỷ lệ nghỉ việc (%)] FROM Counts""", (date(year,1,1), year))
    if name == "Tỷ lệ vắng mặt":
        first = date(year, month, 1); following = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        days = sum(1 for offset in range((following-first).days) if (first+timedelta(days=offset)).weekday()<5)
        return ("""SELECT COUNT(CASE WHEN TrangThai IN (N'Nghỉ phép',N'Nghỉ không phép') THEN 1 END) AS [Ngày vắng có ghi nhận],CAST(CASE WHEN ?*(SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm')=0 THEN 0 ELSE ROUND(COUNT(CASE WHEN TrangThai IN (N'Nghỉ phép',N'Nghỉ không phép') THEN 1 END)*100.0/(?*(SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm')),2) END AS DECIMAL(7,2)) AS [Tỷ lệ vắng mặt (%)] FROM ChamCong WHERE Ngay>=? AND Ngay<?""", (days, days, first, following))
    if name == "Chi phí nhân sự (kỳ lương đã khóa)":
        return ("SELECT COUNT(l.MaNV) AS [Số nhân viên],CAST(ISNULL(SUM(l.TongLuong+ISNULL(l.BHXHDN,0)+ISNULL(l.BHYTDN,0)+ISNULL(l.BHTNDN,0)+ISNULL(l.BH_TNLDBNN_DN,0)),0) AS DECIMAL(18,0)) AS [Chi phí nhân sự đã khóa] FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang WHERE l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'", (year, month))
    if name == "Thời gian tuyển dụng":
        return ("SELECT COUNT(*) AS [Số ứng viên đã tuyển],CAST(ROUND(AVG(CAST(DATEDIFF(day,u.TaoLuc,n.NgayVaoLam) AS FLOAT)),1) AS DECIMAL(8,1)) AS [Thời gian tuyển dụng trung bình (ngày)] FROM UngVien u JOIN NhanVien n ON n.MaNV=u.MaNV WHERE n.NgayVaoLam>=DATEFROMPARTS(?,1,1) AND n.NgayVaoLam<DATEFROMPARTS(?+1,1,1) AND n.NgayVaoLam>=CAST(u.TaoLuc AS DATE)", (year, year))
    if name == "Tỷ lệ hoàn thành KPI":
        return ("SELECT COUNT(r.MaKetQua) AS [Số kết quả KPI đã duyệt],CAST(ROUND(ISNULL(AVG(CAST(r.TienDo AS FLOAT)),0),2) AS DECIMAL(7,2)) AS [Tiến độ KPI trung bình (%)] FROM KetQuaKPI r JOIN MucTieuKPI g ON g.MaMucTieu=r.MaMucTieu JOIN ChuKyKPI c ON c.MaChuKy=g.MaChuKy WHERE r.TrangThai=N'Đã duyệt' AND c.DenNgay>=DATEFROMPARTS(?,1,1) AND c.DenNgay<DATEFROMPARTS(?+1,1,1)", (year, year))
    if name == "Dự báo nhu cầu nhân lực":
        return ("SELECT p.TenPB AS [Phòng ban],SUM(k.SoLuongKeHoach) AS [Nhu cầu kế hoạch],(SELECT COUNT(*) FROM NhanVien n WHERE n.MaPB=k.MaPB AND n.TrangThai=N'Đang làm') AS [Nhân sự hiện tại],SUM(k.SoLuongKeHoach)-(SELECT COUNT(*) FROM NhanVien n WHERE n.MaPB=k.MaPB AND n.TrangThai=N'Đang làm') AS [Chênh lệch cần tuyển],SUM(k.ChiPhiDuKien) AS [Chi phí dự kiến] FROM KeHoachDinhBien k JOIN PhongBan p ON p.MaPB=k.MaPB WHERE k.Nam=? AND k.TrangThai=N'Đã duyệt' GROUP BY p.TenPB,k.MaPB ORDER BY p.TenPB", (year,))
    raise ValueError("Unknown report")



@app.get("/api/v1/reports/hr")
def api_v1_hr_summary():
    """Versioned, aggregate-only reporting endpoint for trusted HR consumers."""
    if not session.get("user"):
        return jsonify({"error": {"code": "unauthorized", "message": "Authentication required."}}), 401
    if not has_permission("reports.hr"):
        return jsonify({"error": {"code": "forbidden", "message": "Insufficient permission."}}), 403
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if year not in range(2000, today.year + 1) or month not in range(1, 13):
            raise ValueError
        active = int(db.scalar("SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm'") or 0)
        metrics = {"active_headcount": active}
        if has_permission("payroll.view"):
            row = db.query("SELECT CAST(ISNULL(SUM(l.TongLuong+ISNULL(l.BHXHDN,0)+ISNULL(l.BHYTDN,0)+ISNULL(l.BHTNDN,0)+ISNULL(l.BH_TNLDBNN_DN,0)),0) AS DECIMAL(18,0)) FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang WHERE l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'", (year, month))[1]
            metrics["locked_payroll_employer_cost"] = row[0][0] if row else 0
        return jsonify({"api_version": "v1", "period": {"year": year, "month": month}, "metrics": metrics})
    except ValueError:
        return jsonify({"error": {"code": "invalid_period", "message": "Year or month is invalid."}}), 400
    except Exception:
        app.logger.exception("HR summary API failed")
        return jsonify({"error": {"code": "internal_error", "message": "Unable to load HR summary."}}), 500


@app.route("/baocao")
@login_required
def baocao():
    if not has_permission("reports.hr"):
        return redirect(url_for("dashboard"))
    name = request.args.get("name", list(REPORTS)[0])
    if name not in REPORTS:
        name = next(iter(REPORTS))
    today = date.today()
    try:
        month = int(request.args.get("month", today.month))
        year = int(request.args.get("year", today.year))
    except (TypeError, ValueError):
        month, year = today.month, today.year
    if (
        month not in range(1, 13)
        or year not in range(2000, today.year + 1)
        or (
            name == "Ngày công theo nhân viên"
            and (year, month) > (today.year, today.month)
        )
    ):
        flash("Tháng hoặc năm báo cáo không hợp lệ.", "error")
        month, year = today.month, today.year
    if name == "Ngày công theo nhân viên":
        first = date(year, month, 1)
        sql = ATTENDANCE_PROGRESS_SQL
        params = (first, first, CONG_CHUAN, CONG_CHUAN)
    elif name in EXTENDED_REPORTS:
        sql, params = _extended_report_query(name, year, month)
    else:
        sql, params = REPORTS[name]
    try:
        cols, rows = db.query(sql, params)
    except Exception as e:
        cols, rows = [], []
        flash(_safe_error(e, "Không tải được báo cáo."), "error")
    chart = None
    if rows:
        number_type = lambda value: (
            isinstance(value, (int, float)) or value.__class__.__name__ == "Decimal"
        )
        numeric = [
            i
            for i in range(len(cols))
            if any(number_type(row[i]) for row in rows if row[i] is not None)
        ]
        if numeric:
            preferred = {
                "Tỷ lệ nghỉ việc": "Tỷ lệ nghỉ việc (%)",
                "Tỷ lệ vắng mặt": "Tỷ lệ vắng mặt (%)",
                "Chi phí nhân sự (kỳ lương đã khóa)": "Chi phí nhân sự đã khóa",
                "Thời gian tuyển dụng": "Thời gian tuyển dụng trung bình (ngày)",
                "Tỷ lệ hoàn thành KPI": "Tiến độ KPI trung bình (%)",
                "Dự báo nhu cầu nhân lực": "Chênh lệch cần tuyển",
            }
            metric = next(
                (cols.index(preferred[name]) for _ in (0,) if preferred.get(name) in cols and cols.index(preferred[name]) in numeric),
                next((i for i in numeric if i > 0), numeric[0]),
            )
            values = [float(row[metric] or 0) for row in rows]
            maximum = max(values, default=0)
            bars = []
            for i, row in enumerate(rows):
                label = (
                    name
                    if len(rows) == 1 and name in EXTENDED_REPORTS
                    else (str(row[0]) if metric > 0 else (name if len(rows) == 1 else str(i + 1)))
                )
                value = values[i]
                bars.append(
                    {
                        "label": label,
                        "value": value,
                        "display_value": f"{value:.1f}%"
                        if name in ("Ngày công theo nhân viên", "Tỷ lệ nghỉ việc", "Tỷ lệ vắng mặt", "Tỷ lệ hoàn thành KPI")
                        else (f"{value:,.1f} ngày" if name == "Thời gian tuyển dụng" else f"{value:,.0f}"),
                        "height": max(3, round(value * 100 / maximum))
                        if maximum > 0 and value > 0
                        else 0,
                    }
                )
            chart = {"title": cols[metric] if metric > 0 else name, "bars": bars}
        else:
            chart = {
                "title": "Số bản ghi",
                "bars": [
                    {
                        "label": name,
                        "value": len(rows),
                        "display_value": f"{len(rows):,}",
                        "height": 100,
                    }
                ],
            }
    return render_template(
        "reports.html",
        names=list(REPORTS),
        name=name,
        cols=cols,
        rows=rows,
        chart=chart,
        month=month,
        year=year,
        workday_standard=CONG_CHUAN,
        admin=admin(),
    )


@app.route("/taikhoan", methods=["GET", "POST"])
@login_required
def taikhoan():
    if not system_admin():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        try:
            action = request.form.get("action")
            if action == "send_otp":
                manv = request.form.get("MaNV")
                channel = request.form.get("channel", "email").strip().lower()
                if channel not in ("email", "sms"):
                    return jsonify(ok=False, error="Kênh nhận mã không hợp lệ."), 400
                if not manv:
                    return jsonify(ok=False, error="Vui lòng chọn nhân viên."), 400
                row = db.query(
                    "SELECT Email,SDT,HoTen FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'",
                    (manv,),
                )[1]
                if not row:
                    return jsonify(
                        ok=False, error="Không tìm thấy nhân viên đang làm."
                    ), 400
                if not _otp_can_send(manv):
                    return jsonify(
                        ok=False, error="Vui lòng chờ 30 giây trước khi gửi mã mới."
                    ), 429
                code = f"{secrets.randbelow(1_000_000):06d}"
                if channel == "email":
                    address = (row[0][0] or "").strip()
                    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", address):
                        return jsonify(
                            ok=False,
                            error="Nhân viên chưa có địa chỉ email hợp lệ trong hồ sơ.",
                        ), 400
                    host = os.environ.get("SMTP_HOST", "").strip()
                    user = os.environ.get("SMTP_USER", "").strip()
                    password = os.environ.get("SMTP_PASSWORD", "")
                    if not host or not user or not password:
                        return jsonify(
                            ok=False,
                            error="Chưa cấu hình SMTP_HOST, SMTP_USER và SMTP_PASSWORD để gửi email.",
                        ), 503
                    msg = EmailMessage()
                    msg["Subject"] = "Mã OTP tạo tài khoản QLNS"
                    msg["From"] = os.environ.get("SMTP_FROM", user)
                    msg["To"] = address
                    msg.set_content(
                        f"Xin chào {row[0][2]},\n\nMã OTP để xác nhận tạo tài khoản QLNS là: {code}\nMã có hiệu lực trong 5 phút. Nếu bạn không yêu cầu, hãy bỏ qua email này."
                    )
                    port = int(os.environ.get("SMTP_PORT", "587"))
                    if port == 465:
                        with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
                            smtp.login(user, password)
                            smtp.send_message(msg)
                    else:
                        with smtplib.SMTP(host, port, timeout=15) as smtp:
                            smtp.starttls()
                            smtp.login(user, password)
                            smtp.send_message(msg)
                else:
                    raw_phone = re.sub(r"[\s().-]", "", row[0][1] or "")
                    phone = (
                        "+84" + raw_phone[1:]
                        if raw_phone.startswith("0")
                        else raw_phone
                    )
                    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
                        return jsonify(
                            ok=False,
                            error="Số điện thoại trong hồ sơ chưa hợp lệ. Dùng định dạng quốc tế hoặc số Việt Nam bắt đầu bằng 0.",
                        ), 400
                    account = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
                    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
                    sender = os.environ.get("TWILIO_FROM", "").strip()
                    service = os.environ.get("TWILIO_MESSAGING_SERVICE_SID", "").strip()
                    if not account or not token or not (sender or service):
                        return jsonify(
                            ok=False,
                            error="Chưa cấu hình TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN và TWILIO_FROM hoặc TWILIO_MESSAGING_SERVICE_SID.",
                        ), 503
                    payload = {
                        "To": phone,
                        "Body": f"Ma OTP tao tai khoan QLNS: {code}. Ma co hieu luc trong 5 phut.",
                    }
                    payload["MessagingServiceSid" if service else "From"] = (
                        service or sender
                    )
                    request_ = Request(
                        f"https://api.twilio.com/2010-04-01/Accounts/{account}/Messages.json",
                        data=urlencode(payload).encode(),
                        headers={
                            "Authorization": "Basic "
                            + base64.b64encode(f"{account}:{token}".encode()).decode(),
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                        method="POST",
                    )
                    try:
                        with urlopen(request_, timeout=15) as response:
                            response.read(2048)
                    except (HTTPError, URLError, TimeoutError, OSError):
                        return jsonify(
                            ok=False,
                            error="Nhà cung cấp SMS không gửi được mã. Hãy kiểm tra cấu hình SMS và số điện thoại.",
                        ), 502
                _otp_put(manv, code, channel)
                return jsonify(
                    ok=True,
                    message="Đã gửi mã OTP đến "
                    + ("email" if channel == "email" else "số điện thoại")
                    + " trong hồ sơ nhân viên.",
                )
            if action == "add":
                u = request.form.get("username", "").strip()
                pw = request.form.get("password", "")
                manv = request.form.get("MaNV")
                new_role = request.form.get("role", "NhanVien")
                if not manv:
                    raise ValueError("Vui lòng chọn nhân viên.")
                if new_role not in ROLE_LABELS:
                    raise ValueError("Vai trò tài khoản không hợp lệ.")
                if not re.fullmatch(r"[A-Za-z0-9_.]{3,30}", u):
                    raise ValueError(
                        "Tên đăng nhập gồm 3-30 ký tự: chữ không dấu, số, dấu chấm hoặc gạch dưới."
                    )
                if not 10 <= len(pw) <= 256:
                    raise ValueError("Mật khẩu phải dài từ 10 đến 256 ký tự.")
                if db.scalar("SELECT COUNT(*) FROM TaiKhoan WHERE TenDN=?", (u,)):
                    raise ValueError("Tên đăng nhập đã tồn tại.")
                if db.scalar("SELECT COUNT(*) FROM TaiKhoan WHERE MaNV=?", (manv,)):
                    raise ValueError("Nhân viên này đã có tài khoản.")
                if not db.scalar(
                    "SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'",
                    (manv,),
                ):
                    raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
                otp = request.form.get("otp", "").strip()
                pending = _otp_get(manv)
                if not pending or pending.get("manv") != str(manv):
                    raise ValueError(
                        "Hãy gửi mã OTP đến email hoặc số điện thoại nhân viên trước."
                    )
                if pending.get("channel") != request.form.get("channel", "email"):
                    raise ValueError("Kênh xác nhận không khớp với mã OTP đã gửi.")
                if datetime.utcnow() > pending.get("expires"):
                    _otp_clear(manv)
                    raise ValueError("Mã OTP đã hết hạn. Hãy gửi mã mới.")
                if pending.get("attempts", 0) >= 5:
                    _otp_clear(manv)
                    raise ValueError(
                        "Bạn đã nhập sai OTP quá số lần cho phép. Hãy gửi mã mới."
                    )
                if not hmac.compare_digest(
                    _otp_hash(otp, manv, session["user"]["user"]), pending.get("hash", "")
                ):
                    _otp_fail(manv)
                    raise ValueError("Mã OTP không đúng.")
                auth.create_account(u, pw, new_role, int(manv))
                db.execute("INSERT INTO NhatKyPhanQuyen(TenDN,VaiTroMoi,ThaoTac,NguoiThucHien) VALUES(?,?,N'tao_tai_khoan',?)", (u, new_role, session["user"]["user"]))
                flash("Đã tạo tài khoản " + u + " với vai trò " + ROLE_LABELS[new_role] + ".", "success")
                _otp_clear(manv)
            elif action == "edit":
                old_username = request.form.get("username", "")
                new_username = request.form.get("new_username", "").strip()
                password = request.form.get("password", "")
                new_role = request.form.get("role", "NhanVien")
                if old_username == session["user"]["user"]:
                    raise ValueError("Không thể sửa tài khoản đang đăng nhập.")
                if new_role not in ROLE_LABELS:
                    raise ValueError("Vai trò tài khoản không hợp lệ.")
                if not re.fullmatch(r"[A-Za-z0-9_.]{3,30}", new_username):
                    raise ValueError("Tên đăng nhập phải dài 3-30 ký tự, chỉ gồm chữ không dấu, số, dấu chấm hoặc gạch dưới.")
                if password and not 10 <= len(password) <= 256:
                    raise ValueError("Mật khẩu phải dài từ 10 đến 256 ký tự.")
                old_role = db.scalar("SELECT VaiTro FROM TaiKhoan WHERE TenDN=?", (old_username,))
                if not old_role:
                    raise ValueError("Không tìm thấy tài khoản cần sửa.")
                if old_role in ("QuanTri", "QuanTriHeThong") and new_role not in ("QuanTri", "QuanTriHeThong") and db.scalar("SELECT COUNT(*) FROM TaiKhoan WHERE VaiTro IN (N'QuanTri',N'QuanTriHeThong')") <= 1:
                    raise ValueError("Không thể hạ quyền tài khoản quản trị hệ thống cuối cùng.")
                if db.scalar("SELECT COUNT(*) FROM TaiKhoan WHERE TenDN=? AND TenDN<>?", (new_username, old_username)):
                    raise ValueError("Tên đăng nhập đã được sử dụng.")
                params = (new_username, new_role, auth.hash_password(password), old_username) if password else (new_username, new_role, old_username)
                update_sql = "UPDATE TaiKhoan SET TenDN=?,VaiTro=?,MatKhau=?,SecurityVersion=SecurityVersion+1 WHERE TenDN=?" if password else "UPDATE TaiKhoan SET TenDN=?,VaiTro=?,SecurityVersion=SecurityVersion+1 WHERE TenDN=?"
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; " + update_sql + "; INSERT INTO NhatKyPhanQuyen(TenDN,VaiTroCu,VaiTroMoi,ThaoTac,NguoiThucHien) VALUES(?,?,?,?,?); COMMIT;", params + (new_username, old_role, new_role, "doi_vai_tro" if old_role != new_role else "sua_tai_khoan", session["user"]["user"]))
                flash("Đã cập nhật tài khoản và vai trò. Các phiên cũ đã bị thu hồi.", "success")
            elif action == "delete":
                u = request.form.get("username", "")
                if u == session["user"]["user"]:
                    raise ValueError("Không thể xóa tài khoản đang đăng nhập.")
                role = db.scalar("SELECT VaiTro FROM TaiKhoan WHERE TenDN=?", (u,))
                if not role:
                    raise ValueError("Không tìm thấy tài khoản cần xóa.")
                if role in ("QuanTri", "QuanTriHeThong") and db.scalar("SELECT COUNT(*) FROM TaiKhoan WHERE VaiTro IN (N'QuanTri',N'QuanTriHeThong')") <= 1:
                    raise ValueError("Không thể xóa tài khoản quản trị hệ thống cuối cùng.")
                manager_id = db.scalar("SELECT MaNV FROM TaiKhoan WHERE TenDN=? AND VaiTro IN (N'NhanVien',N'QuanLy')", (u,))
                if manager_id and db.scalar("SELECT COUNT(*) FROM QuanLyTrucTiep WHERE MaQuanLy=?", (manager_id,)):
                    raise ValueError("Tài khoản này đang được gán làm quản lý trực tiếp. Hãy gán quản lý khác trước khi xóa.")
                db.execute("DELETE FROM TaiKhoan WHERE TenDN=?", (u,))
                flash("Đã xóa tài khoản.", "success")
        except Exception as e:
            flash(_safe_error(e), "error")
        return redirect(url_for("taikhoan"))
    try:
        people = db.query(
            "SELECT n.MaNV,n.HoTen,ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))),n.Email,n.SDT FROM NhanVien n WHERE n.TrangThai=N'Đang làm' AND NOT EXISTS (SELECT 1 FROM TaiKhoan t WHERE t.MaNV=n.MaNV) ORDER BY n.HoTen"
        )[1]
        cols, rows = db.query("SELECT t.TenDN AS [Tên đăng nhập],t.VaiTro AS [Vai trò],ISNULL(n.HoTen,N'—') AS [Nhân viên],ISNULL(n.MaNVHT,N'—') AS [Mã NV] FROM TaiKhoan t LEFT JOIN NhanVien n ON n.MaNV=t.MaNV ORDER BY t.VaiTro,t.TenDN")
        cols[1] = "Quyền"
        rows = [[row[0], ROLE_LABELS.get(row[1], row[1]), *row[2:]] for row in rows]
        account_roles = dict(db.query("SELECT TenDN,VaiTro FROM TaiKhoan")[1])
    except Exception as e:
        people = []
        cols, rows = [], []
        account_roles = {}
        flash(_safe_error(e, "Không tải được danh sách tài khoản."), "error")
    return render_template(
        "taikhoan.html", people=people, cols=cols, rows=rows,
        current_username=session["user"]["user"], admin=admin(), role_options=ROLE_LABELS.items(), account_roles=account_roles
    )


@app.route("/scan-nhanvien", methods=["GET", "POST"])
@login_required
def scan_nhanvien():
    if not has_permission("employees.create"):
        return redirect(url_for("dashboard"))
    result = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "continue":
            fields = {
                col: request.form.get(col, "").strip()
                for col in (
                    "HoTen",
                    "NgaySinh",
                    "GioiTinh",
                    "DiaChi",
                    "SDT",
                    "Email",
                    "CCCD",
                )
            }
            if not fields["HoTen"]:
                flash(
                    "Chưa nhận dạng được họ tên. Hãy bổ sung tên trước khi chuyển sang hồ sơ.",
                    "error",
                )
                result = {
                    "document_type": request.form.get("document_type", "Tài liệu"),
                    "fields": fields,
                    "preview": request.form.get("preview", ""),
                }
            else:
                now = time.time()
                for old_token in [
                    key
                    for key, value in EMPLOYEE_SCAN_PREFILL.items()
                    if value["expires"] < now
                ]:
                    EMPLOYEE_SCAN_PREFILL.pop(old_token, None)
                token = uuid.uuid4().hex
                EMPLOYEE_SCAN_PREFILL[token] = {
                    "expires": now + 300,
                    "fields": fields,
                    "user": session["user"]["user"],
                }
                return redirect(
                    url_for("module", key="nhanvien", prefill="1", token=token)
                )
        else:
            upload = request.files.get("document")
            if not upload or not upload.filename:
                flash("Hãy chọn ảnh hoặc PDF để quét.", "error")
            else:
                try:
                    from docscan import MAX_FILE_SIZE, scan_employee_document

                    data = upload.read(MAX_FILE_SIZE + 1)
                    result = scan_employee_document(upload.filename, data)
                    flash(
                        "Đã nhận dạng tài liệu. Hãy kiểm tra và sửa thông tin trước khi chuyển sang hồ sơ nhân viên.",
                        "success",
                    )
                except (ValueError, RuntimeError) as e:
                    flash(str(e), "error")
                except Exception as e:
                    flash(_safe_error(e, "Không quét được tài liệu. Hãy kiểm tra định dạng và chất lượng tệp."), "error")
    return render_template("scan_employee.html", result=result, admin=True)


def _export_response(filename, cols, rows, file_format):
    if file_format == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(cols)
        for row in rows:
            writer.writerow(
                [
                    (
                        "'" + str(value)
                        if isinstance(value, str) and value[:1] in ("=", "+", "-", "@")
                        else value
                    )
                    for value in row
                ]
            )
        response = make_response("\ufeff" + out.getvalue())
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{filename}.csv"'
        )
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        return response
    if file_format == "xlsx":
        from decimal import Decimal

        from openpyxl import Workbook

        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet("Danh sách")
        sheet.append([str(value) for value in cols])
        for row in rows:
            sheet.append(
                [
                    (
                        "'" + value
                        if isinstance(value, str) and value[:1] in ("=", "+", "-", "@")
                        else float(value)
                        if isinstance(value, Decimal)
                        else value
                    )
                    for value in row
                ]
            )
        output = io.BytesIO()
        workbook.save(output)
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{filename}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if file_format == "pdf":
        from html import escape

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import (
            LongTable,
            Paragraph,
            SimpleDocTemplate,
            TableStyle,
        )

        font_paths = [
            (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ),
        ]
        font_pair = next(
            (
                (regular, bold)
                for regular, bold in font_paths
                if os.path.isfile(regular) and os.path.isfile(bold)
            ),
            None,
        )
        if not font_pair:
            raise ValueError("Không tìm thấy phông chữ Unicode để xuất PDF tiếng Việt.")
        if "ExportUnicode" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ExportUnicode", font_pair[0]))
            pdfmetrics.registerFont(TTFont("ExportUnicode-Bold", font_pair[1]))
        style = ParagraphStyle(
            "ExportCell",
            fontName="ExportUnicode",
            fontSize=6.5,
            leading=8,
            alignment=TA_LEFT,
            wordWrap="CJK",
        )
        header = ParagraphStyle(
            "ExportHeader",
            parent=style,
            fontName="ExportUnicode-Bold",
            textColor=colors.white,
        )
        table_data = [[Paragraph(escape(str(value)), header) for value in cols]]
        table_data.extend(
            [
                [
                    Paragraph(
                        escape("" if value is None else str(value)).replace(
                            "\n", "<br/>"
                        ),
                        style,
                    )
                    for value in row
                ]
                for row in rows
            ]
        )
        output = io.BytesIO()
        document = SimpleDocTemplate(
            output,
            pagesize=landscape(A4),
            rightMargin=20,
            leftMargin=20,
            topMargin=24,
            bottomMargin=24,
        )
        table = LongTable(table_data, repeatRows=1, hAlign="LEFT")
        table_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243b61")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ccd4df")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        if rows:
            table_styles.append(
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f3f6fa")],
                )
            )
        table.setStyle(TableStyle(table_styles))
        document.build([table])
        output.seek(0)
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{filename}.pdf",
            mimetype="application/pdf",
        )
    raise ValueError("Vui lòng chọn CSV, Excel hoặc PDF.")


@app.route("/export/<key>")
@login_required
def export(key):
    file_format = request.args.get("format", "csv").lower()
    if key in MODULES:
        permission = module_permission(key, "export")
        if not permission or not has_permission(permission):
            return "Bạn không có quyền xuất danh sách này.", 403
        cols, rows = db.query(MODULES[key]["sql"])
        search = request.args.get("q", "").strip()
        if search:
            if key == "nhanvien":
                q_ = search.casefold()
                rows = [
                    r
                    for r in rows
                    if q_
                    in (
                        str(r[1]).casefold(),
                        re.sub("[a-z]+$", "", str(r[1]).casefold()),
                    )
                ]
            else:
                rows = [
                    r
                    for r in rows
                    if search.casefold()
                    in " ".join(
                        "" if value is None else str(value) for value in r
                    ).casefold()
                ]
        if key == "nhanvien":
            sensitive_audit.record_many(
                [r[0] for r in rows if r and r[0] is not None],
                "LienHe", "export", session["user"]["user"]
            )
            sensitive_audit.record_many(
                [r[0] for r in rows if r and r[0] is not None],
                "CCCD", "export", session["user"]["user"]
            )
            sensitive_audit.record_many(
                [r[0] for r in rows if r and r[0] is not None],
                "Luong", "export", session["user"]["user"]
            )
        elif key == "hopdong" and rows:
            contract_ids = [r[0] for r in rows if r and r[0] is not None]
            placeholders = ",".join("?" for _ in contract_ids)
            employee_ids = [r[0] for r in db.query(
                f"SELECT MaNV FROM HopDong WHERE MaHD IN ({placeholders})", contract_ids
            )[1]] if contract_ids else []
            sensitive_audit.record_many(employee_ids, "HopDong", "export", session["user"]["user"])
        if key == "nhanvien":
            cols = cols[1:]
            rows = [r[1:] for r in rows]
        filename = key
    elif key == "assets":
        if not has_permission("assets.export"):
            return "Bạn không có quyền xuất danh sách tài sản.", 403
        cols, rows = db.query("SELECT a.MaTaiSan AS [Mã tài sản],a.MaNV AS [Mã nhân viên],n.HoTen AS [Nhân viên],a.TenTaiSan AS [Tài sản],a.MaNoiBo AS [Mã nội bộ],a.Serial AS [Serial],a.NgayCap AS [Ngày cấp],a.TrangThai AS [Trạng thái],a.NgayThuHoi AS [Ngày thu hồi],a.TinhTrangThuHoi AS [Tình trạng khi thu hồi] FROM TaiSanNhanVien a JOIN NhanVien n ON n.MaNV=a.MaNV ORDER BY a.MaTaiSan DESC")
        filename = "tai_san_nhan_vien"
    elif key == "contract_templates":
        if not has_permission("contracts.export"):
            return "Bạn không có quyền xuất danh sách hợp đồng mẫu.", 403
        cols, rows = db.query(
            "SELECT TenMau AS [Tên mẫu],FileName AS [Tệp],NgayTai AS [Ngày tải],NoiDung AS [Văn bản trích xuất] FROM MauHopDong ORDER BY MaMau DESC"
        )
        filename = "hop_dong_mau"
    elif key == "attendance":
        try:
            selected_day = date.fromisoformat(
                request.args.get("date", date.today().isoformat())
            )
        except ValueError:
            return "Ngày xuất chấm công không hợp lệ.", 400
        if admin():
            cols, rows = db.query(
                "SELECT n.HoTen AS [Nhân viên],c.Ngay AS [Ngày],c.GioVao AS [Giờ vào],c.GioRa AS [Giờ ra],c.TrangThai AS [Trạng thái] FROM ChamCong c JOIN NhanVien n ON n.MaNV=c.MaNV WHERE c.Ngay=? ORDER BY n.HoTen",
                (selected_day,),
            )
        else:
            cols, rows = db.query(
                "SELECT c.Ngay AS [Ngày],c.GioVao AS [Giờ vào],c.GioRa AS [Giờ ra],c.TrangThai AS [Trạng thái] FROM ChamCong c WHERE c.Ngay=? AND c.MaNV=? ORDER BY c.Ngay DESC",
                (selected_day, session["user"].get("manv") or -1),
            )
        filename = f"cham_cong_{selected_day:%Y_%m_%d}"
    elif key == "leave":
        sql = "SELECT n.HoTen AS [Nhân viên],p.TuNgay AS [Từ ngày],p.DenNgay AS [Đến ngày],p.SoNgay AS [Số ngày],p.LoaiNghi AS [Loại nghỉ],p.LyDo AS [Lý do],p.TrangThai AS [Trạng thái] FROM NghiPhep p JOIN NhanVien n ON n.MaNV=p.MaNV"
        if has_permission("leave.view_all"):
            cols, rows = db.query(sql + " ORDER BY p.MaNP DESC")
        elif has_permission("leave.export_team") and session["user"].get("manv"):
            cols, rows = db.query(sql + " JOIN QuanLyTrucTiep q ON q.MaNV=p.MaNV WHERE q.MaQuanLy=? ORDER BY p.MaNP DESC", (session["user"]["manv"],))
        else:
            cols, rows = db.query(
                sql + " WHERE p.MaNV=? ORDER BY p.MaNP DESC",
                (session["user"].get("manv") or -1,),
            )
        filename = "nghi_phep"
    elif key == "salary":
        if not has_permission("payroll.export"):
            return "Bạn không có quyền xuất bảng lương.", 403
        try:
            month = int(request.args.get("month", date.today().month))
            year = int(request.args.get("year", date.today().year))
        except (TypeError, ValueError):
            return "Tháng hoặc năm không hợp lệ.", 400
        if month not in range(1, 13) or year not in range(2000, 2101):
            return "Tháng hoặc năm không hợp lệ.", 400
        payroll_state = db.query(
            "SELECT TrangThai FROM LuongKy WHERE Nam=? AND Thang=?", (year, month)
        )[1]
        if not payroll_state or payroll_state[0][0] != "Đã khóa":
            return "Chỉ có thể xuất bảng lương sau khi kỳ lương đã được khóa.", 409
        cols, rows = db.query(
            """SELECT n.HoTen AS [Nhân viên],l.NgayCong AS [Ngày đi làm],l.GioGhiNhan AS [Giờ ghi nhận],l.LuongCB AS [Lương cơ bản],
   l.ThuongCC AS [Thưởng chuyên cần],l.TienTangCa AS [Tiền tăng ca],l.TruMuon AS [Trừ đi muộn],
   l.TruNghiKP AS [Trừ nghỉ không phép],l.ThuongThem AS [Thưởng thêm],l.TongLuong AS [Tổng trước thuế/BHXH],
   l.ThueTNCN AS [Thuế TNCN],l.BHXH_NLD AS [BHXH NLĐ],l.BHYT_NLD AS [BHYT NLĐ],l.BHTN_NLD AS [BHTN NLĐ],
   l.BHXHDN AS [BHXH DN],l.BHYTDN AS [BHYT DN],l.BHTNDN AS [BHTN DN],l.BH_TNLDBNN_DN AS [TNLĐ-BNN DN],l.LuongThucLinh AS [Thực lĩnh],CASE WHEN EXISTS(SELECT 1 FROM PayrollResultSnapshot s WHERE s.MaLuong=l.MaLuong) THEN N'Có' ELSE N'Chưa' END AS [Snapshot chính sách]
   FROM Luong l JOIN NhanVien n ON n.MaNV=l.MaNV WHERE l.Thang=? AND l.Nam=? ORDER BY n.HoTen""",
            (month, year),
        )
        payroll_employee_ids = [
            row[0] for row in db.query(
                "SELECT MaNV FROM Luong WHERE Thang=? AND Nam=?", (month, year)
            )[1]
        ]
        sensitive_audit.record_many(
            payroll_employee_ids, "Luong", "export", session["user"]["user"]
        )
        filename = f"luong_{year}_{month:02d}"
    elif key == "transfer":
        if not has_permission("organization.manage"):
            return "Bạn không có quyền xuất lịch sử điều chuyển.", 403
        cols, rows = (
            db.query("""SELECT n.HoTen AS [Nhân viên],ISNULL(cu.TenPB,N'(Chưa phân phòng)') AS [Phòng ban cũ],moi.TenPB AS [Phòng ban mới],
   ls.ThoiDiemChuyen AS [Ngày giờ chuyển],ls.LyDo AS [Lý do],ls.NguoiThucHien AS [Người thực hiện]
   FROM LichSuDieuChuyen ls JOIN NhanVien n ON n.MaNV=ls.MaNV LEFT JOIN PhongBan cu ON cu.MaPB=ls.MaPB_Cu
   JOIN PhongBan moi ON moi.MaPB=ls.MaPB_Moi ORDER BY ls.ThoiDiemChuyen DESC""")
        )
        filename = "lich_su_dieu_chuyen"
    elif key == "accounts":
        if not has_permission("accounts.export"):
            return "Bạn không có quyền xuất danh sách tài khoản.", 403
        cols, rows = db.query("SELECT t.TenDN AS [Tên đăng nhập],t.VaiTro AS [Vai trò],ISNULL(n.HoTen,N'—') AS [Nhân viên],ISNULL(n.MaNVHT,N'—') AS [Mã NV] FROM TaiKhoan t LEFT JOIN NhanVien n ON n.MaNV=t.MaNV ORDER BY t.VaiTro,t.TenDN")
        cols[1] = "Quyền"
        rows = [[row[0], ROLE_LABELS.get(row[1], row[1]), *row[2:]] for row in rows]
        filename = "tai_khoan"
    elif key == "report":
        if not has_permission("reports.hr"):
            return "Bạn không có quyền xuất báo cáo nhân sự.", 403
        name = request.args.get("name", "")
        if name not in REPORTS and name != "Ngày công theo nhân viên":
            return "Báo cáo không hợp lệ.", 400
        if name == "Ngày công theo nhân viên":
            try:
                month = int(request.args.get("month", date.today().month))
                year = int(request.args.get("year", date.today().year))
            except (TypeError, ValueError):
                return "Tháng hoặc năm không hợp lệ.", 400
            if month not in range(1, 13) or year not in range(
                2000, date.today().year + 1
            ):
                return "Tháng hoặc năm không hợp lệ.", 400
            first = date(year, month, 1)
            cols, rows = db.query(
                ATTENDANCE_PROGRESS_SQL,
                (first, first, CONG_CHUAN, CONG_CHUAN),
            )
            filename = f"bao_cao_ngay_cong_{year}_{month:02d}"
        elif name in EXTENDED_REPORTS:
            try:
                month = int(request.args.get("month", date.today().month))
                year = int(request.args.get("year", date.today().year))
            except (TypeError, ValueError):
                return "Tháng hoặc năm không hợp lệ.", 400
            if month not in range(1, 13) or year not in range(2000, date.today().year + 1):
                return "Tháng hoặc năm không hợp lệ.", 400
            sql, params = _extended_report_query(name, year, month)
            cols, rows = db.query(sql, params)
            filename = f"bao_cao_nhan_su_{year}_{month:02d}"
        else:
            sql, params = REPORTS[name]
            cols, rows = db.query(sql, params)
            filename = "bao_cao"
    else:
        return redirect(url_for("dashboard"))
    try:
        return _export_response(filename, cols, rows, file_format)
    except ValueError as error:
        return str(error), 400


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if not 10 <= len(pw) <= 256:
            flash("Mật khẩu phải dài từ 10 đến 256 ký tự.", "error")
        else:
            try:
                if not auth.verify_password(
                    session["user"]["user"], request.form.get("current_password", "")
                ):
                    raise ValueError("Mật khẩu hiện tại không đúng.")
                auth.change_password(session["user"]["user"], pw)
                session.clear()
                flash("Đổi mật khẩu thành công. Hãy đăng nhập lại.", "success")
                return redirect(url_for("login"))
            except Exception as e:
                flash(_safe_error(e), "error")
    return render_template("password.html", admin=admin())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
