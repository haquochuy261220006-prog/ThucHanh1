"""Công thức tính lương tháng.

Tổng lương hiện tại = Lương cơ bản
                + Thưởng chuyên cần (đi làm >= CHUYEN_CAN_SO_NGAY ngày -> + CHUYEN_CAN_TY_LE x lương cơ bản)
                + Tiền tăng ca
                - Ghi nhận đi muộn; mặc định không tự khấu trừ lương
                - Trừ nghỉ không phép (mỗi ngày trừ NGHI_KP_TRU_NGAY ngày lương)
Ngày lương = Lương cơ bản / CONG_CHUAN.
Mọi tham số chỉnh trong config.py.
Tổng hợp công, tính tiền, duyệt kỳ và áp dụng chính sách tháng được tách thành các hàm riêng.
"""

import calendar
import json
from datetime import date, datetime, time, timedelta

import config


def _to_date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _to_time(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.time()
    if isinstance(v, time):
        return v
    try:
        p = [int(x) for x in str(v).split(".")[0].split(":")]
        return time(p[0], p[1] if len(p) > 1 else 0)
    except (ValueError, IndexError):
        return None


def _hm(t):
    return t.hour * 60 + t.minute


def summarize_attendance(
    ngay_vao,
    cham_cong,
    nghi_phep,
    year,
    month,
    today=None,
    work_weekdays=None,
    scheduled_shifts=None,
    holidays=None,
):
    """Tổng hợp công theo ca được phân, lịch tuần cá nhân hoặc lịch mặc định."""
    today = today or date.today()
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    present, excused, so_muon, phut_tc = set(), set(), 0, 0
    gio_vao_chuan = _hm(_to_time(config.GIO_VAO_CHUAN))
    gio_ra_chuan = _hm(_to_time(config.GIO_RA_CHUAN))
    work_weekdays = set(work_weekdays) if work_weekdays is not None else set(range(7)) - set(config.NGAY_NGHI_TUAN)
    scheduled_shifts = scheduled_shifts or {}
    holidays = set(holidays or ())

    for ngay, gio_vao, gio_ra, trang_thai in cham_cong:
        d = _to_date(ngay)
        if d is None:
            continue
        if trang_thai == "Nghỉ phép":
            excused.add(d)
            continue
        if trang_thai in ("Nghỉ", "Nghỉ không phép"):
            continue
        present.add(d)
        tv, tr = _to_time(gio_vao), _to_time(gio_ra)
        shifts = scheduled_shifts.get(d, ())
        if shifts and tv:
            start_time, grace_minutes = min(shifts, key=lambda item: _hm(_to_time(item[0]) or time.min))
            shift_threshold = (_hm(_to_time(start_time)) + int(grace_minutes or 0)) % 1440
            is_late = _hm(tv) > shift_threshold
        else:
            is_late = bool(tv and _hm(tv) > gio_vao_chuan)
        if trang_thai == "Đi muộn" or is_late:
            so_muon += 1
        if tr and _hm(tr) > gio_ra_chuan:
            phut_tc += _hm(tr) - gio_ra_chuan

    for tu, den in nghi_phep:
        tu, den = _to_date(tu), _to_date(den)
        if tu and den:
            d = max(tu, first)
            while d <= min(den, last):
                excused.add(d)
                d += timedelta(days=1)

    start = max(first, _to_date(ngay_vao) or first)
    end = last if last < today else today - timedelta(days=1)
    nghi_kp, d = 0, start
    while d <= end:
        expected_workday = d in scheduled_shifts if scheduled_shifts else d.weekday() in work_weekdays
        if expected_workday and d not in holidays and d not in present and d not in excused:
            nghi_kp += 1
        d += timedelta(days=1)

    return {
        "ngay_di_lam": len(present),
        "gio_tang_ca": round(phut_tc / 60, 2),
        "so_lan_muon": so_muon,
        "so_ngay_nghi_kp": nghi_kp,
    }


def summarize_attendance_event_hours(database, year, month):
    """Return completed event-pair hours by employee for a month, for reconciliation only."""
    first = date(year, month, 1)
    rows = database.query(
        """WITH EffectiveEvents AS (
               SELECT e.MaNV,e.NgayCong,e.MaSuKien,e.ThoiDiem,e.LoaiSuKien
               FROM ChamCongSuKien e
               JOIN ChamCong c ON c.MaNV=e.MaNV AND c.Ngay=e.NgayCong
               WHERE e.NgayCong>=? AND e.NgayCong<DATEADD(month,1,?)
                 AND e.LoaiSuKien IN (N'in',N'out')
                 AND c.TrangThai IN (N'Đi làm',N'Đi muộn')
                 AND e.MaSuKien>ISNULL((SELECT MAX(x.MaSuKien)
                     FROM ChamCongSuKien x
                     WHERE x.MaNV=e.MaNV AND x.NgayCong=e.NgayCong
                       AND x.LoaiSuKien=N'delete'),0)
           ), OrderedEvents AS (
               SELECT MaNV,NgayCong,LoaiSuKien,ThoiDiem,
                   LEAD(LoaiSuKien) OVER(PARTITION BY MaNV,NgayCong ORDER BY MaSuKien) AS NextType,
                   LEAD(ThoiDiem) OVER(PARTITION BY MaNV,NgayCong ORDER BY MaSuKien) AS NextTime
               FROM EffectiveEvents
           )
           SELECT MaNV,ROUND(SUM(DATEDIFF(SECOND,ThoiDiem,NextTime))/3600.0,2) AS HoursWorked
           FROM OrderedEvents
           WHERE LoaiSuKien=N'in' AND NextType=N'out' AND NextTime>=ThoiDiem
           GROUP BY MaNV""",
        (first, first),
    )[1]
    return {int(employee_id): float(hours or 0) for employee_id, hours in rows}

def calculate_payroll(
    base_salary,
    days,
    overtime_hours,
    late_count,
    unpaid_days,
    bonus_rate,
    overtime_factor,
    extra_bonus=0,
    standard_workdays=None,
    hours_per_workday=None,
    attendance_bonus_min_days=None,
):
    """Tính các khoản lương từ số liệu công đã tổng hợp và chính sách kỳ lương."""
    standard_workdays = standard_workdays or config.CONG_CHUAN
    hours_per_workday = hours_per_workday or config.GIO_LAM_NGAY
    attendance_bonus_min_days = attendance_bonus_min_days or config.CHUYEN_CAN_SO_NGAY
    daily = float(base_salary or 0) / standard_workdays
    attendance_bonus = (
        round(float(base_salary or 0) * bonus_rate)
        if (days or 0) >= attendance_bonus_min_days
        else 0
    )
    overtime_pay = round(
        float(overtime_hours or 0) * daily / hours_per_workday * overtime_factor
    )
    late_deduction = round((late_count or 0) * config.MUON_TRU_NGAY * daily)
    unpaid_deduction = round((unpaid_days or 0) * config.NGHI_KP_TRU_NGAY * daily)
    deductions = late_deduction + unpaid_deduction
    total = max(
        0,
        round(float(base_salary or 0))
        + attendance_bonus
        + overtime_pay
        + float(extra_bonus or 0)
        - deductions,
    )
    return (
        attendance_bonus,
        overtime_pay,
        late_deduction,
        unpaid_deduction,
        deductions,
        total,
    )

def get_period_status(database, year, month):
    rows = database.query(
        "SELECT TrangThai FROM LuongKy WHERE Nam=? AND Thang=?", (year, month)
    )[1]
    return rows[0][0] if rows else "Nháp"


def approve_period(database, year, month, username, reason):
    if not database.scalar("SELECT COUNT(*) FROM Luong WHERE Thang=? AND Nam=?", (month, year)):
        raise ValueError("Hãy tính bảng lương trước khi phê duyệt.")
    database.execute(
        "SET XACT_ABORT ON; BEGIN TRAN; UPDATE LuongKy SET TrangThai=N'Đã duyệt',DuyetLuc=SYSUTCDATETIME(),DuyetBoi=? WHERE Nam=? AND Thang=? AND TrangThai=N'Nháp' AND TinhLuc IS NOT NULL; IF @@ROWCOUNT<>1 THROW 50001,'Kỳ lương không ở trạng thái nháp.',1; INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,GiaTriMoi,LyDo,NguoiThucHien) VALUES(NULL,?,?,N'Phê duyệt kỳ lương',N'Nháp',N'Đã duyệt',?,?); COMMIT;",
        (username, year, month, month, year, reason, username),
    )


def lock_period(database, year, month, username, reason):
    database.execute(
        "SET XACT_ABORT ON; BEGIN TRAN; UPDATE LuongKy SET TrangThai=N'Đã khóa',KhoaLuc=SYSUTCDATETIME(),KhoaBoi=? WHERE Nam=? AND Thang=? AND TrangThai=N'Đã duyệt'; IF @@ROWCOUNT<>1 THROW 50002,'Chỉ có thể khóa kỳ lương đã duyệt.',1; INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,GiaTriMoi,LyDo,NguoiThucHien) VALUES(NULL,?,?,N'Khóa kỳ lương',N'Đã duyệt',N'Đã khóa',?,?); COMMIT;",
        (username, year, month, month, year, reason, username),
    )


def apply_month_rules(database, year, month, bonus_rate, overtime_factor, old_rules, reason, username):
    rows = database.query(
        "SELECT MaNV,LuongCB,NgayCong,GioTangCa,SoLanMuon,SoNgayNghiKP,ISNULL(ThuongThem,0) FROM Luong WHERE Nam=? AND Thang=?",
        (year, month),
    )[1]
    updates = []
    for manv, base_salary, days, overtime_hours, late_count, unpaid_days, extra_bonus in rows:
        bonus, overtime, late, unpaid, deductions, total = calculate_payroll(
            base_salary, days, overtime_hours, late_count, unpaid_days,
            bonus_rate, overtime_factor, extra_bonus,
        )
        updates.append((bonus, overtime, bonus + overtime, late, unpaid, deductions, total, manv, month, year))
    database.execute_batches([
        (
            "IF NOT EXISTS(SELECT 1 FROM LuongKy WITH(UPDLOCK,HOLDLOCK) WHERE Nam=? AND Thang=?) INSERT INTO LuongKy(Nam,Thang,TrangThai) VALUES(?, ?, N'Nháp')",
            [(year, month, year, month)],
        ),
        (
            "IF EXISTS(SELECT 1 FROM LuongCauHinhThang WHERE Nam=? AND Thang=?) UPDATE LuongCauHinhThang SET TyLeThuongCC=?,HeSoTangCa=? WHERE Nam=? AND Thang=? ELSE INSERT INTO LuongCauHinhThang(Nam,Thang,TyLeThuongCC,HeSoTangCa) VALUES(?,?,?,?)",
            [(year, month, bonus_rate, overtime_factor, year, month, year, month, bonus_rate, overtime_factor)],
        ),
        ("UPDATE Luong SET ThuongCC=?,TienTangCa=?,PhuCap=?,TruMuon=?,TruNghiKP=?,KhauTru=?,TongLuong=? WHERE MaNV=? AND Thang=? AND Nam=?", updates),
        (
            "INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,GiaTriMoi,LyDo,NguoiThucHien) VALUES(NULL,?,?,N'Điều chỉnh chung tháng',?,?,?,?)",
            [(month, year, json.dumps(old_rules, ensure_ascii=False), json.dumps({"TyLeThuongCC": bonus_rate * 100, "HeSoTangCa": overtime_factor}, ensure_ascii=False), reason, username)],
        ),
        (
            "UPDATE LuongKy SET TinhLuc=SYSUTCDATETIME(),TinhBoi=?,PhienBan=PhienBan+1 WHERE Nam=? AND Thang=? AND TrangThai=N'Nháp'; IF @@ROWCOUNT<>1 THROW 50005,'Kỳ lương không còn ở trạng thái nháp.',1",
            [(username, year, month)],
        ),
    ])

def reopen_period(database, year, month, username, reason):
    database.execute(
        "SET XACT_ABORT ON; BEGIN TRAN; UPDATE LuongKy SET TrangThai=N'Nháp' WHERE Nam=? AND Thang=? AND TrangThai=N'Đã khóa'; IF @@ROWCOUNT<>1 THROW 50003,'Chỉ có thể mở lại kỳ lương đã khóa.',1; INSERT INTO NhatKyLuong(MaNV,Thang,Nam,HanhDong,GiaTriCu,GiaTriMoi,LyDo,NguoiThucHien) VALUES(NULL,?,?,N'Mở lại kỳ lương',N'Đã khóa',N'Nháp',?,?); COMMIT;",
        (year, month, month, year, reason, username),
    )


def touch_period(database, year, month, username):
    database.execute(
        "UPDATE LuongKy SET TinhLuc=SYSUTCDATETIME(),TinhBoi=?,PhienBan=PhienBan+1 WHERE Nam=? AND Thang=? AND TrangThai=N'Nháp'",
        (username, year, month),
    )


def invalidate_period(database, year, month, username):
    """Mark a draft calculation stale after a source input or policy changes."""
    database.execute(
        "UPDATE LuongKy SET TinhLuc=NULL,TinhBoi=?,PhienBan=PhienBan+1 WHERE Nam=? AND Thang=? AND TrangThai=N'Nháp'",
        (username, year, month),
    )
