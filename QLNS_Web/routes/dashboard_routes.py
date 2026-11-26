from flask import Blueprint, redirect, render_template, session, url_for
from datetime import date
from database import db
from utils.decorators import login_required
from services.common_service import _safe_error, admin, has_permission
from services.reports.report_service import (REPORT_ATTENDANCE, REPORT_PAYROLL_MIX, REPORT_TURNOVER, _extended_report_query, _hr_dashboard_summary, _payroll_trend)
from services.attendance.attendance_service import today_vietnam
from services import audit_service as sensitive_audit

bp = Blueprint('dashboard', __name__)


@bp.route("/")
@login_required
def dashboard():
    if not has_permission("reports.hr"):
        return redirect(url_for("attendance.chamcong"))
    stats = {}
    trend = []
    try:
        stats = _hr_dashboard_summary()
        today = today_vietnam()
        _, turnover_rows = db.query(*_extended_report_query(REPORT_TURNOVER, today.year, today.month))
        _, attendance_rows = db.query(*_extended_report_query(REPORT_ATTENDANCE, today.year, today.month))
        payroll_rows = []
        if has_permission("payroll.view"):
            _, payroll_rows = db.query(*_extended_report_query(REPORT_PAYROLL_MIX, today.year, today.month))
        stats["turnover"] = turnover_rows[0][6] if turnover_rows else 0
        attendance_days = sum(float(row[1] or 0) for row in attendance_rows)
        expected_days = sum(float(row[2] or 0) for row in attendance_rows)
        stats["attendance_rate"] = round(attendance_days * 100 / expected_days, 2) if expected_days else 0
        payroll = payroll_rows[0] if payroll_rows else ()
        stats["payroll_cost"] = payroll[6] if payroll and payroll[6] is not None else 0
        stats["payroll_net"] = payroll[5] if payroll and payroll[5] is not None else 0
        if has_permission("payroll.view") and payroll and payroll[6] is not None:
            employee_ids = [row[0] for row in db.query("SELECT l.MaNV FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang WHERE l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'", (today.year, today.month))[1]]
            sensitive_audit.record_many(employee_ids, "Luong", "view", session["user"]["user"])
        if has_permission("payroll.view"):
            trend = _payroll_trend(today.year, today.month)
        if has_permission("kpi.view_all"):
            period_start = today.replace(day=1)
            period_end = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
            _, kpi_rows = db.query(
                "SELECT COUNT(CASE WHEN DiemTong IS NOT NULL THEN 1 END),AVG(DiemTong),SUM(CASE WHEN TrangThai=N'Đã xác nhận' THEN 1 ELSE 0 END),SUM(CASE WHEN TrangThai=N'Đã xác nhận' THEN ISNULL(TienThuong,0) ELSE 0 END) FROM KPI_Danhgia WHERE DenNgay>=? AND DenNgay<?",
                (period_start, period_end),
            )
            if kpi_rows:
                stats["kpi_evaluated"], stats["kpi_average"], stats["kpi_confirmed"], stats["kpi_bonus"] = kpi_rows[0]
        cols, rows = db.query(
            "SELECT TOP 8 ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) AS [Mã NV],HoTen AS [Họ tên],Email,TrangThai AS [Trạng thái] FROM NhanVien ORDER BY MaNV DESC"
        )
    except Exception as e:
        stats["error"] = _safe_error(e, "Không tải được số liệu tổng quan.")
        cols, rows = [], []
    return render_template(
        "dashboard.html",
        stats=stats,
        trend=trend,
        trend_max=max((float(row[3] or 0) for row in trend), default=0),
        cols=cols,
        rows=rows,
        admin=admin(),
        can_view_payroll=has_permission("payroll.view"),
        can_view_kpi=has_permission("kpi.view_all"),
        now=today_vietnam().strftime("%d/%m/%Y"),
    )

