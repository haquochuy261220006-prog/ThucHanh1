from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from datetime import date
from utils.app_catalog import ATTENDANCE_PROGRESS_SQL, MODULES, REPORTS
from config import CONG_CHUAN
from database import db
from utils.export_utils import _export_response
from utils.permissions import ROLE_LABELS, module_permission
from utils.decorators import login_required
from services import audit_service as sensitive_audit
from services.common_service import _safe_error, admin, has_permission
from services.attendance.attendance_service import today_vietnam
from services.employee_service import _matches_employee_code
from services.reports.report_service import (EXTENDED_REPORTS, PAYROLL_REPORTS, PERSONAL_REPORTS,
    _extended_report_query, _hr_dashboard_summary, _personal_report_query)

bp = Blueprint('reports', __name__)


@bp.get("/api/v1/reports/hr")
def api_v1_hr_summary():
    """Versioned, aggregate-only reporting endpoint for trusted HR consumers."""
    if not session.get("user"):
        return jsonify(
            {"error": {"code": "unauthorized", "message": "Authentication required."}}
        ), 401
    if not has_permission("reports.hr"):
        return jsonify({"error": {"code": "forbidden", "message": "Insufficient permission."}}), 403
    today = today_vietnam()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if year not in range(2000, today.year + 1) or month not in range(1, 13):
            raise ValueError
        summary = _hr_dashboard_summary()
        metrics = {"active_headcount": summary.get("staff", 0)}
        if has_permission("payroll.view"):
            sql, params = _extended_report_query("Chi phí nhân sự (kỳ lương đã khóa)", year, month)
            _, rows = db.query(sql, params)
            metrics["locked_payroll_employer_cost"] = rows[0][1] if rows else 0
        return jsonify(
            {"api_version": "v1", "period": {"year": year, "month": month}, "metrics": metrics}
        )
    except ValueError:
        return jsonify(
            {"error": {"code": "invalid_period", "message": "Year or month is invalid."}}
        ), 400
    except Exception:
        current_app.logger.exception("HR summary API failed")
        return jsonify(
            {"error": {"code": "internal_error", "message": "Unable to load HR summary."}}
        ), 500


@bp.route("/baocao")
@login_required
def baocao():
    can_view_hr = has_permission("reports.hr")
    if not can_view_hr and not any(has_permission(p) for p in ("self.attendance", "self.leave", "self.payroll")):
        return redirect(url_for("dashboard.dashboard"))
    name = request.args.get("name", list(REPORTS)[0])
    report_names = (list(dict.fromkeys([*REPORTS, *EXTENDED_REPORTS])) if can_view_hr else
                    [n for n, p in zip(PERSONAL_REPORTS, ("self.attendance", "self.leave", "self.payroll")) if has_permission(p)])
    if not can_view_hr and name not in report_names:
        name = report_names[0]
    if not can_view_hr and not session.get("user", {}).get("manv"):
        return "Tài khoản chưa được liên kết với hồ sơ nhân viên.", 403
    if name not in report_names:
        name = next(iter(REPORTS))
    if (name in PAYROLL_REPORTS and not has_permission("payroll.view")) or (name == "Lương cá nhân" and not has_permission("self.payroll")):
        return "Bạn không có quyền xem báo cáo quỹ lương.", 403
    today = today_vietnam()
    try:
        month = int(request.args.get("month", today.month))
        year = int(request.args.get("year", today.year))
    except (TypeError, ValueError):
        month, year = today.month, today.year
    if (
        month not in range(1, 13)
        or year not in range(2000, today.year + 1)
        or (name == "Ngày công theo nhân viên" and (year, month) > (today.year, today.month))
    ):
        flash("Tháng hoặc năm báo cáo không hợp lệ.", "error")
        month, year = today.month, today.year
    if name == "Ngày công theo nhân viên":
        first = date(year, month, 1)
        sql = ATTENDANCE_PROGRESS_SQL
        params = (first, first, CONG_CHUAN, CONG_CHUAN)
    elif name in EXTENDED_REPORTS:
        sql, params = _extended_report_query(name, year, month)
    elif name in PERSONAL_REPORTS:
        sql, params = _personal_report_query(name, session["user"]["manv"], year, month)
    else:
        sql, params = REPORTS[name]
    try:
        cols, rows = db.query(sql, params)
        if name == "Lương cá nhân" and rows:
            sensitive_audit.record_many([session["user"]["manv"]], "Luong", "view", session["user"]["user"])
        if name in PAYROLL_REPORTS:
            if name == "Biến động quỹ lương 6 tháng":
                payroll_employee_ids = [r[0] for r in db.query("SELECT DISTINCT l.MaNV FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang WHERE k.TrangThai=N'Đã khóa' AND DATEFROMPARTS(l.Nam,l.Thang,1)>=DATEADD(month,-5,DATEFROMPARTS(?,?,1)) AND DATEFROMPARTS(l.Nam,l.Thang,1)<=DATEFROMPARTS(?,?,1)", (year, month, year, month))[1]]
            else:
                payroll_employee_ids = [r[0] for r in db.query("SELECT MaNV FROM Luong WHERE Nam=? AND Thang=?", (year, month))[1]]
            sensitive_audit.record_many(payroll_employee_ids, "Luong", "view", session["user"]["user"])
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
                "Tỷ lệ vắng mặt": "Tỷ lệ vắng mặt (%)",
                "Chi phí nhân sự (kỳ lương đã khóa)": "Chi phí nhân sự đã khóa",
                "Quỹ lương theo phòng ban": "Tổng trước khấu trừ",
                "Cơ cấu quỹ lương": "Tổng chi phí",
                "Biến động quỹ lương 6 tháng": "Tổng chi phí",
                "Tỷ lệ nghỉ việc": "Tỷ lệ nghỉ việc (%)",
                "Chuyên cần theo phòng ban": "Tỷ lệ chuyên cần (%)",
                "Biến động nhân sự theo phòng ban": "Nghỉ việc",
                "KPI theo phòng ban": "Điểm KPI trung bình",
                "KPI theo nhân viên": "Điểm KPI",
                "Lương cá nhân": "Thực lĩnh",
                "Nghỉ phép cá nhân": "Số ngày",
                "Chấm công cá nhân": "Phút làm việc",
            }
            metric = next(
                (
                    cols.index(preferred[name])
                    for _ in (0,)
                    if preferred.get(name) in cols and cols.index(preferred[name]) in numeric
                ),
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
                        if name in ("Ngày công theo nhân viên", "Tỷ lệ vắng mặt", "Tỷ lệ nghỉ việc", "Chuyên cần theo phòng ban")
                        else f"{value:,.0f}",
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
        "reports/reports.html",
        names=report_names,
        name=name,
        cols=cols,
        rows=rows,
        chart=chart,
        month=month,
        year=year,
        workday_standard=CONG_CHUAN,
        admin=admin(),
    )


