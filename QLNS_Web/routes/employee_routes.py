from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for
from cryptography.fernet import InvalidToken
from datetime import date, datetime, timedelta
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename
from database import db
from utils.decorators import login_required
import io
import os
import re
from services import audit_service as sensitive_audit
from services.common_service import _EMAIL_RE, _parse_iso_date, _safe_error, admin, has_permission
from services.employee_service import _RECORD_MIME_TYPES, _audit_profile_value, _can_access_employee_records, _employee_header, _employee_record_cipher

bp = Blueprint('employees', __name__)


@bp.route("/ho-so-ca-nhan", methods=["GET", "POST"])
@login_required
def employee_self_profile():
    user = session.get("user", {})
    employee_id = user.get("manv")
    if not employee_id or not has_permission("self.profile"):
        return "Tài khoản không có hồ sơ nhân viên hoặc không có quyền sửa hồ sơ cá nhân.", 403

    columns = (
        "HoTen", "NgaySinh", "GioiTinh", "SDT", "Email", "CCCD", "DiaChi", "AnhHoSo"
    )
    if request.method == "POST":
        try:
            name = request.form.get("HoTen", "").strip()
            if not name or len(name) > 100:
                raise ValueError("Họ tên bắt buộc và tối đa 100 ký tự.")
            birth_date = request.form.get("NgaySinh", "").strip()
            birth_date = date.fromisoformat(birth_date) if birth_date else None
            gender = request.form.get("GioiTinh", "").strip() or None
            if gender not in (None, "Nam", "Nữ", "Khác"):
                raise ValueError("Giới tính không hợp lệ.")
            phone = request.form.get("SDT", "").strip() or None
            if phone and (
                not re.fullmatch(r"\+?[0-9][0-9 .()-]{6,18}", phone)
                or not 8 <= len(re.sub(r"\D", "", phone)) <= 15
            ):
                raise ValueError("Số điện thoại không hợp lệ.")
            email = request.form.get("Email", "").strip() or None
            if email and (len(email) > 100 or not _EMAIL_RE.fullmatch(email)):
                raise ValueError("Địa chỉ email không hợp lệ.")
            if email and db.scalar(
                "SELECT COUNT(*) FROM NhanVien WHERE Email=? AND MaNV<>?",
                (email, employee_id),
            ):
                raise ValueError("Email này đã được hồ sơ nhân viên khác sử dụng.")
            identity_number = request.form.get("CCCD", "").strip() or None
            if identity_number:
                identity_number = re.sub(r"\D", "", identity_number)
                if len(identity_number) not in (9, 12):
                    raise ValueError("CCCD phải có 9 hoặc 12 chữ số.")
                if db.scalar(
                    "SELECT COUNT(*) FROM NhanVien WHERE REPLACE(REPLACE(REPLACE(CCCD,' ',''),'.',''),'-','')=? AND MaNV<>?",
                    (identity_number, employee_id),
                ):
                    raise ValueError("Số CCCD này đã được hồ sơ khác sử dụng.")
            address = request.form.get("DiaChi", "").strip() or None
            if address and len(address) > 255:
                raise ValueError("Địa chỉ tối đa 255 ký tự.")
            values = {
                "HoTen": name,
                "NgaySinh": birth_date,
                "GioiTinh": gender,
                "SDT": phone,
                "Email": email,
                "CCCD": identity_number,
                "DiaChi": address,
            }

            photo = None
            uploaded = request.files.get("AnhHoSo")
            photo_changed = bool(uploaded and uploaded.filename)
            if photo_changed:
                raw = uploaded.read(5 * 1024 * 1024 + 1)
                if len(raw) > 5 * 1024 * 1024:
                    raise ValueError("Ảnh hồ sơ tối đa 5 MB.")
                try:
                    with Image.open(io.BytesIO(raw)) as image:
                        if image.format not in ("JPEG", "PNG", "WEBP"):
                            raise ValueError("Chỉ nhận ảnh JPEG, PNG hoặc WEBP.")
                        if image.width * image.height > 20_000_000:
                            raise ValueError("Ảnh có kích thước điểm ảnh quá lớn.")
                        image = ImageOps.exif_transpose(image).convert("RGB")
                        image.thumbnail((1600, 1600))
                        output = io.BytesIO()
                        image.save(output, format="JPEG", quality=88, optimize=True)
                        photo = output.getvalue()
                except (UnidentifiedImageError, OSError):
                    raise ValueError("Tệp tải lên không phải ảnh hợp lệ.")

            current = db.query(
                "SELECT HoTen,NgaySinh,GioiTinh,SDT,Email,CCCD,DiaChi FROM NhanVien WHERE MaNV=?",
                (employee_id,),
            )[1]
            if not current:
                return "Không tìm thấy hồ sơ nhân viên.", 404
            old_values = dict(zip(columns, list(current[0]) + [None]))
            changed_fields = [
                field for field, value in values.items()
                if _audit_profile_value(old_values[field], "date" if field == "NgaySinh" else "text")
                != _audit_profile_value(value, "date" if field == "NgaySinh" else "text")
            ]
            if photo_changed:
                changed_fields.append("AnhHoSo")

            assignments = ",".join(f"{field}=?" for field in values)
            params = list(values.values())
            if photo_changed:
                assignments += ",AnhHoSo=?"
                params.append(photo)
            params.append(employee_id)
            sql = f"UPDATE NhanVien SET {assignments} WHERE MaNV=?;"
            if photo_changed:
                sql += (
                    " INSERT INTO NhatKyChamCong(MaNV,Nguon,ThaoTac,KetQua,NguoiThucHien,ChiTiet) "
                    "SELECT MaNV,N'system',N'profile_photo_changed',N'deleted',?,N'Face template removed after profile photo change' "
                    "FROM NhanVienKhuonMat WHERE MaNV=?; DELETE FROM NhanVienKhuonMat WHERE MaNV=?;"
                )
                params.extend((user["user"], employee_id, employee_id))
            for field in changed_fields:
                sql += " INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'cap_nhat',?,?);"
                params.extend((employee_id, field, user["user"]))
            if sql:
                db.execute(sql, params)
            if changed_fields:
                flash("Đã cập nhật hồ sơ cá nhân.", "success")
            return redirect(url_for("employees.employee_self_profile"))
        except Exception as error:
            flash(_safe_error(error, "Không thể cập nhật hồ sơ cá nhân."), "error")

    cols, rows = db.query(
        "SELECT n.MaNV,ISNULL(n.MaNVHT,CAST(n.MaNV AS NVARCHAR(10))) AS MaNVHT,"
        "n.HoTen,n.NgaySinh,n.GioiTinh,n.SDT,n.Email,n.CCCD,n.DiaChi,p.TenPB,c.TenCV,v.TenViTri "
        "FROM NhanVien n LEFT JOIN PhongBan p ON p.MaPB=n.MaPB "
        "LEFT JOIN ChucVu c ON c.MaCV=n.MaCV LEFT JOIN ViTriCongViec v ON v.MaViTri=n.MaViTri "
        "WHERE n.MaNV=?",
        (employee_id,),
    )
    if not rows:
        return "Không tìm thấy hồ sơ nhân viên.", 404
    sensitive_audit.record_many([employee_id], ("LienHe", "CCCD"), "view", user["user"])
    return render_template(
        "employees/employee_self_profile.html", profile=dict(zip(cols, rows[0])), admin=admin()
    )


