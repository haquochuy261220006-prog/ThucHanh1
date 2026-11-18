"""Audit access to sensitive HR records without copying their values."""

import db


_DATA_TYPES = {"CCCD", "LienHe", "Luong", "HopDong", "HoSoDienTu"}
_ACTIONS = {"view", "list", "download", "export"}


def record(employee_id, data_type, action, actor):
    if data_type not in _DATA_TYPES or action not in _ACTIONS:
        raise ValueError("Loại nhật ký truy cập không hợp lệ.")
    db.execute(
        "INSERT INTO NhatKyTruyCapNhanSu(MaNV,LoaiDuLieu,ThaoTac,NguoiThucHien) VALUES(?,?,?,?)",
        (employee_id, data_type, action, actor),
    )


def record_many(employee_ids, data_type, action, actor):
    """Ghi nhật ký cho nhiều nhân viên; `data_type` có thể là một loại hoặc nhiều loại."""
    data_types = (data_type,) if isinstance(data_type, str) else tuple(data_type)
    if not data_types or not set(data_types) <= _DATA_TYPES or action not in _ACTIONS:
        raise ValueError("Loại nhật ký truy cập không hợp lệ.")
    ids = sorted({int(employee_id) for employee_id in employee_ids if employee_id is not None})
    if not ids:
        return
    db.execute_batches(
        [
            (
                "INSERT INTO NhatKyTruyCapNhanSu(MaNV,LoaiDuLieu,ThaoTac,NguoiThucHien) VALUES(?,?,?,?)",
                [(employee_id, kind, action, actor) for employee_id in ids for kind in data_types],
            )
        ]
    )
