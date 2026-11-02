"""Shared creation and source-link boundary for employee master profiles."""

import re

import db


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


def link_source(source_type, source_key, employee_id, actor):
    """Link an external record to an existing employee without copying profile data."""
    _validate_source(source_type, source_key, actor)
    try:
        employee_id = int(employee_id)
    except (TypeError, ValueError):
        raise ValueError("Mã nhân viên không hợp lệ.") from None
    if employee_id <= 0:
        raise ValueError("Mã nhân viên không hợp lệ.")

    sql = (
        "SET XACT_ABORT ON; SET NOCOUNT ON; DECLARE @MaNV INT; "
        "BEGIN TRY BEGIN TRANSACTION; "
        "SELECT @MaNV=MaNV FROM dbo.NhanVienNguon WITH (UPDLOCK,HOLDLOCK) "
        "WHERE LoaiNguon=? AND MaNguonNgoai=?; "
        "IF @MaNV IS NOT NULL AND @MaNV<>? "
        "THROW 51000, 'Source is already linked to another employee', 1; "
        "IF @MaNV IS NULL BEGIN "
        "IF NOT EXISTS(SELECT 1 FROM dbo.NhanVien WITH (UPDLOCK,HOLDLOCK) WHERE MaNV=?) "
        "THROW 51001, 'Employee profile does not exist', 1; "
        "INSERT INTO dbo.NhanVienNguon(LoaiNguon,MaNguonNgoai,MaNV,NguoiTao) "
        "VALUES(?,?,?,?); SET @MaNV=?; END; "
        "SELECT @MaNV AS MaNV; COMMIT TRANSACTION; "
        "END TRY BEGIN CATCH IF @@TRANCOUNT>0 ROLLBACK TRANSACTION; THROW; END CATCH"
    )
    rows = db.query(
        sql,
        (
            source_type,
            source_key,
            employee_id,
            employee_id,
            source_type,
            source_key,
            employee_id,
            actor,
            employee_id,
        ),
    )[1]
    if not rows:
        raise RuntimeError("Không liên kết được nguồn với hồ sơ nhân viên.")
    return int(rows[0][0])
