from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from PIL import Image, ImageOps, UnidentifiedImageError
from datetime import date, datetime
from utils.app_catalog import MODULES
from contracts import sync_contract_statuses
from database import db
from utils.permissions import module_permission
from database.schema_setup import assign_codes
from utils.decorators import login_required
import io
import math
import re
import secrets
from services import audit_service as sensitive_audit
from services.common_service import _EMAIL_RE, _safe_error, admin, has_permission, is_manager
from services.employee_service import _audit_profile_value, _matches_employee_code
from services import employee_service as employee_profiles

bp = Blueprint('departments', __name__)


@bp.route("/api/chucvu-nhanh", methods=["POST"])
@login_required
def chucvu_nhanh():
    if not has_permission("organization.manage"):
        return jsonify(ok=False, error="Bạn không có quyền quản lý chức vụ."), 403
    data = request.get_json(silent=True) or {}
    ten = (data.get("TenCV") or "").strip()
    try:
        if not ten:
            raise ValueError("Vui lòng nhập tên chức vụ.")
        if len(ten) > 100:
            raise ValueError("Tên chức vụ tối đa 100 ký tự.")
        try:
            mapb = int(data.get("MaPB"))
        except (TypeError, ValueError):
            raise ValueError("Vui lòng chọn phòng ban trước.")
        if not db.scalar("SELECT COUNT(*) FROM PhongBan WHERE MaPB=?", (mapb,)):
            raise ValueError("Phòng ban không tồn tại.")
        ensure_pbcv()
        row = db.query("SELECT MaCV,TenCV FROM ChucVu WHERE TenCV=?", (ten,))[1]
        if not row:
            db.execute("INSERT INTO ChucVu(TenCV) VALUES(?)", (ten,))
            row = db.query("SELECT MaCV,TenCV FROM ChucVu WHERE TenCV=?", (ten,))[1]
            db.execute("INSERT INTO PhongBan_ChucVu(MaPB,MaCV) VALUES(?,?)", (mapb, row[0][0]))
        else:
            macv = row[0][0]
            # chức vụ chung (chưa gắn phòng nào) đã dùng được cho mọi phòng -> không gắn thêm để khỏi làm mất ở phòng khác
            if db.scalar(
                "SELECT COUNT(*) FROM PhongBan_ChucVu WHERE MaCV=?", (macv,)
            ) and not db.scalar(
                "SELECT COUNT(*) FROM PhongBan_ChucVu WHERE MaPB=? AND MaCV=?",
                (mapb, macv),
            ):
                db.execute("INSERT INTO PhongBan_ChucVu(MaPB,MaCV) VALUES(?,?)", (mapb, macv))
        return jsonify(ok=True, id=row[0][0], name=row[0][1])
    except Exception as e:
        status = 400 if isinstance(e, ValueError) else 500
        return jsonify(ok=False, error=_safe_error(e, "Không thể tạo chức vụ lúc này.")), status


