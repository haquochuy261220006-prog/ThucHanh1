from __future__ import annotations

import math
import hmac
from datetime import date, datetime, timedelta

from cryptography.fernet import Fernet
from flask import current_app, jsonify, request, session

import config
from config import GIO_VAO_CHUAN
from database import db

_face_purge_day = None


def _purge_expired_face_templates():
    global _face_purge_day
    today = date.today()
    if _face_purge_day == today:
        return
    try:
        db.execute(
            "SET XACT_ABORT ON; BEGIN TRAN; INSERT INTO NhatKyChamCong(MaNV,Nguon,ThaoTac,KetQua,ChiTiet) SELECT MaNV,N'system',N'retention_delete',N'deleted',N'Mẫu khuôn mặt hết thời hạn lưu' FROM NhanVienKhuonMat WHERE ConsentAt<DATEADD(day,-?,SYSUTCDATETIME()); DELETE FROM NhanVienKhuonMat WHERE ConsentAt<DATEADD(day,-?,SYSUTCDATETIME()); COMMIT;",
            (config.FACE_RETENTION_DAYS, config.FACE_RETENTION_DAYS),
        )
    except Exception:
        current_app.logger.exception("Face template retention purge failed")
        return
    _face_purge_day = today

def _face_cipher():
    if not config.FACE_ENCRYPTION_KEY:
        raise RuntimeError(
            "Quản trị viên cần cấu hình FACE_ENCRYPTION_KEY trước khi dùng nhận diện khuôn mặt."
        )
    try:
        return Fernet(config.FACE_ENCRYPTION_KEY.encode("ascii"))
    except (ValueError, TypeError):
        raise RuntimeError("FACE_ENCRYPTION_KEY không hợp lệ; hãy tạo khóa Fernet mới.")

def _audit_attendance(
    manv, source, action, result, attendance_id=None, similarity=None, actor=None, detail=None
):
    db.execute(
        "INSERT INTO NhatKyChamCong(MaCC,MaNV,Nguon,ThaoTac,KetQua,Similarity,NguoiThucHien,ChiTiet) VALUES(?,?,?,?,?,?,?,?)",
        (
            attendance_id,
            manv,
            source,
            action,
            result,
            similarity,
            actor,
            (detail or "")[:500] or None,
        ),
    )

def _record_attendance_event(
    manv,
    attendance_id,
    action,
    source,
    result,
    actor,
    detail=None,
    similarity=None,
    happened_at=None,
    work_date=None,
):
    """Append an event while retaining its business date and legacy summary link."""
    happened_at = happened_at or datetime.now()
    db.execute(
        "INSERT INTO ChamCongSuKien(MaNV,NgayCong,MaCC,ThoiDiem,LoaiSuKien,Nguon,KetQua,Similarity,NguoiThucHien,ChiTiet) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            manv,
            work_date or happened_at.date(),
            attendance_id,
            happened_at,
            action,
            source,
            result,
            similarity,
            actor,
            (detail or "")[:500],
        ),
    )

def _attendance_status(manv, work_date, occurred_at):
    shifts = db.query(
        "SELECT COALESCE(p.GioBatDauOverride,c.GioBatDau),c.PhutAnHan FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.MaNV=? AND p.Ngay=? ORDER BY COALESCE(p.GioBatDauOverride,c.GioBatDau)",
        (manv, work_date),
    )[1]
    actual_minutes = occurred_at.hour * 60 + occurred_at.minute
    if shifts:
        start, grace = shifts[0]
        cutoff = (start.hour * 60 + start.minute + grace) % 1440
    else:
        cutoff_time = datetime.strptime(GIO_VAO_CHUAN, "%H:%M").time()
        cutoff = cutoff_time.hour * 60 + cutoff_time.minute
    return "Đi muộn" if actual_minutes > cutoff else "Đi làm"

def _attendance_work_date(manv, occurred_at):
    work_date = occurred_at.date()
    previous_day = work_date - timedelta(days=1)
    overnight_shifts = db.query(
        "SELECT COALESCE(p.GioKetThucOverride,c.GioKetThuc) FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.MaNV=? AND p.Ngay=? AND ((p.GioBatDauOverride IS NOT NULL OR p.GioKetThucOverride IS NOT NULL) AND COALESCE(p.GioKetThucOverride,c.GioKetThuc)<COALESCE(p.GioBatDauOverride,c.GioBatDau) OR p.GioBatDauOverride IS NULL AND p.GioKetThucOverride IS NULL AND c.QuaDem=1)",
        (manv, previous_day),
    )[1]
    return (
        previous_day
        if any(occurred_at.time() <= shift_end for (shift_end,) in overnight_shifts)
        else work_date
    )

