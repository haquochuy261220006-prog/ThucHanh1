from __future__ import annotations

from datetime import timedelta

import config
from database import db

LEAVE_TYPES = ("Phép năm", "Không lương", "Nghỉ ốm", "Việc riêng có lương", "Khác")

_LEAVE_PENDING_DAYS = """ISNULL(SUM(CASE
    WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
         AND LoaiCu=N'Phép năm' AND SoNgayCu IS NOT NULL
    THEN CASE WHEN SoNgay>SoNgayCu THEN SoNgay-SoNgayCu ELSE 0 END
    ELSE SoNgay END),0)"""


def _leave_days(employee_id, start, end):
    scheduled = db.query("SELECT Thu FROM LichLamViecNhanVien WHERE MaNV=?", (employee_id,))[1]
    work_days = (
        {row[0] for row in scheduled} if scheduled else set(range(7)) - set(config.NGAY_NGHI_TUAN)
    )
    holidays = {
        row[0]
        for row in db.query("SELECT Ngay FROM LichNgayLe WHERE Ngay>=? AND Ngay<=?", (start, end))[
            1
        ]
    }
    assigned_days = {
        row[0]
        for row in db.query(
            "SELECT DISTINCT Ngay FROM PhanCaNhanVien WHERE MaNV=? AND Ngay>=? AND Ngay<=?",
            (employee_id, start, end),
        )[1]
    }
    if assigned_days:
        return sum(day not in holidays for day in assigned_days)
    return sum(
        1
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() in work_days
        and start + timedelta(days=offset) not in holidays
    )

def _leave_audit(leave_id, employee_id, action, old_status, new_status, detail, actor):
    db.execute(
        "INSERT INTO NhatKyNghiPhep(MaNP,MaNV,ThaoTac,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien) VALUES(?,?,?,?,?,?,?)",
        (leave_id, employee_id, action, old_status, new_status, (detail or "")[:1000], actor),
    )

def _leave_notify(employee_id, leave_id, message):
    db.execute(
        "INSERT INTO ThongBaoNghiPhep(MaNV,MaNP,NoiDung) VALUES(?,?,?)",
        (employee_id, leave_id, message[:500]),
    )

def _leave_quota(employee_id, year):
    row = db.query(
        "SELECT SoNgayCap,SoNgayChuyen FROM QuyPhepNam WHERE MaNV=? AND Nam=?", (employee_id, year)
    )[1]
    allocated, carry = row[0] if row else (0, 0)
    used = (
        db.scalar(
            "SELECT ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0) FROM NghiPhep WHERE MaNV=? AND ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy')) OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL)) AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=?",
            (employee_id, year),
        )
        or 0
    )
    pending = (
        db.scalar(
            f"SELECT {_LEAVE_PENDING_DAYS} FROM NghiPhep WHERE MaNV=? AND LoaiNghi=N'Phép năm' AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND YEAR(TuNgay)=?",
            (employee_id, year),
        )
        or 0
    )
    return float(allocated), float(carry), float(used), float(pending)

