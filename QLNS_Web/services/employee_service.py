"""Shared creation and source-link boundary for employee master profiles."""

import re
import os
from decimal import Decimal, InvalidOperation

from cryptography.fernet import Fernet
from flask import session
from permissions import role_can

from database import db


_RECORD_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

PROFILE_COLUMNS = (
    "HoTen",
    "NgaySinh",
    "GioiTinh",
    "DiaChi",
    "SDT",
    "Email",
    "CCCD",
    "NgayVaoLam",
    "MaPB",
    "MaCV",
    "MaViTri",
    "LuongCoBan",
    "TrangThai",
    "AnhHoSo",
)
SOURCE_TYPE_RE = re.compile(r"[a-z][a-z0-9_-]{0,29}\Z")


def _validate_source(source_type, source_key, actor):
    if not isinstance(source_type, str) or not SOURCE_TYPE_RE.fullmatch(source_type):
        raise ValueError("Loại nguồn hồ sơ không hợp lệ.")
    if not isinstance(source_key, str) or not 1 <= len(source_key) <= 100:
        raise ValueError("Mã nguồn hồ sơ không hợp lệ.")
    if not isinstance(actor, str) or not 1 <= len(actor) <= 50:
        raise ValueError("Người tạo hồ sơ không hợp lệ.")


def find_source_employee(source_type, source_key):
    _validate_source(source_type, source_key, "lookup")
    rows = db.query(
        "SELECT MaNV FROM NhanVienNguon WHERE LoaiNguon=? AND MaNguonNgoai=?",
        (source_type, source_key),
    )[1]
    return int(rows[0][0]) if rows else None


def create_employee(source_type, source_key, values, actor):
    """Create a profile once per source key; retries return the same MaNV."""
    _validate_source(source_type, source_key, actor)
    if not isinstance(values, dict) or any(key not in PROFILE_COLUMNS for key in values):
        raise ValueError("Dữ liệu hồ sơ nhân viên không hợp lệ.")
    if not values.get("HoTen"):
        raise ValueError("Họ tên nhân viên là bắt buộc.")

    columns = [column for column in PROFILE_COLUMNS if column in values]
    insert_columns = ",".join(columns)
    placeholders = ",".join("?" for _ in columns)
    sql = (
        "SET XACT_ABORT ON; SET NOCOUNT ON; "
        "DECLARE @MaNV INT, @Result NVARCHAR(20)=N'ok', @Created TABLE(MaNV INT); "
        "BEGIN TRY BEGIN TRANSACTION; "
        "SELECT @MaNV=MaNV FROM dbo.NhanVienNguon WITH (UPDLOCK,HOLDLOCK) "
        "WHERE LoaiNguon=? AND MaNguonNgoai=?; "
        "IF @MaNV IS NULL AND ? IS NOT NULL AND EXISTS( "
        "SELECT 1 FROM dbo.NhanVien WITH (UPDLOCK,HOLDLOCK) WHERE Email=?) "
        "SET @Result=N'duplicate_email'; "
        "IF @MaNV IS NULL AND @Result=N'ok' AND ? IS NOT NULL AND EXISTS( "
        "SELECT 1 FROM dbo.NhanVien WITH (UPDLOCK,HOLDLOCK) "
        "WHERE REPLACE(REPLACE(REPLACE(CCCD,' ',''),'.',''),'-','')=?) "
        "SET @Result=N'duplicate_cccd'; "
        "IF @MaNV IS NULL AND @Result=N'ok' BEGIN "
        f"INSERT INTO dbo.NhanVien({insert_columns}) "
        f"OUTPUT INSERTED.MaNV INTO @Created(MaNV) VALUES({placeholders}); "
        "SELECT @MaNV=MaNV FROM @Created; "
        "INSERT INTO dbo.NhanVienNguon(LoaiNguon,MaNguonNgoai,MaNV,NguoiTao) "
        "VALUES(?,?,@MaNV,?); END; "
        "IF @Result<>N'ok' BEGIN ROLLBACK TRANSACTION; "
        "SELECT @Result AS Result,CAST(NULL AS INT) AS MaNV; END "
        "ELSE BEGIN COMMIT TRANSACTION; "
        "SELECT @Result AS Result,@MaNV AS MaNV; END; "
        "END TRY BEGIN CATCH IF @@TRANCOUNT>0 ROLLBACK TRANSACTION; THROW; END CATCH"
    )
    params = (
        source_type,
        source_key,
        values.get("Email"),
        values.get("Email"),
        re.sub(r"\D", "", values["CCCD"]) if values.get("CCCD") else None,
        re.sub(r"\D", "", values["CCCD"]) if values.get("CCCD") else None,
        *(values[column] for column in columns),
        source_type,
        source_key,
        actor,
    )
    rows = db.query(sql, params)[1]
    if not rows or rows[0][0] == "duplicate_email":
        raise ValueError("Email này đã được hồ sơ nhân viên khác sử dụng.")
    if rows[0][0] == "duplicate_cccd":
        raise ValueError("Số CCCD này đã được hồ sơ nhân viên khác sử dụng.")
    if rows[0][1] is None:
        raise RuntimeError("Không tạo hoặc tìm thấy được hồ sơ nhân viên.")
    return int(rows[0][1])


def _employee_header(manv):
    """Dòng (MaNV, HoTen, mã hiển thị) của một nhân viên; danh sách rỗng nếu không có."""
    return db.query(
        "SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE MaNV=?",
        (manv,),
    )[1]

def _matches_employee_code(row, search):
    if not row or len(row) < 2:
        return False
    employee_code = str(row[1] or "").casefold()
    numeric_code = re.sub(r"[a-z]+$", "", employee_code)
    return search in employee_code or search in numeric_code

def _audit_profile_value(value, field_type):
    if value is None or value == "":
        return ""
    if field_type == "date":
        return str(value)[:10]
    if field_type == "number":
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except (InvalidOperation, ValueError):
            return str(value).strip()
    return str(value).strip()

def _employee_record_cipher():
    key = os.environ.get("HR_DOCUMENT_ENCRYPTION_KEY", "")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise RuntimeError(
            "Cần cấu hình HR_DOCUMENT_ENCRYPTION_KEY bằng khóa Fernet để mã hóa hồ sơ tải lên."
        )

def _can_access_employee_records(manv):
    user = session.get("user", {})
    return user.get("role") == "QuanTri" or role_can(
        user.get("role"), "employees.view"
    ) or int(user.get("manv") or 0) == int(manv)


_RECORD_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