def _record_attendance_cycle(
    manv, work_date, action, source, result, actor, detail=None, similarity=None, occurred_at=None
):
    """Atomically append an in/out event and update the compatible daily summary."""
    occurred_at = occurred_at or datetime.now()
    status = _attendance_status(manv, work_date, occurred_at)
    sql = """
    SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    DECLARE @action NVARCHAR(20)=?, @employee_id INT=?, @work_date DATE=?,
            @event_at DATETIME2=?, @status NVARCHAR(20)=?, @source NVARCHAR(20)=?,
            @result NVARCHAR(30)=?, @similarity DECIMAL(7,5)=?,
            @actor NVARCHAR(50)=?, @detail NVARCHAR(500)=?, @attendance_id INT,
            @last_action NVARCHAR(20), @lock_result INT, @resource NVARCHAR(255);
    SET @resource=CONCAT(N'attendance:',@employee_id,N':',CONVERT(NVARCHAR(10),@work_date,23));
    EXEC @lock_result=sys.sp_getapplock
        @Resource=@resource,
        @LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=5000,@DbPrincipal='public';
    IF @lock_result<0 THROW 51010,'Attendance record is busy.',1;
    SELECT TOP (1) @last_action=LoaiSuKien
      FROM ChamCongSuKien WITH (UPDLOCK,HOLDLOCK)
     WHERE MaNV=@employee_id AND NgayCong=@work_date
       AND LoaiSuKien IN (N'in',N'out',N'delete')
     ORDER BY MaSuKien DESC;
    IF @last_action=N'delete' SET @last_action=NULL;
    IF @action=N'in' AND @last_action=N'in' THROW 51011,'An in event is already open.',1;
    IF @action=N'out' AND ISNULL(@last_action,N'')<>N'in' THROW 51012,'There is no open in event.',1;
    SELECT @attendance_id=MaCC FROM ChamCong WITH (UPDLOCK,HOLDLOCK)
     WHERE MaNV=@employee_id AND Ngay=@work_date;
    IF @action=N'in'
    BEGIN
        IF @attendance_id IS NULL
            INSERT INTO ChamCong(MaNV,Ngay,GioVao,TrangThai)
            VALUES(@employee_id,@work_date,CAST(@event_at AS TIME),@status);
        ELSE
            UPDATE ChamCong SET GioVao=COALESCE(GioVao,CAST(@event_at AS TIME)),
                GioRa=NULL,TrangThai=CASE WHEN GioVao IS NULL THEN @status ELSE TrangThai END
             WHERE MaCC=@attendance_id;
    END
    ELSE
    BEGIN
        IF @attendance_id IS NULL THROW 51012,'There is no daily summary for this event.',1;
        UPDATE ChamCong SET GioRa=CAST(@event_at AS TIME) WHERE MaCC=@attendance_id;
    END;
    SELECT @attendance_id=MaCC FROM ChamCong WHERE MaNV=@employee_id AND Ngay=@work_date;
    INSERT INTO ChamCongSuKien(MaNV,NgayCong,MaCC,ThoiDiem,LoaiSuKien,Nguon,KetQua,Similarity,NguoiThucHien,ChiTiet)
    VALUES(@employee_id,@work_date,@attendance_id,@event_at,@action,@source,@result,@similarity,@actor,@detail);
    INSERT INTO NhatKyChamCong(MaCC,MaNV,Nguon,ThaoTac,KetQua,Similarity,NguoiThucHien,ChiTiet)
    VALUES(@attendance_id,@employee_id,@source,@action,@result,@similarity,@actor,@detail);
    COMMIT;
    """
    try:
        db.execute(
            sql,
            (
                action,
                manv,
                work_date,
                occurred_at,
                status,
                source,
                result,
                similarity,
                actor,
                (detail or "")[:500],
            ),
        )
    except Exception as error:
        message = str(error)
        if "51010" in message:
            raise ValueError("Đang ghi nhận chấm công khác cho ngày này. Hãy thử lại.") from error
        if "51011" in message:
            raise ValueError("Chưa chấm ra khỏi lượt làm trước đó.") from error
        if "51012" in message:
            raise ValueError("Cần chấm vào trước khi chấm ra.") from error
        raise