def _save_leave_quota(employee_id, year, allocated, carry):
    sql = f"""SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    DECLARE @employee_id INT=?, @year INT=?, @allocated DECIMAL(6,2)=?,
            @carry DECIMAL(6,2)=?, @resource NVARCHAR(255), @lock_result INT,
            @used DECIMAL(9,2)=0, @pending DECIMAL(9,2)=0;
    SET @resource=CONCAT(N'leave-quota:',@employee_id);
    EXEC @lock_result=sys.sp_getapplock @Resource=@resource,@LockMode='Exclusive',
         @LockOwner='Transaction',@LockTimeout=10000,@DbPrincipal='public';
    IF @lock_result<0 THROW 52030,'Leave quota lock unavailable.',1;
    SELECT @used=ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
           AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0)
    FROM NghiPhep WHERE MaNV=@employee_id AND
         ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy'))
          OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL))
      AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
                    AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=@year;
    SELECT @pending={_LEAVE_PENDING_DAYS}
    FROM NghiPhep WHERE MaNV=@employee_id AND LoaiNghi=N'Phép năm'
      AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
      AND YEAR(TuNgay)=@year;
    IF @allocated+@carry<@used+@pending
        THROW 52031,'Annual leave allocation is below reserved balance.',1;
    IF EXISTS(SELECT 1 FROM QuyPhepNam WITH(UPDLOCK,HOLDLOCK) WHERE MaNV=@employee_id AND Nam=@year)
        UPDATE QuyPhepNam SET SoNgayCap=@allocated,SoNgayChuyen=@carry WHERE MaNV=@employee_id AND Nam=@year;
    ELSE
        INSERT INTO QuyPhepNam(MaNV,Nam,SoNgayCap,SoNgayChuyen) VALUES(@employee_id,@year,@allocated,@carry);
    COMMIT;
    SELECT 1 AS Saved;"""
    try:
        result = db.query(sql, (employee_id, year, allocated, carry))[1]
    except Exception as error:
        message = str(error)
        if "52030" in message:
            raise ValueError("Đang cập nhật quỹ phép khác; vui lòng thử lại.") from error
        if "52031" in message:
            allocated, carry, used, pending = _leave_quota(employee_id, year)
            raise ValueError(
                f"Quỹ mới phải tối thiểu {used + pending:g} ngày để giữ đủ ngày đã dùng và các đơn đang chờ."
            ) from error
        raise
    if not result:
        raise RuntimeError("SQL Server không xác nhận đã lưu quỹ phép.")

def _create_leave_request(employee_id, start, end, days, reason, leave_type, state, actor):
    sql = f"""SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    DECLARE @employee_id INT=?, @start DATE=?, @end DATE=?, @days INT=?,
            @reason NVARCHAR(255)=?, @leave_type NVARCHAR(40)=?, @state NVARCHAR(20)=?,
            @actor NVARCHAR(50)=?, @year INT=YEAR(?), @lock_result INT,
            @resource NVARCHAR(255), @allocated DECIMAL(6,2)=0, @carry DECIMAL(6,2)=0,
            @used DECIMAL(9,2)=0, @pending DECIMAL(9,2)=0, @leave_id INT;
    SET @resource=CONCAT(N'leave-quota:',@employee_id);
    EXEC @lock_result=sys.sp_getapplock @Resource=@resource,@LockMode='Exclusive',
         @LockOwner='Transaction',@LockTimeout=10000,@DbPrincipal='public';
    IF @lock_result<0 THROW 52010,'Leave request lock unavailable.',1;
    IF EXISTS(SELECT 1 FROM NghiPhep WITH(UPDLOCK,HOLDLOCK)
        WHERE MaNV=@employee_id AND TrangThai NOT IN (N'Từ chối',N'Đã rút',N'Đã hủy')
          AND ((TuNgay<=@end AND DenNgay>=@start) OR (NgayCuTu<=@end AND NgayCuDen>=@start)))
        THROW 52011,'Leave date overlaps another active request.',1;
    IF @leave_type=N'Phép năm'
    BEGIN
        SELECT @allocated=SoNgayCap,@carry=SoNgayChuyen
        FROM QuyPhepNam WITH(UPDLOCK,HOLDLOCK) WHERE MaNV=@employee_id AND Nam=@year;
        SELECT @used=ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
               AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0)
        FROM NghiPhep WHERE MaNV=@employee_id AND
             ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy'))
              OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL))
          AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
                        AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=@year;
        SELECT @pending={_LEAVE_PENDING_DAYS}
        FROM NghiPhep WHERE MaNV=@employee_id AND LoaiNghi=N'Phép năm'
          AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
          AND YEAR(TuNgay)=@year;
        IF @days>@allocated+@carry-@used-@pending
            THROW 52012,'Annual leave quota is insufficient.',1;
    END;
    INSERT INTO NghiPhep(MaNV,TuNgay,DenNgay,SoNgay,LyDo,LoaiNghi,TrangThai)
    VALUES(@employee_id,@start,@end,@days,@reason,@leave_type,@state);
    SET @leave_id=CONVERT(INT,SCOPE_IDENTITY());
    INSERT INTO NhatKyNghiPhep(MaNP,MaNV,ThaoTac,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien)
    VALUES(@leave_id,@employee_id,N'submit',NULL,@state,CONCAT(@leave_type,N'; ',@days,N' ngày'),@actor);
    COMMIT;
    SELECT @leave_id AS MaNP;"""
    try:
        result = db.query(
            sql,
            (employee_id, start, end, days, reason, leave_type, state, actor, start),
        )[1]
    except Exception as error:
        message = str(error)
        if "52010" in message:
            raise ValueError("Đang xử lý yêu cầu nghỉ khác; vui lòng gửi lại.") from error
        if "52011" in message:
            raise ValueError("Khoảng ngày vừa trùng với một đơn nghỉ đang hoạt động.") from error
        if "52012" in message:
            allocated, carry, used, pending = _leave_quota(employee_id, start.year)
            available = max(0, allocated + carry - used - pending)
            raise ValueError(
                f"Quỹ phép năm còn {available:g} ngày, không đủ cho yêu cầu {days} ngày."
            ) from error
        raise
    if not result:
        raise RuntimeError("SQL Server đã lưu đơn nhưng không trả mã đơn mới.")
    return result[0][0]

