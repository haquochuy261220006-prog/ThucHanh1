from flask import Blueprint, current_app, flash, jsonify, make_response, redirect, render_template, request, session, url_for
from cryptography.fernet import InvalidToken
from datetime import date, datetime, time, timedelta
import config
import hmac
import json
import math
import re
import secrets
import time
from config import FACE_MATCH_THRESHOLD
from database import db
from utils.decorators import login_required
from services.common_service import _parse_iso_date, _safe_error, admin, has_permission
from services.attendance.leave_service import _leave_days
from services.attendance.attendance_service import (_attendance_deviation_minutes, _attendance_work_date, _audit_attendance, _face_cipher, _observed_overtime_hours, _parse_optional_shift_time, _purge_expired_face_templates, _record_attendance_cycle, _record_attendance_event, _sync_attendance_work_minutes, _validate_employee_shift_assignment, face_employee_id, face_payload, now_vietnam, today_vietnam)
from services.ai.ai_service import AIRateLimitError, AIUnavailableError, call_ai
from services.ai.attendance_anomaly_service import load_attendance_anomalies

bp = Blueprint('attendance', __name__)

def attendance_manager():
    return admin() or has_permission("attendance.manage")


@bp.get("/chamcong/bat-thuong")
@login_required
def attendance_anomalies():
    if not attendance_manager():
        return "Chỉ Nhân sự/Admin được xem cảnh báo chấm công toàn hệ thống.", 403
    today = today_vietnam()
    try:
        month = int(request.args.get("month", today.month))
        year = int(request.args.get("year", today.year))
        if month not in range(1, 13) or year not in range(2000, today.year + 1):
            raise ValueError
    except (TypeError, ValueError):
        return "Tháng hoặc năm không hợp lệ.", 400
    try:
        alerts, category_counts = load_attendance_anomalies(year, month, today)
    except Exception as error:
        current_app.logger.exception("Attendance anomaly report failed")
        flash(_safe_error(error, "Không tải được cảnh báo chấm công."), "error")
        alerts, category_counts = [], {}
    return render_template(
        "attendance/attendance_anomalies.html",
        alerts=alerts,
        category_counts=category_counts,
        month=month,
        year=year,
        today=today,
    )


@bp.post("/api/chamcong/ai-giai-thich-bat-thuong")
@login_required
def ai_explain_attendance_anomalies():
    if not attendance_manager():
        return jsonify(error="Không đủ quyền xem phân tích chấm công."), 403
    today = today_vietnam()
    try:
        month = int(request.form.get("month", today.month))
        year = int(request.form.get("year", today.year))
        if month not in range(1, 13) or year not in range(2000, today.year + 1):
            raise ValueError
        _, category_counts = load_attendance_anomalies(year, month, today)
        if not category_counts:
            return jsonify(explanation="Không phát hiện trường hợp vượt các ngưỡng rà soát trong kỳ này.")
        user_prompt = json.dumps(
            {"period": f"{year:04d}-{month:02d}", "aggregate_alert_counts": category_counts},
            ensure_ascii=False,
        )
        explanation = call_ai(
            actor=session["user"]["user"],
            feature="attendance_anomaly_explain",
            system_prompt=(
                "Bạn giải thích số liệu tổng hợp cảnh báo chấm công cho HR. "
                "Chỉ nhận xét các loại và số lượng được cung cấp, nêu bước kiểm tra trung lập. "
                "Không kết luận gian lận, không đề xuất tự phạt hoặc trừ lương, không suy đoán "
                "nguyên nhân cá nhân. Trả lời tiếng Việt tối đa 120 từ."
            ),
            user_prompt=user_prompt,
            max_tokens=250,
        )
        return jsonify(explanation=str(explanation).strip()[:1200])
    except (TypeError, ValueError):
        return jsonify(error="Tháng hoặc năm không hợp lệ."), 400
    except AIRateLimitError as error:
        return jsonify(error=str(error)), 429
    except AIUnavailableError as error:
        return jsonify(error=str(error)), 503
    except Exception:
        current_app.logger.exception("Attendance anomaly AI explanation failed")
        return jsonify(error="Không thể tạo giải thích AI lúc này. Hãy thử lại sau."), 502


@bp.route("/api/chamcong/face/delete", methods=["POST"])
@login_required
def face_delete():
    if admin():
        return jsonify(error="Quản lý mẫu khuôn mặt chỉ dành cho tài khoản nhân viên."), 403
    data = request.get_json(silent=True) or {}
    if not hmac.compare_digest(
        request.headers.get("X-Face-CSRF", ""), session.get("face_csrf", "")
    ):
        return jsonify(error="Phiên làm việc hết hạn. Hãy tải lại trang."), 400
    try:
        manv = face_employee_id(data)
        db.execute("DELETE FROM NhanVienKhuonMat WHERE MaNV=?", (manv,))
        _audit_attendance(
            manv,
            "face",
            "delete_template",
            "success",
            actor=session["user"]["user"],
            detail="Nhân viên chủ động thu hồi đồng ý/xóa mẫu",
        )
        return jsonify(message="Đã xóa dữ liệu khuôn mặt."), 200
    except Exception:
        current_app.logger.exception("Face template deletion failed")
        return jsonify(
            error="Không thể xóa dữ liệu khuôn mặt. Hãy thử lại hoặc liên hệ quản trị viên."
        ), 400


@bp.route("/api/chamcong/face/challenge", methods=["POST"])
@login_required
def face_challenge():
    if admin():
        return jsonify(error="Chấm công khuôn mặt chỉ dành cho tài khoản nhân viên."), 403
    if not hmac.compare_digest(
        request.headers.get("X-Face-CSRF", ""), session.get("face_csrf", "")
    ):
        return jsonify(error="Phiên làm việc hết hạn. Hãy tải lại trang."), 400
    own_id = int(session.get("user", {}).get("manv") or 0)
    if not own_id or not db.scalar("SELECT COUNT(*) FROM NhanVienKhuonMat WHERE MaNV=?", (own_id,)):
        return jsonify(error="Tài khoản chưa có mẫu khuôn mặt. Hãy đăng ký mẫu trước."), 409
    sequence = ["left", "right"]
    secrets.SystemRandom().shuffle(sequence)
    nonce = secrets.token_urlsafe(24)
    session["face_live_challenge"] = {
        "nonce": nonce,
        "sequence": sequence,
        "expires": time.time() + 90,
    }
    return jsonify(nonce=nonce, sequence=sequence, expires_in=90), 200