@bp.route("/nhanvien/tai-lieu/<int:ma_tep>/tai-xuong")
@login_required
def download_employee_record(ma_tep):
    rows = db.query(
        "SELECT MaNV,TenTep,DinhDang,DuLieu FROM HoSoTepNhanVien WHERE MaTep=?", (ma_tep,)
    )[1]
    if not rows:
        return "Không tìm thấy tài liệu.", 404
    manv, filename, extension, encrypted = rows[0]
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền tải tài liệu này.", 403
    try:
        content = _employee_record_cipher().decrypt(bytes(encrypted))
    except (InvalidToken, RuntimeError):
        current_app.logger.exception("Employee document decryption failed")
        return "Không thể giải mã tài liệu. Hãy liên hệ quản trị viên.", 503
    db.execute(
        "INSERT INTO NhatKyHoSoTep(MaTep,MaNV,ThaoTac,NguoiThucHien) VALUES(?,?,N'download',?)",
        (ma_tep, manv, session["user"]["user"]),
    )
    sensitive_audit.record(manv, "HoSoDienTu", "download", session["user"]["user"])
    return send_file(
        io.BytesIO(content),
        mimetype=_RECORD_MIME_TYPES.get(extension, "application/octet-stream"),
        as_attachment=True,
        download_name=filename,
    )