@bp.route("/<key>", methods=["GET", "POST"])
@login_required
def module(key):
    if key not in MODULES:
        return redirect(url_for("dashboard.dashboard"))
    view_permission = (
        "employees.team_view"
        if key == "nhanvien" and is_manager()
        else module_permission(key, "view")
    )
    if not view_permission or not has_permission(view_permission):
        return "Bạn không có quyền xem dữ liệu này.", 403
    if key == "hopdong":
        sync_contract_statuses()
    m = MODULES[key]
    edit_id = request.args.get("edit")
    if edit_id and not re.fullmatch(r"[0-9]{1,9}", edit_id):
        return "Mã bản ghi cần sửa không hợp lệ.", 400
    can_manage = bool(
        module_permission(key, "edit") and has_permission(module_permission(key, "edit"))
    )
    can_export = bool(
        module_permission(key, "export") and has_permission(module_permission(key, "export"))
    )
    if edit_id and not can_manage:
        return "Bạn không có quyền sửa dữ liệu này.", 403
    employee_source_key = secrets.token_urlsafe(32) if key == "nhanvien" and not edit_id else None
    if request.method == "POST":
        action = request.form.get("action")
        action_permission = module_permission(key, action)
        if not action_permission or not has_permission(action_permission):
            return "Bạn không có quyền thực hiện thao tác này.", 403
        source_key = (
            request.form.get("employee_source_key", "")
            if key == "nhanvien" and action == "add"
            else None
        )
        vals = []
        write_fields = []
        photo_changed = False
        try:
            if key == "nhanvien" and action == "add":
                if not source_key:
                    raise ValueError("Biểu mẫu đã hết hạn. Hãy tải lại trang thêm nhân viên.")
                existing_employee = employee_profiles.find_source_employee("manual", source_key)
                if existing_employee:
                    assign_codes()
                    flash(
                        f"Hồ sơ đã được tạo trước đó với mã nhân viên {existing_employee}.",
                        "success",
                    )
                    return redirect(url_for("departments.module", key=key))
            if key == "hopdong" and action == "update":
                status = db.scalar(
                    "SELECT TrangThai FROM HopDong WHERE MaHD=?", (request.form.get("id"),)
                )
                if status != "Bản nháp" or db.scalar(
                    "SELECT COUNT(*) FROM TepHopDong WHERE MaHD=?", (request.form.get("id"),)
                ):
                    raise ValueError(
                        "Chỉ sửa hợp đồng nháp chưa có tệp phiên bản; dùng chức năng soạn/vòng đời để tạo phiên bản mới."
                    )
            if action in ("add", "update"):
                for col, label, typ, req in m["fields"]:
                    if typ == "image":
                        uploaded = request.files.get(col)
                        if not uploaded or not uploaded.filename:
                            if action == "add":
                                write_fields.append((col, label, typ, req))
                                vals.append(None)
                            continue
                        raw = uploaded.read(5 * 1024 * 1024 + 1)
                        if len(raw) > 5 * 1024 * 1024:
                            raise ValueError("Ảnh hồ sơ tối đa 5 MB.")
                        try:
                            with Image.open(io.BytesIO(raw)) as im:
                                if im.format not in ("JPEG", "PNG", "WEBP"):
                                    raise ValueError("Chỉ nhận ảnh JPEG, PNG hoặc WEBP.")
                                if im.width * im.height > 20_000_000:
                                    raise ValueError("Ảnh có kích thước điểm ảnh quá lớn.")
                                im = ImageOps.exif_transpose(im).convert("RGB")
                                im.thumbnail((1600, 1600))
                                output = io.BytesIO()
                                im.save(output, format="JPEG", quality=88, optimize=True)
                                value = output.getvalue()
                        except (UnidentifiedImageError, OSError):
                            raise ValueError("Tệp tải lên không phải ảnh hợp lệ.")
                        write_fields.append((col, label, typ, req))
                        vals.append(value)
                        photo_changed = True
                        continue
                    value = request.form.get(col, "").strip()
                    if typ in ("unit", "department", "department_parent", "jobposition") and value:
                        try:
                            value = str(int(value))
                        except ValueError:
                            raise ValueError(label + " không hợp lệ.")
                        table, pk = {
                            "unit": ("DonVi", "MaDonVi"),
                            "department": ("PhongBan", "MaPB"),
                            "department_parent": ("PhongBan", "MaPB"),
                            "jobposition": ("ViTriCongViec", "MaViTri"),
                        }[typ]
                        if not db.scalar(f"SELECT COUNT(*) FROM {table} WHERE {pk}=?", (value,)):
                            raise ValueError(label + " không tồn tại.")
                        if (
                            key == "donvi"
                            and col == "MaDonViCha"
                            and action == "update"
                            and value == request.form.get("id")
                        ):
                            raise ValueError("Đơn vị không thể là cấp trên của chính nó.")
                        if (
                            key == "phongban"
                            and col == "MaPBCha"
                            and action == "update"
                            and value == request.form.get("id")
                        ):
                            raise ValueError("Phòng ban không thể là cấp trên của chính nó.")
                        if key in ("donvi", "phongban") and col in ("MaDonViCha", "MaPBCha"):
                            table_name, id_col, parent_col = (
                                ("DonVi", "MaDonVi", "MaDonViCha")
                                if key == "donvi"
                                else ("PhongBan", "MaPB", "MaPBCha")
                            )
                            ancestors = dict(
                                db.query(f"SELECT {id_col},{parent_col} FROM {table_name}")[1]
                            )
                            node = int(value)
                            visited = set()
                            while node and node not in visited:
                                if action == "update" and node == int(request.form.get("id") or 0):
                                    raise ValueError(
                                        "Không thể chuyển nút xuống dưới một nút con của nó."
                                    )
                                visited.add(node)
                                node = ancestors.get(node) or 0
                    if key == "nhanvien" and col == "Email" and value:
                        if not _EMAIL_RE.fullmatch(value):
                            raise ValueError("Địa chỉ email không hợp lệ.")
                        if action == "update" and db.scalar(
                            "SELECT COUNT(*) FROM NhanVien WHERE Email=? AND MaNV<>?",
                            (value, request.form.get("id") or -1),
                        ):
                            raise ValueError("Email này đã được hồ sơ nhân viên khác sử dụng.")
                    if key == "nhanvien" and col == "CCCD" and value:
                        digits = re.sub(r"\D", "", value)
                        if len(digits) not in (9, 12):
                            raise ValueError("CCCD phải có 9 hoặc 12 chữ số.")
                        if action == "update" and db.scalar(
                            "SELECT COUNT(*) FROM NhanVien WHERE REPLACE(REPLACE(REPLACE(CCCD,' ',''),'.',''),'-','')=? AND MaNV<>?",
                            (digits, request.form.get("id") or -1),
                        ):
                            raise ValueError("Số CCCD này đã được hồ sơ khác sử dụng.")
                        value = digits
                    if key == "nhanvien" and col == "SDT" and value:
                        phone_digits = re.sub(r"\D", "", value)
                        if (
                            not re.fullmatch(r"\+?[0-9][0-9 .()-]{6,18}", value)
                            or not 8 <= len(phone_digits) <= 15
                        ):
                            raise ValueError("Số điện thoại không hợp lệ.")
                    if typ == "number" and value:
                        try:
                            number = float(value)
                        except ValueError:
                            raise ValueError(label + " phải là số.")
                        if not math.isfinite(number) or number < 0:
                            raise ValueError(label + " phải là số không âm hợp lệ.")
                    if col == "KyHieu":
                        value = value.upper()
                        if not re.fullmatch("[A-Z]{1,5}", value):
                            raise ValueError(
                                "Ký hiệu phòng ban gồm 1-5 chữ cái không dấu, ví dụ KT."
                            )
                        if db.scalar(
                            "SELECT COUNT(*) FROM PhongBan WHERE KyHieu=? AND MaPB<>?",
                            (value, request.form.get("id") or -1),
                        ):
                            raise ValueError("Ký hiệu " + value + " đã được phòng ban khác dùng.")
                    if req and not value:
                        raise ValueError("Vui lòng nhập " + label + ".")
                    write_fields.append((col, label, typ, req))
                    vals.append(value or None)
            if key == "nhanvien" and action in ("add", "update"):
                submitted = dict(zip((field[0] for field in write_fields), vals))
                selected_department = submitted.get("MaPB")
                selected_position = submitted.get("MaViTri")
                if action == "update":
                    current_assignment = db.query(
                        "SELECT MaPB,MaViTri FROM NhanVien WHERE MaNV=?", (request.form.get("id"),)
                    )[1]
                    if current_assignment:
                        selected_department = submitted.get("MaPB", current_assignment[0][0])
                        selected_position = submitted.get("MaViTri", current_assignment[0][1])
                if selected_position:
                    position_department = db.scalar(
                        "SELECT MaPB FROM ViTriCongViec WHERE MaViTri=?", (selected_position,)
                    )
                    if position_department is not None and str(position_department) != str(
                        selected_department
                    ):
                        raise ValueError(
                            "Vị trí công việc này thuộc phòng ban khác với phòng ban đã chọn."
                        )
            if action == "add":
                cols = [f[0] for f in write_fields]
                if key == "hopdong":
                    contract_id = db.query(
                        f"INSERT INTO HopDong ({','.join(cols)},TrangThai,NguoiLap,PhienBan) OUTPUT INSERTED.MaHD VALUES ({','.join(['?'] * len(cols))},N'Bản nháp',?,1)",
                        vals + [session["user"]["user"]],
                    )[1][0][0]
                    db.execute(
                        "INSERT INTO LichSuHopDong(MaHD,HanhDong,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien) VALUES(?,N'tao_ban_nhap',NULL,N'Bản nháp',N'Tạo từ màn hình quản lý hợp đồng',?)",
                        (contract_id, session["user"]["user"]),
                    )
                elif key == "nhanvien":
                    created_id = employee_profiles.create_employee(
                        "manual",
                        source_key,
                        dict(zip(cols, vals)),
                        session["user"]["user"],
                    )
                    db.execute(
                        "INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'tao',N'*',?)",
                        (created_id, session["user"]["user"]),
                    )
                    db.execute(
                        "INSERT INTO LichSuCongTac(MaNV,TuNgay,MaPB,MaCV,MaViTri,MaQuanLy,LuongCoBan,NguoiCapNhat,LyDo) VALUES(?,?,?,?,?,NULL,?,?,N'Tạo hồ sơ nhân viên')",
                        (
                            created_id,
                            date.today(),
                            dict(zip(cols, vals)).get("MaPB"),
                            dict(zip(cols, vals)).get("MaCV"),
                            dict(zip(cols, vals)).get("MaViTri"),
                            dict(zip(cols, vals)).get("LuongCoBan") or 0,
                            session["user"]["user"],
                        ),
                    )
                else:
                    db.execute(
                        f"INSERT INTO {m['table']} ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
                        vals,
                    )
                if key == "nhanvien":
                    assign_codes()
                flash("Đã thêm dữ liệu.", "success")
            elif action == "update":
                sets = ",".join(f"{f[0]}=?" for f in write_fields)
                if sets and key == "nhanvien":
                    employee_id = int(request.form["id"])
                    current = db.query(
                        "SELECT MaPB,MaCV,MaViTri,LuongCoBan,(SELECT MaQuanLy FROM QuanLyTrucTiep q WHERE q.MaNV=NhanVien.MaNV) FROM NhanVien WHERE MaNV=?",
                        (employee_id,),
                    )[1]
                    if not current:
                        raise ValueError("Không tìm thấy hồ sơ nhân viên.")
                    audit_fields = [field for field in m["fields"] if field[2] != "image"]
                    audit_columns = [field[0] for field in audit_fields]
                    old_profile_rows = db.query(
                        f"SELECT {','.join(audit_columns)} FROM NhanVien WHERE MaNV=?",
                        (employee_id,),
                    )[1]
                    old_profile = dict(zip(audit_columns, old_profile_rows[0]))
                    submitted_profile = dict(zip((field[0] for field in write_fields), vals))
                    changed_profile_fields = [
                        field[0]
                        for field in audit_fields
                        if field[0] in submitted_profile
                        and _audit_profile_value(old_profile.get(field[0]), field[2])
                        != _audit_profile_value(submitted_profile.get(field[0]), field[2])
                    ]
                    if photo_changed:
                        changed_profile_fields.append("AnhHoSo")
                    audit_sql = "".join(
                        " INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'cap_nhat',?,?);"
                        for _ in changed_profile_fields
                    )
                    audit_params = [
                        value
                        for field in changed_profile_fields
                        for value in (employee_id, field, session["user"]["user"])
                    ]
                    tracked = ("MaPB", "MaCV", "MaViTri", "LuongCoBan", "MaQuanLy")
                    current_values = dict(zip(tracked, current[0]))
                    new_values = dict(current_values)
                    submitted = dict(zip((field[0] for field in write_fields), vals))
                    new_values.update(
                        {field: submitted[field] for field in tracked if field in submitted}
                    )
                    changed = any(
                        str(current_values[field] or "") != str(new_values[field] or "")
                        for field in tracked
                    )
                    update_sql = f"UPDATE NhanVien SET {sets} WHERE MaNV=?;"
                    update_params = vals + [employee_id]
                    deactivating = (
                        old_profile.get("TrangThai") == "Đang làm"
                        and submitted_profile.get("TrangThai") == "Đã nghỉ việc"
                    )
                    if deactivating:
                        update_sql += (
                            " UPDATE NhanVien SET NgayNghiViec=CAST(GETDATE() AS DATE) WHERE MaNV=?;"
                            " INSERT INTO NhatKyChamCong(MaNV,Nguon,ThaoTac,KetQua,NguoiThucHien,ChiTiet) "
                            "SELECT MaNV,N'system',N'employee_deactivated_face_delete',N'deleted',?,N'Biometric template removed after employee deactivation' "
                            "FROM NhanVienKhuonMat WHERE MaNV=?;"
                            " DELETE FROM NhanVienKhuonMat WHERE MaNV=?;"
                            " UPDATE TaiKhoan SET SecurityVersion=SecurityVersion+1 WHERE MaNV=?;"
                            " DELETE FROM QuanLyTrucTiep WHERE MaNV=?;"
                        )
                        update_params.extend(
                            [
                                employee_id,
                                session["user"]["user"],
                                employee_id,
                                employee_id,
                                employee_id,
                                employee_id,
                            ]
                        )
                    reactivating = (
                        old_profile.get("TrangThai") == "Đã nghỉ việc"
                        and submitted_profile.get("TrangThai") == "Đang làm"
                    )
                    if reactivating:
                        update_sql += " UPDATE NhanVien SET NgayNghiViec=NULL WHERE MaNV=?;"
                        update_params.append(employee_id)
                    if photo_changed:
                        update_sql += " DELETE FROM NhanVienKhuonMat WHERE MaNV=?;"
                        update_params.append(employee_id)
                    update_sql += audit_sql
                    if changed:
                        try:
                            effective = datetime.strptime(
                                request.form.get("NgayHieuLuc", ""), "%Y-%m-%d"
                            ).date()
                        except ValueError:
                            raise ValueError("Ngày hiệu lực phải hợp lệ.")
                        current_start = db.scalar(
                            "SELECT MAX(TuNgay) FROM LichSuCongTac WHERE MaNV=? AND DenNgay IS NULL",
                            (employee_id,),
                        )
                        if current_start and effective < current_start:
                            raise ValueError("Ngày hiệu lực không được trước mốc lịch sử hiện tại.")
                        snapshot = [new_values[field] for field in tracked]
                        reason = (
                            request.form.get("LyDoDieuChinh", "").strip()[:500]
                            or "Cập nhật hồ sơ công tác"
                        )
                        if current_start and effective == current_start:
                            history_sql = "UPDATE LichSuCongTac SET MaPB=?,MaCV=?,MaViTri=?,LuongCoBan=?,MaQuanLy=?,NguoiCapNhat=?,LyDo=? WHERE MaNV=? AND DenNgay IS NULL;"
                            history_params = snapshot + [
                                session["user"]["user"],
                                reason,
                                employee_id,
                            ]
                        else:
                            history_sql = "UPDATE LichSuCongTac SET DenNgay=DATEADD(day,-1,?) WHERE MaNV=? AND DenNgay IS NULL; INSERT INTO LichSuCongTac(MaNV,TuNgay,MaPB,MaCV,MaViTri,MaQuanLy,LuongCoBan,NguoiCapNhat,LyDo) VALUES(?,?,?,?,?,?,?,?,?);"
                            history_params = (
                                [effective, employee_id, employee_id, effective]
                                + snapshot
                                + [session["user"]["user"], reason]
                            )
                        db.execute(
                            "SET XACT_ABORT ON; BEGIN TRAN; "
                            + history_sql
                            + " "
                            + update_sql
                            + " COMMIT;",
                            history_params + update_params + audit_params,
                        )
                    else:
                        db.execute(
                            "SET XACT_ABORT ON; BEGIN TRAN; " + update_sql + " COMMIT;",
                            update_params + audit_params,
                        )
                elif sets:
                    db.execute(
                        f"UPDATE {m['table']} SET {sets} WHERE {m['pk']}=?",
                        vals + [request.form["id"]],
                    )
                    if key == "hopdong":
                        db.execute(
                            "INSERT INTO LichSuHopDong(MaHD,HanhDong,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien) VALUES(?,N'sua_ban_nhap',N'Bản nháp',N'Bản nháp',N'Cập nhật thông tin hợp đồng nháp',?)",
                            (request.form["id"], session["user"]["user"]),
                        )
                flash("Đã cập nhật dữ liệu.", "success")
            elif action == "delete":
                delete_record(key, m, request.form["id"])
                flash("Đã xóa dữ liệu.", "success")
            return redirect(url_for("departments.module", key=key))
        except Exception as e:
            flash(friendly_delete_error(e) if action == "delete" else _safe_error(e), "error")
    edit = None
    if edit_id:
        edit = db.query(
            f"SELECT {','.join('CASE WHEN AnhHoSo IS NULL THEN 0 ELSE 1 END AS AnhHoSo' if f[0] == 'AnhHoSo' else f[0] for f in m['fields'])} FROM {m['table']} WHERE {m['pk']}=?",
            (edit_id,),
        )[1]
        edit = dict(zip([f[0] for f in m["fields"]], edit[0])) if edit else None
    try:
        cols, rows = db.query(m["sql"])
        if key == "nhanvien" and is_manager():
            own_id = int(session.get("user", {}).get("manv") or 0)
            team_ids = {
                row[0]
                for row in db.query("SELECT MaNV FROM QuanLyTrucTiep WHERE MaQuanLy=?", (own_id,))[
                    1
                ]
            }
            if own_id:
                team_ids.add(own_id)
            rows = [row for row in rows if row and row[0] in team_ids]
            hidden_columns = {"Email", "SĐT", "CCCD", "Lương CB"}
            visible = [index for index, col in enumerate(cols) if col not in hidden_columns]
            cols = [cols[index] for index in visible]
            rows = [[row[index] for index in visible] for row in rows]
        search = request.args.get("q", "").strip()
        if search:
            if key == "nhanvien":
                q_ = search.casefold()
                rows = [r for r in rows if _matches_employee_code(r, q_)]
            else:
                rows = [
                    r
                    for r in rows
                    if search.casefold()
                    in " ".join("" if x is None else str(x) for x in r).casefold()
                ]
    except Exception as e:
        cols, rows = [], []
        flash(_safe_error(e, "Không tải được dữ liệu. Vui lòng thử lại."), "error")
    if has_permission("employees.view_cccd") and key == "nhanvien":
        actor = session["user"]["user"]
        employee_ids = [row[0] for row in rows if row and row[0] is not None]
        sensitive_audit.record_many(employee_ids, ("LienHe", "CCCD", "Luong"), "list", actor)
        if edit:
            employee_id = int(edit_id)
            for data_type in ("CCCD", "LienHe", "Luong"):
                sensitive_audit.record(employee_id, data_type, "view", actor)
    elif has_permission("contracts.view") and key == "hopdong" and rows:
        contract_ids = [int(row[0]) for row in rows if row and row[0] is not None]
        if contract_ids:
            placeholders = ",".join("?" for _ in contract_ids)
            employee_ids = [
                row[0]
                for row in db.query(
                    f"SELECT MaNV FROM HopDong WHERE MaHD IN ({placeholders})", contract_ids
                )[1]
            ]
            sensitive_audit.record_many(employee_ids, "HopDong", "list", session["user"]["user"])
    options = {}
    if key == "nhanvien":
        try:
            options["MaPB"] = db.query(
                "SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB"
            )[1]
            options["MaCV"] = db.query("SELECT MaCV,TenCV FROM ChucVu ORDER BY TenCV")[1]
            options["MaViTri"] = db.query(
                "SELECT MaViTri,TenViTri FROM ViTriCongViec WHERE TrangThai=N'Hoạt động' ORDER BY TenViTri"
            )[1]
            ensure_pbcv()
            links = db.query("SELECT MaPB,MaCV FROM PhongBan_ChucVu")[1]
            dm = {}
            for pb_, cv_ in links:
                dm.setdefault(cv_, []).append(pb_)
            options["cv_data"] = [
                {"id": c[0], "name": c[1], "depts": dm.get(c[0], [])} for c in options["MaCV"]
            ]
        except Exception as e:
            flash(_safe_error(e, "Không tải được danh sách phòng ban/chức vụ."), "error")
    if key in ("donvi", "phongban", "vitri"):
        try:
            options["MaDonViCha"] = db.query(
                "SELECT MaDonVi,TenDonVi FROM DonVi WHERE TrangThai=N'Hoạt động' ORDER BY TenDonVi"
            )[1]
            options["MaDonVi"] = options["MaDonViCha"]
            options["MaPBCha"] = db.query(
                "SELECT MaPB,TenPB FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB"
            )[1]
            options["MaPB"] = options["MaPBCha"]
        except Exception as e:
            flash(_safe_error(e, "Không tải được cấu trúc tổ chức."), "error")
    if key == "hopdong":
        try:
            options["MaNV"] = [
                [r[0], (r[2] or str(r[0])) + " - " + r[1]]
                for r in db.query("SELECT MaNV,HoTen,MaNVHT FROM NhanVien ORDER BY HoTen")[1]
            ]
        except Exception as e:
            flash(_safe_error(e, "Không tải được danh sách nhân viên."), "error")
    contract_templates = []
    if key == "hopdong":
        try:
            contract_templates = db.query(
                "SELECT MaMau,TenMau,FileName,NgayTai,NoiDung FROM MauHopDong ORDER BY MaMau DESC"
            )[1]
        except Exception as e:
            flash(_safe_error(e, "Không tải được danh sách hợp đồng mẫu."), "error")
    contract_documents = []
    contract_expiry_alerts = []
    if key == "hopdong":
        try:
            contract_documents = db.query(
                "SELECT t.MaTep,n.HoTen,h.MaHD,t.TenTep,t.DinhDang,t.LoaiTaiLieu,t.PhienBan,t.TrangThai,t.NgayTao FROM TepHopDong t JOIN HopDong h ON h.MaHD=t.MaHD JOIN NhanVien n ON n.MaNV=h.MaNV ORDER BY t.MaTep DESC"
            )[1]
        except Exception as e:
            flash(_safe_error(e, "Không tải được tệp hợp đồng đã lưu."), "error")
        try:
            contract_expiry_alerts = db.query(
                "SELECT h.MaHD,n.HoTen,h.LoaiHD,h.NgayKetThuc,DATEDIFF(day,CAST(GETDATE() AS DATE),h.NgayKetThuc) AS SoNgay FROM HopDong h JOIN NhanVien n ON n.MaNV=h.MaNV WHERE h.TrangThai IN (N'Còn hiệu lực',N'Đã ký') AND h.NgayBatDau<=CAST(GETDATE() AS DATE) AND h.NgayKetThuc>=CAST(GETDATE() AS DATE) AND h.NgayKetThuc<=DATEADD(day,90,CAST(GETDATE() AS DATE)) ORDER BY h.NgayKetThuc"
            )[1]
        except Exception as e:
            flash(_safe_error(e, "Không tải được cảnh báo hết hạn hợp đồng."), "error")
    return render_template(
        "departments/module.html",
        m=m,
        key=key,
        cols=cols,
        rows=rows,
        edit=edit,
        edit_id=edit_id,
        options=options,
        admin=admin(),
        can_manage=can_manage,
        can_export=can_export,
        contract_templates=contract_templates,
        contract_documents=contract_documents,
        contract_expiry_alerts=contract_expiry_alerts,
        employee_source_key=employee_source_key,
        today=date.today().isoformat(),
    )


