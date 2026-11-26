from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from datetime import date, timedelta
import math
import config
from database import db
from utils.decorators import login_required
from services.common_service import _safe_error, has_permission, is_manager
from services.attendance.leave_service import (LEAVE_TYPES, _LEAVE_PENDING_DAYS, _create_leave_request, _leave_audit, _leave_days, _leave_notify, _leave_quota, _save_leave_quota, _update_leave_request)

bp = Blueprint('leave', __name__)


@bp.route("/nghiphep", methods=["GET", "POST"])
@login_required
def nghiphep():
    leave_admin = has_permission("leave.view_all")
    manager_role = is_manager()
    if request.method == "POST":
        try:
            action = request.form.get("action")
            actor = session["user"]["user"]
            own_id = int(session["user"].get("manv") or 0)
            policy = db.query("SELECT YeuCauQuanLy,YeuCauNhanSu FROM CauHinhNghiPhep WHERE Id=1")[
                1
            ][0]
            # The three-role model routes leave approvals to HR/Accounting.
            require_manager, require_hr = False, True
            if action == "policy" and has_permission("leave.manage_policy"):
                db.execute(
                    "UPDATE CauHinhNghiPhep SET YeuCauQuanLy=0,YeuCauNhanSu=1 WHERE Id=1",
                )
                flash("Đã lưu luồng duyệt nghỉ phép.", "success")
            elif action == "manager" and has_permission("leave.manage_policy"):
                employee_id, manager_id = int(request.form["MaNV"]), int(request.form["MaQuanLy"])
                if employee_id == manager_id or not db.scalar(
                    "SELECT COUNT(*) FROM NhanVien n JOIN TaiKhoan t ON t.MaNV=n.MaNV AND t.MaVaiTro=3 AND t.TrangThai=1 WHERE n.MaNV=? AND n.TrangThai=N'Đang làm'",
                    (manager_id,),
                ):
                    raise ValueError(
                        "Quản lý phải có vai trò QuanLy, đang làm và khác với nhân viên được gán."
                    )
                old_manager = db.scalar(
                    "SELECT MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (employee_id,)
                )
                if old_manager != manager_id:
                    current_start = db.scalar(
                        "SELECT MAX(TuNgay) FROM LichSuCongTac WHERE MaNV=? AND DenNgay IS NULL",
                        (employee_id,),
                    )
                    today = date.today()
                    if current_start and today < current_start:
                        raise ValueError("Ngày hiệu lực mới trước mốc lịch sử hiện tại.")
                    snapshot = db.query(
                        "SELECT MaPB,MaCV,MaViTri,LuongCoBan FROM NhanVien WHERE MaNV=?",
                        (employee_id,),
                    )[1]
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
                        history_params = (
                            [today, employee_id, employee_id, today]
                            + snapshot[:3]
                            + [manager_id, snapshot[3], actor]
                        )
                    manager_audit_sql = "INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'cap_nhat',N'MaQuanLy',?);"
                    db.execute(
                        "SET XACT_ABORT ON; BEGIN TRAN; "
                        + manager_sql
                        + history_sql
                        + manager_audit_sql
                        + " COMMIT;",
                        manager_params + history_params + [employee_id, actor],
                    )
                flash("Đã lưu quản lý trực tiếp.", "success")
            elif action == "quota" and has_permission("leave.manage_quota"):
                employee_id, quota_year = int(request.form["MaNV"]), int(request.form["Nam"])
                allocated, carry = (
                    float(request.form.get("SoNgayCap", 0)),
                    float(request.form.get("SoNgayChuyen", 0)),
                )
                if not 2000 <= quota_year <= 2100 or not all(
                    math.isfinite(v) and 0 <= v <= 366 for v in (allocated, carry)
                ):
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
                db.execute_batches(
                    [
                        ("DELETE FROM LichLamViecNhanVien WHERE MaNV=?", [(employee_id,)]),
                        (
                            "INSERT INTO LichLamViecNhanVien(MaNV,Thu) VALUES(?,?)",
                            [(employee_id, day) for day in sorted(days)],
                        ),
                    ]
                )
                flash("Đã lưu lịch làm việc theo tuần.", "success")
            elif action == "read_notice" and not leave_admin:
                db.execute(
                    "UPDATE ThongBaoNghiPhep SET DaDoc=1 WHERE MaTB=? AND MaNV=?",
                    (request.form["id"], own_id),
                )
            elif action == "submit":
                employee_id = int(request.form["MaNV"] if leave_admin else own_id)
                start, end = (
                    date.fromisoformat(request.form["TuNgay"]),
                    date.fromisoformat(request.form["DenNgay"]),
                )
                leave_type, reason = (
                    request.form.get("LoaiNghi", ""),
                    request.form.get("LyDo", "").strip(),
                )
                if not employee_id or end < start or start.year != end.year:
                    raise ValueError(
                        "Tài khoản hoặc khoảng ngày nghỉ không hợp lệ; mỗi đơn chỉ thuộc một năm."
                    )
                if leave_type not in LEAVE_TYPES or len(reason) > 255:
                    raise ValueError("Loại nghỉ không hợp lệ hoặc lý do vượt quá 255 ký tự.")
                if not db.scalar(
                    "SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'",
                    (employee_id,),
                ):
                    raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
                days = _leave_days(employee_id, start, end)
                if not days:
                    raise ValueError("Khoảng nghỉ không có ngày làm việc theo lịch nhân viên.")
                if db.scalar(
                    "SELECT COUNT(*) FROM NghiPhep WHERE MaNV=? AND TrangThai NOT IN (N'Từ chối',N'Đã rút',N'Đã hủy') AND ((TuNgay<=? AND DenNgay>=?) OR (NgayCuTu<=? AND NgayCuDen>=?))",
                    (employee_id, end, start, end, start),
                ):
                    raise ValueError(
                        "Khoảng ngày trùng với đơn đang chờ, đã duyệt hoặc đang yêu cầu hủy."
                    )
                if leave_type == "Phép năm":
                    allocated, carry, used, pending = _leave_quota(employee_id, start.year)
                    available = allocated + carry - used - pending
                    if days > available:
                        raise ValueError(
                            f"Quỹ phép năm còn {max(0, available):g} ngày, không đủ cho yêu cầu {days} ngày."
                        )
                manager = db.scalar(
                    "SELECT MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (employee_id,)
                )
                if require_manager and not manager:
                    raise ValueError(
                        "Chưa gán quản lý trực tiếp cho nhân viên; quản trị viên cần cấu hình trước khi gửi đơn."
                    )
                state = (
                    "Chờ quản lý"
                    if require_manager
                    else ("Chờ nhân sự" if require_hr else "Đã duyệt")
                )
                leave_id = _create_leave_request(
                    employee_id, start, end, days, reason, leave_type, state, actor
                )
                _leave_notify(
                    employee_id,
                    leave_id,
                    f"Đơn nghỉ {start}–{end} đã được gửi; trạng thái: {state}.",
                )
                if state == "Chờ quản lý":
                    _leave_notify(
                        manager,
                        leave_id,
                        f"Có đơn nghỉ phép của nhân viên cần bạn xem xét ({start}–{end}).",
                    )
                flash("Đã gửi đơn nghỉ phép.", "success")
            elif action in ("approve", "reject"):
                leave_id = int(request.form["id"])
                item = db.query(
                    "SELECT p.MaNV,p.TrangThai,p.TuNgay,p.DenNgay,p.SoNgay,p.NgayCuTu,p.NgayCuDen,p.SoNgayCu,p.LoaiCu,q.MaQuanLy FROM NghiPhep p LEFT JOIN QuanLyTrucTiep q ON q.MaNV=p.MaNV WHERE p.MaNP=?",
                    (leave_id,),
                )[1]
                if not item:
                    raise ValueError("Không tìm thấy đơn nghỉ phép.")
                employee_id, old_state = item[0][0], item[0][1]
                if old_state not in (
                    "Chờ quản lý",
                    "Chờ nhân sự",
                    "Chờ quản lý hủy",
                    "Chờ nhân sự hủy",
                    "Chờ quản lý thay đổi",
                    "Chờ nhân sự thay đổi",
                ):
                    raise ValueError("Đơn không còn ở trạng thái chờ duyệt.")
                is_direct_manager = (
                    manager_role and own_id and item[0][9] == own_id
                )
                is_hr_reviewer = has_permission("leave.approve_hr")
                if old_state.startswith("Chờ quản lý") and not (is_direct_manager or is_hr_reviewer):
                    raise ValueError("Chỉ nhân sự/kế toán được xử lý bước duyệt này.")
                if old_state.startswith("Chờ nhân sự") and not is_hr_reviewer:
                    raise ValueError("Đơn đang chờ bước nhân sự.")
                if not (is_direct_manager or is_hr_reviewer):
                    raise ValueError("Bạn không có quyền xử lý đơn này.")
                if action == "reject":
                    if "hủy" in old_state:
                        new_state = "Đã duyệt"
                        db.execute(
                            "UPDATE NghiPhep SET TrangThai=N'Đã duyệt',PhanHoi=? WHERE MaNP=?",
                            (request.form.get("PhanHoi", "").strip()[:1000], leave_id),
                        )
                    elif "thay đổi" in old_state and item[0][5]:
                        db.execute(
                            "UPDATE NghiPhep SET TuNgay=?,DenNgay=?,SoNgay=?,LoaiNghi=?,TrangThai=N'Đã duyệt',NgayCuTu=NULL,NgayCuDen=NULL,SoNgayCu=NULL,LoaiCu=NULL WHERE MaNP=?",
                            (item[0][5], item[0][6], item[0][7], item[0][8], leave_id),
                        )
                        new_state = "Đã duyệt"
                    else:
                        new_state = "Từ chối"
                        db.execute(
                            "UPDATE NghiPhep SET TrangThai=?,PhanHoi=? WHERE MaNP=?",
                            (new_state, request.form.get("PhanHoi", "").strip()[:1000], leave_id),
                        )
                    _leave_notify(
                        employee_id,
                        leave_id,
                        f"Đơn nghỉ {item[0][2]}–{item[0][3]} bị từ chối. {request.form.get('PhanHoi', '').strip()[:300]}",
                    )
                elif old_state.startswith("Chờ quản lý"):
                    stem = (
                        "hủy"
                        if "hủy" in old_state
                        else ("thay đổi" if "thay đổi" in old_state else "")
                    )
                    new_state = (
                        ("Chờ nhân sự " + stem).strip()
                        if require_hr and is_direct_manager
                        else ("Đã hủy" if stem == "hủy" else "Đã duyệt")
                    )
                    db.execute(
                        "UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id)
                    )
                    if new_state.startswith("Chờ nhân sự"):
                        _leave_notify(
                            employee_id, leave_id, "Quản lý đã duyệt; đơn đang chờ nhân sự."
                        )
                    else:
                        db.execute(
                            "UPDATE NghiPhep SET NgayCuTu=NULL,NgayCuDen=NULL,SoNgayCu=NULL,LoaiCu=NULL WHERE MaNP=?",
                            (leave_id,),
                        )
                        _leave_notify(
                            employee_id,
                            leave_id,
                            "Đơn nghỉ đã được hủy."
                            if new_state == "Đã hủy"
                            else "Đơn nghỉ đã được duyệt.",
                        )
                else:
                    new_state = "Đã hủy" if "hủy" in old_state else "Đã duyệt"
                    db.execute(
                        "UPDATE NghiPhep SET TrangThai=?,PhanHoi=?,NgayCuTu=NULL,NgayCuDen=NULL,SoNgayCu=NULL,LoaiCu=NULL WHERE MaNP=?",
                        (new_state, request.form.get("PhanHoi", "").strip()[:1000], leave_id),
                    )
                    _leave_notify(
                        employee_id,
                        leave_id,
                        "Đơn nghỉ đã được hủy."
                        if new_state == "Đã hủy"
                        else "Đơn nghỉ đã được nhân sự duyệt.",
                    )
                _leave_audit(
                    leave_id,
                    employee_id,
                    action,
                    old_state,
                    new_state,
                    request.form.get("PhanHoi", ""),
                    actor,
                )
                flash("Đã cập nhật trạng thái đơn nghỉ.", "success")
            elif action == "withdraw":
                leave_id = int(request.form["id"])
                item = db.query(
                    "SELECT MaNV,TrangThai,TuNgay,DenNgay FROM NghiPhep WHERE MaNP=?", (leave_id,)
                )[1]
                if not item or item[0][0] != own_id:
                    raise ValueError("Không tìm thấy đơn của bạn.")
                employee_id, old_state, start, end = item[0]
                if old_state in (
                    "Chờ quản lý",
                    "Chờ nhân sự",
                    "Chờ quản lý thay đổi",
                    "Chờ nhân sự thay đổi",
                ):
                    if old_state.endswith("thay đổi"):
                        change = db.query(
                            "SELECT NgayCuTu,NgayCuDen,SoNgayCu,LoaiCu FROM NghiPhep WHERE MaNP=?",
                            (leave_id,),
                        )[1][0]
                        if change[0]:
                            db.execute(
                                "UPDATE NghiPhep SET TuNgay=?,DenNgay=?,SoNgay=?,LoaiNghi=?,TrangThai=N'Đã duyệt',NgayCuTu=NULL,NgayCuDen=NULL,SoNgayCu=NULL,LoaiCu=NULL WHERE MaNP=?",
                                (*change, leave_id),
                            )
                            new_state = "Đã duyệt"
                        else:
                            new_state = "Đã rút"
                            db.execute(
                                "UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?",
                                (new_state, leave_id),
                            )
                    else:
                        new_state = "Đã rút"
                        db.execute(
                            "UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id)
                        )
                elif old_state in ("Chờ quản lý hủy", "Chờ nhân sự hủy"):
                    new_state = "Đã duyệt"
                    db.execute(
                        "UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id)
                    )
                elif old_state == "Đã duyệt":
                    manager = db.scalar(
                        "SELECT MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (employee_id,)
                    )
                    new_state = (
                        "Chờ quản lý hủy" if require_manager and manager else "Chờ nhân sự hủy"
                    )
                else:
                    raise ValueError("Đơn này không thể rút hoặc hủy ở trạng thái hiện tại.")
                db.execute("UPDATE NghiPhep SET TrangThai=? WHERE MaNP=?", (new_state, leave_id))
                _leave_audit(
                    leave_id,
                    employee_id,
                    "withdraw",
                    old_state,
                    new_state,
                    "Nhân viên yêu cầu rút/hủy đơn",
                    actor,
                )
                _leave_notify(
                    employee_id, leave_id, f"Yêu cầu rút/hủy đơn đang ở trạng thái {new_state}."
                )
                if new_state == "Chờ quản lý hủy":
                    _leave_notify(
                        manager,
                        leave_id,
                        f"Có yêu cầu hủy đơn đã duyệt ({start}–{end}) cần bạn xem xét.",
                    )
                flash("Đã ghi nhận yêu cầu rút/hủy đơn.", "success")
            elif action == "change":
                leave_id = int(request.form["id"])
                item = db.query(
                    "SELECT MaNV,TuNgay,DenNgay,SoNgay,LoaiNghi,TrangThai FROM NghiPhep WHERE MaNP=?",
                    (leave_id,),
                )[1]
                if not item or item[0][0] != own_id:
                    raise ValueError("Không tìm thấy đơn của bạn.")
                employee_id, old_start, old_end, old_days, old_type, old_state = item[0]
                if old_state not in ("Chờ quản lý", "Chờ nhân sự", "Đã duyệt"):
                    raise ValueError("Đơn ở trạng thái hiện tại không thể thay đổi.")
                start, end = (
                    date.fromisoformat(request.form["TuNgay"]),
                    date.fromisoformat(request.form["DenNgay"]),
                )
                leave_type, reason = (
                    request.form.get("LoaiNghi", ""),
                    request.form.get("LyDo", "").strip(),
                )
                days = _leave_days(employee_id, start, end)
                if (
                    end < start
                    or start.year != end.year
                    or not days
                    or leave_type not in LEAVE_TYPES
                ):
                    raise ValueError("Ngày, lịch làm việc hoặc loại nghỉ không hợp lệ.")
                if db.scalar(
                    "SELECT COUNT(*) FROM NghiPhep WHERE MaNV=? AND MaNP<>? AND TrangThai NOT IN (N'Từ chối',N'Đã rút',N'Đã hủy') AND ((TuNgay<=? AND DenNgay>=?) OR (NgayCuTu<=? AND NgayCuDen>=?))",
                    (employee_id, leave_id, end, start, end, start),
                ):
                    raise ValueError("Khoảng ngày mới bị trùng một đơn đang hiệu lực.")
                if leave_type == "Phép năm":
                    allocated, carry, used, pending = _leave_quota(employee_id, start.year)
                    reusable_days = (
                        old_days if old_type == "Phép năm" and old_start.year == start.year else 0
                    )
                    available = allocated + carry - used - pending + reusable_days
                    if days > available:
                        raise ValueError(
                            f"Quỹ phép năm còn {max(0, available):g} ngày, không đủ cho thay đổi này."
                        )
                if len(reason) > 255:
                    raise ValueError("Lý do nghỉ tối đa 255 ký tự.")
                manager = db.scalar(
                    "SELECT MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (employee_id,)
                )
                if require_manager and not manager:
                    raise ValueError("Chưa gán quản lý trực tiếp cho nhân viên.")
                state = (
                    "Chờ quản lý thay đổi"
                    if require_manager
                    else ("Chờ nhân sự thay đổi" if require_hr else "Đã duyệt")
                )
                _update_leave_request(
                    leave_id,
                    employee_id,
                    start,
                    end,
                    days,
                    reason,
                    leave_type,
                    state,
                    old_state,
                    old_start,
                    old_end,
                    old_days,
                    old_type,
                    actor,
                )
                _leave_notify(
                    employee_id,
                    leave_id,
                    f"Đã ghi nhận yêu cầu thay đổi ngày nghỉ; trạng thái: {state}.",
                )
                if state.startswith("Chờ quản lý"):
                    _leave_notify(
                        manager, leave_id, "Có yêu cầu thay đổi ngày nghỉ cần bạn xem xét."
                    )
                flash("Đã gửi yêu cầu thay đổi ngày nghỉ.", "success")
            else:
                raise ValueError("Thao tác nghỉ phép không hợp lệ hoặc bạn không đủ quyền.")
        except Exception as e:
            flash(_safe_error(e), "error")
        return redirect(url_for("leave.nghiphep"))

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
        manager_rows = (
            db.query(
                "SELECT p.MaNP,n.HoTen,p.TuNgay,p.DenNgay,p.SoNgay,p.LoaiNghi,p.LyDo,p.TrangThai,p.PhanHoi FROM NghiPhep p JOIN NhanVien n ON n.MaNV=p.MaNV JOIN QuanLyTrucTiep q ON q.MaNV=p.MaNV WHERE q.MaQuanLy=? AND p.TrangThai LIKE N'Chờ quản lý%' ORDER BY p.MaNP DESC",
                (own_id,),
            )[1]
            if manager_role and own_id
            else []
        )
        if leave_admin:
            manager_map = {
                row[0]: row[1]
                for row in db.query("SELECT MaNV,MaQuanLy FROM QuanLyTrucTiep", ())[1]
            }
        elif manager_role and own_id:
            manager_map = {
                row[0]: row[1]
                for row in db.query(
                    "SELECT MaNV,MaQuanLy FROM QuanLyTrucTiep WHERE MaQuanLy=? OR MaNV=?",
                    (own_id, own_id),
                )[1]
            }
        else:
            manager_map = (
                {
                    row[0]: row[1]
                    for row in db.query(
                        "SELECT MaNV,MaQuanLy FROM QuanLyTrucTiep WHERE MaNV=?", (own_id,)
                    )[1]
                }
                if own_id
                else {}
            )
        schedules, quotas = {}, {}
        if leave_admin:
            for employee, day in db.query("SELECT MaNV,Thu FROM LichLamViecNhanVien", ())[1]:
                schedules.setdefault(employee, set()).add(day)
            quota_base = {
                employee: (float(allocated), float(carry))
                for employee, allocated, carry in db.query(
                    "SELECT MaNV,SoNgayCap,SoNgayChuyen FROM QuyPhepNam WHERE Nam=?",
                    (date.today().year,),
                )[1]
            }
            quota_used = {
                employee: float(days or 0)
                for employee, days in db.query(
                    "SELECT MaNV,ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0) FROM NghiPhep WHERE ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy')) OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL)) AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=? GROUP BY MaNV",
                    (date.today().year,),
                )[1]
            }
            quota_pending = {
                employee: float(days or 0)
                for employee, days in db.query(
                    f"SELECT MaNV,{_LEAVE_PENDING_DAYS} FROM NghiPhep WHERE LoaiNghi=N'Phép năm' AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND YEAR(TuNgay)=? GROUP BY MaNV",
                    (date.today().year,),
                )[1]
            }
            quotas = {
                employee: (
                    *quota_base.get(employee, (0, 0)),
                    quota_used.get(employee, 0),
                    quota_pending.get(employee, 0),
                )
                for employee, _, _ in people
            }
        elif own_id:
            quotas[own_id] = _leave_quota(own_id, date.today().year)
        notices = (
            db.query(
                "SELECT TOP 30 MaTB,MaNP,NoiDung,TaoLuc,DaDoc FROM ThongBaoNghiPhep WHERE MaNV=? ORDER BY MaTB DESC",
                (own_id,),
            )[1]
            if own_id
            else []
        )
        policy = (False, True)
        available_managers = (
            db.query(
                "SELECT n.MaNV,n.HoTen FROM NhanVien n JOIN TaiKhoan t "
                "ON t.MaNV=n.MaNV AND t.MaVaiTro=3 AND t.TrangThai=1 "
                "WHERE n.TrangThai=N'Đang làm' ORDER BY n.HoTen"
            )[1]
            if has_permission("leave.manage_policy")
            else []
        )
    except Exception as e:
        people, manager_rows, manager_map, schedules, quotas, notices = [], [], {}, {}, {}, []
        cols, rows = [], []
        policy, available_managers = (False, True), []
        flash(_safe_error(e, "Không tải được dữ liệu nghỉ phép."), "error")
    balance = quotas.get(own_id, (0, 0, 0, 0))
    current_year = date.today().year
    default_work_days = set(range(7)) - set(config.NGAY_NGHI_TUAN)
    return render_template(
        "leave/leave.html",
        people=people,
        cols=cols,
        rows=rows,
        admin=leave_admin,
        manager_rows=manager_rows,
        manager_map=manager_map,
        schedules=schedules,
        quotas=quotas,
        notices=notices,
        policy=policy,
        available_managers=available_managers,
        leave_types=LEAVE_TYPES,
        own_id=own_id,
        balance=balance,
        current_year=current_year,
        default_work_days=default_work_days,
        leave_days=list(
            enumerate(("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"))
        ),
    )