@bp.route("/nhanvien/tai-lieu/han-luu")
@login_required
def employee_record_retention():
    if not has_permission("records.manage"):
        return "Chỉ quản trị viên được xem danh sách hạn lưu tài liệu.", 403
    today = date.today()
    _, rows = db.query(
        """SELECT TOP 500 t.MaTep,n.MaNV,n.HoTen,t.LoaiTaiLieu,t.TenTep,
                  t.NgayHieuLuc,t.HanLuuDen,t.NguoiTai,t.TaoLuc
           FROM HoSoTepNhanVien t JOIN NhanVien n ON n.MaNV=t.MaNV
           WHERE t.HanLuuDen IS NOT NULL AND t.HanLuuDen<=?
           ORDER BY CASE WHEN t.HanLuuDen<? THEN 0 ELSE 1 END,
                    t.HanLuuDen,n.HoTen,t.MaTep DESC""",
        (today + timedelta(days=90), today),
    )
    sensitive_audit.record_many(
        [row[1] for row in rows], "HoSoDienTu", "list", session["user"]["user"]
    )
    return render_template("employees/employee_record_retention.html", rows=rows, today=today)


@bp.route("/dieuchuyen", methods=["GET", "POST"])
@login_required
def dieuchuyen():
    if not has_permission("employees.edit"):
        return redirect(url_for("dashboard.dashboard"))
    try:
        db.execute("""IF OBJECT_ID('LichSuDieuChuyen','U') IS NULL
    CREATE TABLE LichSuDieuChuyen(
      MaDieuChuyen INT IDENTITY(1,1) PRIMARY KEY,
      MaNV INT NOT NULL REFERENCES NhanVien(MaNV),
      MaPB_Cu INT NULL REFERENCES PhongBan(MaPB),
      MaPB_Moi INT NOT NULL REFERENCES PhongBan(MaPB),
      ThoiDiemChuyen DATETIME2(0) NOT NULL,
      LyDo NVARCHAR(500) NULL,
      NguoiThucHien NVARCHAR(100) NULL)""")
    except Exception as e:
        flash(_safe_error(e, "Không tạo được bảng lịch sử điều chuyển."), "error")
    if request.method == "POST":
        try:
            manv = int(request.form["MaNV"])
            pb_moi = int(request.form["MaPB_Moi"])
            thoi_diem = datetime.fromisoformat(request.form["ThoiDiemChuyen"])
            current = db.query("SELECT MaPB FROM NhanVien WHERE MaNV=?", (manv,))[1]
            if not current:
                raise ValueError("Không tìm thấy nhân viên.")
            pb_cu = current[0][0]
            if pb_cu is not None and int(pb_cu) == pb_moi:
                raise ValueError("Nhân viên hiện đã thuộc phòng ban này.")
            if not db.scalar(
                "SELECT COUNT(*) FROM PhongBan WHERE MaPB=? AND TrangThai=N'Hoạt động'",
                (pb_moi,),
            ):
                raise ValueError("Phòng ban mới không tồn tại hoặc đã ngừng hoạt động.")
            db.execute(
                """SET XACT_ABORT ON; BEGIN TRAN;
      INSERT INTO LichSuDieuChuyen(MaNV,MaPB_Cu,MaPB_Moi,ThoiDiemChuyen,LyDo,NguoiThucHien)
      VALUES(?,?,?,?,?,?);
      UPDATE NhanVien SET MaPB=? WHERE MaNV=?;
      COMMIT;""",
                (
                    manv,
                    pb_cu,
                    pb_moi,
                    thoi_diem,
                    request.form.get("LyDo", "").strip() or None,
                    session["user"]["user"],
                    pb_moi,
                    manv,
                ),
            )
            flash("Đã điều chuyển nhân viên và lưu ngày giờ chuyển.", "success")
        except Exception as e:
            flash(_safe_error(e, "Không thể hoàn tất điều chuyển lúc này."), "error")
        return redirect(url_for("employees.dieuchuyen"))
    try:
        people = db.query(
            "SELECT MaNV,HoTen,ISNULL(MaNVHT,CAST(MaNV AS NVARCHAR(10))) FROM NhanVien WHERE TrangThai=N'Đang làm' ORDER BY HoTen"
        )[1]
        departments = db.query(
            "SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB"
        )[1]
        cols, rows = db.query("""SELECT ls.MaDieuChuyen AS [Mã],n.HoTen AS [Nhân viên],
    ISNULL(cu.TenPB,N'(Chưa phân phòng)') AS [Phòng ban cũ],moi.TenPB AS [Phòng ban mới],
    ls.ThoiDiemChuyen AS [Ngày giờ chuyển],ls.LyDo AS [Lý do],ls.NguoiThucHien AS [Người thực hiện]
    FROM LichSuDieuChuyen ls JOIN NhanVien n ON n.MaNV=ls.MaNV
    LEFT JOIN PhongBan cu ON cu.MaPB=ls.MaPB_Cu JOIN PhongBan moi ON moi.MaPB=ls.MaPB_Moi
    ORDER BY ls.ThoiDiemChuyen DESC""")
    except Exception as e:
        people = []
        departments = []
        cols, rows = [], []
        flash(_safe_error(e, "Không tải được lịch sử điều chuyển."), "error")
    return render_template(
        "departments/transfer.html",
        people=people,
        departments=departments,
        cols=cols,
        rows=rows,
        admin=admin(),
    )