@bp.route("/lich-ca", methods=["GET", "POST"])
@login_required
def workforce_shifts():
    if request.method == "POST":
        actor = session["user"]["user"]
        try:
            action = request.form.get("action")
            if action == "swap_request":
                own_id = int(session.get("user", {}).get("manv") or 0)
                assignment_a, assignment_b = (
                    int(request.form["CaCuaToi"]),
                    int(request.form["CaDoi"]),
                )
                rows = db.query(
                    "SELECT p.MaPhanCa,p.MaNV,p.Ngay,p.MaCa,COALESCE(p.GioBatDauOverride,c.GioBatDau),COALESCE(p.GioKetThucOverride,c.GioKetThuc),c.QuaDem,n.MaPB FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa JOIN NhanVien n ON n.MaNV=p.MaNV WHERE p.MaPhanCa IN (?,?)",
                    (assignment_a, assignment_b),
                )[1]
                by_id = {int(row[0]): row for row in rows}
                first, second = by_id.get(assignment_a), by_id.get(assignment_b)
                if (
                    not own_id
                    or not first
                    or not second
                    or first[1] == second[1]
                    or first[2] != second[2]
                    or first[2] < today_vietnam()
                ):
                    raise ValueError("Chỉ yêu cầu đổi hai ca sắp tới trong cùng ngày.")
                if own_id not in (first[1], second[1]) or first[7] != second[7]:
                    raise ValueError("Bạn chỉ có thể đổi ca với nhân viên cùng phòng ban.")
                if db.scalar(
                    "SELECT COUNT(*) FROM YeuCauDoiCa WHERE TrangThai IN (N'Chờ xác nhận',N'Chờ duyệt') AND (MaPhanCaA IN (?,?) OR MaPhanCaB IN (?,?))",
                    (assignment_a, assignment_b, assignment_a, assignment_b),
                ):
                    raise ValueError("Một trong hai ca đã có yêu cầu đổi đang xử lý.")
                swap_id = db.query(
                    "INSERT INTO YeuCauDoiCa(MaPhanCaA,MaPhanCaB,MaNVCau) OUTPUT INSERTED.MaYeuCau VALUES(?,?,?)",
                    (assignment_a, assignment_b, own_id),
                )[1][0][0]
                db.execute(
                    "INSERT INTO NhatKyDoiCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'submit',NULL,N'Chờ xác nhận',?,?)",
                    (swap_id, actor, request.form.get("LyDo", "").strip()[:500] or None),
                )
                flash("Đã gửi đề nghị đổi ca cho đồng nghiệp xác nhận.", "success")
            elif action in ("swap_accept", "swap_reject"):
                swap_id = int(request.form["MaYeuCau"])
                own_id = int(session.get("user", {}).get("manv") or 0)
                swap = db.query(
                    "SELECT s.MaPhanCaA,s.MaPhanCaB,s.TrangThai,s.MaNVCau,a.MaNV,b.MaNV FROM YeuCauDoiCa s JOIN PhanCaNhanVien a ON a.MaPhanCa=s.MaPhanCaA JOIN PhanCaNhanVien b ON b.MaPhanCa=s.MaPhanCaB WHERE s.MaYeuCau=?",
                    (swap_id,),
                )[1]
                if (
                    not swap
                    or swap[0][2] != "Chờ xác nhận"
                    or own_id not in (swap[0][4], swap[0][5])
                    or own_id == swap[0][3]
                ):
                    raise ValueError("Yêu cầu đổi ca không còn chờ bạn xác nhận.")
                status = "Chờ duyệt" if action == "swap_accept" else "Từ chối"
                reason = request.form.get("LyDo", "").strip()[:500]
                if action == "swap_reject" and not reason:
                    raise ValueError("Hãy ghi lý do từ chối đổi ca.")
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; UPDATE YeuCauDoiCa SET TrangThai=?,XacNhanBoi=?,XacNhanLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Chờ xác nhận'; IF @@ROWCOUNT<>1 THROW 51030,'Swap request has already changed.',1; INSERT INTO NhatKyDoiCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,?,?,?,?,?); COMMIT;",
                    (
                        status,
                        actor,
                        reason or None,
                        swap_id,
                        swap_id,
                        action,
                        "Chờ xác nhận",
                        status,
                        actor,
                        reason or None,
                    ),
                )
                flash(
                    "Đã xác nhận đề nghị đổi ca."
                    if status == "Chờ duyệt"
                    else "Đã từ chối đề nghị đổi ca.",
                    "success",
                )
            elif action in ("swap_approve", "swap_admin_reject") and attendance_manager():
                swap_id = int(request.form["MaYeuCau"])
                swap = db.query(
                    "SELECT s.MaPhanCaA,s.MaPhanCaB,s.TrangThai,a.MaNV,a.Ngay,a.MaCa,COALESCE(a.GioBatDauOverride,ca.GioBatDau),COALESCE(a.GioKetThucOverride,ca.GioKetThuc),CASE WHEN a.GioBatDauOverride IS NOT NULL OR a.GioKetThucOverride IS NOT NULL THEN CASE WHEN COALESCE(a.GioKetThucOverride,ca.GioKetThuc)<COALESCE(a.GioBatDauOverride,ca.GioBatDau) THEN 1 ELSE 0 END ELSE ca.QuaDem END,b.MaNV,b.MaCa,COALESCE(b.GioBatDauOverride,cb.GioBatDau),COALESCE(b.GioKetThucOverride,cb.GioKetThuc),CASE WHEN b.GioBatDauOverride IS NOT NULL OR b.GioKetThucOverride IS NOT NULL THEN CASE WHEN COALESCE(b.GioKetThucOverride,cb.GioKetThuc)<COALESCE(b.GioBatDauOverride,cb.GioBatDau) THEN 1 ELSE 0 END ELSE cb.QuaDem END FROM YeuCauDoiCa s JOIN PhanCaNhanVien a ON a.MaPhanCa=s.MaPhanCaA JOIN CaLamViec ca ON ca.MaCa=a.MaCa JOIN PhanCaNhanVien b ON b.MaPhanCa=s.MaPhanCaB JOIN CaLamViec cb ON cb.MaCa=b.MaCa WHERE s.MaYeuCau=? AND s.TrangThai=N'Chờ duyệt'",
                    (swap_id,),
                )[1]
                if not swap or swap[0][4] < today_vietnam():
                    raise ValueError("Yêu cầu không còn hợp lệ hoặc ca đã qua ngày làm.")
                row = swap[0]
                reason = request.form.get("LyDo", "").strip()[:500]
                if action == "swap_admin_reject" and not reason:
                    raise ValueError("Hãy ghi lý do từ chối đổi ca.")
                if action == "swap_approve":
                    _validate_employee_shift_assignment(
                        row[3], row[4], row[11], row[12], bool(row[13]), (row[0], row[1])
                    )
                    _validate_employee_shift_assignment(
                        row[9], row[4], row[6], row[7], bool(row[8]), (row[0], row[1])
                    )
                    db.execute(
                        "SET XACT_ABORT ON; BEGIN TRAN; UPDATE PhanCaNhanVien SET MaCa=CASE WHEN MaPhanCa=? THEN ? ELSE ? END,GioBatDauOverride=CASE WHEN MaPhanCa=? THEN ? ELSE ? END,GioKetThucOverride=CASE WHEN MaPhanCa=? THEN ? ELSE ? END WHERE MaPhanCa IN (?,?) AND ((MaPhanCa=? AND MaNV=?) OR (MaPhanCa=? AND MaNV=?)); IF @@ROWCOUNT<>2 THROW 51031,'Shift assignments changed after approval.',1; UPDATE YeuCauDoiCa SET TrangThai=N'Đã đổi',NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Chờ duyệt'; IF @@ROWCOUNT<>1 THROW 51032,'Swap request has already changed.',1; INSERT INTO NhatKyDoiCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'approve',N'Chờ duyệt',N'Đã đổi',?,?); COMMIT;",
                        (
                            row[0],
                            row[10],
                            row[5],
                            row[0],
                            row[11],
                            row[6],
                            row[0],
                            row[12],
                            row[7],
                            row[0],
                            row[1],
                            row[0],
                            row[3],
                            row[1],
                            row[9],
                            actor,
                            reason or "Quản trị viên duyệt đổi ca",
                            swap_id,
                            swap_id,
                            actor,
                            reason or None,
                        ),
                    )
                else:
                    db.execute(
                        "SET XACT_ABORT ON; BEGIN TRAN; UPDATE YeuCauDoiCa SET TrangThai=N'Từ chối',NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Chờ duyệt'; IF @@ROWCOUNT<>1 THROW 51032,'Swap request has already changed.',1; INSERT INTO NhatKyDoiCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'reject',N'Chờ duyệt',N'Từ chối',?,?); COMMIT;",
                        (actor, reason, swap_id, swap_id, actor, reason),
                    )
                flash("Đã xử lý yêu cầu đổi ca.", "success")
            elif (
                action in ("shift", "toggle_shift", "assign", "assign_group", "holiday") and attendance_manager()
            ):
                if action == "shift":
                    name = request.form.get("TenCa", "").strip()
                    start = datetime.strptime(request.form.get("GioBatDau", ""), "%H:%M").time()
                    end = datetime.strptime(request.form.get("GioKetThuc", ""), "%H:%M").time()
                    overnight, grace = (
                        bool(request.form.get("QuaDem")),
                        int(request.form.get("PhutAnHan") or 0),
                    )
                    if (
                        not name
                        or len(name) > 80
                        or start == end
                        or (end < start) != overnight
                        or grace not in range(241)
                    ):
                        raise ValueError("Tên ca, giờ qua đêm hoặc số phút ân hạn không hợp lệ.")
                    db.execute(
                        "INSERT INTO CaLamViec(TenCa,GioBatDau,GioKetThuc,QuaDem,PhutAnHan) VALUES(?,?,?,?,?)",
                        (name, start, end, overnight, grace),
                    )
                    flash("Đã thêm ca làm việc.", "success")
                elif action == "toggle_shift":
                    db.execute(
                        "UPDATE CaLamViec SET TrangThai=CASE WHEN TrangThai=1 THEN 0 ELSE 1 END WHERE MaCa=?",
                        (int(request.form["MaCa"]),),
                    )
                    flash("Đã cập nhật trạng thái ca.", "success")
                elif action in ("assign", "assign_group"):
                    shift_id, work_date = (
                        int(request.form["MaCa"]),
                        date.fromisoformat(request.form["Ngay"]),
                    )
                    shift = db.query(
                        "SELECT GioBatDau,GioKetThuc FROM CaLamViec WHERE MaCa=? AND TrangThai=1",
                        (shift_id,),
                    )[1]
                    if not shift:
                        raise ValueError("Ca không tồn tại hoặc đã ngừng hoạt động.")
                    start = _parse_optional_shift_time(request.form.get("GioBatDau")) or shift[0][0]
                    end = _parse_optional_shift_time(request.form.get("GioKetThuc")) or shift[0][1]
                    overnight = end < start
                    if action == "assign":
                        employee_ids = [int(request.form["MaNV"])]
                    else:
                        department_id = int(request.form["MaPB"])
                        employee_ids = [
                            row[0]
                            for row in db.query(
                                "SELECT MaNV FROM NhanVien WHERE MaPB=? AND TrangThai=N'Đang làm'",
                                (department_id,),
                            )[1]
                        ]
                        if not employee_ids:
                            raise ValueError("Phòng ban chưa có nhân viên đang làm.")
                    for employee_id in employee_ids:
                        if not db.scalar(
                            "SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'",
                            (employee_id,),
                        ):
                            raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
                        _validate_employee_shift_assignment(
                            employee_id, work_date, start, end, overnight
                        )
                    db.execute_batches(
                        [
                            (
                                "INSERT INTO PhanCaNhanVien(MaNV,MaCa,Ngay,NguoiPhan,GioBatDauOverride,GioKetThucOverride) VALUES(?,?,?,?,?,?)",
                                [
                                    (employee_id, shift_id, work_date, actor, start, end)
                                    for employee_id in employee_ids
                                ],
                            )
                        ]
                    )
                    flash(f"Đã phân ca cho {len(employee_ids)} nhân viên.", "success")
                else:
                    holiday = date.fromisoformat(request.form.get("Ngay", ""))
                    name = request.form.get("TenNgay", "").strip()
                    if not name or len(name) > 120:
                        raise ValueError("Tên ngày lễ bắt buộc, tối đa 120 ký tự.")
                    db.execute(
                        "INSERT INTO LichNgayLe(Ngay,TenNgay,HuongLuong,NguoiTao) VALUES(?,?,?,?)",
                        (holiday, name, bool(request.form.get("HuongLuong")), actor),
                    )
                    flash("Đã thêm ngày lễ vào lịch.", "success")
            else:
                raise ValueError("Thao tác lịch ca không hợp lệ hoặc không đủ quyền.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("attendance.workforce_shifts"))

    own_id = int(session.get("user", {}).get("manv") or 0)
    assignment_sql = "SELECT p.MaPhanCa,n.HoTen,c.TenCa,p.Ngay,COALESCE(p.GioBatDauOverride,c.GioBatDau),COALESCE(p.GioKetThucOverride,c.GioKetThuc),CASE WHEN p.GioBatDauOverride IS NOT NULL OR p.GioKetThucOverride IS NOT NULL THEN CASE WHEN COALESCE(p.GioKetThucOverride,c.GioKetThuc)<COALESCE(p.GioBatDauOverride,c.GioBatDau) THEN 1 ELSE 0 END ELSE c.QuaDem END,p.NguoiPhan,p.MaNV,p.MaCa FROM PhanCaNhanVien p JOIN NhanVien n ON n.MaNV=p.MaNV JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.Ngay>=DATEADD(day,-1,CAST(GETDATE() AS DATE))"
    if attendance_manager():
        shifts = db.query(
            "SELECT MaCa,TenCa,GioBatDau,GioKetThuc,QuaDem,PhutAnHan,TrangThai FROM CaLamViec ORDER BY TenCa"
        )[1]
        people = db.query(
            "SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen"
        )[1]
        assignments = db.query(assignment_sql + " ORDER BY p.Ngay DESC,n.HoTen")[1]
        departments = db.query(
            "SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB"
        )[1]
        swap_requests = db.query(
            "SELECT s.MaYeuCau,a.Ngay,na.HoTen,ca.TenCa,nb.HoTen,cb.TenCa,s.TrangThai,s.PhanHoi,s.MaNVCau,b.MaNV FROM YeuCauDoiCa s JOIN PhanCaNhanVien a ON a.MaPhanCa=s.MaPhanCaA JOIN NhanVien na ON na.MaNV=a.MaNV JOIN CaLamViec ca ON ca.MaCa=a.MaCa JOIN PhanCaNhanVien b ON b.MaPhanCa=s.MaPhanCaB JOIN NhanVien nb ON nb.MaNV=b.MaNV JOIN CaLamViec cb ON cb.MaCa=b.MaCa WHERE s.TrangThai=N'Chờ duyệt' ORDER BY s.TaoLuc DESC",
            (),
        )[1]
        swap_mine, swap_targets = [], []
    else:
        shifts, people, departments = [], [], []
        assignments = db.query(assignment_sql + " AND p.MaNV=? ORDER BY p.Ngay DESC", (own_id,))[1]
        swap_mine = [row for row in assignments if row[3] >= today_vietnam()]
        swap_targets = db.query(
            assignment_sql
            + " AND p.MaNV<>? AND n.MaPB=(SELECT MaPB FROM NhanVien WHERE MaNV=?) ORDER BY p.Ngay,n.HoTen",
            (own_id, own_id),
        )[1]
        swap_requests = db.query(
            "SELECT s.MaYeuCau,a.Ngay,na.HoTen,ca.TenCa,nb.HoTen,cb.TenCa,s.TrangThai,s.PhanHoi,s.MaNVCau,CASE WHEN s.MaNVCau=a.MaNV THEN b.MaNV ELSE a.MaNV END AS MaNVXacNhan FROM YeuCauDoiCa s JOIN PhanCaNhanVien a ON a.MaPhanCa=s.MaPhanCaA JOIN NhanVien na ON na.MaNV=a.MaNV JOIN CaLamViec ca ON ca.MaCa=a.MaCa JOIN PhanCaNhanVien b ON b.MaPhanCa=s.MaPhanCaB JOIN NhanVien nb ON nb.MaNV=b.MaNV JOIN CaLamViec cb ON cb.MaCa=b.MaCa WHERE (s.MaNVCau=? OR a.MaNV=? OR b.MaNV=?) AND s.TrangThai IN (N'Chờ xác nhận',N'Chờ duyệt') ORDER BY s.TaoLuc DESC",
            (own_id, own_id, own_id),
        )[1]
    holidays = db.query(
        "SELECT Ngay,TenNgay,HuongLuong FROM LichNgayLe WHERE Ngay>=DATEADD(day,-30,CAST(GETDATE() AS DATE)) ORDER BY Ngay"
    )[1]
    return render_template(
        "attendance/workforce_shifts.html",
        shifts=shifts,
        people=people,
        assignments=assignments,
        holidays=holidays,
        departments=departments,
        swap_requests=swap_requests,
        swap_mine=swap_mine,
        swap_targets=swap_targets,
        own_id=own_id,
        admin=attendance_manager(),
        today=today_vietnam().isoformat(),
    )


@bp.route("/chamcong", methods=["GET", "POST"])
@login_required
def chamcong():
    _purge_expired_face_templates()
    today = today_vietnam()
    clock_now = now_vietnam()
    try:
        selected_day = date.fromisoformat(request.args.get("date", today.isoformat()))
    except ValueError:
        selected_day = today
        flash("Ngày xem chấm công không hợp lệ.", "error")
    try:
        report_month = int(request.args.get("month", today.month))
        report_year = int(request.args.get("year", today.year))
        if report_month not in range(1, 13) or report_year not in range(2000, today.year + 1):
            raise ValueError
    except (TypeError, ValueError):
        report_month, report_year = today.month, today.year
        flash("Tháng tổng hợp không hợp lệ.", "error")
    period_start = date(report_year, report_month, 1)
    period_end = date(report_year + (report_month == 12), report_month % 12 + 1, 1)
    face_csrf = session.setdefault("face_csrf", secrets.token_urlsafe(32))
    if request.method == "POST":
        manv = request.form.get("MaNV") if attendance_manager() else session["user"].get("manv")
        action = request.form.get("action")
        source = "admin" if attendance_manager() else "manual"
        try:
            if action in ("in", "out") and not manv:
                raise ValueError("Tài khoản chưa gắn với nhân viên nào, hãy liên hệ quản trị viên.")
            if action == "update_status":
                if not attendance_manager():
                    raise ValueError("Chỉ quản trị viên mới được sửa trạng thái chấm công.")
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
                _audit_attendance(
                    manv_,
                    "admin",
                    "edit_status",
                    "updated",
                    int(request.form.get("id")),
                    actor=session["user"]["user"],
                    detail=f"{old_status} -> {status}",
                )
                _record_attendance_event(
                    manv_,
                    int(request.form.get("id")),
                    "correction",
                    "admin",
                    "updated",
                    session["user"]["user"],
                    f"Trạng thái: {old_status} -> {status}",
                    work_date=work_date,
                )
                flash("Đã cập nhật trạng thái chấm công.", "success")
                manv_, work_date = existing[0][:2]
                if db.scalar(
                    "SELECT COUNT(*) FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?",
                    (manv_, work_date.month, work_date.year),
                ):
                    flash(
                        "Kỳ lương tương ứng đã được tính trước đó; hãy tính lại kỳ lương để áp dụng thay đổi.",
                        "error",
                    )
                return redirect(
                    url_for("attendance.chamcong", date=request.form.get("date", today.isoformat()))
                )
            if action == "delete":
                if not attendance_manager():
                    raise ValueError("Chỉ quản trị viên mới được xóa bản ghi chấm công.")
                existing = db.query(
                    "SELECT MaNV,Ngay,TrangThai FROM ChamCong WHERE MaCC=?",
                    (request.form["id"],),
                )[1]
                if not existing:
                    raise ValueError("Không tìm thấy bản ghi chấm công.")
                db.execute(
                    "UPDATE ChamCongSuKien SET MaCC=NULL WHERE MaCC=?; DELETE FROM ChamCong WHERE MaCC=?",
                    (request.form["id"], request.form["id"]),
                )
                _audit_attendance(
                    existing[0][0],
                    "admin",
                    "delete",
                    "deleted",
                    int(request.form["id"]),
                    actor=session["user"]["user"],
                    detail="Quản trị viên xóa bản ghi",
                )
                _record_attendance_event(
                    existing[0][0],
                    None,
                    "delete",
                    "admin",
                    "deleted",
                    session["user"]["user"],
                    f"Xóa dòng tổng hợp ngày {existing[0][1]}",
                    work_date=existing[0][1],
                )
                flash("Đã xóa bản ghi chấm công.", "success")
                manv_, work_date = existing[0][:2]
                if db.scalar(
                    "SELECT COUNT(*) FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?",
                    (manv_, work_date.month, work_date.year),
                ):
                    flash(
                        "Kỳ lương tương ứng đã được tính trước đó; hãy tính lại kỳ lương để áp dụng thay đổi.",
                        "error",
                    )
                return redirect(
                    url_for("attendance.chamcong", date=request.form.get("date", today.isoformat()))
                )
            if action == "resolve_complaint":
                if not attendance_manager():
                    raise ValueError("Chỉ quản trị viên được xử lý khiếu nại.")
                complaint_id = int(request.form.get("MaKN", ""))
                resolution = request.form.get("PhanHoi", "").strip()
                status = request.form.get("TrangThai", "").strip()
                if (
                    status not in ("Đi làm", "Đi muộn", "Nghỉ phép", "Nghỉ không phép")
                    or not resolution
                ):
                    raise ValueError("Cần chọn trạng thái hợp lệ và ghi phản hồi xử lý.")
                record = db.query(
                    "SELECT MaNV,Ngay,TrangThai FROM KhieuNaiChamCong WHERE MaKN=? AND TrangThai=N'Chờ xử lý'",
                    (complaint_id,),
                )[1]
                if not record:
                    raise ValueError("Không tìm thấy khiếu nại đang chờ xử lý.")
                employee_id, complaint_day, _ = record[0]
                clock_in = request.form.get("GioVao", "").strip() or None
                clock_out = request.form.get("GioRa", "").strip() or None
                old_times = db.query(
                    "SELECT GioVao,GioRa FROM ChamCong WHERE MaNV=? AND Ngay=?",
                    (employee_id, complaint_day),
                )[1]
                if old_times:
                    clock_in = clock_in or (
                        old_times[0][0].strftime("%H:%M") if old_times[0][0] else None
                    )
                    clock_out = clock_out or (
                        old_times[0][1].strftime("%H:%M") if old_times[0][1] else None
                    )
                for clock_value in (clock_in, clock_out):
                    if clock_value and not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", clock_value):
                        raise ValueError("Giờ vào/ra phải theo định dạng HH:MM.")
                late_minutes = early_minutes = 0
                if clock_in:
                    punch_in = datetime.combine(
                        complaint_day, datetime.strptime(clock_in, "%H:%M").time()
                    )
                    late_minutes, _ = _attendance_deviation_minutes(
                        employee_id, complaint_day, punch_in, "in"
                    )
                if clock_out:
                    punch_out_day = (
                        complaint_day + timedelta(days=1)
                        if clock_in and clock_out < clock_in
                        else complaint_day
                    )
                    punch_out = datetime.combine(
                        punch_out_day, datetime.strptime(clock_out, "%H:%M").time()
                    )
                    _, early_minutes = _attendance_deviation_minutes(
                        employee_id, complaint_day, punch_out, "out"
                    )
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; IF EXISTS(SELECT 1 FROM ChamCong WHERE MaNV=? AND Ngay=?) UPDATE ChamCong SET GioVao=?,GioRa=?,TrangThai=?,SoPhutMuon=?,SoPhutVeSom=? WHERE MaNV=? AND Ngay=? ELSE INSERT INTO ChamCong(MaNV,Ngay,GioVao,GioRa,TrangThai,SoPhutMuon,SoPhutVeSom) VALUES(?,?,?,?,?,?,?); UPDATE KhieuNaiChamCong SET TrangThai=N'Đã xử lý',PhanHoi=?,NguoiXuLy=?,XuLyLuc=SYSUTCDATETIME() WHERE MaKN=?; COMMIT;",
                    (
                        employee_id,
                        complaint_day,
                        clock_in,
                        clock_out,
                        status,
                        late_minutes,
                        early_minutes,
                        employee_id,
                        complaint_day,
                        employee_id,
                        complaint_day,
                        clock_in,
                        clock_out,
                        status,
                        late_minutes,
                        early_minutes,
                        resolution,
                        session["user"]["user"],
                        complaint_id,
                    ),
                )
                _audit_attendance(
                    employee_id,
                    "admin",
                    "resolve_complaint",
                    "updated",
                    actor=session["user"]["user"],
                    detail=f"KN {complaint_id}: {resolution}",
                )
                _record_attendance_event(
                    employee_id,
                    None,
                    "delete",
                    "admin",
                    "replaced",
                    session["user"]["user"],
                    f"Đặt lại luồng sự kiện theo khiếu nại {complaint_id}",
                    work_date=complaint_day,
                )
                if clock_in:
                    event_time = datetime.combine(
                        complaint_day, datetime.strptime(clock_in, "%H:%M").time()
                    )
                    _record_attendance_event(
                        employee_id,
                        None,
                        "in",
                        "admin",
                        "corrected",
                        session["user"]["user"],
                        f"Giờ vào đã xác minh theo khiếu nại {complaint_id}",
                        happened_at=event_time,
                        work_date=complaint_day,
                    )
                if clock_out:
                    event_day = (
                        complaint_day + timedelta(days=1)
                        if clock_in and clock_out < clock_in
                        else complaint_day
                    )
                    event_time = datetime.combine(
                        event_day, datetime.strptime(clock_out, "%H:%M").time()
                    )
                    _record_attendance_event(
                        employee_id,
                        None,
                        "out",
                        "admin",
                        "corrected",
                        session["user"]["user"],
                        f"Giờ ra đã xác minh theo khiếu nại {complaint_id}",
                        happened_at=event_time,
                        work_date=complaint_day,
                    )
                _record_attendance_event(
                    employee_id,
                    None,
                    "correction",
                    "admin",
                    "updated",
                    session["user"]["user"],
                    f"KN {complaint_id}: {resolution}",
                    work_date=complaint_day,
                )
                _sync_attendance_work_minutes(employee_id, complaint_day)
                flash("Đã cập nhật giờ công và xử lý khiếu nại.", "success")
                if db.scalar(
                    "SELECT COUNT(*) FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?",
                    (employee_id, complaint_day.month, complaint_day.year),
                ):
                    flash(
                        "Kỳ lương đã tính trước đó; hãy mở lại và tính lại kỳ để áp dụng thay đổi.",
                        "error",
                    )
                return redirect(url_for("attendance.chamcong", date=complaint_day.isoformat()))
            if action == "complaint":
                if attendance_manager():
                    raise ValueError("Nhân viên gửi khiếu nại bằng tài khoản của mình.")
                exception_type = request.form.get("LoaiNgoaiLe", "")
                detail = request.form.get("NoiDung", "").strip()
                if exception_type not in (
                    "Quên chấm vào/ra",
                    "Máy chấm công lỗi",
                    "Sai giờ ghi nhận",
                    "Khác",
                ):
                    raise ValueError("Loại ngoại lệ chấm công không hợp lệ.")
                reason = f"[{exception_type}] {detail}"
                complaint_day = _parse_iso_date(request.form.get("Ngay"), "Ngày khiếu nại")
                if not detail or len(reason) > 1000:
                    raise ValueError("Nội dung khiếu nại bắt buộc và tối đa 1000 ký tự.")
                db.execute(
                    "INSERT INTO KhieuNaiChamCong(MaNV,Ngay,NoiDung) VALUES(?,?,?)",
                    (manv, complaint_day, reason),
                )
                _audit_attendance(
                    manv,
                    "manual",
                    "complaint",
                    "submitted",
                    actor=session["user"]["user"],
                    detail=reason,
                )
                flash("Đã gửi khiếu nại chấm công để quản trị viên xem xét.", "success")
                return redirect(url_for("attendance.chamcong", date=complaint_day.isoformat()))
            if action not in ("in", "out"):
                raise ValueError("Thao tác chấm công không hợp lệ.")
            if not attendance_manager() and (
                not request.form.get("LyDo") or len(request.form.get("LyDo", "").strip()) < 5
            ):
                raise ValueError("Hãy nhập lý do khi dùng chấm công dự phòng.")
            occurred_at = now_vietnam()
            actor = session["user"]["user"]
            detail = request.form.get("LyDo", "")
            work_date = _attendance_work_date(int(manv), occurred_at)
            _record_attendance_cycle(
                int(manv),
                work_date,
                action,
                source,
                "recorded",
                actor,
                detail=detail,
                occurred_at=occurred_at,
            )
            _sync_attendance_work_minutes(int(manv), work_date)
            flash("Đã ghi nhận chấm công.", "success")
            if db.scalar(
                "SELECT COUNT(*) FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?",
                (manv, work_date.month, work_date.year),
            ):
                flash(
                    "Dữ liệu công đã thay đổi sau khi có phiếu lương. Hãy tính lại kỳ lương nháp hoặc mở lại kỳ đã duyệt/khóa theo quy trình.",
                    "warning",
                )
        except Exception as e:
            flash(_safe_error(e), "error")
        return redirect(url_for("attendance.chamcong"))
    flt = "" if attendance_manager() else " AND MaNV=%d" % int(session["user"].get("manv") or -1)
    try:
        people = db.query(
            "SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm'"
            + flt
            + " ORDER BY HoTen"
        )[1]
        cols, rows = db.query(
            "SELECT c.MaCC AS [Mã CC],n.HoTen AS [Nhân viên],c.Ngay AS [Ngày],c.GioVao AS [Giờ vào],c.GioRa AS [Giờ ra],c.TrangThai AS [Trạng thái],c.SoPhutMuon AS [Phút muộn],c.SoPhutLamViec AS [Phút làm việc],c.SoPhutVeSom AS [Phút về sớm] FROM ChamCong c JOIN NhanVien n ON n.MaNV=c.MaNV WHERE c.Ngay=?"
            + flt.replace("MaNV", "c.MaNV")
            + " ORDER BY c.MaCC DESC",
            (selected_day,),
        )
        current_employee = None
        if not attendance_manager() and session["user"].get("manv"):
            current_employee_rows = db.query(
                "SELECT HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE MaNV=?",
                (session["user"]["manv"],),
            )[1]
            current_employee = current_employee_rows[0] if current_employee_rows else None
        own_attendance = None
        own_hours = 0
        if not attendance_manager() and session["user"].get("manv"):
            own_id = int(session["user"]["manv"])
            own_work_date = _attendance_work_date(own_id, clock_now)
            summary_row = db.query(
                "SELECT GioVao,GioRa,TrangThai,SoPhutMuon,SoPhutVeSom FROM ChamCong WHERE MaNV=? AND Ngay=?",
                (own_id, own_work_date),
            )[1]
            own_hours = _observed_overtime_hours(
                own_id,
                datetime.combine(own_work_date, time.min),
                datetime.combine(own_work_date + timedelta(days=1), time.min),
            )
            own_attendance = {
                "work_date": own_work_date,
                "row": summary_row[0] if summary_row else None,
                "hours": own_hours,
            }
        summary_sql = """
            WITH Work AS (
                SELECT MaNV,
                    SUM(CASE WHEN TrangThai IN (N'Đi làm',N'Đi muộn') THEN 1 ELSE 0 END) AS WorkDays,
                    SUM(CASE WHEN TrangThai=N'Đi muộn' THEN 1 ELSE 0 END) AS LateCount,
                    SUM(CASE WHEN SoPhutVeSom>0 THEN 1 ELSE 0 END) AS EarlyCount,
                    SUM(SoPhutMuon) AS LateMinutes,SUM(SoPhutVeSom) AS EarlyMinutes,
                    SUM(CASE WHEN TrangThai IN (N'Đi làm',N'Đi muộn') AND (GioVao IS NULL OR GioRa IS NULL) THEN 1 ELSE 0 END) AS MissingPunches
                FROM ChamCong WHERE Ngay>=? AND Ngay<? GROUP BY MaNV
            ), Overtime AS (
                SELECT MaNV,SUM(SoGioThucTe) AS OvertimeHours FROM TangCaYeuCau
                WHERE TrangThai=N'Đã xác nhận' AND BatDau>=? AND BatDau<? GROUP BY MaNV
            )
            SELECT n.MaNV,ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))),n.HoTen,
                ISNULL(w.WorkDays,0),
                ISNULL(w.LateCount,0),ISNULL(w.EarlyCount,0),ISNULL(w.LateMinutes,0),ISNULL(w.EarlyMinutes,0),
                ISNULL(o.OvertimeHours,0),ISNULL(w.MissingPunches,0),n.NgayVaoLam
            FROM NhanVien n LEFT JOIN Work w ON w.MaNV=n.MaNV
            LEFT JOIN Overtime o ON o.MaNV=n.MaNV
            WHERE n.TrangThai=N'Đang làm' """
        summary_params = (
            period_start, period_end,
            datetime.combine(period_start, time.min), datetime.combine(period_end, time.min),
        )
        if not attendance_manager():
            summary_sql += " AND n.MaNV=?"
            summary_params += (int(session["user"].get("manv") or -1),)
        summary_sql += " ORDER BY n.HoTen"
        summary_rows = db.query(summary_sql, summary_params)[1]
        leave_sql = "SELECT MaNV,TuNgay,DenNgay,SoNgay,LoaiNghi FROM NghiPhep WHERE TrangThai=N'Đã duyệt' AND DenNgay>=? AND TuNgay<?"
        leave_params = (period_start, period_end)
        if not attendance_manager():
            leave_sql += " AND MaNV=?"
            leave_params += (int(session["user"].get("manv") or -1),)
        leave_rows = db.query(leave_sql, leave_params)[1]
        leave_totals = {}
        leave_dates = {}
        for leave_employee, leave_start, leave_end, leave_days, leave_type in leave_rows:
            whole_days = _leave_days(leave_employee, leave_start, leave_end)
            overlap_start, overlap_end = max(leave_start, period_start), min(leave_end, period_end - timedelta(days=1))
            overlap_days = _leave_days(leave_employee, overlap_start, overlap_end) if overlap_start <= overlap_end else 0
            prorated = float(leave_days or 0) * overlap_days / whole_days if whole_days else 0
            totals = leave_totals.setdefault(int(leave_employee), [0.0, 0.0])
            totals[1 if leave_type == "Không lương" else 0] += prorated
            clipped_start, clipped_end = max(leave_start, period_start), min(leave_end, period_end - timedelta(days=1))
            leave_dates.setdefault(int(leave_employee), set()).update(
                clipped_start + timedelta(days=offset)
                for offset in range((clipped_end - clipped_start).days + 1)
            )
        employee_filter = " AND MaNV=?" if not attendance_manager() else ""
        employee_params = (int(session["user"].get("manv") or -1),) if employee_filter else ()
        weekly_rows = db.query(
            "SELECT MaNV,Thu FROM LichLamViecNhanVien WHERE 1=1" + employee_filter,
            employee_params,
        )[1]
        scheduled_rows = db.query(
            "SELECT MaNV,Ngay FROM PhanCaNhanVien WHERE Ngay>=? AND Ngay<?" + employee_filter,
            (period_start, period_end) + employee_params,
        )[1]
        holiday_dates = {
            row[0]
            for row in db.query(
                "SELECT Ngay FROM LichNgayLe WHERE Ngay>=? AND Ngay<?",
                (period_start, period_end),
            )[1]
        }
        punch_dates = {}
        for employee_id, punch_day in db.query(
            "SELECT MaNV,Ngay FROM ChamCong WHERE Ngay>=? AND Ngay<?" + employee_filter,
            (period_start, period_end) + employee_params,
        )[1]:
            punch_dates.setdefault(int(employee_id), set()).add(punch_day)
        weekdays_by_employee = {}
        for employee_id, weekday in weekly_rows:
            weekdays_by_employee.setdefault(int(employee_id), set()).add(int(weekday))
        shifts_by_employee = {}
        for employee_id, shift_day in scheduled_rows:
            shifts_by_employee.setdefault(int(employee_id), set()).add(shift_day)
        month_summary = []
        last_day = min(period_end - timedelta(days=1), today - timedelta(days=1))
        for row in summary_rows:
            employee_id = int(row[0])
            expected_weekdays = weekdays_by_employee.get(
                employee_id, set(range(7)) - set(config.NGAY_NGHI_TUAN)
            )
            scheduled_days = shifts_by_employee.get(employee_id, set())
            first_expected = max(period_start, row[10] or period_start)
            missing_days = 0
            current_day = first_expected
            while current_day <= last_day:
                expected = (
                    current_day in scheduled_days
                    if scheduled_days
                    else current_day.weekday() in expected_weekdays
                )
                if (
                    expected
                    and current_day not in holiday_dates
                    and current_day not in leave_dates.get(employee_id, set())
                    and current_day not in punch_dates.get(employee_id, set())
                ):
                    missing_days += 1
                current_day += timedelta(days=1)
            leaves = leave_totals.get(employee_id, [0, 0])
            month_summary.append(
                (row[1], row[2], row[3], round(leaves[0], 2), round(leaves[1], 2),
                 row[4], row[5], row[6], row[7], row[8], int(row[9]) + missing_days)
            )
    except Exception as e:
        people = []
        cols, rows = [], []
        current_employee = None
        own_attendance = None
        month_summary = []
        flash(_safe_error(e, "Không tải được dữ liệu chấm công."), "error")
    has_photo = False
    has_face = False
    has_current_face = False
    if not attendance_manager():
        manv = session["user"].get("manv")
        if manv:
            has_photo = bool(
                db.scalar(
                    "SELECT CASE WHEN AnhHoSo IS NULL THEN 0 ELSE 1 END FROM NhanVien WHERE MaNV=?",
                    (manv,),
                )
                or 0
            )
            has_face = bool(
                db.scalar("SELECT COUNT(*) FROM NhanVienKhuonMat WHERE MaNV=?", (manv,)) or 0
            )
            has_current_face = bool(
                db.scalar(
                    "SELECT COUNT(*) FROM NhanVienKhuonMat WHERE MaNV=? AND ConsentVersion=?",
                    (manv, config.FACE_CONSENT_VERSION),
                )
                or 0
            )
    return render_template(
        "attendance/attendance.html",
        people=people,
        current_employee=current_employee,
        own_attendance=own_attendance,
        current_time=clock_now,
        report_month=report_month,
        report_year=report_year,
        month_summary=month_summary,
        cols=cols,
        rows=rows,
        today=today,
        selected_day=selected_day,
        admin=attendance_manager(),
        face_csrf=face_csrf,
        has_photo=has_photo,
        has_face=has_face,
        has_current_face=has_current_face,
        face_logs=db.query(
            "SELECT TOP 200 n.HoTen,j.Nguon,j.ThaoTac,j.KetQua,j.Similarity,j.ThoiDiem,j.NguoiThucHien,j.ChiTiet FROM NhatKyChamCong j JOIN NhanVien n ON n.MaNV=j.MaNV ORDER BY j.MaNhatKy DESC",
            (),
        )[1]
        if attendance_manager()
        else [],
        attendance_events=(
            db.query(
                "SELECT TOP 300 n.HoTen,e.NgayCong,e.ThoiDiem,e.LoaiSuKien,e.Nguon,e.KetQua,e.Similarity,e.NguoiThucHien,e.ChiTiet FROM ChamCongSuKien e JOIN NhanVien n ON n.MaNV=e.MaNV ORDER BY e.ThoiDiem DESC",
                (),
            )[1]
            if attendance_manager()
            else db.query(
                "SELECT TOP 100 n.HoTen,e.NgayCong,e.ThoiDiem,e.LoaiSuKien,e.Nguon,e.KetQua,e.Similarity,e.NguoiThucHien,e.ChiTiet FROM ChamCongSuKien e JOIN NhanVien n ON n.MaNV=e.MaNV WHERE e.MaNV=? ORDER BY e.ThoiDiem DESC",
                (session["user"].get("manv") or -1,),
            )[1]
        ),
        complaints=db.query(
            "SELECT k.MaKN,k.MaNV,n.HoTen,k.Ngay,k.NoiDung,k.TaoLuc FROM KhieuNaiChamCong k JOIN NhanVien n ON n.MaNV=k.MaNV WHERE k.TrangThai=N'Chờ xử lý' ORDER BY k.TaoLuc",
            (),
        )[1]
        if attendance_manager()
        else [],
        face_retention_days=config.FACE_RETENTION_DAYS,
        face_consent_version=config.FACE_CONSENT_VERSION,
        my_complaints=db.query(
            "SELECT Ngay,NoiDung,TrangThai,PhanHoi FROM KhieuNaiChamCong WHERE MaNV=? ORDER BY TaoLuc DESC",
            (session["user"].get("manv") or -1,),
        )[1]
        if not attendance_manager()
        else [],
    )


