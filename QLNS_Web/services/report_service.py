from __future__ import annotations

from datetime import timedelta

from datetime import date

from database import db


def _hr_dashboard_summary():
    columns, rows = db.query(
        """SELECT
            (SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm') AS staff,
            (SELECT COUNT(*) FROM PhongBan) AS departments,
            (SELECT COUNT(*) FROM HopDong WHERE TrangThai IN (N'Còn hiệu lực',N'Đã ký') AND NgayBatDau<=CAST(GETDATE() AS DATE) AND (NgayKetThuc IS NULL OR NgayKetThuc>=CAST(GETDATE() AS DATE))) AS contracts,
            (SELECT COUNT(*) FROM NghiPhep WHERE TrangThai LIKE N'Chờ%') AS leaves"""
    )
    return dict(zip(columns, rows[0])) if rows else {}

def _extended_report_query(name, year, month):
    if name == "Tỷ lệ vắng mặt":
        first = date(year, month, 1)
        following = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
        days = sum(
            1
            for offset in range((following - first).days)
            if (first + timedelta(days=offset)).weekday() < 5
        )
        sql = """SELECT COUNT(CASE WHEN TrangThai IN (N'Nghỉ phép',N'Nghỉ không phép') THEN 1 END) AS [Ngày vắng có ghi nhận],
            CAST(CASE WHEN ?*(SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm')=0 THEN 0
            ELSE ROUND(COUNT(CASE WHEN TrangThai IN (N'Nghỉ phép',N'Nghỉ không phép') THEN 1 END)*100.0/
            (?*(SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm')),2) END AS DECIMAL(7,2)) AS [Tỷ lệ vắng mặt (%)]
            FROM ChamCong WHERE Ngay>=? AND Ngay<?"""
        return sql, (days, days, first, following)
    if name == "Chi phí nhân sự (kỳ lương đã khóa)":
        sql = """SELECT COUNT(l.MaNV) AS [Số nhân viên],
            CAST(ISNULL(SUM(l.TongLuong+ISNULL(l.BHXHDN,0)+ISNULL(l.BHYTDN,0)+ISNULL(l.BHTNDN,0)+ISNULL(l.BH_TNLDBNN_DN,0)),0) AS DECIMAL(18,0)) AS [Chi phí nhân sự đã khóa]
            FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang
            WHERE l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'"""
        return sql, (year, month)
    raise ValueError("Unknown report")


EXTENDED_REPORTS = {
    "Tỷ lệ vắng mặt",
    "Chi phí nhân sự (kỳ lương đã khóa)",
}


EXTENDED_REPORTS = {
    "Tỷ lệ vắng mặt",
    "Chi phí nhân sự (kỳ lương đã khóa)",
}