@bp.route("/nhanvien/<int:manv>/tai-lieu", methods=["GET", "POST"])
@login_required
def employee_records(manv):
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền truy cập hồ sơ nhân viên này.", 403
    employee = _employee_header(manv)
    if not employee:
        return "Không tìm thấy hồ sơ nhân viên.", 404
    if request.method == "POST":
        try:
            uploaded = request.files.get("file")
            category = request.form.get("LoaiTaiLieu", "").strip()
            allowed_categories = {
                "CCCD",
                "Bằng cấp",
                "Chứng chỉ",
                "Quyết định",
                "Hồ sơ cá nhân",
                "Khác",
            }
            if category not in allowed_categories or not uploaded or not uploaded.filename:
                raise ValueError("Chọn loại tài liệu và tệp cần tải lên.")
            extension = os.path.splitext(secure_filename(uploaded.filename))[1].lower()
            if extension not in _RECORD_MIME_TYPES:
                raise ValueError("Chỉ nhận PDF, DOCX, JPEG hoặc PNG.")
            raw = uploaded.read(8 * 1024 * 1024 + 1)
            if not raw or len(raw) > 8 * 1024 * 1024:
                raise ValueError("Tài liệu phải có dung lượng từ 1 byte đến 8 MB.")
            signatures = {
                ".pdf": raw.startswith(b"%PDF-"),
                ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
                ".jpg": raw.startswith(b"\xff\xd8\xff"),
                ".jpeg": raw.startswith(b"\xff\xd8\xff"),
                ".docx": raw.startswith(b"PK\x03\x04"),
            }
            if not signatures[extension]:
                raise ValueError("Nội dung tệp không khớp với định dạng phần mở rộng.")
            effective = (
                _parse_iso_date(request.form["NgayHieuLuc"], "Ngày hiệu lực")
                if request.form.get("NgayHieuLuc")
                else None
            )
            retention = (
                _parse_iso_date(request.form["HanLuuDen"], "Hạn lưu")
                if has_permission("records.manage") and request.form.get("HanLuuDen")
                else None
            )
            if retention and effective and retention < effective:
                raise ValueError("Hạn lưu không được trước ngày hiệu lực.")
            filename = secure_filename(uploaded.filename)[:180] or ("tai-lieu" + extension)
            encrypted = _employee_record_cipher().encrypt(raw)
            new_id = db.query(
                "INSERT INTO HoSoTepNhanVien(MaNV,LoaiTaiLieu,TenTep,DinhDang,DuLieu,NgayHieuLuc,HanLuuDen,NguoiTai) OUTPUT INSERTED.MaTep VALUES(?,?,?,?,?,?,?,?)",
                (
                    manv,
                    category,
                    filename,
                    extension,
                    encrypted,
                    effective,
                    retention,
                    session["user"]["user"],
                ),
            )[1][0][0]
            db.execute(
                "INSERT INTO NhatKyHoSoTep(MaTep,MaNV,ThaoTac,NguoiThucHien) VALUES(?,?,N'upload',?)",
                (new_id, manv, session["user"]["user"]),
            )
            flash("Đã mã hóa và lưu tài liệu hồ sơ.", "success")
            return redirect(url_for("employees.employee_records", manv=manv))
        except Exception as error:
            flash(
                _safe_error(
                    error, "Không thể lưu tài liệu. Kiểm tra khóa mã hóa và thông tin tệp."
                ),
                "error",
            )
    documents = db.query(
        "SELECT MaTep,LoaiTaiLieu,TenTep,DinhDang,NgayHieuLuc,HanLuuDen,NguoiTai,TaoLuc FROM HoSoTepNhanVien WHERE MaNV=? ORDER BY TaoLuc DESC",
        (manv,),
    )[1]
    db.execute(
        "INSERT INTO NhatKyHoSoTep(MaNV,ThaoTac,NguoiThucHien) VALUES(?,N'view_list',?)",
        (manv, session["user"]["user"]),
    )
    sensitive_audit.record(manv, "HoSoDienTu", "list", session["user"]["user"])
    return render_template(
        "employees/employee_records.html",
        employee=employee[0],
        documents=documents,
        admin=admin() or has_permission("records.manage"),
        today=date.today(),
    )