def _attendance_intervals(employee_id, start_at, end_at):
    rows = db.query(
        "SELECT e.ThoiDiem,e.LoaiSuKien FROM ChamCongSuKien e WHERE e.MaNV=? AND e.ThoiDiem>=? AND e.ThoiDiem<=? AND e.LoaiSuKien IN (N'in',N'out') AND e.MaSuKien>ISNULL((SELECT MAX(x.MaSuKien) FROM ChamCongSuKien x WHERE x.MaNV=e.MaNV AND x.NgayCong=e.NgayCong AND x.LoaiSuKien=N'delete'),0) ORDER BY e.ThoiDiem,e.MaSuKien",
        (employee_id, start_at - timedelta(hours=24), end_at),
    )[1]
    intervals, opened = [], None
    for occurred_at, action in rows:
        if action == "delete":
            opened = None
        elif action == "in" and opened is None:
            opened = occurred_at
        elif action == "out" and opened is not None and occurred_at >= opened:
            intervals.append((opened, occurred_at))
            opened = None
    return intervals

def _observed_overtime_hours(employee_id, start_at, end_at):
    seconds = sum(
        (min(end, end_at) - max(start, start_at)).total_seconds()
        for start, end in _attendance_intervals(employee_id, start_at, end_at)
        if min(end, end_at) > max(start, start_at)
    )
    return round(seconds / 3600, 2)

def face_payload():
    if not hmac.compare_digest(
        request.headers.get("X-Face-CSRF", ""), session.get("face_csrf", "")
    ):
        return None, (jsonify(error="Phiên làm việc hết hạn. Hãy tải lại trang."), 400)
    if request.content_length and request.content_length > 65536:
        return None, (jsonify(error="Dữ liệu quét quá lớn. Hãy thử lại."), 413)
    data = request.get_json(silent=True) or {}
    embedding = data.get("embedding")
    if (
        not isinstance(embedding, list)
        or len(embedding) != 1024
        or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or abs(v) > 10
            for v in embedding
        )
    ):
        return None, (jsonify(error="Mẫu khuôn mặt không hợp lệ. Hãy quét lại."), 400)
    return data, None

def face_employee_id(data):
    if session.get("user", {}).get("role") == "QuanTri":
        raise ValueError("Chấm công bằng khuôn mặt chỉ dành cho tài khoản nhân viên.")
    try:
        manv = int(session["user"].get("manv") or 0)
    except (TypeError, ValueError):
        manv = 0
    if not manv:
        raise ValueError("Tài khoản chưa gắn với nhân viên nào hoặc chưa chọn nhân viên.")
    if not db.scalar(
        "SELECT COUNT(*) FROM NhanVien WHERE MaNV=? AND TrangThai=N'Đang làm'", (manv,)
    ):
        raise ValueError("Nhân viên không tồn tại hoặc đã nghỉ việc.")
    return manv


FACE_MATCH_THRESHOLD = config.FACE_MATCH_THRESHOLD


def _parse_optional_shift_time(value):
    value = (value or "").strip()
    return datetime.strptime(value, "%H:%M").time() if value else None

def _validate_employee_shift_assignment(
    employee_id, work_date, start, end, overnight, exclude_ids=()
):
    if start == end or (end < start) != bool(overnight):
        raise ValueError("Giờ bắt đầu/kết thúc của ca không hợp lệ.")
    rows = db.query(
        "SELECT p.MaPhanCa,p.Ngay,COALESCE(p.GioBatDauOverride,c.GioBatDau),COALESCE(p.GioKetThucOverride,c.GioKetThuc),CASE WHEN p.GioBatDauOverride IS NOT NULL OR p.GioKetThucOverride IS NOT NULL THEN CASE WHEN COALESCE(p.GioKetThucOverride,c.GioKetThuc)<COALESCE(p.GioBatDauOverride,c.GioBatDau) THEN 1 ELSE 0 END ELSE c.QuaDem END FROM PhanCaNhanVien p JOIN CaLamViec c ON c.MaCa=p.MaCa WHERE p.MaNV=? AND p.Ngay BETWEEN DATEADD(day,-1,?) AND DATEADD(day,1,?)",
        (employee_id, work_date, work_date),
    )[1]
    start_min = start.hour * 60 + start.minute
    end_min = end.hour * 60 + end.minute + (1440 if overnight else 0)
    excluded = {int(value) for value in exclude_ids}
    for assignment_id, old_day, old_start, old_end, old_overnight in rows:
        if int(assignment_id) in excluded:
            continue
        offset = (old_day - work_date).days * 1440
        old_start_min = offset + old_start.hour * 60 + old_start.minute
        old_end_min = offset + old_end.hour * 60 + old_end.minute + (1440 if old_overnight else 0)
        if max(start_min, old_start_min) < min(end_min, old_end_min):
            raise ValueError("Ca bị trùng giờ với một ca đã phân cho nhân viên.")
