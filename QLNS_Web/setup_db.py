"""Chạy 1 lần: tạo database, các bảng, dữ liệu mẫu và tài khoản admin.

Mật khẩu admin lấy từ biến môi trường ADMIN_PASSWORD (10-256 ký tự); nếu chưa đặt,
chương trình tự sinh mật khẩu ngẫu nhiên và in ra MỘT LẦN khi tạo tài khoản."""

import os
import secrets

import pyodbc

from auth import hash_password
from config import DATABASE, conn_str

TABLES = [
    (
        "DonVi",
        """CREATE TABLE DonVi(
        MaDonVi INT IDENTITY PRIMARY KEY,
        TenDonVi NVARCHAR(120) NOT NULL UNIQUE,
        MaDonViCha INT NULL REFERENCES DonVi(MaDonVi),
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Hoạt động')""",
    ),
    (
        "PhongBan",
        """CREATE TABLE PhongBan(
        MaPB INT IDENTITY PRIMARY KEY, 
        TenPB NVARCHAR(100) NOT NULL UNIQUE,
        KyHieu NVARCHAR(10) NULL,
        MaDonVi INT NULL REFERENCES DonVi(MaDonVi),
        MaPBCha INT NULL REFERENCES PhongBan(MaPB),
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
        "ViTriCongViec",
        """CREATE TABLE ViTriCongViec(
        MaViTri INT IDENTITY PRIMARY KEY,
        TenViTri NVARCHAR(120) NOT NULL,
        MaPB INT NULL REFERENCES PhongBan(MaPB),
        MoTa NVARCHAR(255) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Hoạt động',
        CONSTRAINT UQ_ViTriCongViec UNIQUE(TenViTri,MaPB))""",
    ),
    (
        "PhongBan_ChucVu",
        """CREATE TABLE PhongBan_ChucVu(
        MaPB INT NOT NULL REFERENCES PhongBan(MaPB) ON DELETE CASCADE,
        MaCV INT NOT NULL REFERENCES ChucVu(MaCV) ON DELETE CASCADE,
        PRIMARY KEY(MaPB, MaCV))""",
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
        MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri),
        MaPB INT NULL REFERENCES PhongBan(MaPB), 
        MaCV INT NULL REFERENCES ChucVu(MaCV),
        MaNVHT NVARCHAR(20) NULL,
        LuongCoBan DECIMAL(18,0) NOT NULL DEFAULT 0, 
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang làm')""",
    ),
    (
        "NhanVienNguon",
        """CREATE TABLE NhanVienNguon(
        MaNguon BIGINT IDENTITY PRIMARY KEY,
        LoaiNguon NVARCHAR(30) NOT NULL,
        MaNguonNgoai NVARCHAR(100) NOT NULL,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_NhanVienNguon UNIQUE(LoaiNguon,MaNguonNgoai))""",
    ),
    (
        "TaiSanNhanVien",
        """CREATE TABLE TaiSanNhanVien(
        MaTaiSan BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        TenTaiSan NVARCHAR(120) NOT NULL,
        MaNoiBo NVARCHAR(60) NULL,
        Serial NVARCHAR(100) NULL,
        NgayCap DATE NOT NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang sử dụng'
            CHECK(TrangThai IN (N'Đang sử dụng',N'Đã thu hồi')),
        NgayThuHoi DATE NULL,
        TinhTrangThuHoi NVARCHAR(200) NULL,
        NguoiCap NVARCHAR(50) NOT NULL,
        NguoiThuHoi NVARCHAR(50) NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "NhatKyTaiSanNhanVien",
        """CREATE TABLE NhatKyTaiSanNhanVien(
        MaNhatKy BIGINT IDENTITY PRIMARY KEY,
        MaTaiSan BIGINT NOT NULL REFERENCES TaiSanNhanVien(MaTaiSan),
        ThaoTac NVARCHAR(20) NOT NULL CHECK(ThaoTac IN (N'cấp',N'thu hồi')),
        NguoiThucHien NVARCHAR(50) NOT NULL,
        ChiTiet NVARCHAR(500) NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "YeuCauTuyenDung",
        """CREATE TABLE YeuCauTuyenDung(
        MaYeuCau INT IDENTITY PRIMARY KEY,
        TieuDe NVARCHAR(120) NOT NULL,
        MaPB INT NULL REFERENCES PhongBan(MaPB),
        MaCV INT NULL REFERENCES ChucVu(MaCV),
        MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri),
        SoLuong SMALLINT NOT NULL DEFAULT 1,
        MoTa NVARCHAR(2000) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang tuyển',
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(SoLuong BETWEEN 1 AND 500))""",
    ),
    (
        "UngVien",
        """CREATE TABLE UngVien(
        MaUngVien BIGINT IDENTITY PRIMARY KEY,
        MaYeuCau INT NOT NULL REFERENCES YeuCauTuyenDung(MaYeuCau),
        HoTen NVARCHAR(100) NOT NULL,
        Email NVARCHAR(100) NULL,
        SDT NVARCHAR(20) NULL,
        KenhNguon NVARCHAR(80) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Mới',
        MaNV INT NULL UNIQUE REFERENCES NhanVien(MaNV),
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "PhongVanUngVien",
        """CREATE TABLE PhongVanUngVien(
        MaPhongVan BIGINT IDENTITY PRIMARY KEY,
        MaUngVien BIGINT NOT NULL REFERENCES UngVien(MaUngVien),
        ThoiDiem DATETIME2 NOT NULL,
        HinhThuc NVARCHAR(40) NOT NULL,
        NguoiPhongVan NVARCHAR(100) NOT NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đã lên lịch',
        GhiChu NVARCHAR(1000) NULL,
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "DanhGiaUngVien",
        """CREATE TABLE DanhGiaUngVien(
        MaDanhGia BIGINT IDENTITY PRIMARY KEY,
        MaPhongVan BIGINT NOT NULL REFERENCES PhongVanUngVien(MaPhongVan),
        Diem TINYINT NOT NULL CHECK(Diem BETWEEN 1 AND 5),
        NhanXet NVARCHAR(2000) NOT NULL,
        NguoiDanhGia NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "OfferUngVien",
        """CREATE TABLE OfferUngVien(
        MaOffer BIGINT IDENTITY PRIMARY KEY,
        MaUngVien BIGINT NOT NULL REFERENCES UngVien(MaUngVien),
        LuongDeXuat DECIMAL(18,0) NOT NULL,
        NgayBatDau DATE NOT NULL,
        HanPhanHoi DATE NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Bản nháp',
        MaNV INT NULL REFERENCES NhanVien(MaNV),
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(LuongDeXuat>=0),
        UNIQUE(MaUngVien))""",
    ),
    (
        "MauChecklistNhanSu",
        """CREATE TABLE MauChecklistNhanSu(
        MaMau INT IDENTITY PRIMARY KEY,
        GiaiDoan NVARCHAR(20) NOT NULL CHECK(GiaiDoan IN (N'Onboarding',N'Offboarding')),
        TenViec NVARCHAR(160) NOT NULL,
        BoPhanPhuTrach NVARCHAR(80) NOT NULL,
        SoNgayHan SMALLINT NOT NULL DEFAULT 0,
        TrangThai BIT NOT NULL DEFAULT 1,
        UNIQUE(GiaiDoan,TenViec))""",
    ),
    (
        "VongDoiNhanVien",
        """CREATE TABLE VongDoiNhanVien(
        MaVongDoi BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        GiaiDoan NVARCHAR(20) NOT NULL,
        NgayBatDau DATE NOT NULL,
        NgayHieuLucKetThuc DATE NULL,
        LyDo NVARCHAR(500) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang xử lý',
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(GiaiDoan IN (N'Onboarding',N'Offboarding')))""",
    ),
    (
        "ChecklistNhanVien",
        """CREATE TABLE ChecklistNhanVien(
        MaChecklist BIGINT IDENTITY PRIMARY KEY,
        MaVongDoi BIGINT NOT NULL REFERENCES VongDoiNhanVien(MaVongDoi),
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        TenViec NVARCHAR(160) NOT NULL,
        BoPhanPhuTrach NVARCHAR(80) NOT NULL,
        HanHoanThanh DATE NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chưa làm',
        HoanThanhBoi NVARCHAR(50) NULL,
        HoanThanhLuc DATETIME2 NULL,
        GhiChu NVARCHAR(500) NULL)""",
    ),
    (
        "ChuKyKPI",
        """CREATE TABLE ChuKyKPI(
        MaChuKy INT IDENTITY PRIMARY KEY,
        TenChuKy NVARCHAR(120) NOT NULL,
        TuNgay DATE NOT NULL,
        DenNgay DATE NOT NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang mở',
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(DenNgay>=TuNgay))""",
    ),
    (
        "MucTieuKPI",
        """CREATE TABLE MucTieuKPI(
        MaMucTieu BIGINT IDENTITY PRIMARY KEY,
        MaChuKy INT NOT NULL REFERENCES ChuKyKPI(MaChuKy),
        MaNV INT NULL REFERENCES NhanVien(MaNV),
        MaPB INT NULL REFERENCES PhongBan(MaPB),
        TenMucTieu NVARCHAR(160) NOT NULL,
        MoTa NVARCHAR(1000) NULL,
        GiaTriMucTieu DECIMAL(18,2) NOT NULL,
        DonVi NVARCHAR(40) NOT NULL,
        TrongSo DECIMAL(5,2) NOT NULL DEFAULT 0,
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(GiaTriMucTieu>=0),
        CHECK(TrongSo BETWEEN 0 AND 100),
        CHECK((MaNV IS NOT NULL AND MaPB IS NULL) OR (MaNV IS NULL AND MaPB IS NOT NULL)))""",
    ),
    (
        "KetQuaKPI",
        """CREATE TABLE KetQuaKPI(
        MaKetQua BIGINT IDENTITY PRIMARY KEY,
        MaMucTieu BIGINT NOT NULL REFERENCES MucTieuKPI(MaMucTieu),
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        GiaTriThucTe DECIMAL(18,2) NOT NULL DEFAULT 0,
        TienDo DECIMAL(5,2) NOT NULL DEFAULT 0,
        NhanXet NVARCHAR(1000) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp',
        NguoiCapNhat NVARCHAR(50) NOT NULL,
        CapNhatLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        NguoiDuyet NVARCHAR(50) NULL,
        DuyetLuc DATETIME2 NULL,
        UNIQUE(MaMucTieu,MaNV),
        CHECK(GiaTriThucTe>=0),
        CHECK(TienDo BETWEEN 0 AND 100))""",
    ),
    (
        "PhanHoiKPI",
        """CREATE TABLE PhanHoiKPI(
        MaPhanHoi BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        MaChuKy INT NULL REFERENCES ChuKyKPI(MaChuKy),
        NguoiGui NVARCHAR(50) NOT NULL,
        LoaiPhanHoi NVARCHAR(30) NOT NULL,
        NoiDung NVARCHAR(2000) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "KhoaDaoTao",
        """CREATE TABLE KhoaDaoTao(
        MaKhoa INT IDENTITY PRIMARY KEY,
        TenKhoa NVARCHAR(160) NOT NULL,
        NhaCungCap NVARCHAR(120) NULL,
        MoTa NVARCHAR(1000) NULL,
        SoGio DECIMAL(6,2) NOT NULL DEFAULT 0,
        HieuLucChungChiThang SMALLINT NULL,
        TrangThai BIT NOT NULL DEFAULT 1,
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(SoGio>=0),
        CHECK(HieuLucChungChiThang IS NULL OR HieuLucChungChiThang BETWEEN 1 AND 600))""",
    ),
    (
        "DangKyDaoTao",
        """CREATE TABLE DangKyDaoTao(
        MaDangKy BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        MaKhoa INT NOT NULL REFERENCES KhoaDaoTao(MaKhoa),
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt',
        NgayDangKy DATE NOT NULL DEFAULT CAST(GETDATE() AS DATE),
        NgayBatDau DATE NULL,
        NgayHoanThanh DATE NULL,
        TenChungChi NVARCHAR(160) NULL,
        HanChungChi DATE NULL,
        GhiChu NVARCHAR(500) NULL,
        NguoiDuyet NVARCHAR(50) NULL,
        DuyetLuc DATETIME2 NULL,
        UNIQUE(MaNV,MaKhoa))""",
    ),
    (
        "KyNang",
        """CREATE TABLE KyNang(
        MaKyNang INT IDENTITY PRIMARY KEY,
        TenKyNang NVARCHAR(100) NOT NULL UNIQUE,
        LinhVuc NVARCHAR(80) NULL,
        TrangThai BIT NOT NULL DEFAULT 1)""",
    ),
    (
        "NhanVienKyNang",
        """CREATE TABLE NhanVienKyNang(
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        MaKyNang INT NOT NULL REFERENCES KyNang(MaKyNang),
        CapDo TINYINT NOT NULL CHECK(CapDo BETWEEN 1 AND 5),
        MucTieuCapDo TINYINT NULL CHECK(MucTieuCapDo IS NULL OR MucTieuCapDo BETWEEN 1 AND 5),
        DuocXacNhanBoi NVARCHAR(50) NULL,
        CapNhatLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        PRIMARY KEY(MaNV,MaKyNang))""",
    ),
    (
        "KeHoachPhatTrien",
        """CREATE TABLE KeHoachPhatTrien(
        MaKeHoach BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        TenVaiTroMucTieu NVARCHAR(120) NULL,
        KyNangCanPhatTrien NVARCHAR(1000) NOT NULL,
        HanMucTieu DATE NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Đang thực hiện',
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "PhucLoi",
        """CREATE TABLE PhucLoi(
        MaPhucLoi INT IDENTITY PRIMARY KEY,
        TenPhucLoi NVARCHAR(120) NOT NULL UNIQUE,
        MoTa NVARCHAR(1000) NULL,
        DieuKienHuong NVARCHAR(1000) NULL,
        TrangThai BIT NOT NULL DEFAULT 1,
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "DangKyPhucLoi",
        """CREATE TABLE DangKyPhucLoi(
        MaDangKy BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        MaPhucLoi INT NOT NULL REFERENCES PhucLoi(MaPhucLoi),
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt',
        NgayDangKy DATE NOT NULL DEFAULT CAST(GETDATE() AS DATE),
        GhiChu NVARCHAR(500) NULL,
        NguoiDuyet NVARCHAR(50) NULL,
        DuyetLuc DATETIME2 NULL,
        UNIQUE(MaNV,MaPhucLoi))""",
    ),
    (
        "KeHoachDinhBien",
        """CREATE TABLE KeHoachDinhBien(
        MaKeHoach INT IDENTITY PRIMARY KEY,
        Nam SMALLINT NOT NULL,
        MaPB INT NOT NULL REFERENCES PhongBan(MaPB),
        MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri),
        SoLuongKeHoach SMALLINT NOT NULL,
        ChiPhiDuKien DECIMAL(18,0) NOT NULL DEFAULT 0,
        LyDo NVARCHAR(500) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp',
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(Nam BETWEEN 2000 AND 2100),
        CHECK(SoLuongKeHoach BETWEEN 0 AND 50000),
        CHECK(ChiPhiDuKien>=0))""",
    ),
    (
        "KeHoachKeNhiem",
        """CREATE TABLE KeHoachKeNhiem(
        MaKeNhiem BIGINT IDENTITY PRIMARY KEY,
        MaViTri INT NOT NULL REFERENCES ViTriCongViec(MaViTri),
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        MucDoSanSang NVARCHAR(20) NOT NULL,
        KhoangTrongKyNang NVARCHAR(1000) NULL,
        GhiChu NVARCHAR(500) NULL,
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(MucDoSanSang IN (N'Sẵn sàng',N'6-12 tháng',N'12-24 tháng',N'Cần phát triển')))""",
    ),
    (
        "LichSuCongTac",
        """CREATE TABLE LichSuCongTac(
        MaLichSu BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        TuNgay DATE NOT NULL,
        DenNgay DATE NULL,
        MaPB INT NULL REFERENCES PhongBan(MaPB),
        MaCV INT NULL REFERENCES ChucVu(MaCV),
        MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri),
        MaQuanLy INT NULL REFERENCES NhanVien(MaNV),
        LuongCoBan DECIMAL(18,0) NOT NULL DEFAULT 0,
        NguoiCapNhat NVARCHAR(50) NOT NULL,
        LyDo NVARCHAR(500) NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_LichSuCongTac_Ngay CHECK(DenNgay IS NULL OR DenNgay>=TuNgay))""",
    ),
    (
        "NhatKyHoSoNhanVien",
        """CREATE TABLE NhatKyHoSoNhanVien(
        MaNhatKy BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL,
        HanhDong NVARCHAR(20) NOT NULL,
        TruongDuLieu NVARCHAR(80) NULL,
        NguoiThucHien NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "NhatKyTruyCapNhanSu",
        """CREATE TABLE NhatKyTruyCapNhanSu(
        MaNhatKy BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NULL,
        LoaiDuLieu NVARCHAR(30) NOT NULL CHECK(LoaiDuLieu IN (N'CCCD',N'LienHe',N'Luong',N'HopDong',N'HoSoDienTu')),
        ThaoTac NVARCHAR(12) NOT NULL CHECK(ThaoTac IN (N'view',N'list',N'download',N'export')),
        NguoiThucHien NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "HoSoTepNhanVien",
        """CREATE TABLE HoSoTepNhanVien(
        MaTep BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        LoaiTaiLieu NVARCHAR(60) NOT NULL,
        TenTep NVARCHAR(180) NOT NULL,
        DinhDang NVARCHAR(20) NOT NULL,
        DuLieu VARBINARY(MAX) NOT NULL,
        NgayHieuLuc DATE NULL,
        HanLuuDen DATE NULL,
        NguoiTai NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "NhatKyHoSoTep",
        """CREATE TABLE NhatKyHoSoTep(
        MaNhatKy BIGINT IDENTITY PRIMARY KEY,
        MaTep BIGINT NULL,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        ThaoTac NVARCHAR(30) NOT NULL,
        NguoiThucHien NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "TruongMoRongNhanVien",
        """CREATE TABLE TruongMoRongNhanVien(
        MaTruong INT IDENTITY PRIMARY KEY,
        TenTruong NVARCHAR(80) NOT NULL UNIQUE,
        KieuDuLieu NVARCHAR(12) NOT NULL CHECK(KieuDuLieu IN (N'text',N'number',N'date',N'boolean',N'email')),
        BatBuoc BIT NOT NULL DEFAULT 0,
        NhayCam BIT NOT NULL DEFAULT 0,
        TrangThai BIT NOT NULL DEFAULT 1,
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "GiaTriMoRongNhanVien",
        """CREATE TABLE GiaTriMoRongNhanVien(
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        MaTruong INT NOT NULL REFERENCES TruongMoRongNhanVien(MaTruong),
        GiaTri NVARCHAR(1000) NOT NULL,
        CapNhatBoi NVARCHAR(50) NOT NULL,
        CapNhatLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_GiaTriMoRongNhanVien PRIMARY KEY(MaNV,MaTruong))""",
    ),
    (
        "NhatKyTruongNhanVien",
        """CREATE TABLE NhatKyTruongNhanVien(
        MaNhatKy BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        MaTruong INT NOT NULL REFERENCES TruongMoRongNhanVien(MaTruong),
        NguoiThucHien NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "HopDong",
        """CREATE TABLE HopDong(
        MaHD INT IDENTITY PRIMARY KEY, 
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        LoaiHD NVARCHAR(50) NOT NULL, 
        NgayBatDau DATE NOT NULL, 
        NgayKetThuc DATE NULL,
        LuongHD DECIMAL(18,0) NOT NULL DEFAULT 0, 
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
        CONSTRAINT UQ_CC UNIQUE(MaNV, Ngay))""",
    ),
    (
        "ChamCongSuKien",
        """CREATE TABLE ChamCongSuKien(
        MaSuKien BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        NgayCong DATE NOT NULL,
        MaCC INT NULL REFERENCES ChamCong(MaCC),
        ThoiDiem DATETIME2 NOT NULL,
        LoaiSuKien NVARCHAR(20) NOT NULL,
        Nguon NVARCHAR(20) NOT NULL,
        KetQua NVARCHAR(30) NOT NULL,
        Similarity DECIMAL(7,5) NULL,
        NguoiThucHien NVARCHAR(50) NULL,
        ChiTiet NVARCHAR(500) NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "CaLamViec",
        """CREATE TABLE CaLamViec(
        MaCa INT IDENTITY PRIMARY KEY,
        TenCa NVARCHAR(80) NOT NULL UNIQUE,
        GioBatDau TIME NOT NULL,
        GioKetThuc TIME NOT NULL,
        QuaDem BIT NOT NULL DEFAULT 0,
        PhutAnHan SMALLINT NOT NULL DEFAULT 0,
        TrangThai BIT NOT NULL DEFAULT 1,
        CHECK(GioBatDau<>GioKetThuc),
        CHECK(PhutAnHan BETWEEN 0 AND 240))""",
    ),
    (
        "PhanCaNhanVien",
        """CREATE TABLE PhanCaNhanVien(
        MaPhanCa BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        MaCa INT NOT NULL REFERENCES CaLamViec(MaCa),
        Ngay DATE NOT NULL,
        NguoiPhan NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_PhanCaNhanVien UNIQUE(MaNV,MaCa,Ngay))""",
    ),
    (
        "LichNgayLe",
        """CREATE TABLE LichNgayLe(
        MaNgayLe INT IDENTITY PRIMARY KEY,
        Ngay DATE NOT NULL UNIQUE,
        TenNgay NVARCHAR(120) NOT NULL,
        HuongLuong BIT NOT NULL DEFAULT 1,
        NguoiTao NVARCHAR(50) NOT NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "TangCaYeuCau",
        """CREATE TABLE TangCaYeuCau(
        MaYeuCau BIGINT IDENTITY PRIMARY KEY,
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        BatDau DATETIME2 NOT NULL,
        KetThuc DATETIME2 NOT NULL,
        SoGio DECIMAL(5,2) NOT NULL,
        SoGioThucTe DECIMAL(5,2) NULL,
        LyDo NVARCHAR(500) NOT NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt',
        NguoiDuyet NVARCHAR(50) NULL,
        DuyetLuc DATETIME2 NULL,
        XacNhanBoi NVARCHAR(50) NULL,
        XacNhanLuc DATETIME2 NULL,
        PhanHoi NVARCHAR(500) NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        CHECK(KetThuc>BatDau),
        CHECK(SoGio>0 AND SoGio<=24))""",
    ),
    (
        "NhatKyTangCa",
        """CREATE TABLE NhatKyTangCa(
        MaNhatKy BIGINT IDENTITY PRIMARY KEY,
        MaYeuCau BIGINT NOT NULL REFERENCES TangCaYeuCau(MaYeuCau),
        ThaoTac NVARCHAR(30) NOT NULL,
        TrangThaiCu NVARCHAR(20) NULL,
        TrangThaiMoi NVARCHAR(20) NOT NULL,
        NguoiThucHien NVARCHAR(50) NOT NULL,
        LyDo NVARCHAR(500) NULL,
        TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())""",
    ),
    (
        "NghiPhep",
        """CREATE TABLE NghiPhep(
        MaNP INT IDENTITY PRIMARY KEY, 
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        TuNgay DATE NOT NULL, 
        DenNgay DATE NOT NULL, 
        SoNgay INT NOT NULL, 
        LyDo NVARCHAR(255) NULL,
        TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt')""",
    ),
    (
        "Luong",
        """CREATE TABLE Luong(
        MaLuong INT IDENTITY PRIMARY KEY, 
        MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
        Thang INT NOT NULL, 
        Nam INT NOT NULL, 
        NgayCong DECIMAL(5,1) NOT NULL DEFAULT 0,
        LuongCB DECIMAL(18,0) NOT NULL DEFAULT 0, 
        PhuCap DECIMAL(18,0) NOT NULL DEFAULT 0,
        KhauTru DECIMAL(18,0) NOT NULL DEFAULT 0, 
        TongLuong DECIMAL(18,0) NOT NULL DEFAULT 0,
        ThuongCC DECIMAL(18,0) NOT NULL DEFAULT 0, GioTangCa DECIMAL(7,2) NOT NULL DEFAULT 0,
        TienTangCa DECIMAL(18,0) NOT NULL DEFAULT 0, SoLanMuon INT NOT NULL DEFAULT 0,
        TruMuon DECIMAL(18,0) NOT NULL DEFAULT 0, SoNgayNghiKP INT NOT NULL DEFAULT 0,
        TruNghiKP DECIMAL(18,0) NOT NULL DEFAULT 0,
        GioGhiNhan DECIMAL(8,2) NULL,
        CONSTRAINT UQ_Luong UNIQUE(MaNV, Thang, Nam))""",
    ),
    (
        "TaiKhoan",
        """CREATE TABLE TaiKhoan(
        TenDN NVARCHAR(50) PRIMARY KEY, 
        MatKhau NVARCHAR(200) NOT NULL,
        VaiTro NVARCHAR(20) NOT NULL CHECK (VaiTro IN (N'QuanTri',N'QuanTriHeThong',N'HR',N'KeToan',N'QuanLy',N'NhanVien')),
        SecurityVersion INT NOT NULL DEFAULT 1,
        MaNV INT NULL REFERENCES NhanVien(MaNV))""",
    ),
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
        for t in [
            "Phòng Nhân sự",
            "Phòng Kế toán",
            "Phòng Kinh doanh",
            "Phòng Kỹ thuật",
            "Phòng Marketing",
        ]:
            cur.execute("INSERT INTO PhongBan(TenPB) VALUES(?)", t)
    if cur.execute("SELECT COUNT(*) FROM ChucVu").fetchval() == 0:
        for t in [
            "Giám đốc",
            "Trưởng phòng",
            "Phó phòng",
            "Nhân viên",
            "Kỹ thuật viên",
        ]:
            cur.execute("INSERT INTO ChucVu(TenCV) VALUES(?)", t)
    new_admin_pw = None
    if cur.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TenDN='admin'").fetchval() == 0:
        new_admin_pw = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
        if not 10 <= len(new_admin_pw) <= 256:
            raise SystemExit("ADMIN_PASSWORD phải dài từ 10 đến 256 ký tự.")
        cur.execute(
            "INSERT INTO TaiKhoan(TenDN, MatKhau, VaiTro) VALUES('admin', ?, N'QuanTri')",
            hash_password(new_admin_pw),
        )
    c.close()
    print(f"Xong. Database {DATABASE} đã sẵn sàng.")
    if new_admin_pw:
        print(f"Tài khoản quản trị: admin / {new_admin_pw}")
        print("Hãy lưu mật khẩu này và đổi lại sau khi đăng nhập; mật khẩu sẽ không hiển thị lần nữa.")
    else:
        print("Tài khoản admin đã tồn tại, giữ nguyên mật khẩu hiện có.")


if __name__ == "__main__":
    main()
