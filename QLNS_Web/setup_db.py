"""Tạo database SQL Server và schema nền cho 8 phân hệ HR."""

import os
import re
import secrets

import pyodbc

from auth import hash_password
from config import DATABASE, conn_str
import db


CORE_TABLES = [
    (
        "PhongBan",
        """CREATE TABLE PhongBan(
        MaPB INT IDENTITY PRIMARY KEY,
        TenPB NVARCHAR(100) NOT NULL UNIQUE,
        KyHieu NVARCHAR(10) NULL,
        NguoiPhuTrach NVARCHAR(100) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Hoạt động')""",
    ),
    (
        "ChucVu",
        """CREATE TABLE ChucVu(
        MaCV INT IDENTITY PRIMARY KEY,
        TenCV NVARCHAR(100) NOT NULL UNIQUE,
        MoTa NVARCHAR(255) NULL)""",
    ),
    (
        "NhanVien",
        """CREATE TABLE NhanVien(
        MaNV INT IDENTITY PRIMARY KEY,
        HoTen NVARCHAR(100) NOT NULL,
        NgaySinh DATE NULL,
        GioiTinh NVARCHAR(10) NULL,
        DiaChi NVARCHAR(255) NULL,
        SDT VARCHAR(20) NULL,
        Email VARCHAR(100) NULL,
        CCCD VARCHAR(20) NULL,
        NgayVaoLam DATE NULL,
        MaPB INT NULL REFERENCES PhongBan(MaPB),
        MaCV INT NULL REFERENCES ChucVu(MaCV),
        MaNVHT NVARCHAR(20) NULL,
        LuongCoBan DECIMAL(18,0) NOT NULL DEFAULT 0,
        AnhHoSo VARBINARY(MAX) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang làm')""",
    ),
    (
        "HopDong",
        """CREATE TABLE HopDong(
        MaHD INT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        LoaiHD NVARCHAR(40) NOT NULL,
        NgayBatDau DATE NOT NULL,
        NgayKetThuc DATE NULL,
        LuongHD DECIMAL(18,0) NULL,
        TrangThai NVARCHAR(30) NOT NULL DEFAULT N'Bản nháp')""",
    ),
    (
        "ChamCong",
        """CREATE TABLE ChamCong(
        MaCC INT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        Ngay DATE NOT NULL,
        GioVao TIME NULL,
        GioRa TIME NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đi làm',
        CONSTRAINT UQ_ChamCong_NhanVien_Ngay UNIQUE(MaNV,Ngay))""",
    ),
    (
        "NghiPhep",
        """CREATE TABLE NghiPhep(
        MaNP INT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        TuNgay DATE NOT NULL,
        DenNgay DATE NOT NULL,
        SoNgay DECIMAL(6,2) NOT NULL DEFAULT 0,
        LyDo NVARCHAR(1000) NOT NULL,
        TrangThai NVARCHAR(40) NOT NULL DEFAULT N'Chờ quản lý')""",
    ),
    (
        "Luong",
        """CREATE TABLE Luong(
        MaLuong INT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        Thang INT NOT NULL,
        Nam INT NOT NULL,
        NgayCong DECIMAL(6,2) NOT NULL DEFAULT 0,
        LuongCB DECIMAL(18,0) NOT NULL DEFAULT 0,
        LuongDieuChinh DECIMAL(18,0) NULL,
        PhuCap DECIMAL(18,0) NOT NULL DEFAULT 0,
        KhauTru DECIMAL(18,0) NOT NULL DEFAULT 0,
        TongLuong DECIMAL(18,0) NOT NULL DEFAULT 0,
        ThuongCC DECIMAL(18,0) NOT NULL DEFAULT 0,
        ThuongThem DECIMAL(18,0) NOT NULL DEFAULT 0,
        GioTangCa DECIMAL(7,2) NOT NULL DEFAULT 0,
        TienTangCa DECIMAL(18,0) NOT NULL DEFAULT 0,
        SoLanMuon INT NOT NULL DEFAULT 0,
        TruMuon DECIMAL(18,0) NOT NULL DEFAULT 0,
        SoNgayNghiKP INT NOT NULL DEFAULT 0,
        TruNghiKP DECIMAL(18,0) NOT NULL DEFAULT 0,
        GioGhiNhan DECIMAL(8,2) NULL,
        ThueTNCN DECIMAL(18,0) NOT NULL DEFAULT 0,
        BHXH_NLD DECIMAL(18,0) NOT NULL DEFAULT 0,
        BHYT_NLD DECIMAL(18,0) NOT NULL DEFAULT 0,
        BHTN_NLD DECIMAL(18,0) NOT NULL DEFAULT 0,
        BHXHDN DECIMAL(18,0) NOT NULL DEFAULT 0,
        BHYTDN DECIMAL(18,0) NOT NULL DEFAULT 0,
        BHTNDN DECIMAL(18,0) NOT NULL DEFAULT 0,
        BH_TNLDBNN_DN DECIMAL(18,0) NOT NULL DEFAULT 0,
        LuongThucLinh DECIMAL(18,0) NOT NULL DEFAULT 0,
        CONSTRAINT UQ_Luong_NhanVien_Ky UNIQUE(MaNV,Thang,Nam))""",
    ),
    (
        "TaiKhoan",
        """CREATE TABLE TaiKhoan(
        MaTK INT IDENTITY PRIMARY KEY,
        TenDN NVARCHAR(50) NOT NULL UNIQUE,
        MatKhau NVARCHAR(256) NOT NULL,
        VaiTro NVARCHAR(20) NOT NULL DEFAULT N'NhanVien',
        MaNV INT NULL REFERENCES NhanVien(MaNV),
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
]


def _create_database():
    if not re.fullmatch(r"[A-Za-z0-9_]+", DATABASE):
        raise ValueError("Tên database chứa ký tự không hợp lệ.")
    connection = pyodbc.connect(conn_str("master"), autocommit=True)
    try:
        connection.cursor().execute(f"IF DB_ID(N'{DATABASE}') IS NULL CREATE DATABASE [{DATABASE}]")
    finally:
        connection.close()


def _provision_core_schema():
    from schema_setup import ensure_schema

    for name, ddl in CORE_TABLES:
        db_sql = f"IF OBJECT_ID(N'dbo.{name}',N'U') IS NULL {ddl}"
        db.execute(db_sql)
    ensure_schema()


def _seed_defaults():
    for department in ("Phòng Nhân sự", "Phòng Kế toán", "Phòng Kinh doanh"):
        db.execute(
            "IF NOT EXISTS(SELECT 1 FROM PhongBan WHERE TenPB=?) INSERT INTO PhongBan(TenPB) VALUES(?)",
            (department, department),
        )
    for title in ("Giám đốc", "Trưởng phòng", "Nhân viên"):
        db.execute(
            "IF NOT EXISTS(SELECT 1 FROM ChucVu WHERE TenCV=?) INSERT INTO ChucVu(TenCV) VALUES(?)",
            (title, title),
        )
    if not db.scalar("SELECT COUNT(*) FROM TaiKhoan WHERE TenDN=N'admin'"):
        password = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(18)
        db.execute(
            "INSERT INTO TaiKhoan(TenDN,MatKhau,VaiTro) VALUES(N'admin',?,N'QuanTri')",
            (hash_password(password),),
        )
        print(f"Tài khoản quản trị: admin / {password}")
        print("Lưu mật khẩu này an toàn; mật khẩu không hiển thị lại.")
    else:
        print("Tài khoản admin đã tồn tại; giữ nguyên mật khẩu hiện có.")


def main():
    from schema_migrations import begin_migration, finish_migration

    _create_database()
    begin_migration(db)
    _provision_core_schema()
    _seed_defaults()
    finish_migration(db)
    print(f"Database {DATABASE} đã sẵn sàng cho 8 phân hệ.")


if __name__ == "__main__":
    main()