@bp.route("/to-chuc")
@login_required
def to_chuc():
    if not has_permission("organization.manage"):
        return redirect(url_for("dashboard.dashboard"))
    units = db.query(
        "SELECT MaDonVi,TenDonVi,MaDonViCha FROM DonVi WHERE TrangThai=N'Hoạt động' ORDER BY TenDonVi"
    )[1]
    departments = db.query(
        "SELECT MaPB,TenPB,MaDonVi,MaPBCha FROM PhongBan WHERE TrangThai=N'Hoạt động' ORDER BY TenPB"
    )[1]
    employees = db.query(
        "SELECT n.MaNV,n.HoTen,n.MaPB,c.TenCV,v.TenViTri FROM NhanVien n LEFT JOIN ChucVu c ON c.MaCV=n.MaCV LEFT JOIN ViTriCongViec v ON v.MaViTri=n.MaViTri WHERE n.TrangThai=N'Đang làm' ORDER BY n.HoTen"
    )[1]
    unit_nodes = {row[0]: {"label": row[1], "kind": "unit", "children": []} for row in units}
    dept_nodes = {
        row[0]: {"label": row[1], "kind": "department", "children": []} for row in departments
    }
    roots = []
    for unit_id, _, parent_id in units:
        node = unit_nodes[unit_id]
        if parent_id in unit_nodes:
            unit_nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)
    for dept_id, _, unit_id, parent_id in departments:
        node = dept_nodes[dept_id]
        if parent_id in dept_nodes:
            dept_nodes[parent_id]["children"].append(node)
        elif unit_id in unit_nodes:
            unit_nodes[unit_id]["children"].append(node)
        else:
            roots.append(node)
    for employee_id, name, dept_id, title, position in employees:
        item = {
            "label": name,
            "kind": "employee",
            "detail": " · ".join(x for x in (title, position) if x),
            "children": [],
        }
        if dept_id in dept_nodes:
            dept_nodes[dept_id]["children"].append(item)
        else:
            roots.append(item)
    return render_template("departments/organization.html", roots=roots, admin=admin())


