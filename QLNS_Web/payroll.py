"""Công thức tính lương tháng.

Lương thực lĩnh = Lương cơ bản
                + Thưởng chuyên cần (đi làm >= CHUYEN_CAN_SO_NGAY ngày -> + CHUYEN_CAN_TY_LE x lương cơ bản)
                + Tiền tăng ca
                - Trừ đi muộn   (mỗi lần muộn trừ MUON_TRU_NGAY ngày lương)
                - Trừ nghỉ không phép (mỗi ngày trừ NGHI_KP_TRU_NGAY ngày lương)
Ngày lương = Lương cơ bản / CONG_CHUAN.
Mọi tham số chỉnh trong config.py.
"""
import calendar
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


def tinh_luong(luong_cb, ngay_vao, cham_cong, nghi_phep, year, month, today=None):
    """cham_cong: [(Ngay, GioVao, GioRa, TrangThai)]; nghi_phep: [(TuNgay, DenNgay)] đã duyệt."""
    today = today or date.today()
    luong_cb = float(luong_cb or 0)
    ngay_luong = luong_cb / config.CONG_CHUAN
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])

    present, excused, so_muon, phut_tc = set(), set(), 0, 0
    gio_vao_chuan = _hm(_to_time(config.GIO_VAO_CHUAN))
    gio_ra_chuan = _hm(_to_time(config.GIO_RA_CHUAN))
    for ngay, gio_vao, gio_ra, trang_thai in cham_cong:
        d = _to_date(ngay)
        if d is None:
            continue
        if trang_thai == "Nghỉ phép":
            excused.add(d)
            continue
        if trang_thai == "Nghỉ":
            continue
        present.add(d)
        tv, tr = _to_time(gio_vao), _to_time(gio_ra)
        if trang_thai == "Đi muộn" or (tv and _hm(tv) > gio_vao_chuan):
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

    # Ngày làm việc cần xét nghỉ không phép: từ ngày vào làm đến hết tháng (tháng đang chạy: đến hôm qua)
    start = max(first, _to_date(ngay_vao) or first)
    end = last if last < today else today - timedelta(days=1)
    nghi_kp, d = 0, start
    while d <= end:
        if d.weekday() not in config.NGAY_NGHI_TUAN and d not in present and d not in excused:
            nghi_kp += 1
        d += timedelta(days=1)

    thuong = round(luong_cb * config.CHUYEN_CAN_TY_LE) if len(present) >= config.CHUYEN_CAN_SO_NGAY else 0
    gio_tc = round(phut_tc / 60, 2)
    tien_tc = round(gio_tc * ngay_luong / config.GIO_LAM_NGAY * config.HE_SO_TANG_CA)
    tru_muon = round(so_muon * config.MUON_TRU_NGAY * ngay_luong)
    tru_nghi = round(nghi_kp * config.NGHI_KP_TRU_NGAY * ngay_luong)
    return {
        "ngay_di_lam": len(present), "thuong_cc": thuong,
        "gio_tang_ca": gio_tc, "tien_tang_ca": tien_tc,
        "so_lan_muon": so_muon, "tru_muon": tru_muon,
        "so_ngay_nghi_kp": nghi_kp, "tru_nghi_kp": tru_nghi,
        "phu_cap": thuong + tien_tc, "khau_tru": tru_muon + tru_nghi,
        "tong": max(0, round(luong_cb) + thuong + tien_tc - tru_muon - tru_nghi),
    }
