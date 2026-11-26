from __future__ import annotations

from datetime import timedelta

from datetime import date

import config
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
    first = date(year, month, 1)
    following = date(year + (month == 12), month % 12 + 1, 1)
    last = following - timedelta(days=1)
    if name == "Tỷ lệ vắng mặt":
        days = sum(1 for offset in range((following-first).days) if (first+timedelta(days=offset)).weekday() < 5)
        sql = """SELECT COUNT(CASE WHEN TrangThai IN (N'Nghỉ phép',N'Nghỉ không phép') THEN 1 END) AS [Ngày vắng có ghi nhận],
            CAST(CASE WHEN ?*(SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm')=0 THEN 0
            ELSE ROUND(COUNT(CASE WHEN TrangThai IN (N'Nghỉ phép',N'Nghỉ không phép') THEN 1 END)*100.0/(?*(SELECT COUNT(*) FROM NhanVien WHERE TrangThai=N'Đang làm')),2) END AS DECIMAL(7,2)) AS [Tỷ lệ vắng mặt (%)]
            FROM ChamCong WHERE Ngay>=? AND Ngay<?"""
        return sql, (days, days, first, following)
    if name == "Chi phí nhân sự (kỳ lương đã khóa)":
        sql = """SELECT COUNT(l.MaNV) AS [Số nhân viên],
            CAST(ISNULL(SUM(l.TongLuong+ISNULL(l.BHXHDN,0)+ISNULL(l.BHYTDN,0)+ISNULL(l.BHTNDN,0)+ISNULL(l.BH_TNLDBNN_DN,0)),0) AS DECIMAL(18,0)) AS [Chi phí nhân sự đã khóa]
            FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang
            WHERE l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'"""
        return sql, (year, month)
    if name == "Quỹ lương theo phòng ban":
        sql = """SELECT COALESCE(p.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],COUNT(l.MaNV) AS [Nhân viên],
            SUM(l.LuongCB) AS [Lương cơ bản],SUM(l.PhuCap) AS [Phụ cấp],SUM(l.ThuongCC+ISNULL(l.ThuongThem,0)+ISNULL(pi.KhoanCongThem,0)) AS [Thưởng/khoản cộng thêm],
            SUM(l.TienTangCa) AS [Tiền tăng ca],SUM(l.TongLuong) AS [Tổng trước khấu trừ],SUM(l.LuongThucLinh) AS [Thực lĩnh]
            FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang JOIN NhanVien n ON n.MaNV=l.MaNV
            LEFT JOIN PhongBan p ON p.MaPB=n.MaPB LEFT JOIN (SELECT MaNV,Nam,Thang,SUM(CASE WHEN Loai=N'earning' THEN SoTien ELSE 0 END) AS KhoanCongThem FROM PayrollItem GROUP BY MaNV,Nam,Thang) pi ON pi.MaNV=l.MaNV AND pi.Nam=l.Nam AND pi.Thang=l.Thang
            WHERE l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'
            GROUP BY p.TenPB ORDER BY SUM(l.TongLuong) DESC"""
        return sql, (year, month)
    if name == "Cơ cấu quỹ lương":
        sql = """SELECT SUM(l.LuongCB) AS [Lương cơ bản],SUM(l.PhuCap) AS [Phụ cấp],
            SUM(l.ThuongCC+ISNULL(l.ThuongThem,0)+ISNULL(pi.KhoanCongThem,0)) AS [Thưởng/khoản cộng thêm],SUM(l.TienTangCa) AS [Tăng ca],
            SUM(l.TongLuong-l.LuongThucLinh) AS [Khấu trừ],SUM(l.LuongThucLinh) AS [Thực lĩnh],
            SUM(l.TongLuong+ISNULL(l.BHXHDN,0)+ISNULL(l.BHYTDN,0)+ISNULL(l.BHTNDN,0)+ISNULL(l.BH_TNLDBNN_DN,0)) AS [Tổng chi phí]
            FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang LEFT JOIN (SELECT MaNV,Nam,Thang,SUM(CASE WHEN Loai=N'earning' THEN SoTien ELSE 0 END) AS KhoanCongThem FROM PayrollItem GROUP BY MaNV,Nam,Thang) pi ON pi.MaNV=l.MaNV AND pi.Nam=l.Nam AND pi.Thang=l.Thang
            WHERE l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'"""
        return sql, (year, month)
    if name == "Biến động quỹ lương 6 tháng":
        sql = """WITH Months AS (SELECT m.Offset,DATEADD(month,-m.Offset,DATEFROMPARTS(?, ?, 1)) AS MonthStart
                 FROM (VALUES(0),(1),(2),(3),(4),(5)) m(Offset))
            SELECT FORMAT(m.MonthStart,'yyyy-MM') AS [Tháng],ISNULL(SUM(l.TongLuong),0) AS [Tổng lương],
                ISNULL(SUM(l.LuongThucLinh),0) AS [Thực lĩnh],
                ISNULL(SUM(l.TongLuong+ISNULL(l.BHXHDN,0)+ISNULL(l.BHYTDN,0)+ISNULL(l.BHTNDN,0)+ISNULL(l.BH_TNLDBNN_DN,0)),0) AS [Tổng chi phí]
            FROM Months m LEFT JOIN LuongKy k ON k.Nam=YEAR(m.MonthStart) AND k.Thang=MONTH(m.MonthStart) AND k.TrangThai=N'Đã khóa'
            LEFT JOIN Luong l ON l.Nam=YEAR(m.MonthStart) AND l.Thang=MONTH(m.MonthStart) AND k.TrangThai=N'Đã khóa'
            GROUP BY m.Offset,m.MonthStart ORDER BY m.Offset DESC"""
        return sql, (year, month)
    if name == "Biến động nhân sự theo phòng ban":
        sql = """SELECT COALESCE(p.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],
            SUM(CASE WHEN n.TrangThai=N'Đang làm' THEN 1 ELSE 0 END) AS [Nhân viên hiện tại],
            SUM(CASE WHEN n.NgayVaoLam>=? AND n.NgayVaoLam<? THEN 1 ELSE 0 END) AS [Tuyển mới],
            SUM(CASE WHEN n.NgayNghiViec>=? AND n.NgayNghiViec<? THEN 1 ELSE 0 END) AS [Nghỉ việc]
            FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB GROUP BY p.TenPB ORDER BY p.TenPB"""
        return sql, (first, following, first, following)
    if name in ("Biến động nhân sự", "Tỷ lệ nghỉ việc"):
        sql = """WITH Counts AS (
            SELECT COALESCE(SUM(CASE WHEN NgayVaoLam<=? AND ((TrangThai=N'Đang làm' AND NgayNghiViec IS NULL) OR NgayNghiViec>=?) THEN 1 ELSE 0 END),0) AS HeadcountStart,
              COALESCE(SUM(CASE WHEN NgayVaoLam<=? AND ((TrangThai=N'Đang làm' AND NgayNghiViec IS NULL) OR NgayNghiViec>=?) THEN 1 ELSE 0 END),0) AS HeadcountEnd,
              COALESCE(SUM(CASE WHEN NgayVaoLam>=? AND NgayVaoLam<? THEN 1 ELSE 0 END),0) AS Hires,
              COALESCE(SUM(CASE WHEN NgayNghiViec>=? AND NgayNghiViec<? THEN 1 ELSE 0 END),0) AS Exits,
              COALESCE(SUM(CASE WHEN TrangThai=N'Đang làm' THEN 1 ELSE 0 END),0) AS CurrentHeadcount FROM NhanVien
        ) SELECT CurrentHeadcount AS [Nhân viên hiện tại],HeadcountStart AS [Đầu kỳ],HeadcountEnd AS [Cuối kỳ],Hires AS [Tuyển mới],Exits AS [Nghỉ việc],
            CAST((HeadcountStart+HeadcountEnd)/2.0 AS DECIMAL(10,2)) AS [Bình quân],
            CAST(CASE WHEN HeadcountStart+HeadcountEnd=0 THEN 0 ELSE ROUND(Exits*200.0/(HeadcountStart+HeadcountEnd),2) END AS DECIMAL(7,2)) AS [Tỷ lệ nghỉ việc (%)] FROM Counts"""
        return sql, (first, first, last, last, first, following, first, following)
    if name == "KPI theo phòng ban":
        sql = """SELECT COALESCE(pb.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],COUNT(*) AS [Số đánh giá],
            CAST(AVG(d.DiemTong) AS DECIMAL(7,2)) AS [Điểm KPI trung bình],
            CAST(AVG(CASE WHEN d.TrangThai=N'Đã xác nhận' THEN 100.0 ELSE 0 END) AS DECIMAL(7,2)) AS [Tỷ lệ hoàn thành (%)],
            SUM(CASE WHEN d.TrangThai=N'Đã xác nhận' THEN ISNULL(d.TienThuong,0) ELSE 0 END) AS [Tổng thưởng KPI]
            FROM KPI_Danhgia d JOIN NhanVien n ON n.MaNV=d.MaNV LEFT JOIN PhongBan pb ON pb.MaPB=n.MaPB
            WHERE YEAR(d.DenNgay)=? AND MONTH(d.DenNgay)=? AND d.DiemTong IS NOT NULL GROUP BY pb.TenPB ORDER BY AVG(d.DiemTong) DESC"""
        return sql, (year, month)
    if name == "KPI theo nhân viên":
        sql = """SELECT n.HoTen AS [Nhân viên],COALESCE(pb.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],
            d.Ky AS [Kỳ],d.DiemTong AS [Điểm KPI],d.TrangThai AS [Trạng thái],ISNULL(d.TienThuong,0) AS [Thưởng KPI]
            FROM KPI_Danhgia d JOIN NhanVien n ON n.MaNV=d.MaNV LEFT JOIN PhongBan pb ON pb.MaPB=n.MaPB
            WHERE YEAR(d.DenNgay)=? AND MONTH(d.DenNgay)=? AND d.DiemTong IS NOT NULL ORDER BY d.DiemTong DESC,n.HoTen"""
        return sql, (year, month)
    if name == "Chuyên cần theo phòng ban":
        days_off = tuple(config.NGAY_NGHI_TUAN)
        default_schedule = (
            f"DATEDIFF(day,CONVERT(date,'19000101'),d.WorkDate)%7 NOT IN ({','.join('?' for _ in days_off)})"
            if days_off else "1=1"
        )
        sql = """WITH Calendar AS (SELECT CAST(? AS DATE) AS WorkDate UNION ALL
              SELECT DATEADD(day,1,WorkDate) FROM Calendar WHERE WorkDate<DATEADD(day,-1,CAST(? AS DATE))),
            ExpectedCalendar AS (SELECT n.MaNV,n.MaPB,d.WorkDate FROM NhanVien n CROSS JOIN Calendar d
              WHERE n.NgayVaoLam<=d.WorkDate AND ((n.TrangThai=N'Đang làm' AND n.NgayNghiViec IS NULL) OR n.NgayNghiViec>=d.WorkDate)
                AND (EXISTS(SELECT 1 FROM LichLamViecNhanVien x WHERE x.MaNV=n.MaNV AND x.Thu=(DATEDIFF(day,CONVERT(date,'19000101'),d.WorkDate)%7))
                     OR (NOT EXISTS(SELECT 1 FROM LichLamViecNhanVien x WHERE x.MaNV=n.MaNV) AND {default_schedule}))
                AND NOT EXISTS(SELECT 1 FROM LichNgayLe h WHERE h.Ngay=d.WorkDate)
                AND NOT EXISTS(SELECT 1 FROM NghiPhep np WHERE np.MaNV=n.MaNV AND np.TrangThai=N'Đã duyệt' AND np.TuNgay<=d.WorkDate AND np.DenNgay>=d.WorkDate)
              ), Expected AS (SELECT MaNV,MaPB,COUNT(*) AS ExpectedDays FROM ExpectedCalendar GROUP BY MaNV,MaPB),
            Present AS (SELECT ex.MaNV,COUNT(DISTINCT c.Ngay) AS PresentDays,SUM(CASE WHEN c.SoPhutMuon>0 THEN 1 ELSE 0 END) AS LateCount,
                SUM(CASE WHEN c.SoPhutVeSom>0 THEN 1 ELSE 0 END) AS EarlyCount,SUM(c.SoPhutMuon) AS LateMinutes,SUM(c.SoPhutVeSom) AS EarlyMinutes
              FROM ExpectedCalendar ex JOIN ChamCong c ON c.MaNV=ex.MaNV AND c.Ngay=ex.WorkDate AND c.GioVao IS NOT NULL AND c.TrangThai IN (N'Đi làm',N'Đi muộn') GROUP BY ex.MaNV)
            SELECT COALESCE(pb.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],SUM(ISNULL(pr.PresentDays,0)) AS [Ngày công thực tế],SUM(e.ExpectedDays) AS [Ngày công dự kiến],
              CAST(CASE WHEN SUM(e.ExpectedDays)=0 THEN 0 ELSE ROUND(SUM(ISNULL(pr.PresentDays,0))*100.0/SUM(e.ExpectedDays),2) END AS DECIMAL(7,2)) AS [Tỷ lệ chuyên cần (%)],
              SUM(ISNULL(pr.LateCount,0)) AS [Lượt đi muộn],SUM(ISNULL(pr.EarlyCount,0)) AS [Lượt về sớm],SUM(ISNULL(pr.LateMinutes,0)) AS [Phút muộn],SUM(ISNULL(pr.EarlyMinutes,0)) AS [Phút về sớm]
            FROM Expected e LEFT JOIN Present pr ON pr.MaNV=e.MaNV LEFT JOIN PhongBan pb ON pb.MaPB=e.MaPB GROUP BY pb.TenPB ORDER BY [Phòng ban] OPTION(MAXRECURSION 31)""".format(default_schedule=default_schedule)
        return sql, (first, following, *days_off)
    raise ValueError("Unknown report")


