MODULES = {
    "nhanvien": {
        "title": "Nhân viên",
        "table": "NhanVien",
        "pk": "MaNV",
        "fields": [
            ("HoTen", "Họ tên", "text", True),
            ("NgaySinh", "Ngày sinh", "date", False),
            ("GioiTinh", "Giới tính", "choice:Nam|Nữ|Khác", False),
            ("DiaChi", "Địa chỉ", "text", False),
            ("SDT", "Số điện thoại", "text", False),
            ("Email", "Email", "email", False),
            ("CCCD", "CCCD", "text", False),
            ("NgayVaoLam", "Ngày vào làm", "date", False),
            ("MaPB", "Phòng ban", "department", False),
            ("MaCV", "Chức vụ", "position", False),
            ("MaViTri", "Vị trí công việc", "jobposition", False),
            ("LuongCoBan", "Lương cơ bản", "number", False),
            ("TrangThai", "Trạng thái", "choice:Đang làm|Đã nghỉ việc", True),
            ("AnhHoSo", "Ảnh hồ sơ", "image", False),
        ],
        "sql": "SELECT n.MaNV AS [_id],ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))) AS [Mã NV],n.HoTen AS [Họ tên],n.NgaySinh AS [Ngày sinh],n.GioiTinh AS [Giới tính],n.SDT AS [SĐT],n.Email,p.TenPB AS [Phòng ban],c.TenCV AS [Chức danh],v.TenViTri AS [Vị trí],n.NgayVaoLam AS [Ngày vào],n.LuongCoBan AS [Lương CB],n.TrangThai AS [Trạng thái] FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB LEFT JOIN ChucVu c ON c.MaCV=n.MaCV LEFT JOIN ViTriCongViec v ON v.MaViTri=n.MaViTri ORDER BY n.MaNV DESC",
    },
    "phongban": {
        "title": "Phòng ban",
        "table": "PhongBan",
        "pk": "MaPB",
        "fields": [
            ("TenPB", "Tên phòng ban", "text", True),
            ("KyHieu", "Ký hiệu (VD: KT)", "text", True),
            ("MaDonVi", "Đơn vị", "unit", False),
            ("MaPBCha", "Phòng ban cấp trên", "department_parent", False),
            ("NguoiPhuTrach", "Người phụ trách", "text", False),
            ("TrangThai", "Trạng thái", "choice:Hoạt động|Ngừng hoạt động", True),
        ],
        "sql": "SELECT p.MaPB AS [Mã PB],p.TenPB AS [Tên phòng ban],p.KyHieu AS [Ký hiệu],d.TenDonVi AS [Đơn vị],cha.TenPB AS [Cấp trên],p.NguoiPhuTrach AS [Người phụ trách],p.TrangThai AS [Trạng thái] FROM PhongBan p LEFT JOIN DonVi d ON d.MaDonVi=p.MaDonVi LEFT JOIN PhongBan cha ON cha.MaPB=p.MaPBCha ORDER BY p.MaPB DESC",
    },
    "donvi": {
        "title": "Đơn vị",
        "table": "DonVi",
        "pk": "MaDonVi",
        "fields": [
            ("TenDonVi", "Tên đơn vị", "text", True),
            ("MaDonViCha", "Đơn vị cấp trên", "unit", False),
            ("TrangThai", "Trạng thái", "choice:Hoạt động|Ngừng hoạt động", True),
        ],
        "sql": "SELECT d.MaDonVi AS [Mã đơn vị],d.TenDonVi AS [Tên đơn vị],cha.TenDonVi AS [Đơn vị cấp trên],d.TrangThai AS [Trạng thái] FROM DonVi d LEFT JOIN DonVi cha ON cha.MaDonVi=d.MaDonViCha ORDER BY d.TenDonVi",
    },
    "vitri": {
        "title": "Vị trí công việc",
        "table": "ViTriCongViec",
        "pk": "MaViTri",
        "fields": [
            ("TenViTri", "Tên vị trí", "text", True),
            ("MaPB", "Phòng ban", "department", False),
            ("MoTa", "Mô tả", "text", False),
            ("TrangThai", "Trạng thái", "choice:Hoạt động|Ngừng hoạt động", True),
        ],
        "sql": "SELECT v.MaViTri AS [Mã vị trí],v.TenViTri AS [Vị trí],p.TenPB AS [Phòng ban],v.MoTa AS [Mô tả],v.TrangThai AS [Trạng thái] FROM ViTriCongViec v LEFT JOIN PhongBan p ON p.MaPB=v.MaPB ORDER BY v.TenViTri",
    },
    "chucvu": {
        "title": "Chức vụ",
        "table": "ChucVu",
        "pk": "MaCV",
        "fields": [
            ("TenCV", "Tên chức vụ", "text", True),
            ("MoTa", "Mô tả", "text", False),
        ],
        "sql": "SELECT MaCV AS [Mã CV],TenCV AS [Tên chức vụ],MoTa AS [Mô tả] FROM ChucVu ORDER BY MaCV DESC",
    },
    "hopdong": {
        "title": "Hợp đồng",
        "table": "HopDong",
        "pk": "MaHD",
        "fields": [
            ("MaNV", "Nhân viên", "employee", True),
            (
                "LoaiHD",
                "Loại hợp đồng",
                "choice:Thử việc|Có thời hạn|Không thời hạn|Thời vụ|Bán thời gian|Học việc|Cộng tác viên|Đào tạo",
                True,
            ),
            ("NgayBatDau", "Ngày bắt đầu", "date", True),
            ("NgayKetThuc", "Ngày kết thúc", "date", False),
            ("LuongHD", "Lương hợp đồng", "number", False),
        ],
        "sql": "SELECT h.MaHD AS [Mã HĐ],n.HoTen AS [Nhân viên],h.LoaiHD AS [Loại],h.NgayBatDau AS [Bắt đầu],h.NgayKetThuc AS [Kết thúc],h.LuongHD AS [Lương HĐ],h.TrangThai AS [Trạng thái] FROM HopDong h JOIN NhanVien n ON n.MaNV=h.MaNV ORDER BY h.MaHD DESC",
    },
}
REPORTS = {
    "Tổng số nhân viên đang làm": (
        "SELECT COUNT(*) AS [Tổng nhân viên] FROM NhanVien WHERE TrangThai=N'Đang làm'",
        (),
    ),
    "Nhân viên theo phòng ban": (
        "SELECT ISNULL(p.TenPB,N'(Chưa phân phòng)') AS [Phòng ban],COUNT(*) AS [Số nhân viên] FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB WHERE n.TrangThai=N'Đang làm' GROUP BY p.TenPB ORDER BY 2 DESC",
        (),
    ),
    "Nhân viên theo chức vụ": (
        "SELECT ISNULL(c.TenCV,N'(Chưa có chức vụ)') AS [Chức vụ],COUNT(*) AS [Số nhân viên] FROM NhanVien n LEFT JOIN ChucVu c ON c.MaCV=n.MaCV WHERE n.TrangThai=N'Đang làm' GROUP BY c.TenCV ORDER BY 2 DESC",
        (),
    ),
    "Nhân viên đã nghỉ việc": (
        "SELECT ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) AS [Mã NV],HoTen AS [Họ tên],NgayVaoLam AS [Ngày vào làm] FROM NhanVien WHERE TrangThai=N'Đã nghỉ việc'",
        (),
    ),
    "Đơn nghỉ phép theo trạng thái": (
        "SELECT TrangThai AS [Trạng thái],COUNT(*) AS [Số đơn],SUM(SoNgay) AS [Tổng ngày] FROM NghiPhep GROUP BY TrangThai",
        (),
    ),
    "Ngày công theo nhân viên": (None, ()),
    "Tỷ lệ vắng mặt": (None, ()),
    "Chi phí nhân sự (kỳ lương đã khóa)": (None, ()),
}
ATTENDANCE_PROGRESS_SQL = """WITH EffectiveEvents AS (
       SELECT e.MaNV,e.NgayCong,e.MaSuKien,e.ThoiDiem,e.LoaiSuKien
       FROM ChamCongSuKien e
       JOIN ChamCong c ON c.MaNV=e.MaNV AND c.Ngay=e.NgayCong
       WHERE e.NgayCong>=? AND e.NgayCong<DATEADD(month,1,?)
         AND e.LoaiSuKien IN (N'in',N'out')
         AND c.TrangThai IN (N'Đi làm',N'Đi muộn')
         AND e.MaSuKien>ISNULL((SELECT MAX(x.MaSuKien) FROM ChamCongSuKien x
             WHERE x.MaNV=e.MaNV AND x.NgayCong=e.NgayCong AND x.LoaiSuKien=N'delete'),0)
   ), AttendanceDays AS (
       SELECT DISTINCT MaNV,NgayCong FROM EffectiveEvents WHERE LoaiSuKien=N'in'
   ), OrderedEvents AS (
       SELECT MaNV,NgayCong,LoaiSuKien,ThoiDiem,
           LEAD(LoaiSuKien) OVER(PARTITION BY MaNV,NgayCong ORDER BY MaSuKien) AS NextType,
           LEAD(ThoiDiem) OVER(PARTITION BY MaNV,NgayCong ORDER BY MaSuKien) AS NextTime
       FROM EffectiveEvents
   ), EventHours AS (
       SELECT MaNV,NgayCong,SUM(DATEDIFF(SECOND,ThoiDiem,NextTime))/3600.0 AS HoursWorked
       FROM OrderedEvents
       WHERE LoaiSuKien=N'in' AND NextType=N'out' AND NextTime>=ThoiDiem
       GROUP BY MaNV,NgayCong
   ), EmployeeSummary AS (
       SELECT n.MaNV,n.HoTen,COUNT(a.NgayCong) AS WorkDays,
           CAST(ROUND(ISNULL(SUM(h.HoursWorked),0),2) AS DECIMAL(8,2)) AS HoursWorked
       FROM NhanVien n
       LEFT JOIN AttendanceDays a ON a.MaNV=n.MaNV
       LEFT JOIN EventHours h ON h.MaNV=a.MaNV AND h.NgayCong=a.NgayCong
       WHERE n.TrangThai=N'Đang làm'
       GROUP BY n.MaNV,n.HoTen
   )
   SELECT HoTen AS [Nhân viên],
       CAST(ROUND(WorkDays*100.0/?,1) AS DECIMAL(6,1)) AS [Tiến độ ngày công (%)],
       WorkDays AS [Ngày đi làm],? AS [Chuẩn ngày công],
       HoursWorked AS [Giờ ghi nhận]
   FROM EmployeeSummary ORDER BY HoTen"""

