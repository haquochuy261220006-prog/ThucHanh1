"""Chạy 1 lần: tạo database, các bảng, dữ liệu mẫu và tài khoản admin/admin123."""
import pyodbc

from auth import hash_password
from config import DATABASE, conn_str

TABLES = [
    ("PhongBan", """CREATE TABLE PhongBan(
        MaPB INT IDENTITY PRIMARY KEY, TenPB NVARCHAR(100) NOT NULL UNIQUE,
        NguoiPhuTrach NVARCHAR(100) NULL, TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Hoạt động')"""),
    ("ChucVu", """CREATE TABLE ChucVu(
        MaCV INT IDENTITY PRIMARY KEY, TenCV NVARCHAR(100) NOT NULL UNIQUE, MoTa NVARCHAR(255) NULL)"""),
    ("NhanVien", """CREATE TABLE NhanVien(
        MaNV INT IDENTITY PRIMARY KEY, HoTen NVARCHAR(100) NOT NULL, NgaySinh DATE NULL,
        GioiTinh NVARCHAR(10) NULL, DiaChi NVARCHAR(255) NULL, SDT VARCHAR(20) NULL,
        Email VARCHAR(100) NULL, CCCD VARCHAR(20) NULL, NgayVaoLam DATE NULL,
        MaPB INT NULL REFERENCES PhongBan(MaPB), MaCV INT NULL REFERENCES ChucVu(MaCV),
        LuongCoBan DECIMAL(18,0) NOT NULL DEFAULT 0, TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang làm')"""),
    ("HopDong", """CREATE TABLE HopDong(
        MaHD INT IDENTITY PRIMARY KEY, MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        LoaiHD NVARCHAR(50) NOT NULL, NgayBatDau DATE NOT NULL, NgayKetThuc DATE NULL,
        LuongHD DECIMAL(18,0) NOT NULL DEFAULT 0, TrangThai NVARCHAR(30) NOT NULL DEFAULT N'Còn hiệu lực')"""),
    ("ChamCong", """CREATE TABLE ChamCong(
        MaCC INT IDENTITY PRIMARY KEY, MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        Ngay DATE NOT NULL, GioVao TIME NULL, GioRa TIME NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đi làm', CONSTRAINT UQ_CC UNIQUE(MaNV, Ngay))"""),
    ("NghiPhep", """CREATE TABLE NghiPhep(
        MaNP INT IDENTITY PRIMARY KEY, MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        TuNgay DATE NOT NULL, DenNgay DATE NOT NULL, SoNgay INT NOT NULL, LyDo NVARCHAR(255) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt')"""),
    ("Luong", """CREATE TABLE Luong(
        MaLuong INT IDENTITY PRIMARY KEY, MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        Thang INT NOT NULL, Nam INT NOT NULL, NgayCong DECIMAL(5,1) NOT NULL DEFAULT 0,
        LuongCB DECIMAL(18,0) NOT NULL DEFAULT 0, PhuCap DECIMAL(18,0) NOT NULL DEFAULT 0,
        KhauTru DECIMAL(18,0) NOT NULL DEFAULT 0, TongLuong DECIMAL(18,0) NOT NULL DEFAULT 0,
        CONSTRAINT UQ_Luong UNIQUE(MaNV, Thang, Nam))"""),
    ("TaiKhoan", """CREATE TABLE TaiKhoan(
        TenDN NVARCHAR(50) PRIMARY KEY, MatKhau NVARCHAR(200) NOT NULL,
        VaiTro NVARCHAR(20) NOT NULL CHECK (VaiTro IN (N'QuanTri', N'NhanVien')),
        MaNV INT NULL REFERENCES NhanVien(MaNV))"""),
]


def main():
    c = pyodbc.connect(conn_str("master"), autocommit=True)
    c.execute(f"IF DB_ID('{DATABASE}') IS NULL CREATE DATABASE [{DATABASE}]")
    c.close()

    c = pyodbc.connect(conn_str(), autocommit=True)
    for name, ddl in TABLES:
        c.execute(f"IF OBJECT_ID('{name}', 'U') IS NULL {ddl}")
    cur = c.cursor()
    if cur.execute("SELECT COUNT(*) FROM PhongBan").fetchval() == 0:
        for t in ["Phòng Nhân sự", "Phòng Kế toán", "Phòng Kinh doanh", "Phòng Kỹ thuật", "Phòng Marketing"]:
            cur.execute("INSERT INTO PhongBan(TenPB) VALUES(?)", t)
    if cur.execute("SELECT COUNT(*) FROM ChucVu").fetchval() == 0:
        for t in ["Giám đốc", "Trưởng phòng", "Phó phòng", "Nhân viên", "Kỹ thuật viên"]:
            cur.execute("INSERT INTO ChucVu(TenCV) VALUES(?)", t)
    if cur.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TenDN='admin'").fetchval() == 0:
        cur.execute("INSERT INTO TaiKhoan(TenDN, MatKhau, VaiTro) VALUES('admin', ?, N'QuanTri')",
                    hash_password("admin123"))
    c.close()
    print(f"Xong. Database {DATABASE} đã sẵn sàng. Đăng nhập: admin / admin123")


if __name__ == "__main__":
    main()
