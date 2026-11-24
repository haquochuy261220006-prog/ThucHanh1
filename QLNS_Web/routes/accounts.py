from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import auth
import base64
import hmac
import os
import re
import secrets
import smtplib
import time
from database import db
from permissions import ROLE_LABELS
from web_auth import login_required
from services.common_service import _EMAIL_RE, _safe_error, _utcnow, admin, system_admin
from services.auth_service import (LOGIN_LOCK_SECONDS, LOGIN_MAX_FAILS, _login_fails, _login_locked, _otp_can_send, _otp_clear, _otp_fail, _otp_get, _otp_hash, _otp_put)

bp = Blueprint('accounts', __name__)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("accounts.login"))


@bp.route("/taikhoan", methods=["GET", "POST"])
@login_required
def taikhoan():
    if not system_admin():
        return redirect(url_for("dashboard.dashboard"))
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
                    return jsonify(ok=False, error="Không tìm thấy nhân viên đang làm."), 400
                if not _otp_can_send(manv):
                    return jsonify(
                        ok=False, error="Vui lòng chờ 30 giây trước khi gửi mã mới."
                    ), 429
                code = f"{secrets.randbelow(1_000_000):06d}"
                if channel == "email":
                    address = (row[0][0] or "").strip()
                    if not _EMAIL_RE.fullmatch(address):
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
                    try:
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
                    except (smtplib.SMTPException, OSError, ValueError):
                        current_app.logger.exception("OTP email delivery failed")
                        return jsonify(
                            ok=False,
                            error="Không gửi được email OTP. Hãy kiểm tra cấu hình SMTP.",
                        ), 502
                else:
                    raw_phone = re.sub(r"[\s().-]", "", row[0][1] or "")
                    phone = "+84" + raw_phone[1:] if raw_phone.startswith("0") else raw_phone
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
                    payload["MessagingServiceSid" if service else "From"] = service or sender
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
                    raise ValueError("Hãy gửi mã OTP đến email hoặc số điện thoại nhân viên trước.")
                if pending.get("channel") != request.form.get("channel", "email"):
                    raise ValueError("Kênh xác nhận không khớp với mã OTP đã gửi.")
                if _utcnow() > pending.get("expires"):
                    _otp_clear(manv)
                    raise ValueError("Mã OTP đã hết hạn. Hãy gửi mã mới.")
                if pending.get("attempts", 0) >= 5:
                    _otp_clear(manv)
                    raise ValueError("Bạn đã nhập sai OTP quá số lần cho phép. Hãy gửi mã mới.")
                if not hmac.compare_digest(
                    _otp_hash(otp, manv, session["user"]["user"]), pending.get("hash", "")
                ):
                    _otp_fail(manv)
                    raise ValueError("Mã OTP không đúng.")
                auth.create_account(u, pw, new_role, int(manv))
                db.execute(
                    "INSERT INTO NhatKyPhanQuyen(TenDN,VaiTroMoi,ThaoTac,NguoiThucHien) VALUES(?,?,N'tao_tai_khoan',?)",
                    (u, new_role, session["user"]["user"]),
                )
                flash(
                    "Đã tạo tài khoản " + u + " với vai trò " + ROLE_LABELS[new_role] + ".",
                    "success",
                )
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
                    raise ValueError(
                        "Tên đăng nhập phải dài 3-30 ký tự, chỉ gồm chữ không dấu, số, dấu chấm hoặc gạch dưới."
                    )
                if password and not 10 <= len(password) <= 256:
                    raise ValueError("Mật khẩu phải dài từ 10 đến 256 ký tự.")
                old_role = db.scalar("SELECT VaiTro FROM TaiKhoan WHERE TenDN=?", (old_username,))
                if not old_role:
                    raise ValueError("Không tìm thấy tài khoản cần sửa.")
                if (
                    old_role in ("QuanTri", "QuanTriHeThong")
                    and new_role not in ("QuanTri", "QuanTriHeThong")
                    and db.scalar(
                        "SELECT COUNT(*) FROM TaiKhoan WHERE VaiTro IN (N'QuanTri',N'QuanTriHeThong')"
                    )
                    <= 1
                ):
                    raise ValueError("Không thể hạ quyền tài khoản quản trị hệ thống cuối cùng.")
                if db.scalar(
                    "SELECT COUNT(*) FROM TaiKhoan WHERE TenDN=? AND TenDN<>?",
                    (new_username, old_username),
                ):
                    raise ValueError("Tên đăng nhập đã được sử dụng.")
                params = (
                    (new_username, new_role, auth.hash_password(password), old_username)
                    if password
                    else (new_username, new_role, old_username)
                )
                update_sql = (
                    "UPDATE TaiKhoan SET TenDN=?,VaiTro=?,MatKhau=?,SecurityVersion=SecurityVersion+1 WHERE TenDN=?"
                    if password
                    else "UPDATE TaiKhoan SET TenDN=?,VaiTro=?,SecurityVersion=SecurityVersion+1 WHERE TenDN=?"
                )
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; "
                    + update_sql
                    + "; INSERT INTO NhatKyPhanQuyen(TenDN,VaiTroCu,VaiTroMoi,ThaoTac,NguoiThucHien) VALUES(?,?,?,?,?); COMMIT;",
                    params
                    + (
                        new_username,
                        old_role,
                        new_role,
                        "doi_vai_tro" if old_role != new_role else "sua_tai_khoan",
                        session["user"]["user"],
                    ),
                )
                flash("Đã cập nhật tài khoản và vai trò. Các phiên cũ đã bị thu hồi.", "success")
            elif action == "delete":
                u = request.form.get("username", "")
                if u == session["user"]["user"]:
                    raise ValueError("Không thể xóa tài khoản đang đăng nhập.")
                role = db.scalar("SELECT VaiTro FROM TaiKhoan WHERE TenDN=?", (u,))
                if not role:
                    raise ValueError("Không tìm thấy tài khoản cần xóa.")
                if (
                    role in ("QuanTri", "QuanTriHeThong")
                    and db.scalar(
                        "SELECT COUNT(*) FROM TaiKhoan WHERE VaiTro IN (N'QuanTri',N'QuanTriHeThong')"
                    )
                    <= 1
                ):
                    raise ValueError("Không thể xóa tài khoản quản trị hệ thống cuối cùng.")
                manager_id = db.scalar(
                    "SELECT MaNV FROM TaiKhoan WHERE TenDN=? AND VaiTro IN (N'NhanVien',N'QuanLy')",
                    (u,),
                )
                if manager_id and db.scalar(
                    "SELECT COUNT(*) FROM QuanLyTrucTiep WHERE MaQuanLy=?", (manager_id,)
                ):
                    raise ValueError(
                        "Tài khoản này đang được gán làm quản lý trực tiếp. Hãy gán quản lý khác trước khi xóa."
                    )
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; DELETE FROM TaiKhoan WHERE TenDN=?; IF @@ROWCOUNT<>1 THROW 50014,'Tài khoản đã thay đổi.',1; INSERT INTO NhatKyPhanQuyen(TenDN,VaiTroCu,VaiTroMoi,ThaoTac,NguoiThucHien) VALUES(?,?,NULL,N'xoa_tai_khoan',?); COMMIT;",
                    (u, u, role, session["user"]["user"]),
                )
                flash("Đã xóa tài khoản.", "success")
        except Exception as e:
            if request.form.get("action") == "send_otp":  # lời gọi fetch cần JSON, không phải redirect
                return jsonify(ok=False, error=_safe_error(e)), 500
            flash(_safe_error(e), "error")
        return redirect(url_for("accounts.taikhoan"))
    try:
        people = db.query(
            "SELECT n.MaNV,n.HoTen,ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))),n.Email,n.SDT FROM NhanVien n WHERE n.TrangThai=N'Đang làm' AND NOT EXISTS (SELECT 1 FROM TaiKhoan t WHERE t.MaNV=n.MaNV) ORDER BY n.HoTen"
        )[1]
        cols, rows = db.query(
            "SELECT t.TenDN AS [Tên đăng nhập],t.VaiTro AS [Vai trò],ISNULL(n.HoTen,N'—') AS [Nhân viên],ISNULL(n.MaNVHT,N'—') AS [Mã NV] FROM TaiKhoan t LEFT JOIN NhanVien n ON n.MaNV=t.MaNV ORDER BY t.VaiTro,t.TenDN"
        )
        cols[1] = "Quyền"
        rows = [[row[0], ROLE_LABELS.get(row[1], row[1]), *row[2:]] for row in rows]
        account_roles = dict(db.query("SELECT TenDN,VaiTro FROM TaiKhoan")[1])
    except Exception as e:
        people = []
        cols, rows = [], []
        account_roles = {}
        flash(_safe_error(e, "Không tải được danh sách tài khoản."), "error")
    return render_template(
        "taikhoan.html",
        people=people,
        cols=cols,
        rows=rows,
        current_username=session["user"]["user"],
        admin=admin(),
        role_options=ROLE_LABELS.items(),
        account_roles=account_roles,
    )


@bp.route("/change-password", methods=["GET", "POST"])
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
                return redirect(url_for("accounts.login"))
            except Exception as e:
                flash(_safe_error(e), "error")
    return render_template("password.html", admin=admin())


@bp.route("/login", methods=["GET", "POST"])
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
            current_app.logger.exception("Login database error")
            flash(
                "Không kết nối được SQL Server. Kiểm tra config.py và dịch vụ SQL Server.",
                "error",
            )
            return render_template("login.html")
        if u:
            _login_fails.pop(key, None)
            session.clear()  # cấp phiên mới sau khi đăng nhập
            session["user"] = u
            return redirect(url_for("dashboard.dashboard"))
        if len(_login_fails) > 5000:  # tránh bộ nhớ phình ra khi bị dò mật khẩu hàng loạt
            cutoff = time.time() - LOGIN_LOCK_SECONDS
            for stale in [k for k, (_, ts) in _login_fails.items() if ts < cutoff]:
                del _login_fails[stale]
        n = _login_fails.get(key, (0, 0))[0] + 1
        _login_fails[key] = (n, time.time())
        flash("Tên đăng nhập hoặc mật khẩu không đúng.", "error")
    return render_template("login.html")