EXTENDED_REPORTS = (
    "Tỷ lệ vắng mặt",
    "Chi phí nhân sự (kỳ lương đã khóa)",
    "Quỹ lương theo phòng ban",
    "Cơ cấu quỹ lương",
    "Biến động quỹ lương 6 tháng",
    "Biến động nhân sự",
    "Biến động nhân sự theo phòng ban",
    "Tỷ lệ nghỉ việc",
    "Chuyên cần theo phòng ban",
    "KPI theo phòng ban",
    "KPI theo nhân viên",
)

REPORT_TURNOVER = "Tỷ lệ nghỉ việc"
REPORT_ATTENDANCE = "Chuyên cần theo phòng ban"
REPORT_PAYROLL_MIX = "Cơ cấu quỹ lương"
PAYROLL_REPORTS = frozenset((
    "Chi phí nhân sự (kỳ lương đã khóa)",
    "Quỹ lương theo phòng ban",
    REPORT_PAYROLL_MIX,
    "Biến động quỹ lương 6 tháng",
))

PERSONAL_REPORTS = (
    "Chấm công cá nhân",
    "Nghỉ phép cá nhân",
    "Lương cá nhân",
)


def _personal_report_query(name, employee_id, year, month):
    """Personal reports are always scoped by the authenticated employee id."""
    if name == "Chấm công cá nhân":
        first = date(year, month, 1)
        following = date(year + (month == 12), month % 12 + 1, 1)
        return ("SELECT Ngay AS [Ngày],GioVao AS [Giờ vào],GioRa AS [Giờ ra],"
                "SoPhutLamViec AS [Phút làm việc],SoPhutMuon AS [Phút muộn],"
                "SoPhutVeSom AS [Phút về sớm],TrangThai AS [Trạng thái] "
                "FROM ChamCong WHERE MaNV=? AND Ngay>=? AND Ngay<? ORDER BY Ngay",
                (employee_id, first, following))
    if name == "Nghỉ phép cá nhân":
        first = date(year, month, 1)
        following = date(year + (month == 12), month % 12 + 1, 1)
        return ("SELECT TuNgay AS [Từ ngày],DenNgay AS [Đến ngày],SoNgay AS [Số ngày],"
                "LoaiNghi AS [Loại nghỉ],LyDo AS [Lý do],TrangThai AS [Trạng thái] "
                "FROM NghiPhep WHERE MaNV=? AND TuNgay<? AND DenNgay>=? ORDER BY TuNgay",
                (employee_id, following, first))
    if name == "Lương cá nhân":
        return ("SELECT l.Thang AS [Tháng],l.Nam AS [Năm],l.LuongCB AS [Lương cơ bản],"
                "l.PhuCap AS [Phụ cấp],l.ThuongCC+ISNULL(l.ThuongThem,0)+ISNULL((SELECT SUM(SoTien) FROM PayrollItem i WHERE i.MaNV=l.MaNV AND i.Nam=l.Nam AND i.Thang=l.Thang AND i.Loai=N'earning'),0) AS [Thưởng/khoản cộng thêm],"
                "l.TienTangCa AS [Tiền tăng ca],l.TongLuong AS [Tổng trước khấu trừ],"
                "l.ThueTNCN AS [Thuế TNCN],l.LuongThucLinh AS [Thực lĩnh] "
                "FROM Luong l JOIN LuongKy k ON k.Nam=l.Nam AND k.Thang=l.Thang "
                "WHERE l.MaNV=? AND l.Nam=? AND l.Thang=? AND k.TrangThai=N'Đã khóa'",
                (employee_id, year, month))
    raise ValueError("Unknown personal report")


def _payroll_trend(year, month):
    sql, params = _extended_report_query("Biến động quỹ lương 6 tháng", year, month)
    return db.query(sql, params)[1]