@bp.route("/nhat-ky-truy-cap")
@login_required
def sensitive_access_audit():
    if not has_permission("audit.view"):
        return "Chỉ quản trị viên được xem nhật ký truy cập.", 403
    _, rows = db.query(
        "SELECT TOP 500 a.MaNhatKy,a.MaNV,ISNULL(n.HoTen,N'(Hồ sơ đã xóa)'),a.LoaiDuLieu,a.ThaoTac,a.NguoiThucHien,a.TaoLuc "
        "FROM NhatKyTruyCapNhanSu a LEFT JOIN NhanVien n ON n.MaNV=a.MaNV ORDER BY a.TaoLuc DESC,a.MaNhatKy DESC"
    )
    return render_template("reports/sensitive_access_audit.html", rows=rows)


@bp.route("/export/<key>")
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
                rows = [r for r in rows if _matches_employee_code(r, q_)]
            else:
                rows = [
                    r
                    for r in rows
                    if search.casefold()
                    in " ".join("" if value is None else str(value) for value in r).casefold()
                ]
        if key == "nhanvien":
            sensitive_audit.record_many(
                [r[0] for r in rows if r and r[0] is not None],
                ("LienHe", "CCCD", "Luong"),
                "export",
                session["user"]["user"],
            )
        elif key == "hopdong" and rows:
            contract_ids = [r[0] for r in rows if r and r[0] is not None]
            placeholders = ",".join("?" for _ in contract_ids)
            employee_ids = (
                [
                    r[0]
                    for r in db.query(
                        f"SELECT MaNV FROM HopDong WHERE MaHD IN ({placeholders})", contract_ids
                    )[1]
                ]
                if contract_ids
                else []
            )
            sensitive_audit.record_many(employee_ids, "HopDong", "export", session["user"]["user"])
        if key == "nhanvien":
            cols = cols[1:]
            rows = [r[1:] for r in rows]
        filename = key
    elif key == "contract_templates":
        if not has_permission("contracts.export"):
            return "Bạn không có quyền xuất danh sách hợp đồng mẫu.", 403
        cols, rows = db.query(
            "SELECT TenMau AS [Tên mẫu],FileName AS [Tệp],NgayTai AS [Ngày tải],NoiDung AS [Văn bản trích xuất] FROM MauHopDong ORDER BY MaMau DESC"
        )
        filename = "hop_dong_mau"
    elif key == "attendance":
        try:
            selected_day = date.fromisoformat(request.args.get("date", today_vietnam().isoformat()))
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
            cols, rows = db.query(
                sql
                + " JOIN QuanLyTrucTiep q ON q.MaNV=p.MaNV WHERE q.MaQuanLy=? ORDER BY p.MaNP DESC",
                (session["user"]["manv"],),
            )
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
            month = int(request.args.get("month", today_vietnam().month))
            year = int(request.args.get("year", today_vietnam().year))
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
            row[0]
            for row in db.query("SELECT MaNV FROM Luong WHERE Thang=? AND Nam=?", (month, year))[1]
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
        cols, rows = db.query(
            "SELECT t.TenDangNhap AS [Tên đăng nhập],v.TenVaiTro AS [Vai trò],ISNULL(n.HoTen,N'—') AS [Nhân viên],ISNULL(n.MaNVHT,N'—') AS [Mã NV] FROM TaiKhoan t JOIN VaiTro v ON v.MaVaiTro=t.MaVaiTro LEFT JOIN NhanVien n ON n.MaNV=t.MaNV ORDER BY v.MaVaiTro,t.TenDangNhap"
        )
        cols[1] = "Quyền"
        rows = [[row[0], ROLE_LABELS.get(row[1], row[1]), *row[2:]] for row in rows]
        filename = "tai_khoan"
    elif key == "report":
        can_view_hr = has_permission("reports.hr")
        if not can_view_hr and not any(has_permission(p) for p in ("self.attendance_export", "self.leave", "self.payroll")):
            return "Bạn không có quyền xuất báo cáo nhân sự.", 403
        name = request.args.get("name", "")
        if name not in REPORTS and name not in EXTENDED_REPORTS and name not in PERSONAL_REPORTS:
            return "Báo cáo không hợp lệ.", 400
        if not can_view_hr and name not in PERSONAL_REPORTS:
            return "Bạn chỉ có thể xuất báo cáo cá nhân.", 403
        if name in PAYROLL_REPORTS and not has_permission("payroll.export"):
            return "Bạn không có quyền xuất báo cáo quỹ lương.", 403
        if name == "Ngày công theo nhân viên":
            try:
                month = int(request.args.get("month", today_vietnam().month))
                year = int(request.args.get("year", today_vietnam().year))
            except (TypeError, ValueError):
                return "Tháng hoặc năm không hợp lệ.", 400
            if month not in range(1, 13) or year not in range(2000, today_vietnam().year + 1):
                return "Tháng hoặc năm không hợp lệ.", 400
            first = date(year, month, 1)
            cols, rows = db.query(
                ATTENDANCE_PROGRESS_SQL,
                (first, first, CONG_CHUAN, CONG_CHUAN),
            )
            filename = f"bao_cao_ngay_cong_{year}_{month:02d}"
        elif name in EXTENDED_REPORTS:
            try:
                month = int(request.args.get("month", today_vietnam().month))
                year = int(request.args.get("year", today_vietnam().year))
            except (TypeError, ValueError):
                return "Tháng hoặc năm không hợp lệ.", 400
            if month not in range(1, 13) or year not in range(2000, today_vietnam().year + 1):
                return "Tháng hoặc năm không hợp lệ.", 400
            sql, params = _extended_report_query(name, year, month)
            cols, rows = db.query(sql, params)
            filename = f"bao_cao_nhan_su_{year}_{month:02d}"
        elif name in PERSONAL_REPORTS:
            if not session.get("user", {}).get("manv"):
                return "Tài khoản chưa được liên kết với hồ sơ nhân viên.", 403
            personal_permissions = {"Chấm công cá nhân": "self.attendance_export", "Nghỉ phép cá nhân": "self.leave", "Lương cá nhân": "self.payroll"}
            if not has_permission(personal_permissions[name]):
                return "Bạn không có quyền xuất báo cáo này.", 403
            try:
                month = int(request.args.get("month", today_vietnam().month))
                year = int(request.args.get("year", today_vietnam().year))
            except (TypeError, ValueError):
                return "Tháng hoặc năm không hợp lệ.", 400
            if month not in range(1, 13) or year not in range(2000, today_vietnam().year + 1):
                return "Tháng hoặc năm không hợp lệ.", 400
            cols, rows = db.query(*_personal_report_query(name, session["user"]["manv"], year, month))
            if name == "Lương cá nhân" and rows:
                sensitive_audit.record_many([session["user"]["manv"]], "Luong", "export", session["user"]["user"])
            filename = f"bao_cao_ca_nhan_{year}_{month:02d}"
        else:
            sql, params = REPORTS[name]
            cols, rows = db.query(sql, params)
            filename = "bao_cao"
        if name in PAYROLL_REPORTS:
            if name == "Biến động quỹ lương 6 tháng":
                payroll_employee_ids = [r[0] for r in db.query("SELECT DISTINCT l.MaNV FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang WHERE k.TrangThai=N'Đã khóa' AND DATEFROMPARTS(l.Nam,l.Thang,1)>=DATEADD(month,-5,DATEFROMPARTS(?,?,1)) AND DATEFROMPARTS(l.Nam,l.Thang,1)<=DATEFROMPARTS(?,?,1)", (year, month, year, month))[1]]
            else:
                payroll_employee_ids = [r[0] for r in db.query("SELECT l.MaNV FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang WHERE l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'", (year, month))[1]]
            sensitive_audit.record_many(payroll_employee_ids, "Luong", "export", session["user"]["user"])
    else:
        return redirect(url_for("dashboard.dashboard"))
    try:
        return _export_response(filename, cols, rows, file_format)
    except ValueError as error:
        return str(error), 400