@bp.route("/api/chamcong/face/enroll", methods=["POST"])
@login_required
def face_enroll():
    if admin():
        return jsonify(error="Đăng ký khuôn mặt chỉ dành cho tài khoản nhân viên."), 403
    data, error = face_payload()
    if error:
        return error
    try:
        if data.get("consent") is not True:
            raise ValueError("Cần xác nhận đã có sự đồng ý trước khi lưu dữ liệu khuôn mặt.")
        manv = face_employee_id(data)
        if (
            not data.get("consent_purpose")
            or data.get("consent_version") != config.FACE_CONSENT_VERSION
        ):
            raise ValueError(
                "Cần xác nhận rõ mục đích và phiên bản thông báo xử lý dữ liệu khuôn mặt."
            )
        cipher = _face_cipher()
        embedding = cipher.encrypt(
            json.dumps(data["embedding"], separators=(",", ":")).encode()
        ).decode("ascii")
        db.execute(
            "IF EXISTS(SELECT 1 FROM NhanVienKhuonMat WHERE MaNV=?) UPDATE NhanVienKhuonMat SET Embedding=?,ConsentAt=SYSUTCDATETIME(),ConsentVersion=?,UpdatedAt=SYSUTCDATETIME() WHERE MaNV=? ELSE INSERT INTO NhanVienKhuonMat(MaNV,Embedding,ConsentVersion) VALUES(?,?,?)",
            (
                manv,
                embedding,
                config.FACE_CONSENT_VERSION,
                manv,
                manv,
                embedding,
                config.FACE_CONSENT_VERSION,
            ),
        )
        _audit_attendance(
            manv,
            "face",
            "enroll",
            "success",
            actor=session["user"]["user"],
            detail="Đồng ý phiên bản " + config.FACE_CONSENT_VERSION,
        )
        return jsonify(message="Đã đăng ký mẫu khuôn mặt đã mã hóa."), 200
    except Exception:
        current_app.logger.exception("Face enrollment failed")
        return jsonify(
            error="Không thể đăng ký dữ liệu khuôn mặt. Hãy thử lại hoặc liên hệ quản trị viên."
        ), 400