def friendly_delete_error(e):
    s = str(e)
    if "REFERENCE constraint" in s or "FOREIGN KEY" in s:
        return "Không thể xóa vì bản ghi này đang được dùng ở dữ liệu khác (ví dụ phòng ban/chức vụ còn nhân viên). Hãy chuyển hoặc xóa dữ liệu liên quan trước."
    return _safe_error(e, "Không thể xóa dữ liệu lúc này.")

def delete_record(key, m, id_):
    if key == "nhanvien":
        if str(session["user"].get("manv") or "") == str(id_):
            raise ValueError("Không thể xóa nhân viên đang gắn với tài khoản bạn đang đăng nhập.")
        # Giữ lại toàn bộ hồ sơ đã tham gia nghiệp vụ để bảo toàn lịch sử.
        if db.scalar(
            "SELECT COUNT(*) FROM QuanLyTrucTiep WHERE MaQuanLy=? OR MaNV=?",
            (id_, id_),
        ):
            raise ValueError(
                "Hồ sơ này đang có liên kết quản lý trực tiếp. Hãy xử lý liên kết trước khi xóa."
            )
        if db.scalar(
            "SELECT COUNT(*) FROM NhanVienNguon WHERE MaNV=? AND LoaiNguon<>N'manual'",
            (id_,),
        ):
            raise ValueError(
                "Hồ sơ này đang được liên kết với nguồn nghiệp vụ khác. Hãy chuyển trạng thái nhân viên thay vì xóa."
            )
        if db.scalar(
            "SELECT (SELECT COUNT(*) FROM Luong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM ChamCong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM NghiPhep WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM HopDong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM NhatKyChamCong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM KhieuNaiChamCong WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM NhatKyNghiPhep WHERE MaNV=?)"
            "+(SELECT COUNT(*) FROM NhatKyLuong WHERE MaNV=?)",
            (id_,) * 8,
        ):
            raise ValueError(
                "Nhân viên này đã có lịch sử nghiệp vụ nên không xóa để tránh mất dữ liệu. "
                "Hãy sửa hồ sơ và chuyển Trạng thái sang “Đã nghỉ việc”."
            )
        if db.scalar("SELECT COUNT(*) FROM LichSuCongTac WHERE MaNV=?", (id_,)) > 1:
            raise ValueError(
                "Hồ sơ có nhiều giai đoạn công tác. Hãy chuyển trạng thái sang Đã nghỉ việc để giữ lịch sử."
            )
        if db.scalar("SELECT COUNT(*) FROM HoSoTepNhanVien WHERE MaNV=?", (id_,)):
            raise ValueError(
                "Hồ sơ có tài liệu. Hãy chuyển trạng thái sang Đã nghỉ việc để bảo toàn hồ sơ."
            )
        # Nhân viên chưa có lịch sử nghiệp vụ: xóa cùng dữ liệu phụ trong 1 giao dịch.
        if db.scalar("SELECT OBJECT_ID('LichSuDieuChuyen','U')") and db.scalar(
            "SELECT COUNT(*) FROM LichSuDieuChuyen WHERE MaNV=?", (id_,)
        ):
            raise ValueError(
                "Nhân viên đã có lịch sử điều chuyển. Hãy chuyển trạng thái sang Đã nghỉ việc để giữ lịch sử."
            )
        db.execute(
            "SET NOCOUNT ON; SET XACT_ABORT ON; BEGIN TRAN; "
            "INSERT INTO NhatKyHoSoNhanVien(MaNV,HanhDong,TruongDuLieu,NguoiThucHien) VALUES(?,N'xoa',N'*',?); "
            "IF OBJECT_ID('LichSuDieuChuyen','U') IS NOT NULL DELETE FROM LichSuDieuChuyen WHERE MaNV=?; "
            "DELETE FROM NghiPhep WHERE MaNV=?; DELETE FROM LichSuCongTac WHERE MaNV=?; DELETE FROM NhatKyHoSoTep WHERE MaNV=?; DELETE FROM QuanLyTrucTiep WHERE MaQuanLy=?; "
            "DELETE FROM QuanLyTrucTiep WHERE MaNV=?; DELETE FROM HopDong WHERE MaNV=?; "
            "DELETE FROM TaiKhoan WHERE MaNV=?; "
            "DELETE FROM NhanVienNguon WHERE MaNV=? AND LoaiNguon=N'manual'; "
            "DELETE FROM NhanVien WHERE MaNV=?; COMMIT;",
            (id_, session["user"]["user"]) + (id_,) * 10,
        )
    elif key == "hopdong":
        status = db.scalar("SELECT TrangThai FROM HopDong WHERE MaHD=?", (id_,))
        if (
            status != "Bản nháp"
            or db.scalar("SELECT COUNT(*) FROM TepHopDong WHERE MaHD=?", (id_,))
            or db.scalar("SELECT COUNT(*) FROM LichSuHopDong WHERE MaHD=?", (id_,))
        ):
            raise ValueError(
                "Hợp đồng đã có tài liệu hoặc lịch sử; không thể xóa để bảo toàn vòng đời."
            )
        db.execute("DELETE FROM HopDong WHERE MaHD=?", (id_,))
    else:
        db.execute(f"DELETE FROM {m['table']} WHERE {m['pk']}=?", (id_,))

def ensure_pbcv():
    db.execute(
        "IF OBJECT_ID('PhongBan_ChucVu','U') IS NULL CREATE TABLE PhongBan_ChucVu(MaPB INT NOT NULL REFERENCES PhongBan(MaPB) ON DELETE CASCADE, MaCV INT NOT NULL REFERENCES ChucVu(MaCV) ON DELETE CASCADE, PRIMARY KEY(MaPB,MaCV))"
    )
