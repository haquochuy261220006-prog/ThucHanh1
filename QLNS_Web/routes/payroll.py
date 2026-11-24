from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from datetime import date, timedelta
import config
import json
import math
import sensitive_audit
from config import CONG_CHUAN
from database import db
from payroll_engine import (
    calculate_night_hours,
    calculate_night_premium,
    calculate_overtime_pay,
    calculate_statutory_payroll,
    effective_salary_for_period,
    merge_intervals,
    resolve_overtime_intervals,
    validate_policy,
)
from web_auth import login_required
from services.common_service import _parse_iso_date, _safe_error, has_permission, payroll_staff
from services.payroll_service import (apply_month_rules, approve_period, calculate_payroll, get_period_status, invalidate_period, lock_period, reopen_period, summarize_attendance, summarize_attendance_event_hours, summarize_attendance_intervals, touch_period)

bp = Blueprint('payroll', __name__)


@bp.route("/luong/phieu-cua-toi")
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


@bp.route("/luong/phieu/<int:manv>/<int:year>/<int:month>")
@login_required
def salary_slip(manv, year, month):
    if not has_permission("payroll.view") and (session["user"].get("manv") or -1) != manv:
        return "Bạn không có quyền xem phiếu lương này.", 403
    return _salary_slip_response(manv, year, month)