@bp.route("/api/nhanvien/<int:manv>/anh")
@login_required
def nhanvien_anh(manv):
    if not has_permission("employees.view") and str(session["user"].get("manv") or "") != str(manv):
        return "", 403
    blob = db.scalar("SELECT AnhHoSo FROM NhanVien WHERE MaNV=?", (manv,))
    if not blob:
        return "", 404
    response = make_response(bytes(blob))
    response.headers["Content-Type"] = "image/jpeg"
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.route("/tang-ca", methods=["GET", "POST"])
@login_required
def overtime_requests():
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            if action == "request":
                employee_id = (
                    int(request.form["MaNV"]) if attendance_manager() else int(session["user"].get("manv") or 0)
                )
                start = datetime.fromisoformat(request.form.get("BatDau", ""))
                end = datetime.fromisoformat(request.form.get("KetThuc", ""))
                reason = request.form.get("LyDo", "").strip()
                hours = (end - start).total_seconds() / 3600
                if not employee_id or hours <= 0 or hours > 24 or not reason or len(reason) > 500:
                    raise ValueError(
                        "Khoảng tăng ca hoặc lý do không hợp lệ; tối đa 24 giờ mỗi yêu cầu."
                    )
                if not db.scalar(
                    "SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'",
                    (employee_id,),
                ):
                    raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
                if db.scalar(
                    "SELECT COUNT(*) FROM TangCaYeuCau WHERE MaNV=? AND TrangThai IN (N'Chờ duyệt',N'Đã duyệt',N'Đã xác nhận') AND BatDau<? AND KetThuc>?",
                    (employee_id, end, start),
                ):
                    raise ValueError(
                        "Thời gian trùng với một yêu cầu tăng ca đang chờ hoặc đã duyệt."
                    )
                overtime_id = db.query(
                    "INSERT INTO TangCaYeuCau(MaNV,BatDau,KetThuc,SoGio,LyDo) OUTPUT INSERTED.MaYeuCau VALUES(?,?,?,?,?)",
                    (employee_id, start, end, round(hours, 2), reason),
                )[1][0][0]
                db.execute(
                    "INSERT INTO NhatKyTangCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'submit',NULL,N'Chờ duyệt',?,?)",
                    (overtime_id, actor, reason),
                )
                flash("Đã gửi yêu cầu tăng ca để quản trị viên phê duyệt.", "success")
            elif action in ("approve", "reject") and attendance_manager():
                overtime_id = int(request.form["MaYeuCau"])
                response = request.form.get("PhanHoi", "").strip()[:500]
                status = "Đã duyệt" if action == "approve" else "Từ chối"
                if action == "reject" and not response:
                    raise ValueError("Hãy nhập lý do từ chối yêu cầu tăng ca.")
                current = db.query(
                    "SELECT TrangThai FROM TangCaYeuCau WHERE MaYeuCau=?", (overtime_id,)
                )[1]
                if not current or current[0][0] != "Chờ duyệt":
                    raise ValueError("Yêu cầu không còn ở trạng thái chờ duyệt.")
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; UPDATE TangCaYeuCau SET TrangThai=?,NguoiDuyet=?,DuyetLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Chờ duyệt'; IF @@ROWCOUNT<>1 THROW 50011,'Yêu cầu đã được xử lý.',1; INSERT INTO NhatKyTangCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,?,N'Chờ duyệt',?,?,?); COMMIT;",
                    (
                        status,
                        actor,
                        response or None,
                        overtime_id,
                        action,
                        status,
                        actor,
                        response or None,
                    ),
                )
                flash("Đã cập nhật kết quả yêu cầu tăng ca.", "success")
            elif action == "confirm" and attendance_manager():
                overtime_id = int(request.form["MaYeuCau"])
                request_row = db.query(
                    "SELECT MaNV,BatDau,KetThuc,SoGio,TrangThai FROM TangCaYeuCau WHERE MaYeuCau=?",
                    (overtime_id,),
                )[1]
                if (
                    not request_row
                    or request_row[0][4] != "Đã duyệt"
                    or request_row[0][2] > now_vietnam()
                ):
                    raise ValueError(
                        "Chỉ xác nhận tăng ca đã duyệt sau khi thời gian làm việc kết thúc."
                    )
                employee_id, interval_start, interval_end, approved_hours, _ = request_row[0]
                observed_hours = _observed_overtime_hours(employee_id, interval_start, interval_end)
                requested_hours = request.form.get("SoGioThucTe", "").strip()
                actual_hours = float(requested_hours) if requested_hours else observed_hours
                reason = request.form.get("PhanHoi", "").strip()[:500]
                if (
                    not math.isfinite(actual_hours)
                    or actual_hours < 0
                    or actual_hours > float(approved_hours)
                ):
                    raise ValueError("Giờ thực tế phải nằm trong khoảng 0 đến số giờ đã duyệt.")
                if not observed_hours and not reason:
                    raise ValueError(
                        "Không có cặp sự kiện vào/ra trong giờ tăng ca; cần lý do xác nhận ngoại lệ."
                    )
                if abs(actual_hours - observed_hours) >= 0.01 and not reason:
                    raise ValueError("Giờ xác nhận khác giờ đối soát sự kiện; hãy ghi lý do.")
                detail = (
                    reason
                    or f"Đối soát sự kiện: {observed_hours:g} giờ; xác nhận: {actual_hours:g} giờ."
                )
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; UPDATE TangCaYeuCau SET TrangThai=N'Đã xác nhận',SoGioThucTe=?,XacNhanBoi=?,XacNhanLuc=SYSUTCDATETIME(),PhanHoi=? WHERE MaYeuCau=? AND TrangThai=N'Đã duyệt'; IF @@ROWCOUNT<>1 THROW 50012,'Yêu cầu tăng ca đã thay đổi.',1; INSERT INTO NhatKyTangCa(MaYeuCau,ThaoTac,TrangThaiCu,TrangThaiMoi,NguoiThucHien,LyDo) VALUES(?,N'confirm',N'Đã duyệt',N'Đã xác nhận',?,?); UPDATE LuongKy SET TinhLuc=NULL,TinhBoi=?,PhienBan=PhienBan+1 WHERE Nam=YEAR(?) AND Thang=MONTH(?) AND TrangThai=N'Nháp'; COMMIT;",
                    (actual_hours, actor, detail, overtime_id, overtime_id, actor, detail, actor, interval_start, interval_start),
                )
                flash("Đã xác nhận giờ tăng ca sau khi đối soát sự kiện chấm công.", "success")
                if db.scalar(
                    "SELECT COUNT(*) FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?",
                    (employee_id, interval_start.month, interval_start.year),
                ):
                    flash("Dữ liệu tăng ca đã thay đổi sau khi có phiếu lương; cần tính lại kỳ nháp hoặc mở lại kỳ đã khóa.", "warning")
            else:
                raise ValueError("Thao tác tăng ca không hợp lệ hoặc không đủ quyền.")
        except Exception as error:
            flash(_safe_error(error), "error")
        return redirect(url_for("attendance.overtime_requests"))
    if attendance_manager():
        rows = db.query(
            "SELECT t.MaYeuCau,n.HoTen,t.BatDau,t.KetThuc,t.SoGio,t.SoGioThucTe,t.LyDo,t.TrangThai,t.NguoiDuyet,t.PhanHoi,t.MaNV FROM TangCaYeuCau t JOIN NhanVien n ON n.MaNV=t.MaNV ORDER BY CASE WHEN t.TrangThai=N'Chờ duyệt' THEN 0 WHEN t.TrangThai=N'Đã duyệt' THEN 1 ELSE 2 END,t.BatDau DESC"
        )[1]
        people = db.query(
            "SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen"
        )[1]
    else:
        manv = session["user"].get("manv") or -1
        rows = db.query(
            "SELECT t.MaYeuCau,n.HoTen,t.BatDau,t.KetThuc,t.SoGio,t.SoGioThucTe,t.LyDo,t.TrangThai,t.NguoiDuyet,t.PhanHoi,t.MaNV FROM TangCaYeuCau t JOIN NhanVien n ON n.MaNV=t.MaNV WHERE t.MaNV=? ORDER BY t.BatDau DESC",
            (manv,),
        )[1]
        people = []
    rows = [tuple(row) + (_observed_overtime_hours(row[10], row[2], row[3]),) for row in rows]
    return render_template(
        "overtime/overtime.html",
        rows=rows,
        people=people,
        admin=attendance_manager(),
        own_id=session["user"].get("manv"),
        now=now_vietnam(),
    )


