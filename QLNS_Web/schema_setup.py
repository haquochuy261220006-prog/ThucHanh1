import re
import unicodedata

import db


_KY_MAC_DINH = {
    "nhan su": "NS",
    "ke toan": "KTO",
    "kinh doanh": "KD",
    "ky thuat": "KT",
    "marketing": "MKT",
}


def _bo_dau(t):
    t = unicodedata.normalize("NFD", t.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def assign_codes():
    """Cấp Mã NV hiển thị = NV + số thứ tự chung 2 chữ số + ký hiệu phòng ở cuối (NV01KT, NV02NS...)."""
    rows = db.query(
        "SELECT n.MaNV,p.KyHieu FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB WHERE n.MaNVHT IS NULL ORDER BY n.MaNV"
    )[1]
    if not rows:
        return
    mx = 0
    for (code,) in db.query("SELECT MaNVHT FROM NhanVien WHERE MaNVHT IS NOT NULL")[1]:
        m = re.fullmatch(r"NV(\d+)[A-Z]*", code or "")
        if m:
            mx = max(mx, int(m.group(1)))
    for manv, ky in rows:
        mx += 1
        db.execute(
            "UPDATE NhanVien SET MaNVHT=? WHERE MaNV=?",
            ("NV%02d%s" % (mx, (ky or "").upper()), manv),
        )


def ensure_schema():
    db.execute(
        "IF OBJECT_ID('DonVi','U') IS NULL CREATE TABLE DonVi(MaDonVi INT IDENTITY PRIMARY KEY,TenDonVi NVARCHAR(120) NOT NULL UNIQUE,MaDonViCha INT NULL REFERENCES DonVi(MaDonVi),TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Hoạt động')"
    )
    db.execute(
        "IF COL_LENGTH('PhongBan','MaDonVi') IS NULL ALTER TABLE PhongBan ADD MaDonVi INT NULL REFERENCES DonVi(MaDonVi)"
    )
    db.execute(
        "IF COL_LENGTH('PhongBan','MaPBCha') IS NULL ALTER TABLE PhongBan ADD MaPBCha INT NULL REFERENCES PhongBan(MaPB)"
    )
    db.execute(
        "IF OBJECT_ID('ViTriCongViec','U') IS NULL CREATE TABLE ViTriCongViec(MaViTri INT IDENTITY PRIMARY KEY,TenViTri NVARCHAR(120) NOT NULL,MaPB INT NULL REFERENCES PhongBan(MaPB),MoTa NVARCHAR(255) NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Hoạt động',CONSTRAINT UQ_ViTriCongViec UNIQUE(TenViTri,MaPB))"
    )
    db.execute(
        "IF COL_LENGTH('NhanVien','MaViTri') IS NULL ALTER TABLE NhanVien ADD MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri)"
    )
    db.execute(
        "IF OBJECT_ID('LichSuCongTac','U') IS NULL CREATE TABLE LichSuCongTac(MaLichSu BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),TuNgay DATE NOT NULL,DenNgay DATE NULL,MaPB INT NULL REFERENCES PhongBan(MaPB),MaCV INT NULL REFERENCES ChucVu(MaCV),MaViTri INT NULL REFERENCES ViTriCongViec(MaViTri),MaQuanLy INT NULL REFERENCES NhanVien(MaNV),LuongCoBan DECIMAL(18,0) NOT NULL DEFAULT 0,NguoiCapNhat NVARCHAR(50) NOT NULL,LyDo NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CONSTRAINT CK_LichSuCongTac_Ngay CHECK(DenNgay IS NULL OR DenNgay>=TuNgay))"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyHoSoNhanVien','U') IS NULL CREATE TABLE NhatKyHoSoNhanVien(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL,HanhDong NVARCHAR(20) NOT NULL,TruongDuLieu NVARCHAR(80) NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyTruyCapNhanSu','U') IS NULL CREATE TABLE NhatKyTruyCapNhanSu(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaNV INT NULL,LoaiDuLieu NVARCHAR(30) NOT NULL CHECK(LoaiDuLieu IN (N'CCCD',N'LienHe',N'Luong',N'HopDong',N'HoSoDienTu')),ThaoTac NVARCHAR(12) NOT NULL CHECK(ThaoTac IN (N'view',N'list',N'download',N'export')),NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF COL_LENGTH('LichSuCongTac','MaQuanLy') IS NULL ALTER TABLE LichSuCongTac ADD MaQuanLy INT NULL REFERENCES NhanVien(MaNV)"
    )
    db.execute(
        "INSERT INTO LichSuCongTac(MaNV,TuNgay,MaPB,MaCV,MaViTri,MaQuanLy,LuongCoBan,NguoiCapNhat,LyDo) SELECT n.MaNV,CAST(GETDATE() AS DATE),n.MaPB,n.MaCV,n.MaViTri,NULL,n.LuongCoBan,N'system',N'Khởi tạo mốc hiện trạng khi nâng cấp' FROM NhanVien n WHERE NOT EXISTS(SELECT 1 FROM LichSuCongTac l WHERE l.MaNV=n.MaNV AND l.DenNgay IS NULL)"
    )
    db.execute(
        "IF OBJECT_ID('HoSoTepNhanVien','U') IS NULL CREATE TABLE HoSoTepNhanVien(MaTep BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),LoaiTaiLieu NVARCHAR(60) NOT NULL,TenTep NVARCHAR(180) NOT NULL,DinhDang NVARCHAR(20) NOT NULL,DuLieu VARBINARY(MAX) NOT NULL,NgayHieuLuc DATE NULL,HanLuuDen DATE NULL,NguoiTai NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyHoSoTep','U') IS NULL CREATE TABLE NhatKyHoSoTep(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaTep BIGINT NULL,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),ThaoTac NVARCHAR(30) NOT NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF COL_LENGTH('PhongBan','KyHieu') IS NULL ALTER TABLE PhongBan ADD KyHieu NVARCHAR(10) NULL"
    )
    db.execute(
        "IF COL_LENGTH('NhanVien','MaNVHT') IS NULL ALTER TABLE NhanVien ADD MaNVHT NVARCHAR(20) NULL"
    )
    db.execute(
        "IF COL_LENGTH('NhanVien','AnhHoSo') IS NULL ALTER TABLE NhanVien ADD AnhHoSo VARBINARY(MAX) NULL"
    )
    db.execute(
        "IF OBJECT_ID('NhanVienNguon','U') IS NULL CREATE TABLE NhanVienNguon("
        "MaNguon BIGINT IDENTITY PRIMARY KEY,LoaiNguon NVARCHAR(30) NOT NULL,"
        "MaNguonNgoai NVARCHAR(100) NOT NULL,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),"
        "NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),"
        "CONSTRAINT UQ_NhanVienNguon UNIQUE(LoaiNguon,MaNguonNgoai))"
    )
    db.execute(
        "IF COL_LENGTH('TaiKhoan','SecurityVersion') IS NULL ALTER TABLE TaiKhoan ADD SecurityVersion INT NOT NULL CONSTRAINT DF_TaiKhoan_SecurityVersion DEFAULT 1"
    )
    db.execute(
        "IF OBJECT_ID('CK_TaiKhoan_VaiTro','C') IS NULL BEGIN "
        "DECLARE @roleCheck SYSNAME, @roleSql NVARCHAR(MAX); "
        "SELECT TOP (1) @roleCheck=name FROM sys.check_constraints "
        "WHERE parent_object_id=OBJECT_ID('dbo.TaiKhoan') AND definition LIKE '%VaiTro%'; "
        "IF @roleCheck IS NOT NULL BEGIN "
        "SET @roleSql=N'ALTER TABLE dbo.TaiKhoan DROP CONSTRAINT '+QUOTENAME(@roleCheck); "
        "EXEC sys.sp_executesql @roleSql; END; "
        "ALTER TABLE dbo.TaiKhoan ADD CONSTRAINT CK_TaiKhoan_VaiTro "
        "CHECK(VaiTro IN (N'QuanTri',N'QuanTriHeThong',N'HR',N'KeToan',N'QuanLy',N'NhanVien')); END"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyPhanQuyen','U') IS NULL CREATE TABLE NhatKyPhanQuyen(MaNhatKy BIGINT IDENTITY PRIMARY KEY,TenDN NVARCHAR(50) NOT NULL,VaiTroCu NVARCHAR(20) NULL,VaiTroMoi NVARCHAR(20) NULL,ThaoTac NVARCHAR(20) NOT NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF OBJECT_ID('MauHopDong','U') IS NULL CREATE TABLE MauHopDong(MaMau INT IDENTITY(1,1) PRIMARY KEY,TenMau NVARCHAR(120) NOT NULL,FileName NVARCHAR(180) NOT NULL,NoiDung NVARCHAR(MAX) NOT NULL,TepDocx VARBINARY(MAX) NOT NULL,NgayTai DATETIME2 NOT NULL DEFAULT SYSDATETIME())"
    )
    for col, typ in [
        ("ThuongCC", "DECIMAL(18,0)"),
        ("ThuongThem", "DECIMAL(18,0)"),
        ("GioTangCa", "DECIMAL(7,2)"),
        ("TienTangCa", "DECIMAL(18,0)"),
        ("SoLanMuon", "INT"),
        ("TruMuon", "DECIMAL(18,0)"),
        ("SoNgayNghiKP", "INT"),
        ("TruNghiKP", "DECIMAL(18,0)"),
    ]:
        db.execute(
            f"IF COL_LENGTH('Luong','{col}') IS NULL ALTER TABLE Luong ADD {col} {typ} NOT NULL DEFAULT 0"
        )
    db.execute(
        "IF COL_LENGTH('Luong','GioGhiNhan') IS NULL ALTER TABLE Luong ADD GioGhiNhan DECIMAL(8,2) NULL"
    )
    db.execute(
        "IF COL_LENGTH('Luong','LuongDieuChinh') IS NULL ALTER TABLE Luong ADD LuongDieuChinh DECIMAL(18,0) NULL"
    )
    db.execute(
        "IF OBJECT_ID('LuongCauHinhThang','U') IS NULL CREATE TABLE LuongCauHinhThang(Nam INT NOT NULL,Thang INT NOT NULL,TyLeThuongCC DECIMAL(6,4) NOT NULL,HeSoTangCa DECIMAL(5,2) NOT NULL,CONSTRAINT PK_LuongCauHinhThang PRIMARY KEY(Nam,Thang))"
    )
    pbs = db.query("SELECT MaPB,TenPB,KyHieu FROM PhongBan ORDER BY MaPB")[1]
    used = {r[2] for r in pbs if r[2]}
    for mapb, ten, ky in pbs:
        if ky:
            continue
        base = _bo_dau(re.sub(r"(?i)^(phòng|ban)\s+", "", ten.strip())).lower()
        cand = (
            _KY_MAC_DINH.get(base)
            or "".join(w[0] for w in base.split() if w[:1].isalpha()).upper()[:5]
            or "PB"
        )
        cand = re.sub("[^A-Z]", "", cand.upper()) or "PB"
        k = cand
        i = 2
        while k in used:
            k = cand[:4] + chr(64 + i)
            i += 1
        used.add(k)
        db.execute("UPDATE PhongBan SET KyHieu=? WHERE MaPB=?", (k, mapb))
    # đổi từ định dạng mã cũ (vd KT01) sang định dạng mới: cấp lại toàn bộ 1 lần
    if db.scalar(
        "SELECT COUNT(*) FROM NhanVien WHERE MaNVHT IS NOT NULL AND MaNVHT NOT LIKE 'NV[0-9]%'"
    ):
        db.execute("UPDATE NhanVien SET MaNVHT=NULL")
    assign_codes()
    db.execute(
        "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_PhongBan_KyHieu') CREATE UNIQUE INDEX UX_PhongBan_KyHieu ON PhongBan(KyHieu) WHERE KyHieu IS NOT NULL"
    )
    db.execute(
        "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_NhanVien_MaNVHT') CREATE UNIQUE INDEX UX_NhanVien_MaNVHT ON NhanVien(MaNVHT) WHERE MaNVHT IS NOT NULL"
    )
    db.execute(
        "IF OBJECT_ID('NhanVienKhuonMat','U') IS NULL CREATE TABLE NhanVienKhuonMat(MaNV INT NOT NULL PRIMARY KEY REFERENCES NhanVien(MaNV) ON DELETE CASCADE, Embedding NVARCHAR(MAX) NOT NULL, ConsentAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), ConsentVersion NVARCHAR(40) NOT NULL DEFAULT N'2026-10-v1', UpdatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF COL_LENGTH('NhanVienKhuonMat','ConsentVersion') IS NULL ALTER TABLE NhanVienKhuonMat ADD ConsentVersion NVARCHAR(40) NOT NULL DEFAULT N'2026-10-v1'"
    )
    db.execute(
        "IF OBJECT_ID('TaiKhoanOTP','U') IS NULL CREATE TABLE TaiKhoanOTP(MaNV INT NOT NULL PRIMARY KEY REFERENCES NhanVien(MaNV) ON DELETE CASCADE, RequestedBy NVARCHAR(50) NOT NULL, Channel NVARCHAR(10) NOT NULL, CodeHash CHAR(64) NOT NULL, SentAt DATETIME2 NOT NULL, ExpiresAt DATETIME2 NOT NULL, Attempts INT NOT NULL DEFAULT 0)"
    )
    db.execute(
        "IF OBJECT_ID('TepHopDong','U') IS NULL CREATE TABLE TepHopDong(MaTep INT IDENTITY(1,1) PRIMARY KEY, MaHD INT NOT NULL REFERENCES HopDong(MaHD) ON DELETE CASCADE, TenTep NVARCHAR(255) NOT NULL, DinhDang VARCHAR(10) NOT NULL, TepData VARBINARY(MAX) NOT NULL, NoiDung NVARCHAR(MAX) NOT NULL, NguoiTao NVARCHAR(50) NOT NULL, NgayTao DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    for col, typ in [
        ("NguoiLap", "NVARCHAR(50) NULL"),
        ("NguoiDuyet", "NVARCHAR(50) NULL"),
        ("NgayDuyet", "DATETIME2 NULL"),
        ("NgayKy", "DATE NULL"),
        ("NguoiKy", "NVARCHAR(50) NULL"),
        ("PhienBan", "INT NOT NULL DEFAULT 1"),
        ("HopDongGoc", "INT NULL"),
        ("LyDoChamDut", "NVARCHAR(1000) NULL"),
    ]:
        db.execute(f"IF COL_LENGTH('HopDong','{col}') IS NULL ALTER TABLE HopDong ADD {col} {typ}")
    db.execute(
        "DECLARE @df sysname, @sql nvarchar(max); "
        "SELECT @df=dc.name FROM sys.default_constraints dc "
        "JOIN sys.columns c ON c.default_object_id=dc.object_id "
        "WHERE dc.parent_object_id=OBJECT_ID(N'dbo.HopDong') AND c.name=N'TrangThai'; "
        "IF @df IS NOT NULL BEGIN "
        "SET @sql=N'ALTER TABLE dbo.HopDong DROP CONSTRAINT '+QUOTENAME(@df); "
        "EXEC sys.sp_executesql @sql; END; "
        "ALTER TABLE dbo.HopDong ADD CONSTRAINT DF_HopDong_TrangThai "
        "DEFAULT N'Bản nháp' FOR TrangThai"
    )
    for col, typ in [
        ("LoaiTaiLieu", "NVARCHAR(40) NOT NULL DEFAULT N'Bản nháp AI'"),
        ("TrangThai", "NVARCHAR(30) NOT NULL DEFAULT N'Bản nháp'"),
        ("PhienBan", "INT NOT NULL DEFAULT 1"),
        ("NguoiDuyet", "NVARCHAR(50) NULL"),
        ("NgayDuyet", "DATETIME2 NULL"),
        ("NgayKy", "DATE NULL"),
        ("GhiChu", "NVARCHAR(1000) NULL"),
    ]:
        db.execute(
            f"IF COL_LENGTH('TepHopDong','{col}') IS NULL ALTER TABLE TepHopDong ADD {col} {typ}"
        )
    db.execute(
        "IF OBJECT_ID('LichSuHopDong','U') IS NULL CREATE TABLE LichSuHopDong(MaLichSu BIGINT IDENTITY(1,1) PRIMARY KEY,MaHD INT NOT NULL REFERENCES HopDong(MaHD),HanhDong NVARCHAR(40) NOT NULL,TrangThaiCu NVARCHAR(30) NULL,TrangThaiMoi NVARCHAR(30) NULL,ChiTiet NVARCHAR(1000) NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "UPDATE HopDong SET TrangThai=N'Hết hạn' WHERE TrangThai IN (N'Còn hiệu lực',N'Đã ký') AND NgayKetThuc IS NOT NULL AND NgayKetThuc<CAST(GETDATE() AS DATE)"
    )
    db.execute(
        "UPDATE HopDong SET TrangThai=N'Còn hiệu lực' WHERE TrangThai=N'Đã ký' AND NgayBatDau<=CAST(GETDATE() AS DATE) AND (NgayKetThuc IS NULL OR NgayKetThuc>=CAST(GETDATE() AS DATE))"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyChamCong','U') IS NULL CREATE TABLE NhatKyChamCong(MaNhatKy BIGINT IDENTITY(1,1) PRIMARY KEY, MaCC INT NULL, MaNV INT NOT NULL, Nguon NVARCHAR(20) NOT NULL, ThaoTac NVARCHAR(30) NOT NULL, KetQua NVARCHAR(30) NOT NULL, Similarity DECIMAL(7,5) NULL, ThoiDiem DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), NguoiThucHien NVARCHAR(50) NULL, ChiTiet NVARCHAR(500) NULL)"
    )
    db.execute(
        "IF OBJECT_ID('ChamCongSuKien','U') IS NULL CREATE TABLE ChamCongSuKien(MaSuKien BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),NgayCong DATE NOT NULL,MaCC INT NULL REFERENCES ChamCong(MaCC),ThoiDiem DATETIME2 NOT NULL,LoaiSuKien NVARCHAR(20) NOT NULL,Nguon NVARCHAR(20) NOT NULL,KetQua NVARCHAR(30) NOT NULL,Similarity DECIMAL(7,5) NULL,NguoiThucHien NVARCHAR(50) NULL,ChiTiet NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF COL_LENGTH('ChamCongSuKien','NgayCong') IS NULL ALTER TABLE ChamCongSuKien ADD NgayCong DATE NULL; UPDATE e SET NgayCong=COALESCE(c.Ngay,CAST(e.ThoiDiem AS DATE)) FROM ChamCongSuKien e LEFT JOIN ChamCong c ON c.MaCC=e.MaCC WHERE e.NgayCong IS NULL; IF EXISTS(SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID('ChamCongSuKien') AND name='NgayCong' AND is_nullable=1) ALTER TABLE ChamCongSuKien ALTER COLUMN NgayCong DATE NOT NULL"
    )
    db.execute(
        "IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_ChamCongSuKien_Employee_WorkDate') CREATE INDEX IX_ChamCongSuKien_Employee_WorkDate ON ChamCongSuKien(MaNV,NgayCong,MaSuKien)"
    )
    db.execute(
        "INSERT INTO ChamCongSuKien(MaNV,NgayCong,MaCC,ThoiDiem,LoaiSuKien,Nguon,KetQua,NguoiThucHien,ChiTiet) SELECT c.MaNV,c.Ngay,c.MaCC,DATEADD(SECOND,DATEDIFF(SECOND,CAST('00:00:00' AS TIME),c.GioVao),CAST(c.Ngay AS DATETIME2)),N'in',N'legacy',N'imported',N'system',N'Migrated from daily attendance summary' FROM ChamCong c WHERE c.GioVao IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ChamCongSuKien e WHERE e.MaCC=c.MaCC AND e.LoaiSuKien=N'in' AND e.Nguon=N'legacy')"
    )
    db.execute(
        "INSERT INTO ChamCongSuKien(MaNV,NgayCong,MaCC,ThoiDiem,LoaiSuKien,Nguon,KetQua,NguoiThucHien,ChiTiet) SELECT c.MaNV,c.Ngay,c.MaCC,DATEADD(SECOND,DATEDIFF(SECOND,CAST('00:00:00' AS TIME),c.GioRa),CAST(c.Ngay AS DATETIME2)),N'out',N'legacy',N'imported',N'system',N'Migrated from daily attendance summary' FROM ChamCong c WHERE c.GioRa IS NOT NULL AND NOT EXISTS(SELECT 1 FROM ChamCongSuKien e WHERE e.MaCC=c.MaCC AND e.LoaiSuKien=N'out' AND e.Nguon=N'legacy')"
    )
    db.execute(
        "IF OBJECT_ID('CaLamViec','U') IS NULL CREATE TABLE CaLamViec(MaCa INT IDENTITY PRIMARY KEY,TenCa NVARCHAR(80) NOT NULL UNIQUE,GioBatDau TIME NOT NULL,GioKetThuc TIME NOT NULL,QuaDem BIT NOT NULL DEFAULT 0,PhutAnHan SMALLINT NOT NULL DEFAULT 0,TrangThai BIT NOT NULL DEFAULT 1,CHECK(GioBatDau<>GioKetThuc),CHECK(PhutAnHan BETWEEN 0 AND 240))"
    )
    db.execute(
        "IF OBJECT_ID('PhanCaNhanVien','U') IS NULL CREATE TABLE PhanCaNhanVien(MaPhanCa BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),MaCa INT NOT NULL REFERENCES CaLamViec(MaCa),Ngay DATE NOT NULL,NguoiPhan NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CONSTRAINT UQ_PhanCaNhanVien UNIQUE(MaNV,MaCa,Ngay))"
    )
    db.execute(
        "IF COL_LENGTH('PhanCaNhanVien','GioBatDauOverride') IS NULL ALTER TABLE PhanCaNhanVien ADD GioBatDauOverride TIME NULL; IF COL_LENGTH('PhanCaNhanVien','GioKetThucOverride') IS NULL ALTER TABLE PhanCaNhanVien ADD GioKetThucOverride TIME NULL"
    )
    db.execute(
        "IF EXISTS(SELECT 1 FROM sys.key_constraints WHERE parent_object_id=OBJECT_ID('PhanCaNhanVien') AND name='UQ_PhanCaNhanVien') ALTER TABLE PhanCaNhanVien DROP CONSTRAINT UQ_PhanCaNhanVien"
    )
    db.execute(
        "IF NOT EXISTS(SELECT 1 FROM sys.indexes WHERE name='IX_PhanCaNhanVien_Ngay') CREATE INDEX IX_PhanCaNhanVien_Ngay ON PhanCaNhanVien(Ngay,MaNV)"
    )
    db.execute(
        "IF OBJECT_ID('YeuCauDoiCa','U') IS NULL CREATE TABLE YeuCauDoiCa(MaYeuCau BIGINT IDENTITY PRIMARY KEY,MaPhanCaA BIGINT NOT NULL REFERENCES PhanCaNhanVien(MaPhanCa),MaPhanCaB BIGINT NOT NULL REFERENCES PhanCaNhanVien(MaPhanCa),MaNVCau INT NOT NULL REFERENCES NhanVien(MaNV),TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ xác nhận',XacNhanBoi NVARCHAR(50) NULL,XacNhanLuc DATETIME2 NULL,NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,PhanHoi NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(MaPhanCaA<>MaPhanCaB),CHECK(TrangThai IN (N'Chờ xác nhận',N'Chờ duyệt',N'Đã đổi',N'Từ chối')))"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyDoiCa','U') IS NULL CREATE TABLE NhatKyDoiCa(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaYeuCau BIGINT NOT NULL REFERENCES YeuCauDoiCa(MaYeuCau),ThaoTac NVARCHAR(30) NOT NULL,TrangThaiCu NVARCHAR(20) NULL,TrangThaiMoi NVARCHAR(20) NOT NULL,NguoiThucHien NVARCHAR(50) NOT NULL,LyDo NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF OBJECT_ID('LichNgayLe','U') IS NULL CREATE TABLE LichNgayLe(MaNgayLe INT IDENTITY PRIMARY KEY,Ngay DATE NOT NULL UNIQUE,TenNgay NVARCHAR(120) NOT NULL,HuongLuong BIT NOT NULL DEFAULT 1,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF OBJECT_ID('TangCaYeuCau','U') IS NULL CREATE TABLE TangCaYeuCau(MaYeuCau BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),BatDau DATETIME2 NOT NULL,KetThuc DATETIME2 NOT NULL,SoGio DECIMAL(5,2) NOT NULL,SoGioThucTe DECIMAL(5,2) NULL,LyDo NVARCHAR(500) NOT NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ duyệt',NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,XacNhanBoi NVARCHAR(50) NULL,XacNhanLuc DATETIME2 NULL,PhanHoi NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(KetThuc>BatDau),CHECK(SoGio>0 AND SoGio<=24),CHECK(SoGioThucTe IS NULL OR (SoGioThucTe>=0 AND SoGioThucTe<=24)))"
    )
    db.execute(
        "IF COL_LENGTH('TangCaYeuCau','SoGioThucTe') IS NULL ALTER TABLE TangCaYeuCau ADD SoGioThucTe DECIMAL(5,2) NULL"
    )
    db.execute(
        "IF COL_LENGTH('TangCaYeuCau','XacNhanBoi') IS NULL ALTER TABLE TangCaYeuCau ADD XacNhanBoi NVARCHAR(50) NULL"
    )
    db.execute(
        "IF COL_LENGTH('TangCaYeuCau','XacNhanLuc') IS NULL ALTER TABLE TangCaYeuCau ADD XacNhanLuc DATETIME2 NULL"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyTangCa','U') IS NULL CREATE TABLE NhatKyTangCa(MaNhatKy BIGINT IDENTITY PRIMARY KEY,MaYeuCau BIGINT NOT NULL REFERENCES TangCaYeuCau(MaYeuCau),ThaoTac NVARCHAR(30) NOT NULL,TrangThaiCu NVARCHAR(20) NULL,TrangThaiMoi NVARCHAR(20) NOT NULL,NguoiThucHien NVARCHAR(50) NOT NULL,LyDo NVARCHAR(500) NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF OBJECT_ID('KhieuNaiChamCong','U') IS NULL CREATE TABLE KhieuNaiChamCong(MaKN INT IDENTITY(1,1) PRIMARY KEY, MaNV INT NOT NULL, Ngay DATE NOT NULL, NoiDung NVARCHAR(1000) NOT NULL, TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Chờ xử lý', PhanHoi NVARCHAR(1000) NULL, NguoiXuLy NVARCHAR(50) NULL, TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), XuLyLuc DATETIME2 NULL)"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyLuong','U') IS NULL CREATE TABLE NhatKyLuong(MaNhatKy BIGINT IDENTITY(1,1) PRIMARY KEY, MaNV INT NULL, Thang INT NOT NULL, Nam INT NOT NULL, HanhDong NVARCHAR(40) NOT NULL, GiaTriCu NVARCHAR(MAX) NULL, GiaTriMoi NVARCHAR(MAX) NULL, LyDo NVARCHAR(500) NOT NULL, NguoiThucHien NVARCHAR(50) NOT NULL, ThoiDiem DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF COL_LENGTH('NghiPhep','LoaiNghi') IS NULL ALTER TABLE NghiPhep ADD LoaiNghi NVARCHAR(40) NOT NULL CONSTRAINT DF_NghiPhep_LoaiNghi DEFAULT N'Khác'"
    )
    db.execute(
        "IF COL_LENGTH('NghiPhep','PhanHoi') IS NULL ALTER TABLE NghiPhep ADD PhanHoi NVARCHAR(1000) NULL"
    )
    db.execute(
        "IF COL_LENGTH('NghiPhep','TaoLuc') IS NULL ALTER TABLE NghiPhep ADD TaoLuc DATETIME2 NOT NULL CONSTRAINT DF_NghiPhep_TaoLuc DEFAULT SYSUTCDATETIME()"
    )
    db.execute(
        "IF COL_LENGTH('NghiPhep','NgayCuTu') IS NULL ALTER TABLE NghiPhep ADD NgayCuTu DATE NULL, NgayCuDen DATE NULL, SoNgayCu INT NULL, LoaiCu NVARCHAR(40) NULL"
    )
    db.execute("UPDATE NghiPhep SET TrangThai=N'Chờ nhân sự' WHERE TrangThai=N'Chờ duyệt'")
    db.execute(
        "IF OBJECT_ID('QuyPhepNam','U') IS NULL CREATE TABLE QuyPhepNam(MaNV INT NOT NULL REFERENCES NhanVien(MaNV) ON DELETE CASCADE,Nam INT NOT NULL,SoNgayCap DECIMAL(6,2) NOT NULL DEFAULT 0,SoNgayChuyen DECIMAL(6,2) NOT NULL DEFAULT 0,CONSTRAINT PK_QuyPhepNam PRIMARY KEY(MaNV,Nam))"
    )
    db.execute(
        "IF OBJECT_ID('LichLamViecNhanVien','U') IS NULL CREATE TABLE LichLamViecNhanVien(MaNV INT NOT NULL REFERENCES NhanVien(MaNV) ON DELETE CASCADE,Thu TINYINT NOT NULL CHECK(Thu BETWEEN 0 AND 6),CONSTRAINT PK_LichLamViecNhanVien PRIMARY KEY(MaNV,Thu))"
    )
    db.execute(
        "IF OBJECT_ID('QuanLyTrucTiep','U') IS NULL CREATE TABLE QuanLyTrucTiep(MaNV INT NOT NULL PRIMARY KEY REFERENCES NhanVien(MaNV) ON DELETE CASCADE,MaQuanLy INT NOT NULL REFERENCES NhanVien(MaNV))"
    )
    db.execute(
        "UPDATE l SET MaQuanLy=q.MaQuanLy FROM LichSuCongTac l JOIN QuanLyTrucTiep q ON q.MaNV=l.MaNV WHERE l.DenNgay IS NULL AND l.MaQuanLy IS NULL"
    )
    db.execute(
        "IF OBJECT_ID('CauHinhNghiPhep','U') IS NULL CREATE TABLE CauHinhNghiPhep(Id TINYINT NOT NULL PRIMARY KEY CHECK(Id=1),YeuCauQuanLy BIT NOT NULL DEFAULT 0,YeuCauNhanSu BIT NOT NULL DEFAULT 1)"
    )
    db.execute(
        "IF NOT EXISTS(SELECT 1 FROM CauHinhNghiPhep WHERE Id=1) INSERT INTO CauHinhNghiPhep(Id,YeuCauQuanLy,YeuCauNhanSu) VALUES(1,0,1)"
    )
    db.execute(
        "IF OBJECT_ID('ThongBaoNghiPhep','U') IS NULL CREATE TABLE ThongBaoNghiPhep(MaTB BIGINT IDENTITY(1,1) PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV) ON DELETE CASCADE,MaNP INT NULL,NoiDung NVARCHAR(500) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),DaDoc BIT NOT NULL DEFAULT 0)"
    )
    db.execute(
        "IF OBJECT_ID('NhatKyNghiPhep','U') IS NULL CREATE TABLE NhatKyNghiPhep(MaNK BIGINT IDENTITY(1,1) PRIMARY KEY,MaNP INT NOT NULL,MaNV INT NOT NULL,ThaoTac NVARCHAR(40) NOT NULL,TrangThaiCu NVARCHAR(40) NULL,TrangThaiMoi NVARCHAR(40) NULL,ChiTiet NVARCHAR(1000) NULL,NguoiThucHien NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME())"
    )
    db.execute(
        "IF OBJECT_ID('LuongKy','U') IS NULL CREATE TABLE LuongKy(Nam INT NOT NULL, Thang INT NOT NULL, TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp', TinhLuc DATETIME2 NULL, TinhBoi NVARCHAR(50) NULL, DuyetLuc DATETIME2 NULL, DuyetBoi NVARCHAR(50) NULL, KhoaLuc DATETIME2 NULL, KhoaBoi NVARCHAR(50) NULL, PhienBan INT NOT NULL DEFAULT 0, CONSTRAINT PK_LuongKy PRIMARY KEY(Nam,Thang))"
    )
    db.execute(
        "IF OBJECT_ID('PayrollPolicyVersion','U') IS NULL CREATE TABLE PayrollPolicyVersion(MaChinhSach BIGINT IDENTITY PRIMARY KEY,Ten NVARCHAR(120) NOT NULL,NgayHieuLuc DATE NOT NULL,QuyTacJson NVARCHAR(MAX) NOT NULL,CanCu NVARCHAR(1000) NOT NULL,TrangThai NVARCHAR(20) NOT NULL DEFAULT N'Nháp',NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),NguoiDuyet NVARCHAR(50) NULL,DuyetLuc DATETIME2 NULL,CHECK(ISJSON(QuyTacJson)=1),CHECK(TrangThai IN (N'Nháp',N'Đã duyệt',N'Ngừng áp dụng')))"
    )
    db.execute(
        "IF OBJECT_ID('PayrollEmployeeTaxProfile','U') IS NULL CREATE TABLE PayrollEmployeeTaxProfile(MaNV INT NOT NULL REFERENCES NhanVien(MaNV) ON DELETE CASCADE,TuNgay DATE NOT NULL,LaCuTru BIT NULL,NguoiPhuThuoc INT NULL,ThamGiaBaoHiem BIT NULL,LuongTinhBaoHiem DECIMAL(18,0) NULL,NguoiCapNhat NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CONSTRAINT PK_PayrollEmployeeTaxProfile PRIMARY KEY(MaNV,TuNgay),CHECK(NguoiPhuThuoc IS NULL OR NguoiPhuThuoc>=0),CHECK(LuongTinhBaoHiem IS NULL OR LuongTinhBaoHiem>=0))"
    )
    db.execute(
        "IF OBJECT_ID('PayrollItem','U') IS NULL CREATE TABLE PayrollItem(MaKhoan BIGINT IDENTITY PRIMARY KEY,MaNV INT NOT NULL REFERENCES NhanVien(MaNV),Nam INT NOT NULL,Thang INT NOT NULL,Loai NVARCHAR(20) NOT NULL,Ten NVARCHAR(120) NOT NULL,SoTien DECIMAL(18,0) NOT NULL,ChiuThue BIT NOT NULL DEFAULT 0,CanCuBaoHiem BIT NOT NULL DEFAULT 0,DuocTruThue BIT NOT NULL DEFAULT 0,LyDo NVARCHAR(500) NOT NULL,NguoiTao NVARCHAR(50) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(Thang BETWEEN 1 AND 12),CHECK(Loai IN (N'earning',N'reduction',N'deduction')),CHECK(SoTien>=0))"
    )
    db.execute(
        "IF OBJECT_ID('PayrollItem','U') IS NOT NULL AND (EXISTS(SELECT 1 FROM PayrollItem WHERE Loai=N'penalty') OR NOT EXISTS(SELECT 1 FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID('PayrollItem') AND name=N'CK_PayrollItem_Loai')) BEGIN DECLARE @c sysname,@sql nvarchar(max); DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT name FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID('PayrollItem') AND definition LIKE '%Loai%'; OPEN c; FETCH NEXT FROM c INTO @c; WHILE @@FETCH_STATUS=0 BEGIN SET @sql=N'ALTER TABLE PayrollItem DROP CONSTRAINT '+QUOTENAME(@c); EXEC sp_executesql @sql; FETCH NEXT FROM c INTO @c; END; CLOSE c; DEALLOCATE c; UPDATE PayrollItem SET Loai=N'reduction' WHERE Loai=N'penalty'; ALTER TABLE PayrollItem ADD CONSTRAINT CK_PayrollItem_Loai CHECK(Loai IN (N'earning',N'reduction',N'deduction')); END"
    )
    db.execute(
        "IF OBJECT_ID('PayrollResultSnapshot','U') IS NULL CREATE TABLE PayrollResultSnapshot(MaLuong INT NOT NULL PRIMARY KEY REFERENCES Luong(MaLuong) ON DELETE CASCADE,MaChinhSach BIGINT NOT NULL REFERENCES PayrollPolicyVersion(MaChinhSach),QuyTacJson NVARCHAR(MAX) NOT NULL,DuLieuDauVaoJson NVARCHAR(MAX) NOT NULL,ChiTietTinhJson NVARCHAR(MAX) NOT NULL,TaoLuc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),CHECK(ISJSON(QuyTacJson)=1),CHECK(ISJSON(DuLieuDauVaoJson)=1),CHECK(ISJSON(ChiTietTinhJson)=1))"
    )
    for col, typ in [
        ("ThueTNCN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHXH_NLD", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHYT_NLD", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHTN_NLD", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHXHDN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHYTDN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BHTNDN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("BH_TNLDBNN_DN", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
        ("LuongThucLinh", "DECIMAL(18,0) NOT NULL DEFAULT 0"),
    ]:
        db.execute(f"IF COL_LENGTH('Luong','{col}') IS NULL ALTER TABLE Luong ADD [{col}] {typ}")