@bp.route("/luong", methods=["GET", "POST"])
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
    period_state_rows = db.query(
        "SELECT TinhLuc FROM LuongKy WHERE Nam=? AND Thang=?", (year, month)
    )[1]
    period_calculated_at = period_state_rows[0][0] if period_state_rows else None
    if request.method == "POST":
        try:
            action = request.form.get("action")
            action_permission = {
                "approve": "payroll.approve",
                "lock": "payroll.lock",
                "reopen": "payroll.reopen",
                "calculate": "payroll.calculate",
                "delete": "payroll.delete",
                "adjust": "payroll.edit",
                "adjust_common": "payroll.edit",
                "adjust_extra_bonus": "payroll.edit",
                "policy_draft": "payroll.edit",
                "policy_approve": "payroll.approve",
                "profile_save": "payroll.edit",
                "item_add": "payroll.edit",
                "item_delete": "payroll.edit",
            }.get(action)
            if not action_permission or not has_permission(action_permission):
                return "Bạn không có quyền thực hiện thao tác bảng lương này.", 403
            if active_policy and action in {"adjust_common", "adjust_extra_bonus", "adjust"}:
                raise ValueError(
                    "Kỳ này đã có chính sách lương phiên bản. Hãy sửa khoản đầu vào rồi tính lại kỳ nháp để đồng bộ thuế và bảo hiểm."
                )
            if (
                action
                in {
                    "delete",
                    "adjust_common",
                    "adjust_extra_bonus",
                    "adjust",
                    "calculate",
                    "profile_save",
                    "item_add",
                    "item_delete",
                }
                and period_status != "Nháp"
            ):
                raise ValueError("Kỳ lương đã được duyệt hoặc khóa; không thể sửa hoặc tính lại.")
            if action == "policy_draft":
                policy_name = request.form.get("TenChinhSach", "").strip()
                source = request.form.get("CanCu", "").strip()
                effective = _parse_iso_date(request.form.get("NgayHieuLuc"), "Ngày hiệu lực")
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
                    (
                        policy_name,
                        effective,
                        json.dumps(policy_json, ensure_ascii=False),
                        source,
                        session["user"]["user"],
                    ),
                )
                db.execute(
                    "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriMoi,LyDo,NguoiThucHien) VALUES(NULL,?,?,N'Tạo bản nháp chính sách lương',?,?,?)",
                    (
                        effective.month,
                        effective.year,
                        json.dumps(
                            {"ten": policy_name, "hieu_luc": effective, "quy_tac": policy_json},
                            ensure_ascii=False,
                            default=str,
                        ),
                        source,
                        session["user"]["user"],
                    ),
                )
                flash(
                    "Đã lưu bản nháp chính sách lương. Bản nháp chưa được dùng để tính lương.",
                    "success",
                )
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
                    (approval_reason, session["user"]["user"], policy_id),
                )
                db.execute(
                    "UPDATE k SET TinhLuc=NULL,TinhBoi=?,PhienBan=PhienBan+1 FROM LuongKy k WHERE (k.Nam*100+k.Thang)>=(SELECT YEAR(NgayHieuLuc)*100+MONTH(NgayHieuLuc) FROM PayrollPolicyVersion WHERE MaChinhSach=?) AND k.TrangThai=N'Nháp' AND EXISTS(SELECT 1 FROM Luong l WHERE l.Nam=k.Nam AND l.Thang=k.Thang)",
                    (session["user"]["user"], policy_id),
                )
                flash(
                    "Đã duyệt chính sách. Chính sách chỉ áp dụng cho kỳ bắt đầu từ ngày hiệu lực.",
                    "success",
                )
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
                    (
                        employee_id,
                        effective,
                        int(resident_value),
                        dependents,
                        int(insurance_value),
                        insurance_base,
                        session["user"]["user"],
                        employee_id,
                        effective,
                        employee_id,
                        effective,
                        int(resident_value),
                        dependents,
                        int(insurance_value),
                        insurance_base,
                        session["user"]["user"],
                    ),
                )
                db.execute(
                    "UPDATE k SET TinhLuc=NULL,TinhBoi=?,PhienBan=PhienBan+1 FROM LuongKy k WHERE (k.Nam*100+k.Thang)>=(YEAR(?)*100+MONTH(?)) AND k.TrangThai=N'Nháp' AND EXISTS(SELECT 1 FROM Luong l WHERE l.MaNV=? AND l.Nam=k.Nam AND l.Thang=k.Thang)",
                    (session["user"]["user"], effective, effective, employee_id),
                )
                db.execute(
                    "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,N'Cập nhật hồ sơ thuế/bảo hiểm',?,?,?)",
                    (
                        employee_id,
                        month,
                        year,
                        json.dumps(
                            {
                                "hieu_luc": effective,
                                "cu_tru": bool(int(resident_value)),
                                "nguoi_phu_thuoc": dependents,
                                "tham_gia_bao_hiem": bool(int(insurance_value)),
                                "luong_tinh_bao_hiem": insurance_base,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                        "Cập nhật hồ sơ người lao động",
                        session["user"]["user"],
                    ),
                )
                flash("Đã lưu hồ sơ thuế/bảo hiểm có hiệu lực theo ngày đã chọn.", "success")
            elif action == "item_add":
                employee_id = int(request.form.get("MaNV", ""))
                amount = int(request.form.get("SoTien", ""))
                item_type = request.form.get("Loai", "")
                name = request.form.get("TenKhoan", "").strip()
                reason = _payroll_reason()
                if (
                    item_type not in ("earning", "reduction", "deduction")
                    or amount < 0
                    or not name
                    or len(name) > 120
                ):
                    raise ValueError("Loại, tên hoặc số tiền khoản lương không hợp lệ.")
                db.execute(
                    "INSERT INTO PayrollItem(MaNV,Nam,Thang,Loai,Ten,SoTien,ChiuThue,CanCuBaoHiem,DuocTruThue,LyDo,NguoiTao) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        employee_id,
                        year,
                        month,
                        item_type,
                        name,
                        amount,
                        int(request.form.get("ChiuThue") == "on"),
                        int(request.form.get("CanCuBaoHiem") == "on"),
                        int(request.form.get("DuocTruThue") == "on"),
                        reason,
                        session["user"]["user"],
                    ),
                )
                db.execute(
                    "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,N'Thêm khoản lương',?,?,?)",
                    (
                        employee_id,
                        year,
                        month,
                        json.dumps(
                            {
                                "loai": item_type,
                                "ten": name,
                                "so_tien": amount,
                                "chiu_thue": request.form.get("ChiuThue") == "on",
                                "can_cu_bao_hiem": request.form.get("CanCuBaoHiem") == "on",
                                "duoc_tru_thue": request.form.get("DuocTruThue") == "on",
                            },
                            ensure_ascii=False,
                        ),
                        reason,
                        session["user"]["user"],
                    ),
                )
                invalidate_period(db, year, month, session["user"]["user"])
                flash("Đã thêm khoản lương cho kỳ nháp.", "success")
            elif action == "item_delete":
                item_id = int(request.form.get("MaKhoan", ""))
                reason = _payroll_reason()
                old_item = db.query(
                    "SELECT MaNV,Loai,Ten,SoTien FROM PayrollItem WHERE MaKhoan=? AND Nam=? AND Thang=?",
                    (item_id, year, month),
                )[1]
                if not old_item:
                    raise ValueError("Không tìm thấy khoản lương trong kỳ đã chọn.")
                db.execute(
                    "DELETE FROM PayrollItem WHERE MaKhoan=? AND Nam=? AND Thang=?",
                    (item_id, year, month),
                )
                employee_id, old_type, old_name, old_amount = old_item[0]
                db.execute(
                    "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,LyDo,NguoiThucHien) VALUES(?,?,?,N'Xóa khoản lương',?,?,?)",
                    (
                        employee_id,
                        year,
                        month,
                        json.dumps(
                            {"loai": old_type, "ten": old_name, "so_tien": old_amount},
                            ensure_ascii=False,
                            default=str,
                        ),
                        reason,
                        session["user"]["user"],
                    ),
                )
                invalidate_period(db, year, month, session["user"]["user"])
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
                flash(
                    "Đã mở lại kỳ lương để điều chỉnh. Hãy tính lại và gửi duyệt lần nữa.",
                    "success",
                )
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
                        payroll_id,
                        month,
                        year,
                        manv,
                        month,
                        year,
                        "Xóa dòng lương",
                        json.dumps(
                            {"LuongCB": old_base, "ThuongThem": old_bonus, "TongLuong": old_total},
                            ensure_ascii=False,
                            default=str,
                        ),
                        None,
                        reason,
                        session["user"]["user"],
                    ),
                )
                touch_period(db, year, month, session["user"]["user"])
                flash("Đã xóa dòng lương.", "success")
            elif action == "adjust_common":
                reason = _payroll_reason()
                old_rules = {"TyLeThuongCC": bonus_rate * 100, "HeSoTangCa": overtime_factor}
                try:
                    bonus_rate = float(request.form.get("TyLeThuongCC", "")) / 100
                except (TypeError, ValueError):
                    raise ValueError(
                        "Vui lòng nhập phần trăm thưởng chuyên cần hợp lệ."
                    )
                if not math.isfinite(bonus_rate) or not 0 <= bonus_rate <= 1:
                    raise ValueError("Tỷ lệ thưởng chuyên cần phải từ 0% đến 100%.")
                overtime_factor = config.HE_SO_TANG_CA
                apply_month_rules(
                    db,
                    year,
                    month,
                    bonus_rate,
                    overtime_factor,
                    old_rules,
                    reason,
                    session["user"]["user"],
                )
                flash(
                    "Đã áp dụng mức thưởng chuyên cần và hệ số tăng ca chung cho bảng lương tháng này.",
                    "success",
                )
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
                    "SELECT MaNV,LuongCB,NgayCong,GioTangCa,SoLanMuon,SoNgayNghiKP,ISNULL(ThuongThem,0),TienTangCa FROM Luong WHERE MaLuong=? AND Thang=? AND Nam=?",
                    (payroll_id, month, year),
                )[1]
                if not row:
                    raise ValueError("Không tìm thấy dòng lương trong kỳ đã chọn.")
                manv, base_salary, days, overtime_hours, late_count, unpaid_days, old_bonus, overtime_pay = row[0]
                total = calculate_payroll(
                    base_salary,
                    days,
                    overtime_hours,
                    late_count,
                    unpaid_days,
                    bonus_rate,
                    overtime_factor,
                    extra_bonus,
                    overtime_pay_override=overtime_pay,
                )[-1]
                db.execute(
                    "SET XACT_ABORT ON; BEGIN TRAN; UPDATE Luong SET ThuongThem=?,TongLuong=? WHERE MaLuong=? AND Thang=? AND Nam=?; INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,?,?,?,?,?); COMMIT;",
                    (
                        extra_bonus,
                        total,
                        payroll_id,
                        month,
                        year,
                        manv,
                        month,
                        year,
                        "Điều chỉnh thưởng thêm",
                        str(old_bonus),
                        str(extra_bonus),
                        reason,
                        session["user"]["user"],
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
                    "SELECT MaNV,LuongCB,NgayCong,GioTangCa,SoLanMuon,SoNgayNghiKP,ThuongThem,TienTangCa FROM Luong WHERE MaLuong=? AND Thang=? AND Nam=?",
                    (payroll_id, month, year),
                )[1]
                if not row:
                    raise ValueError("Không tìm thấy dòng lương cần điều chỉnh.")
                (
                    manv,
                    old_base_salary,
                    days,
                    overtime_hours,
                    late_count,
                    unpaid_days,
                    extra_bonus,
                    old_overtime_pay,
                ) = row[0]
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
                    overtime_pay_override=(
                        round(old_overtime_pay * base_salary / old_base_salary)
                        if old_base_salary
                        else 0
                    ),
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
                    payroll_items_by_employee.setdefault(int(item[0]), []).append(
                        {
                            "kind": item[1],
                            "name": item[2],
                            "amount": item[3],
                            "taxable": bool(item[4]),
                            "insurable": bool(item[5]),
                            "tax_deductible": bool(item[6]),
                        }
                    )
                employee_profiles_by_id = {}
                if rules:
                    profiles = db.query(
                        "WITH Ranked AS (SELECT MaNV,LaCuTru,NguoiPhuThuoc,ThamGiaBaoHiem,LuongTinhBaoHiem,ROW_NUMBER() OVER(PARTITION BY MaNV ORDER BY TuNgay DESC) AS rn FROM PayrollEmployeeTaxProfile WHERE TuNgay<=?) SELECT MaNV,LaCuTru,NguoiPhuThuoc,ThamGiaBaoHiem,LuongTinhBaoHiem FROM Ranked WHERE rn=1",
                        (first,),
                    )[1]
                    employee_profiles_by_id = {int(r[0]): r[1:] for r in profiles}
                event_hours_by_employee = summarize_attendance_event_hours(db, year, month)
                attendance_intervals_by_employee = summarize_attendance_intervals(db, year, month)
                overtime_by_employee = {}
                overtime_rows = db.query(
                    "SELECT MaNV,BatDau,KetThuc,SoGioThucTe FROM TangCaYeuCau WHERE TrangThai=N'Đã xác nhận' AND XacNhanLuc IS NOT NULL AND BatDau>=? AND BatDau<?",
                    (first, date(year + (month == 12), month % 12 + 1, 1)),
                )[1]
                for employee_id, start, end, actual_hours in overtime_rows:
                    overtime_by_employee.setdefault(int(employee_id), []).append(
                        (start, end, float(actual_hours or 0))
                    )
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
                    leave_reconciliation_by_employee.setdefault(int(r[0]), []).append(
                        {
                            "from": r[1],
                            "to": r[2],
                            "days_recorded": r[3],
                            "type": r[4],
                        }
                    )
                shifts_by_employee = {}
                for employee_id, work_date, start_time, grace in db.query(
                    "SELECT p.MaNV,p.Ngay,COALESCE(p.GioBatDauOverride,c.GioBatDau),c.PhutAnHan FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.Ngay>=? AND p.Ngay<?",
                    (first, date(year + (month == 12), month % 12 + 1, 1)),
                )[1]:
                    shifts_by_employee.setdefault(employee_id, {}).setdefault(work_date, []).append(
                        (start_time, grace)
                    )
                weekdays_by_employee = {}
                for employee_id, weekday in db.query("SELECT MaNV,Thu FROM LichLamViecNhanVien")[1]:
                    weekdays_by_employee.setdefault(employee_id, set()).add(weekday)
                holidays = {
                    row[0]
                    for row in db.query(
                        "SELECT Ngay FROM LichNgayLe WHERE Ngay>=? AND Ngay<?",
                        (
                            first - timedelta(days=1),
                            date(year + (month == 12), month % 12 + 1, 1)
                            + timedelta(days=1),
                        ),
                    )[1]
                }
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
                    r["gio_tang_ca"] = float(
                        db.scalar(
                            "SELECT ISNULL(SUM(SoGioThucTe),0) FROM TangCaYeuCau WHERE MaNV=? AND TrangThai=N'Đã xác nhận' AND XacNhanLuc IS NOT NULL AND BatDau>=CAST(? AS DATETIME2) AND BatDau<CAST(? AS DATETIME2)",
                            (manv, first, next_month),
                        )
                        or 0
                    )
                    employee_attendance_intervals = attendance_intervals_by_employee.get(
                        int(manv), []
                    )
                    overtime_intervals = resolve_overtime_intervals(
                        overtime_by_employee.get(int(manv), []), employee_attendance_intervals
                    )
                    r["gio_tang_ca"] = round(
                        sum((end - start).total_seconds() for start, end in overtime_intervals)
                        / 3600,
                        2,
                    )
                    standard_workdays = (
                        active_policy_rules["standard_workdays_per_month"]
                        if active_policy_rules
                        else (config.CONG_CHUAN if config.CONG_CHUAN in (22, 26) else 22)
                    )
                    work_weekdays = weekdays_by_employee.get(manv)
                    if work_weekdays is None:
                        work_weekdays = set(range(7)) - set(config.NGAY_NGHI_TUAN)
                    overtime_rates = (
                        active_policy_rules.get("overtime_rates") if active_policy_rules else None
                    )
                    overtime_pay = calculate_overtime_pay(
                        luong_cb,
                        overtime_intervals,
                        standard_workdays=standard_workdays,
                        hours_per_workday=(
                            active_policy_rules.get("hours_per_workday", 8)
                            if active_policy_rules
                            else config.GIO_LAM_NGAY
                        ),
                        work_weekdays=work_weekdays,
                        holidays=holidays,
                        rates=overtime_rates,
                    )
                    all_work_intervals = merge_intervals(
                        employee_attendance_intervals + overtime_intervals
                    )
                    night_hours = calculate_night_hours(all_work_intervals)
                    night_premium = calculate_night_premium(
                        luong_cb,
                        night_hours,
                        standard_workdays,
                        hours_per_workday=(
                            active_policy_rules.get("hours_per_workday", 8)
                            if active_policy_rules
                            else config.GIO_LAM_NGAY
                        ),
                        rate=(overtime_rates or {}).get("night"),
                    )
                    extra_bonus = previous[1] if previous and previous[1] is not None else 0
                    (
                        attendance_bonus,
                        overtime_total,
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
                        overtime_pay_override=overtime_pay,
                        night_premium=night_premium,
                        standard_workdays=standard_workdays,
                        hours_per_workday=active_policy_rules["hours_per_workday"]
                        if active_policy_rules
                        else None,
                        attendance_bonus_min_days=active_policy_rules["attendance_bonus_min_days"]
                        if active_policy_rules
                        else None,
                    )
                    vals = (
                        r["ngay_di_lam"],
                        luong_cb or 0,
                        attendance_bonus + overtime_total,
                        deductions,
                        total,
                        attendance_bonus,
                        r["gio_tang_ca"],
                        overtime_total,
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
                            raise ValueError(
                                f"Nhân viên mã {manv} chưa có hồ sơ cư trú, người phụ thuộc và bảo hiểm có hiệu lực từ {first:%d/%m/%Y}."
                            )
                        resident, dependents, insurance_subject, insurance_base = profile
                        vals = list(vals)
                        vals[2] = int(
                            vals[2]
                            + sum(
                                int(item["amount"]) * (-1 if item["kind"] == "reduction" else 1)
                                for item in additional_items
                                if item["kind"] != "deduction"
                            )
                        )
                        vals[3] = int(
                            vals[3]
                            + sum(
                                int(item["amount"])
                                for item in additional_items
                                if item["kind"] == "deduction"
                            )
                        )
                        component_items = []
                        for component_name, amount in (
                            ("attendance_bonus", attendance_bonus),
                            ("overtime", overtime_total),
                            ("extra_bonus", extra_bonus or 0),
                        ):
                            flags = rules["components"][component_name]
                            component_items.append(
                                {
                                    "kind": "earning",
                                    "amount": amount,
                                    "taxable": flags["taxable"],
                                    "insurable": flags["insurable"],
                                }
                            )
                        deduction_flags = rules["components"]["payroll_deductions"]
                        component_items.append(
                            {
                                "kind": "reduction",
                                "amount": deductions,
                                "taxable": deduction_flags["taxable"],
                                "insurable": deduction_flags["insurable"],
                            }
                        )
                        component_items.extend(additional_items)
                        statutory = calculate_statutory_payroll(
                            base_salary=luong_cb,
                            items=component_items,
                            policy=rules,
                            tax_resident=bool(resident),
                            dependents=dependents,
                            insurance_subject=bool(insurance_subject),
                            insurance_base=insurance_base,
                        )
                        vals[4] = int(statutory["gross"])
                        vals.extend(
                            (
                                int(statutory["personal_income_tax"]),
                                int(statutory["employee_contributions"].get("bhxh", 0)),
                                int(statutory["employee_contributions"].get("bhyt", 0)),
                                int(statutory["employee_contributions"].get("bhtn", 0)),
                                int(statutory["employer_contributions"].get("bhxh", 0)),
                                int(statutory["employer_contributions"].get("bhyt", 0)),
                                int(statutory["employer_contributions"].get("bhtn", 0)),
                                int(statutory["employer_contributions"].get("tnld_bnn", 0)),
                                int(statutory["net"]),
                            )
                        )
                        vals = tuple(vals)
                        statutory_snapshots.append(
                            (
                                int(manv),
                                json.dumps(
                                    {
                                        "base_salary": luong_cb,
                                        "attendance_days": r["ngay_di_lam"],
                                        "scheduled_shifts": [
                                            {
                                                "date": work_day,
                                                "start": shift_start,
                                                "grace_minutes": grace,
                                            }
                                            for work_day, shifts in shifts_by_employee.get(
                                                int(manv), {}
                                            ).items()
                                            for shift_start, grace in shifts
                                        ],
                                        "holiday_dates": sorted(holidays),
                                        "overtime_approved_hours": r["gio_tang_ca"],
                                        "overtime_intervals": [
                                            {"start": start, "end": end}
                                            for start, end in overtime_intervals
                                        ],
                                        "event_hours_reconciliation": event_hours_by_employee.get(
                                            manv, 0
                                        ),
                                        "attendance_bonus": attendance_bonus,
                                        "overtime_pay": overtime_pay,
                                        "night_hours": str(night_hours),
                                        "night_premium": int(night_premium),
                                        "unpaid_and_late_deductions": deductions,
                                        "extra_bonus": extra_bonus or 0,
                                        "approved_leave_entries": leave_reconciliation_by_employee.get(
                                            int(manv), []
                                        ),
                                        "profile": {
                                            "tax_resident": bool(resident),
                                            "dependents": dependents,
                                            "insurance_subject": bool(insurance_subject),
                                            "insurance_base": insurance_base,
                                        },
                                        "additional_items": payroll_items_by_employee.get(
                                            int(manv), []
                                        ),
                                    },
                                    ensure_ascii=False,
                                    default=str,
                                ),
                                json.dumps(
                                    {
                                        key: (dict(value) if isinstance(value, dict) else value)
                                        for key, value in statutory.items()
                                    },
                                    ensure_ascii=False,
                                    default=str,
                                ),
                            )
                        )
                    else:
                        vals = list(vals)
                        vals[2] = int(
                            vals[2]
                            + sum(
                                int(item["amount"]) * (-1 if item["kind"] == "reduction" else 1)
                                for item in additional_items
                                if item["kind"] != "deduction"
                            )
                        )
                        vals[3] = int(
                            vals[3]
                            + sum(
                                int(item["amount"])
                                for item in additional_items
                                if item["kind"] == "deduction"
                            )
                        )
                        vals[4] = int(
                            vals[4]
                            + sum(
                                int(item["amount"]) * (-1 if item["kind"] == "reduction" else 1)
                                for item in additional_items
                                if item["kind"] != "deduction"
                            )
                        )
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
                    line_ids = {
                        int(row[0]): int(row[1])
                        for row in db.query(
                            "SELECT MaNV,MaLuong FROM Luong WHERE Nam=? AND Thang=?", (year, month)
                        )[1]
                    }
                    snapshot_batches = []
                    for employee_id, inputs_json, result_json in statutory_snapshots:
                        payroll_row_id = line_ids[employee_id]
                        snapshot_batches.append(
                            (
                                payroll_row_id,
                                active_policy[0],
                                active_policy[3],
                                inputs_json,
                                result_json,
                            )
                        )
                    db.execute_batches(
                        [
                            (
                                "IF EXISTS(SELECT 1 FROM PayrollResultSnapshot WHERE MaLuong=?) UPDATE PayrollResultSnapshot SET MaChinhSach=?,QuyTacJson=?,DuLieuDauVaoJson=?,ChiTietTinhJson=?,TaoLuc=SYSUTCDATETIME() WHERE MaLuong=? ELSE INSERT INTO PayrollResultSnapshot(MaLuong,MaChinhSach,QuyTacJson,DuLieuDauVaoJson,ChiTietTinhJson) VALUES(?,?,?,?,?)",
                                [
                                    (
                                        row[0],
                                        row[1],
                                        row[2],
                                        row[3],
                                        row[4],
                                        row[0],
                                        row[0],
                                        row[1],
                                        row[2],
                                        row[3],
                                        row[4],
                                    )
                                    for row in snapshot_batches
                                ],
                            )
                        ]
                    )
                flash(
                    f"Đã tính lương tháng {month}/{year} cho {len(people)} nhân viên."
                    + (
                        " Tháng chưa kết thúc: ngày nghỉ không phép chỉ tính đến hôm qua."
                        if last >= today
                        else ""
                    ),
                    "success",
                )
            return redirect(url_for("payroll.luong", month=month, year=year))
        except Exception as e:
            flash(_safe_error(e, "Không thể xử lý bảng lương lúc này."), "error")
        return redirect(url_for("payroll.luong", month=month, year=year))
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
        snapshot_ids = {
            int(r[0])
            for r in db.query(
                "SELECT s.MaLuong FROM PayrollResultSnapshot s JOIN Luong l ON l.MaLuong=s.MaLuong WHERE l.Thang=? AND l.Nam=?",
                (month, year),
            )[1]
        }
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
        standard=active_policy_rules["standard_workdays_per_month"]
        if active_policy_rules
        else CONG_CHUAN,
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
        policy_employees=db.query(
            "SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen"
        )[1],
        profile_rows=db.query(
            "SELECT p.MaNV,n.HoTen,p.TuNgay,p.LaCuTru,p.NguoiPhuThuoc,p.ThamGiaBaoHiem,p.LuongTinhBaoHiem FROM PayrollEmployeeTaxProfile p JOIN NhanVien n ON n.MaNV=p.MaNV WHERE p.TuNgay=(SELECT MAX(p2.TuNgay) FROM PayrollEmployeeTaxProfile p2 WHERE p2.MaNV=p.MaNV AND p2.TuNgay<=?) ORDER BY n.HoTen",
            (date(year, month, 1),),
        )[1],
        pay_items=db.query(
            "SELECT i.MaKhoan,n.HoTen,i.Loai,i.Ten,i.SoTien,i.ChiuThue,i.CanCuBaoHiem,i.DuocTruThue,i.LyDo FROM PayrollItem i JOIN NhanVien n ON n.MaNV=i.MaNV WHERE i.Nam=? AND i.Thang=? ORDER BY n.HoTen,i.MaKhoan",
            (year, month),
        )[1],
        admin=payroll_staff(),
    )


def _payroll_reason():
    reason = request.form.get("LyDo", "").strip()
    if not reason:
        raise ValueError("Vui lòng nhập lý do điều chỉnh lương.")
    if len(reason) > 500:
        raise ValueError("Lý do điều chỉnh tối đa 500 ký tự.")
    return reason

def _salary_slip_response(manv, year, month):
    if month not in range(1, 13) or year not in range(2000, 2101):
        return "Tháng hoặc năm không hợp lệ.", 400
    state = db.query("SELECT TrangThai FROM LuongKy WHERE Nam=? AND Thang=?", (year, month))[1]
    if not state or state[0][0] != "Đã khóa":
        return "Phiếu lương chỉ được xem sau khi kỳ lương đã khóa.", 403
    rows = db.query(
        "SELECT n.HoTen,n.MaNV,l.Thang,l.Nam,l.NgayCong,l.LuongCB,l.ThuongCC,l.GioTangCa,l.TienTangCa,l.SoLanMuon,l.TruMuon,l.SoNgayNghiKP,l.TruNghiKP,l.ThuongThem,l.TongLuong,l.GioGhiNhan,l.ThueTNCN,l.BHXH_NLD,l.BHYT_NLD,l.BHTN_NLD,l.BHXHDN,l.BHYTDN,l.BHTNDN,l.BH_TNLDBNN_DN,l.LuongThucLinh FROM Luong l JOIN NhanVien n ON n.MaNV=l.MaNV WHERE l.MaNV=? AND l.Thang=? AND l.Nam=?",
        (manv, month, year),
    )[1]
    if not rows:
        return "Không tìm thấy phiếu lương.", 404
    snapshot = db.query(
        "SELECT MaChinhSach,QuyTacJson,DuLieuDauVaoJson,ChiTietTinhJson,TaoLuc FROM PayrollResultSnapshot WHERE MaLuong=(SELECT MaLuong FROM Luong WHERE MaNV=? AND Thang=? AND Nam=?)",
        (manv, month, year),
    )[1]
    calculation_detail = json.loads(snapshot[0][3]) if snapshot else None
    payroll_inputs = json.loads(snapshot[0][2]) if snapshot else None
    taxable_income_display = (
        f"{int(calculation_detail['taxable_income']):,}" if calculation_detail else None
    )
    return render_template(
        "salary_slip.html",
        row=rows[0],
        calculation_snapshot=snapshot[0] if snapshot else None,
        calculation_detail=calculation_detail,
        payroll_inputs=payroll_inputs,
        taxable_income_display=taxable_income_display,
    )
