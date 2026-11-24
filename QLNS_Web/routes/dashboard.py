from flask import Blueprint, redirect, render_template, url_for
from datetime import date
from database import db
from web_auth import login_required
from services.common_service import _safe_error, admin, has_permission
from services.report_service import _hr_dashboard_summary

bp = Blueprint('dashboard', __name__)


@bp.route("/")
@login_required
def dashboard():
    if not has_permission("reports.hr"):
        return redirect(url_for("attendance.chamcong"))
    stats = {}
    try:
        stats = _hr_dashboard_summary()
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