def _update_leave_request(
    leave_id,
    employee_id,
    start,
    end,
    days,
    reason,
    leave_type,
    state,
    expected_state,
    expected_start,
    expected_end,
    expected_days,
    expected_type,
    actor,
):
    sql = f"""SET NOCOUNT ON;
    SET XACT_ABORT ON;
    BEGIN TRAN;
    DECLARE @leave_id INT=?, @employee_id INT=?, @start DATE=?, @end DATE=?, @days INT=?,
            @reason NVARCHAR(255)=?, @leave_type NVARCHAR(40)=?, @state NVARCHAR(40)=?,
            @expected_state NVARCHAR(40)=?, @expected_start DATE=?, @expected_end DATE=?,
            @expected_days INT=?, @expected_type NVARCHAR(40)=?, @actor NVARCHAR(50)=?,
            @year INT=YEAR(?),
            @old_start DATE, @old_end DATE, @old_days INT, @old_type NVARCHAR(40),
            @old_state NVARCHAR(40), @save_old BIT=0, @lock_result INT,
            @resource NVARCHAR(255), @allocated DECIMAL(6,2)=0, @carry DECIMAL(6,2)=0,
            @used DECIMAL(9,2)=0, @pending DECIMAL(9,2)=0;
    SET @resource=CONCAT(N'leave-quota:',@employee_id);
    EXEC @lock_result=sys.sp_getapplock @Resource=@resource,@LockMode='Exclusive',
         @LockOwner='Transaction',@LockTimeout=10000,@DbPrincipal='public';
    IF @lock_result<0 THROW 52020,'Leave change lock unavailable.',1;
    SELECT @old_start=TuNgay,@old_end=DenNgay,@old_days=SoNgay,@old_type=LoaiNghi,@old_state=TrangThai
    FROM NghiPhep WITH(UPDLOCK,HOLDLOCK)
    WHERE MaNP=@leave_id AND MaNV=@employee_id;
    IF @old_state IS NULL OR @old_state<>@expected_state OR @old_start<>@expected_start
       OR @old_end<>@expected_end OR @old_days<>@expected_days OR @old_type<>@expected_type
        THROW 52021,'Leave request changed before update.',1;
    IF @old_state NOT IN (N'Chờ quản lý',N'Chờ nhân sự',N'Đã duyệt')
        THROW 52021,'Leave request is no longer editable.',1;
    IF EXISTS(SELECT 1 FROM NghiPhep WITH(UPDLOCK,HOLDLOCK)
        WHERE MaNV=@employee_id AND MaNP<>@leave_id
          AND TrangThai NOT IN (N'Từ chối',N'Đã rút',N'Đã hủy')
          AND ((TuNgay<=@end AND DenNgay>=@start) OR (NgayCuTu<=@end AND NgayCuDen>=@start)))
        THROW 52022,'Leave date overlaps another active request.',1;
    IF @leave_type=N'Phép năm'
    BEGIN
        SELECT @allocated=SoNgayCap,@carry=SoNgayChuyen
        FROM QuyPhepNam WITH(UPDLOCK,HOLDLOCK) WHERE MaNV=@employee_id AND Nam=@year;
        SELECT @used=ISNULL(SUM(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
               AND SoNgayCu IS NOT NULL THEN SoNgayCu ELSE SoNgay END),0)
        FROM NghiPhep WHERE MaNV=@employee_id AND MaNP<>@leave_id AND
             ((LoaiNghi=N'Phép năm' AND TrangThai IN (N'Đã duyệt',N'Chờ quản lý hủy',N'Chờ nhân sự hủy'))
              OR (LoaiCu=N'Phép năm' AND TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi') AND SoNgayCu IS NOT NULL))
          AND YEAR(CASE WHEN TrangThai IN (N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
                        AND SoNgayCu IS NOT NULL THEN NgayCuTu ELSE TuNgay END)=@year;
        SELECT @pending={_LEAVE_PENDING_DAYS}
        FROM NghiPhep WHERE MaNV=@employee_id AND MaNP<>@leave_id AND LoaiNghi=N'Phép năm'
          AND TrangThai IN (N'Chờ quản lý',N'Chờ nhân sự',N'Chờ quản lý thay đổi',N'Chờ nhân sự thay đổi')
          AND YEAR(TuNgay)=@year;
        IF @days>@allocated+@carry-@used-@pending
            THROW 52023,'Annual leave quota is insufficient.',1;
    END;
    SET @save_old=CASE WHEN @old_state=N'Đã duyệt' AND @state<>N'Đã duyệt' THEN 1 ELSE 0 END;
    UPDATE NghiPhep SET TuNgay=@start,DenNgay=@end,SoNgay=@days,LyDo=@reason,LoaiNghi=@leave_type,
        NgayCuTu=CASE WHEN @save_old=1 THEN @old_start ELSE NULL END,
        NgayCuDen=CASE WHEN @save_old=1 THEN @old_end ELSE NULL END,
        SoNgayCu=CASE WHEN @save_old=1 THEN @old_days ELSE NULL END,
        LoaiCu=CASE WHEN @save_old=1 THEN @old_type ELSE NULL END,TrangThai=@state
    WHERE MaNP=@leave_id AND MaNV=@employee_id;
    IF @@ROWCOUNT<>1 THROW 52021,'Leave request changed before update.',1;
    INSERT INTO NhatKyNghiPhep(MaNP,MaNV,ThaoTac,TrangThaiCu,TrangThaiMoi,ChiTiet,NguoiThucHien)
    VALUES(@leave_id,@employee_id,N'change',@old_state,@state,
        CONCAT(CONVERT(NVARCHAR(10),@old_start,23),N' -> ',CONVERT(NVARCHAR(10),@start,23)),@actor);
    COMMIT;
    SELECT 1 AS Updated;"""
    try:
        result = db.query(
            sql,
            (
                leave_id,
                employee_id,
                start,
                end,
                days,
                reason,
                leave_type,
                state,
                expected_state,
                expected_start,
                expected_end,
                expected_days,
                expected_type,
                actor,
                start,
            ),
        )[1]
    except Exception as error:
        message = str(error)
        if "52020" in message:
            raise ValueError("Đang xử lý yêu cầu nghỉ khác; vui lòng gửi lại.") from error
        if "52021" in message:
            raise ValueError(
                "Đơn nghỉ đã được cập nhật hoặc không còn ở trạng thái có thể sửa."
            ) from error
        if "52022" in message:
            raise ValueError(
                "Khoảng ngày mới vừa trùng với một đơn nghỉ đang hoạt động."
            ) from error
        if "52023" in message:
            allocated, carry, used, pending = _leave_quota(employee_id, start.year)
            available = max(0, allocated + carry - used - pending)
            raise ValueError(
                f"Quỹ phép năm còn {available:g} ngày, không đủ cho thay đổi này ({days} ngày)."
            ) from error
        raise
    if not result:
        raise RuntimeError("SQL Server không xác nhận đã cập nhật đơn nghỉ.")
