"""KPI setup, employee results, scoring and confirmed bonus handling."""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from database import db
from services.common_service import has_permission
from services.payroll.payroll_service import invalidate_period
from utils.decorators import login_required

bp = Blueprint("kpi", __name__)


def _number(value, label, *, minimum=None, maximum=None):
    try:
        number = Decimal((value or "").strip())
    except (InvalidOperation, AttributeError):
        raise ValueError(f"{label} phải là số hợp lệ.") from None
    if not number.is_finite() or (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        raise ValueError(f"{label} nằm ngoài giới hạn cho phép.")
    return number


def _employee_id():
    try:
        return int(session.get("user", {}).get("manv") or 0)
    except (TypeError, ValueError):
        return 0


def _period_range(key):
    if re.fullmatch(r"\d{4}-\d{2}", key):
        start = date.fromisoformat(key + "-01")
        next_start = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        end = next_start - timedelta(days=1)
        return "Thang", start, end
    if re.fullmatch(r"\d{4}-Q[1-4]", key):
        year, quarter = int(key[:4]), int(key[-1])
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        next_month = start_month + 3
        end = date(year + (next_month > 12), (next_month - 1) % 12 + 1, 1) - timedelta(days=1)
        return "Quy", start, end
    if re.fullmatch(r"\d{4}", key):
        year = int(key)
        return "Nam", date(year, 1, 1), date(year, 12, 31)
    raise ValueError("Mã kỳ phải theo dạng YYYY-MM, YYYY-Q1 đến YYYY-Q4 hoặc YYYY.")


@bp.route("/kpi", methods=["GET", "POST"])
@login_required
def dashboard():
    can_view_all = has_permission("kpi.view_all")
    own_id = _employee_id()
    if not can_view_all and not has_permission("kpi.view_own"):
        return "Bạn không có quyền truy cập KPI.", 403

    if request.method == "POST":
        action = request.form.get("action", "")
        try:
            if action == "metric":
                if not has_permission("kpi.manage"):
                    return "Bạn không có quyền thiết lập chỉ tiêu.", 403
                name = (request.form.get("TenChiTieu") or "").strip()
                description = (request.form.get("MoTa") or "").strip()[:1000]
                period = request.form.get("KyDanhGia", "")
                start = date.fromisoformat(request.form.get("NgayBatDau", ""))
                end = date.fromisoformat(request.form.get("NgayKetThuc", ""))
                target = _number(request.form.get("MucTieu"), "Mục tiêu", minimum=Decimal("0.0001"))
                weight = _number(request.form.get("TrongSo"), "Trọng số", minimum=Decimal("0.01"), maximum=Decimal("100"))
                department = int(request.form.get("MaPB") or 0) or None
                employee = int(request.form.get("MaNV") or 0) or None
                unit = (request.form.get("DonVi") or "%").strip()[:40]
                direction = request.form.get("ChieuDanhGia", "higher")
                if direction not in ("higher", "lower"):
                    raise ValueError("Chọn hướng đánh giá hợp lệ.")
                if not name or period not in ("Thang", "Quy", "Nam") or end < start or bool(department) == bool(employee):
                    raise ValueError("Vui lòng nhập đủ tên, đối tượng áp dụng, kỳ và ngày hiệu lực hợp lệ.")
                db.execute("INSERT INTO KPI_Chitieu(TenChiTieu,MoTa,MaPB,MaNV,MucTieu,DonVi,TrongSo,KyDanhGia,NgayBatDau,NgayKetThuc,NguoiTao,ChieuDanhGia) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (name[:160], description or None, department, employee, target, unit, weight, period, start, end, session["user"]["user"], direction))
                flash("Đã tạo chỉ tiêu KPI.", "success")

            elif action == "metric_update":
                if not has_permission("kpi.manage"):
                    return "Bạn không có quyền chỉnh sửa chỉ tiêu KPI.", 403
                metric_id = int(request.form.get("MaKPI", "0"))
                name = (request.form.get("TenChiTieu") or "").strip()
                description = (request.form.get("MoTa") or "").strip()[:1000] or None
                target = _number(request.form.get("MucTieu"), "Mục tiêu", minimum=Decimal("0.0001"))
                weight = _number(request.form.get("TrongSo"), "Trọng số", minimum=Decimal("0.01"), maximum=Decimal("100"))
                direction = request.form.get("ChieuDanhGia", "higher")
                unit = (request.form.get("DonVi") or "%").strip()[:40]
                if not name or direction not in ("higher", "lower"):
                    raise ValueError("Tên và chiều đánh giá KPI không hợp lệ.")
                changed = db.execute("UPDATE KPI_Chitieu SET TenChiTieu=?,MoTa=?,MucTieu=?,DonVi=?,TrongSo=?,ChieuDanhGia=? WHERE MaKPI=? AND TrangThai=1", (name[:160], description, target, unit, weight, direction, metric_id))
                if not changed:
                    raise ValueError("Không tìm thấy chỉ tiêu KPI đang hoạt động.")
                flash("Đã cập nhật chỉ tiêu KPI; các kỳ đã giao giữ nguyên mục tiêu và trọng số đã chụp.", "success")

            elif action == "assign":
                if not has_permission("kpi.manage"):
                    return "Bạn không có quyền gán KPI.", 403
                period_key = (request.form.get("Ky") or "").strip()[:20]
                start = date.fromisoformat(request.form.get("TuNgay", ""))
                end = date.fromisoformat(request.form.get("DenNgay", ""))
                period_type, period_start, period_end = _period_range(period_key)
                department = int(request.form.get("MaPB") or 0)
                employee = int(request.form.get("MaNV") or 0)
                if start != period_start or end != period_end or bool(department) == bool(employee):
                    raise ValueError("Ngày bắt đầu/kết thúc phải khớp với mã kỳ; chọn đúng một phòng ban hoặc nhân viên.")
                people = db.query("SELECT n.MaNV,n.MaPB,COALESCE((SELECT TOP 1 l.LuongCoBan FROM LichSuCongTac l WHERE l.MaNV=n.MaNV AND l.TuNgay<=? AND (l.DenNgay IS NULL OR l.DenNgay>=?) ORDER BY l.TuNgay DESC),n.LuongCoBan) FROM NhanVien n WHERE n.TrangThai=N'Đang làm' AND " + ("n.MaPB=?" if department else "n.MaNV=?"), (end, end, department or employee))[1]
                count = 0
                for manv, ma_pb, base_salary in people:
                    cur = db.query("SELECT MaNV FROM KPI_Danhgia WHERE MaNV=? AND Ky=?", (manv, period_key))[1]
                    if cur:
                        continue
                    metrics = db.query("SELECT MaKPI,TenChiTieu,MucTieu,TrongSo,ChieuDanhGia FROM KPI_Chitieu WHERE TrangThai=1 AND KyDanhGia=? AND NgayBatDau<=? AND NgayKetThuc>=? AND (MaNV=? OR (MaNV IS NULL AND MaPB=?)) ORDER BY MaKPI", (period_type, end, start, manv, ma_pb))[1]
                    if not metrics:
                        continue
                    total_weight = sum((Decimal(str(item[3])) for item in metrics), Decimal("0"))
                    if total_weight != Decimal("100"):
                        raise ValueError(f"Tổng trọng số KPI của {manv} là {total_weight}%; cần đúng 100% trước khi gán.")
                    result = db.query("INSERT INTO KPI_Danhgia(MaNV,Ky,TuNgay,DenNgay,LuongCoBan) OUTPUT INSERTED.MaDanhGia VALUES(?,?,?,?,?)", (manv, period_key, start, end, base_salary or 0))[1]
                    evaluation_id = int(result[0][0])
                    db.execute_batches([("INSERT INTO KPI_Chitiet(MaDanhGia,MaKPI,TenChiTieu,MucTieu,TrongSo,ChieuDanhGia) VALUES(?,?,?,?,?,?)", [(evaluation_id, item[0], item[1], item[2], item[3], item[4]) for item in metrics])])
                    count += 1
                flash(f"Đã lập {count} phiếu đánh giá KPI.", "success" if count else "info")

            elif action == "actual":
                detail_id = int(request.form.get("MaChiTiet", "0"))
                actual = _number(request.form.get("ThucTe"), "Kết quả thực tế", minimum=Decimal("0"))
                note = (request.form.get("GhiChu") or "").strip()[:500] or None
                row = db.query("SELECT d.MaDanhGia,e.MaNV,e.TrangThai FROM KPI_Chitiet d JOIN KPI_Danhgia e ON e.MaDanhGia=d.MaDanhGia WHERE d.MaChiTiet=?", (detail_id,))[1]
                if not row:
                    raise ValueError("Không tìm thấy chỉ tiêu KPI.")
                evaluation_id, manv, status = row[0]
                permitted = has_permission("kpi.update_results") or (has_permission("kpi.update_own") and int(manv) == own_id)
                if not permitted or status == "Đã xác nhận":
                    return "Bạn không có quyền sửa kết quả này.", 403
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE KPI_Chitiet SET ThucTe=?,GhiChu=?,TyLe=NULL WHERE MaChiTiet=? AND EXISTS(SELECT 1 FROM KPI_Danhgia WHERE MaDanhGia=? AND TrangThai<>?); IF @@ROWCOUNT<>1 THROW 51021,\x27Evaluation is confirmed or unavailable.\x27,1; UPDATE KPI_Danhgia SET TrangThai=?,DiemTong=NULL,YKienPhanHoi=NULL WHERE MaDanhGia=? AND TrangThai<>?; COMMIT", (actual, note, detail_id, evaluation_id, "Đã xác nhận", "Đang thực hiện", evaluation_id, "Đã xác nhận"))
                flash("Đã cập nhật kết quả thực tế.", "success")

            elif action == "return":
                if not has_permission("kpi.confirm"):
                    return "Bạn không có quyền yêu cầu cập nhật KPI.", 403
                evaluation_id = int(request.form.get("MaDanhGia", "0"))
                feedback = (request.form.get("YKienPhanHoi") or "").strip()[:500]
                if not feedback:
                    raise ValueError("Hãy ghi nội dung cần nhân viên cập nhật.")
                db.execute("SET XACT_ABORT ON; BEGIN TRAN; UPDATE KPI_Danhgia SET TrangThai=?,DiemTong=NULL,YKienPhanHoi=? WHERE MaDanhGia=? AND TrangThai<>?; IF @@ROWCOUNT<>1 THROW 51025,\x27Evaluation already confirmed or unavailable.\x27,1; UPDATE KPI_Chitiet SET TyLe=NULL WHERE MaDanhGia=?; COMMIT", ("Đang thực hiện", feedback, evaluation_id, "Đã xác nhận", evaluation_id))
                flash("Đã trả KPI cho nhân viên cập nhật.", "success")

            elif action in ("score", "confirm"):
                if action == "confirm" and not has_permission("kpi.confirm"):
                    return "Bạn không có quyền xác nhận KPI.", 403
                if not has_permission("kpi.score"):
                    return "Bạn không có quyền chấm điểm KPI.", 403
                evaluation_id = int(request.form.get("MaDanhGia", "0"))
                evaluation = db.query("SELECT MaNV,Ky,DenNgay,LuongCoBan,TrangThai FROM KPI_Danhgia WHERE MaDanhGia=?", (evaluation_id,))[1]
                details = db.query("SELECT MaChiTiet,MucTieu,TrongSo,ThucTe,ChieuDanhGia FROM KPI_Chitiet WHERE MaDanhGia=?", (evaluation_id,))[1]
                if not evaluation or not details or any(item[3] is None for item in details):
                    raise ValueError("Cần nhập đủ kết quả thực tế trước khi chấm KPI.")
                if evaluation[0][4] == "Đã xác nhận":
                    raise ValueError("Kỳ KPI này đã được xác nhận.")
                score_updates = []
                total = Decimal("0")
                for detail_id, target, weight, actual, direction in details:
                    target_value, actual_value = Decimal(str(target)), Decimal(str(actual))
                    ratio = target_value / actual_value * 100 if direction == "lower" and actual_value > 0 else (Decimal("120") if direction == "lower" else actual_value / target_value * 100)
                    ratio = min(Decimal("120"), ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    score_updates.append((ratio, detail_id))
                    total += ratio * Decimal(str(weight)) / Decimal("100")
                total = min(Decimal("120"), total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                db.execute_batches([("UPDATE KPI_Chitiet SET TyLe=? WHERE MaChiTiet=?", score_updates)])
                db.execute("UPDATE KPI_Danhgia SET DiemTong=?,TrangThai=N'Đã chấm' WHERE MaDanhGia=? AND TrangThai<>N'Đã xác nhận'", (total, evaluation_id))
                if action == "confirm":
                    salary = Decimal(str(evaluation[0][3] or 0))
                    tier = db.query("SELECT TOP 1 TenXepLoai,TyLeThuong FROM KPI_Thuong WHERE TrangThai=1 AND TuDiem<=? AND (DenDiem IS NULL OR ?<DenDiem) ORDER BY TuDiem DESC", (total, total))[1]
                    title, rate = tier[0] if tier else ("Không đạt", 0)
                    bonus = (salary * Decimal(str(rate)) / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    period_key = evaluation[0][1]
                    _, _, period_end = _period_range(period_key)
                    year, month = period_end.year, period_end.month
                    reason = f"KPI:{evaluation_id}"
                    locked = db.query("SELECT TrangThai FROM LuongKy WHERE Nam=? AND Thang=?", (year, month))[1]
                    if locked and locked[0][0] != "Nháp":
                        raise ValueError("Không thể chuyển thưởng vào kỳ lương đã duyệt hoặc khóa.")
                    if bonus > 0 and not db.query("SELECT MaKhoan FROM PayrollItem WHERE KPIReviewId=?", (evaluation_id,))[1]:
                        db.execute("INSERT INTO PayrollItem(MaNV,Nam,Thang,Loai,Ten,SoTien,ChiuThue,CanCuBaoHiem,DuocTruThue,LyDo,KPIReviewId,NguoiTao) VALUES(?,?,?,N'earning',?, ?,1,0,0,?,?,?)", (evaluation[0][0], year, month, f"Thưởng KPI - {title}", bonus, reason, evaluation_id, session["user"]["user"]))
                        db.execute("INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriMoi,LyDo,NguoiThucHien) VALUES(?,?,?,N'Thêm thưởng KPI',?,?,?)", (evaluation[0][0], month, year, str(int(bonus)), reason, session["user"]["user"]))
                        invalidate_period(db, year, month, session["user"]["user"])
                    db.execute("UPDATE KPI_Danhgia SET TrangThai=N'Đã xác nhận',DiemTong=?,TienThuong=?,NguoiXacNhan=?,XacNhanLuc=SYSUTCDATETIME() WHERE MaDanhGia=? AND TrangThai<>N'Đã xác nhận'", (total, bonus, session["user"]["user"], evaluation_id))
                    flash(f"Đã xác nhận KPI {total} điểm; thưởng {int(bonus):,} VNĐ được ghi vào lương {month:02d}/{year}.", "success")
                else:
                    flash(f"Đã chấm KPI: {total} điểm.", "success")
            elif action == "policy":
                if not has_permission("kpi.bonus_policy"):
                    return "Bạn không có quyền sửa chính sách thưởng KPI.", 403
                tier_id = int(request.form.get("MaMuc", "0"))
                rate = _number(request.form.get("TyLeThuong"), "Tỷ lệ thưởng", minimum=Decimal("0"), maximum=Decimal("100"))
                db.execute("UPDATE KPI_Thuong SET TyLeThuong=?,NguoiCapNhat=?,TaoLuc=SYSUTCDATETIME() WHERE MaMuc=?", (rate, session["user"]["user"], tier_id))
                flash("Đã cập nhật tỷ lệ thưởng KPI.", "success")
            else:
                return "Thao tác KPI không hợp lệ.", 400
        except (ValueError, InvalidOperation) as error:
            flash(str(error), "error")
        except Exception:
            from flask import current_app
            current_app.logger.exception("KPI action failed")
            flash("Không thể xử lý thao tác KPI lúc này.", "error")
        return redirect(url_for("kpi.dashboard"))

    metrics = db.query("SELECT k.MaKPI,k.TenChiTieu,k.MoTa,k.MucTieu,k.DonVi,k.TrongSo,k.KyDanhGia,k.NgayBatDau,k.NgayKetThuc,p.TenPB,n.HoTen,k.ChieuDanhGia FROM KPI_Chitieu k LEFT JOIN PhongBan p ON p.MaPB=k.MaPB LEFT JOIN NhanVien n ON n.MaNV=k.MaNV WHERE k.TrangThai=1 ORDER BY k.MaKPI DESC")[1] if can_view_all else []
    sql = "SELECT e.MaDanhGia,e.MaNV,n.HoTen,e.Ky,e.TuNgay,e.DenNgay,e.TrangThai,e.DiemTong,e.TienThuong,e.LuongCoBan,CASE WHEN e.TrangThai<>N'Đã xác nhận' THEN e.TrangThai WHEN ISNULL(e.TienThuong,0)=0 THEN N'Không phát sinh' WHEN EXISTS(SELECT 1 FROM PayrollItem p WHERE p.KPIReviewId=e.MaDanhGia) THEN N'Đã chuyển lương' ELSE N'Chưa chuyển lương' END AS TrangThaiThuong,e.YKienPhanHoi FROM KPI_Danhgia e JOIN NhanVien n ON n.MaNV=e.MaNV "
    evaluations = db.query(sql + ("ORDER BY e.TuNgay DESC,e.MaDanhGia DESC" if can_view_all else "WHERE e.MaNV=? ORDER BY e.TuNgay DESC,e.MaDanhGia DESC"), () if can_view_all else (own_id,))[1]
    details = {}
    if evaluations:
        ids = [str(int(row[0])) for row in evaluations]
        detail_rows = db.query("SELECT d.MaChiTiet,d.MaDanhGia,d.TenChiTieu,d.MucTieu,d.TrongSo,d.ThucTe,d.TyLe,d.GhiChu,d.ChieuDanhGia FROM KPI_Chitiet d WHERE d.MaDanhGia IN (" + ",".join(ids) + ") ORDER BY d.MaChiTiet")[1]
        for row in detail_rows:
            details.setdefault(int(row[1]), []).append(row)
    departments = db.query("SELECT MaPB,TenPB FROM PhongBan ORDER BY TenPB")[1] if can_view_all else []
    employees = db.query("SELECT MaNV,HoTen FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen")[1] if can_view_all else []
    policies = db.query("SELECT MaMuc,TuDiem,DenDiem,TenXepLoai,TyLeThuong FROM KPI_Thuong WHERE TrangThai=1 ORDER BY TuDiem")[1] if can_view_all else []
    try:
        report_month = int(request.args.get("report_month", date.today().month))
        report_year = int(request.args.get("report_year", date.today().year))
    except (TypeError, ValueError):
        report_month, report_year = date.today().month, date.today().year
    if report_month not in range(1, 13) or report_year not in range(2000, date.today().year + 1):
        report_month, report_year = date.today().month, date.today().year
    scope = "" if can_view_all else " AND e.MaNV=?"
    params = (report_year, report_month) if can_view_all else (report_year, report_month, own_id)
    report_summary = db.query(
        "SELECT COUNT(*),AVG(e.DiemTong),SUM(CASE WHEN e.TrangThai=N'Đã xác nhận' THEN 1 ELSE 0 END),SUM(CASE WHEN e.TrangThai=N'Đã xác nhận' THEN ISNULL(e.TienThuong,0) ELSE 0 END) FROM KPI_Danhgia e WHERE YEAR(e.DenNgay)=? AND MONTH(e.DenNgay)=?" + scope,
        params,
    )[1]
    leaderboard = db.query(
        "SELECT TOP 10 n.HoTen,COALESCE(pb.TenPB,N'Chưa phân phòng'),e.DiemTong,e.TrangThai,e.TienThuong FROM KPI_Danhgia e JOIN NhanVien n ON n.MaNV=e.MaNV LEFT JOIN PhongBan pb ON pb.MaPB=n.MaPB WHERE YEAR(e.DenNgay)=? AND MONTH(e.DenNgay)=? AND e.DiemTong IS NOT NULL" + scope + " ORDER BY e.DiemTong DESC,e.MaDanhGia DESC",
        params,
    )[1]
    department_report = db.query(
        "SELECT COALESCE(pb.TenPB,N'Chưa phân phòng'),COUNT(*),AVG(e.DiemTong),SUM(CASE WHEN e.TrangThai=N'Đã xác nhận' THEN ISNULL(e.TienThuong,0) ELSE 0 END) FROM KPI_Danhgia e JOIN NhanVien n ON n.MaNV=e.MaNV LEFT JOIN PhongBan pb ON pb.MaPB=n.MaPB WHERE YEAR(e.DenNgay)=? AND MONTH(e.DenNgay)=? AND e.DiemTong IS NOT NULL GROUP BY pb.TenPB ORDER BY AVG(e.DiemTong) DESC",
        (report_year, report_month),
    )[1] if can_view_all else []
    bonus_scope = "" if can_view_all else " AND p.MaNV=?"
    monthly_bonus_params = (report_year, report_month) if can_view_all else (report_year, report_month, own_id)
    monthly_bonus = db.query(
        "SELECT COUNT(*),ISNULL(SUM(p.SoTien),0) FROM PayrollItem p WHERE p.Nam=? AND p.Thang=? AND p.KPIReviewId IS NOT NULL" + bonus_scope,
        monthly_bonus_params,
    )[1][0]
    return render_template("kpi/kpi.html", can_view_all=can_view_all, can_manage=has_permission("kpi.manage"), can_update=has_permission("kpi.update_results") or has_permission("kpi.update_own"), can_score=has_permission("kpi.score"), can_confirm=has_permission("kpi.confirm"), can_policy=has_permission("kpi.bonus_policy"), metrics=metrics, evaluations=evaluations, details=details, departments=departments, employees=employees, policies=policies, report_month=report_month, report_year=report_year, report_summary=report_summary[0] if report_summary else (0, 0, 0, 0), leaderboard=leaderboard, department_report=department_report, monthly_bonus=monthly_bonus)