@bp.route("/api/chamcong/face/scan", methods=["POST"])
@login_required
def face_scan():
    if admin():
        return jsonify(error="Chấm công bằng khuôn mặt chỉ dành cho tài khoản nhân viên."), 403
    data, error = face_payload()
    if error:
        return error
    action = data.get("action")
    if action not in ("in", "out"):
        return jsonify(error="Vui lòng chọn chấm vào hoặc chấm ra."), 400
    challenge = session.pop("face_live_challenge", None)
    if (
        not challenge
        or challenge["expires"] < time.time()
        or not hmac.compare_digest(str(data.get("nonce", "")), challenge["nonce"])
    ):
        return jsonify(
            error="Thử thách camera đã hết hạn hoặc không hợp lệ. Hãy bắt đầu lại.", fallback=True
        ), 409
    if data.get("sequence") != challenge["sequence"] or data.get("blinked") is not True:
        return jsonify(
            error="Chưa hoàn thành thử thách chuyển động và chớp mắt.", fallback=True
        ), 409
    try:
        real_score = float(data.get("real_score"))
        live_score = float(data.get("live_score"))
    except (TypeError, ValueError):
        return jsonify(error="Không có điểm xác minh người thật hợp lệ.", fallback=True), 400
    if (
        not math.isfinite(real_score)
        or not math.isfinite(live_score)
        or not 0 <= real_score <= 1
        or not 0 <= live_score <= 1
        or real_score < config.FACE_ANTISPOOF_THRESHOLD
        or live_score < config.FACE_LIVENESS_THRESHOLD
    ):
        _audit_attendance(
            int(session["user"].get("manv") or 0),
            "face",
            action,
            "rejected",
            actor=session["user"]["user"],
            detail=f"Liveness rejected; real={real_score}; live={live_score}",
        )
        return jsonify(
            error="Không vượt qua kiểm tra chống giả mạo. Hãy thử lại bằng camera hoặc dùng chấm công dự phòng.",
            fallback=True,
        ), 409
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
                _audit_attendance(
                    own_id,
                    "face",
                    action,
                    "rejected",
                    actor=session["user"]["user"],
                    detail="Phiên bản đồng ý đã thay đổi; cần đăng ký lại",
                )
                return jsonify(
                    error="Thông báo về dữ liệu khuôn mặt đã thay đổi. Hãy đọc và đồng ý lại bằng cách đăng ký lại mẫu.",
                    fallback=True,
                ), 409
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
            _audit_attendance(
                own_id,
                "face",
                action,
                "rejected",
                similarity=max(0, best_score),
                actor=session["user"]["user"],
                detail="Không đạt ngưỡng; ngưỡng cấu hình=" + str(FACE_MATCH_THRESHOLD),
            )
            return jsonify(
                error="Không nhận diện được khuôn mặt đã đăng ký. Hãy chọn ảnh rõ hơn hoặc dùng chấm công dự phòng.",
                fallback=True,
            ), 404
        manv, name, code = best
        now = now_vietnam()
        work_date = _attendance_work_date(manv, now)
        _record_attendance_cycle(
            manv,
            work_date,
            action,
            "face",
            "matched",
            session["user"]["user"],
            detail=f"Live camera challenge; real={real_score:.3f}; live={live_score:.3f}",
            similarity=best_score,
            occurred_at=now,
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
        current_app.logger.exception("Face attendance processing failed")
        return jsonify(
            error="Không thể ghi nhận chấm công. Hãy dùng phương thức dự phòng hoặc liên hệ quản trị viên."
        ), 400