@bp.route("/nhanvien/<int:manv>/nhat-ky-ho-so")
@login_required
def employee_profile_audit(manv):
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền xem nhật ký hồ sơ này.", 403
    employee = _employee_header(manv)
    if not employee:
        return "Không tìm thấy hồ sơ nhân viên.", 404
    rows = db.query(
        "SELECT TOP 200 HanhDong,TruongDuLieu,NguoiThucHien,TaoLuc FROM NhatKyHoSoNhanVien WHERE MaNV=? ORDER BY MaNhatKy DESC",
        (manv,),
    )[1]
    return render_template(
        "employees/employee_profile_audit.html", employee=employee[0], rows=rows, admin=admin()
    )


@bp.route("/nhanvien/<int:manv>/lich-su-cong-tac")
@login_required
def lich_su_cong_tac(manv):
    if not _can_access_employee_records(manv):
        return "Bạn không có quyền xem lịch sử nhân sự này.", 403
    employee = _employee_header(manv)
    if not employee:
        return "Không tìm thấy hồ sơ nhân viên.", 404
    rows = db.query(
        "SELECT l.TuNgay,l.DenNgay,p.TenPB,c.TenCV,v.TenViTri,ql.HoTen,l.LuongCoBan,l.LyDo,l.NguoiCapNhat,l.TaoLuc FROM LichSuCongTac l LEFT JOIN PhongBan p ON p.MaPB=l.MaPB LEFT JOIN ChucVu c ON c.MaCV=l.MaCV LEFT JOIN ViTriCongViec v ON v.MaViTri=l.MaViTri LEFT JOIN NhanVien ql ON ql.MaNV=l.MaQuanLy WHERE l.MaNV=? ORDER BY l.TuNgay DESC,l.MaLichSu DESC",
        (manv,),
    )[1]
    return render_template(
        "employees/employment_history.html", employee=employee[0], rows=rows, admin=admin()
    )
