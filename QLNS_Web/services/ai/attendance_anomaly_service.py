"""Deterministic attendance anomaly rules; model explanations receive aggregates only."""

from datetime import date

from database import db


def load_attendance_anomalies(year, month, as_of=None):
    start = date(year, month, 1)
    following = date(year + (month == 12), month % 12 + 1, 1)
    as_of = as_of or date.today()
    sql = """WITH Punch AS (
        SELECT MaNV,SUM(CASE WHEN TrangThai=N'Đi muộn' THEN 1 ELSE 0 END) AS SoLanMuon,
            SUM(CASE WHEN SoPhutVeSom>0 THEN 1 ELSE 0 END) AS SoLanVeSom
        FROM ChamCong WHERE Ngay>=? AND Ngay<? GROUP BY MaNV
    ), Overtime AS (
        SELECT MaNV,SUM(SoGioThucTe) AS GioTangCa FROM TangCaYeuCau
        WHERE TrangThai=N'Đã xác nhận' AND XacNhanLuc IS NOT NULL AND BatDau>=? AND BatDau<? GROUP BY MaNV
    )
    SELECT n.MaNV,n.HoTen,ISNULL(p.SoLanMuon,0),ISNULL(p.SoLanVeSom,0),ISNULL(o.GioTangCa,0)
    FROM NhanVien n LEFT JOIN Punch p ON p.MaNV=n.MaNV LEFT JOIN Overtime o ON o.MaNV=n.MaNV
    WHERE n.TrangThai=N'Đang làm' AND (p.MaNV IS NOT NULL OR o.MaNV IS NOT NULL)
    ORDER BY n.HoTen"""
    people = db.query(
        sql,
        (start, following, start, following, start, following),
    )[1]
    daily = db.query(
        "SELECT MaNV,Ngay,MIN(GioVao),MAX(GioRa),MAX(SoPhutLamViec),COUNT(*) "
        "FROM ChamCong WHERE Ngay>=? AND Ngay<? GROUP BY MaNV,Ngay "
        "HAVING COUNT(*)>1 OR MAX(SoPhutLamViec)>960 OR "
        "SUM(CASE WHEN TrangThai IN (N'Đi làm',N'Đi muộn') AND Ngay<CAST(GETDATE() AS DATE) "
        "AND (GioVao IS NULL OR GioRa IS NULL) THEN 1 ELSE 0 END)>0",
        (start, following),
    )[1]
    shift_punches = db.query(
        "SELECT c.MaNV,c.Ngay,c.GioVao,c.GioRa,COALESCE(p.GioBatDauOverride,s.GioBatDau),"
        "COALESCE(p.GioKetThucOverride,s.GioKetThuc) "
        "FROM ChamCong c JOIN PhanCaNhanVien p ON p.MaNV=c.MaNV AND p.Ngay=c.Ngay "
        "JOIN CaLamViec s ON s.MaCa=p.MaCa WHERE c.Ngay>=? AND c.Ngay<?",
        (start, following),
    )[1]

    employee_names = {int(row[0]): row[1] for row in people}
    alerts = []

    def add(employee_id, category, message, count=1, day=None, severity="Cần rà soát"):
        alerts.append({
            "employee": employee_names.get(int(employee_id), "(Hồ sơ không hoạt động)"),
            "category": category,
            "message": message,
            "count": int(count or 0),
            "day": day,
            "severity": severity,
        })

    for employee_id, name, late_count, early_count, overtime_hours in people:
        if late_count >= 3:
            add(employee_id, "Đi muộn lặp lại", f"Đi muộn {late_count} lần trong tháng.", late_count)
        if early_count >= 3:
            add(employee_id, "Về sớm lặp lại", f"Về sớm {early_count} lần trong tháng.", early_count)
        if overtime_hours > 40:
            add(employee_id, "Tăng ca cao", f"Đã xác nhận {float(overtime_hours):.1f} giờ tăng ca trong tháng.", round(overtime_hours), severity="Ưu tiên kiểm tra")

    for employee_id, day, clock_in, clock_out, worked_minutes, duplicate_count in daily:
        if duplicate_count > 1:
            add(employee_id, "Bản ghi trùng", f"Có {duplicate_count} bản ghi chấm công trong một ngày.", duplicate_count, day, "Ưu tiên kiểm tra")
        if worked_minutes and worked_minutes > 16 * 60:
            add(employee_id, "Thời lượng bất thường", f"Thời gian làm được ghi nhận {worked_minutes} phút trong ngày.", worked_minutes, day, "Ưu tiên kiểm tra")
        if day < as_of and (clock_in is None or clock_out is None):
            add(employee_id, "Thiếu lượt vào/ra", "Ngày đã qua nhưng thiếu giờ vào hoặc giờ ra.", 1, day)

    def minute_of_day(value):
        if value is None:
            return None
        if hasattr(value, "hour"):
            return value.hour * 60 + value.minute
        parts = str(value).split(":")
        return int(parts[0]) * 60 + int(parts[1])

    shift_map = {}
    for employee_id, day, clock_in, clock_out, shift_start, shift_end in shift_punches:
        shift_map.setdefault((int(employee_id), day), []).append(
            (minute_of_day(shift_start), minute_of_day(shift_end), minute_of_day(clock_in), minute_of_day(clock_out))
        )
    for (employee_id, day), shifts in shift_map.items():
        def circular_delta(actual, expected):
            return ((actual - expected + 720) % 1440) - 720

        in_deltas = [circular_delta(clock_in, shift_start) for shift_start, _, clock_in, _ in shifts if clock_in is not None]
        out_deltas = [circular_delta(clock_out, shift_end) for _, shift_end, _, clock_out in shifts if clock_out is not None]
        if in_deltas and all(delta < -120 or delta > 180 for delta in in_deltas):
            add(employee_id, "Giờ vào lệch ca", "Giờ vào cách xa giờ bắt đầu ca đã phân công.", 1, day)
        if out_deltas and all(delta < -180 or delta > 240 for delta in out_deltas):
            add(employee_id, "Giờ ra lệch ca", "Giờ ra cách xa giờ kết thúc ca đã phân công.", 1, day)

    category_counts = {}
    for alert in alerts:
        category_counts[alert["category"]] = category_counts.get(alert["category"], 0) + 1
    return alerts, category_counts
