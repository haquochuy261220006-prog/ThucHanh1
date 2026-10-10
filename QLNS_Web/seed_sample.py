"""Nạp dữ liệu MẪU để dùng thử: 10 nhân viên + 9 hợp đồng đủ các loại.
Chạy sau setup_db.py:   python seed_sample.py
An toàn khi chạy lại: nhân viên đã có (trùng số CCCD mẫu) sẽ được bỏ qua.
Toàn bộ họ tên, CCCD, SĐT bên dưới là dữ liệu giả, có thể xóa trong mục Nhân viên."""
from datetime import date, timedelta

import db

T = date.today()
# (Họ tên, ngày sinh, giới tính, địa chỉ, SĐT, email, CCCD, ngày vào làm, phòng ban, chức vụ, lương cơ bản)
EMPLOYEES = [
    ("Nguyễn Văn Hùng",  date(1982, 3, 15), "Nam", "25 Trần Hưng Đạo, Hoàn Kiếm, Hà Nội",   "0901000001", "hung.nv@example.com",  "001082000001", T - timedelta(days=2200), "Phòng Nhân sự",     "Giám đốc",      35000000),
    ("Trần Thị Mai",     date(1990, 7, 22), "Nữ",  "12 Phố Huế, Hai Bà Trưng, Hà Nội",      "0901000002", "mai.tt@example.com",   "001090000002", T - timedelta(days=1700), "Phòng Kế toán",     "Trưởng phòng",  22000000),
    ("Lê Quang Minh",    date(1993, 11, 5), "Nam", "88 Láng Hạ, Đống Đa, Hà Nội",           "0901000003", "minh.lq@example.com",  "001093000003", T - timedelta(days=1200), "Phòng Kỹ thuật",    "Kỹ thuật viên", 16000000),
    ("Phạm Thu Hà",      date(1996, 1, 30), "Nữ",  "5 Nguyễn Chí Thanh, Ba Đình, Hà Nội",   "0901000004", "ha.pt@example.com",    "001096000004", T - timedelta(days=800),  "Phòng Kinh doanh",  "Nhân viên",     12000000),
    ("Đỗ Thanh Tùng",    date(1994, 9, 18), "Nam", "41 Cầu Giấy, Cầu Giấy, Hà Nội",         "0901000005", "tung.dt@example.com",  "001094000005", T - timedelta(days=500),  "Phòng Marketing",   "Nhân viên",     13000000),
    ("Vũ Ngọc Lan",      date(1998, 5, 9),  "Nữ",  "17 Giải Phóng, Hai Bà Trưng, Hà Nội",   "0901000006", "lan.vn@example.com",   "001098000006", T - timedelta(days=300),  "Phòng Nhân sự",     "Nhân viên",     11000000),
    ("Hoàng Đức Anh",    date(2000, 12, 2), "Nam", "63 Xuân Thủy, Cầu Giấy, Hà Nội",        "0901000007", "anh.hd@example.com",   "001200000007", T - timedelta(days=120),  "Phòng Kỹ thuật",    "Kỹ thuật viên", 9000000),
    ("Bùi Phương Thảo",  date(2001, 8, 14), "Nữ",  "9 Kim Mã, Ba Đình, Hà Nội",             "0901000008", "thao.bp@example.com",  "001201000008", T - timedelta(days=60),   "Phòng Kinh doanh",  "Nhân viên",     8000000),
    ("Ngô Gia Bảo",      date(1999, 4, 27), "Nam", "30 Tây Sơn, Đống Đa, Hà Nội",           "0901000009", "bao.ng@example.com",   "001099000009", T - timedelta(days=45),   "Phòng Marketing",   "Nhân viên",     7000000),
    ("Đặng Khánh Linh",  date(2003, 2, 11), "Nữ",  "74 Nguyễn Trãi, Thanh Xuân, Hà Nội",    "0901000010", "linh.dk@example.com",  "001203000010", T - timedelta(days=20),   "Phòng Kế toán",     "Nhân viên",     5000000),
]

# (CCCD nhân viên, loại HĐ, bắt đầu cách hôm nay (ngày), thời hạn (ngày hoặc None), lương HĐ)
CONTRACTS = [
    ("001082000001", "Không thời hạn", -2200, None, 35000000),
    ("001090000002", "Không thời hạn", -1700, None, 22000000),
    ("001093000003", "Có thời hạn",    -400,  730,  16000000),
    ("001096000004", "Có thời hạn",    -300,  730,  12000000),
    ("001200000007", "Thử việc",       -50,   60,   7650000),
    ("001201000008", "Thời vụ",        -30,   150,  8000000),
    ("001099000009", "Bán thời gian",  -45,   320,  7000000),
    ("001203000010", "Học việc",       -20,   70,   3000000),
    ("001094000005", "Cộng tác viên",  -100,  265,  13000000),
]


def main():
    pb = {r[1]: r[0] for r in db.query("SELECT MaPB,TenPB FROM PhongBan")[1]}
    cv = {r[1]: r[0] for r in db.query("SELECT MaCV,TenCV FROM ChucVu")[1]}
    if not pb or not cv:
        print("Chưa có phòng ban/chức vụ. Hãy chạy setup_db.py trước.")
        return
    added = 0
    for (ten, ns, gt, dc, sdt, mail, cccd, vao, p, c, luong) in EMPLOYEES:
        if db.scalar("SELECT COUNT(*) FROM NhanVien WHERE CCCD=?", (cccd,)):
            continue
        db.execute(
            "INSERT INTO NhanVien(HoTen,NgaySinh,GioiTinh,DiaChi,SDT,Email,CCCD,NgayVaoLam,MaPB,MaCV,LuongCoBan) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ten, ns, gt, dc, sdt, mail, cccd, vao, pb.get(p), cv.get(c), luong))
        added += 1
    ct = 0
    for cccd, loai, off, dur, luong in CONTRACTS:
        manv = db.scalar("SELECT MaNV FROM NhanVien WHERE CCCD=?", (cccd,))
        if not manv or db.scalar("SELECT COUNT(*) FROM HopDong WHERE MaNV=? AND LoaiHD=?", (manv, loai)):
            continue
        bd = T + timedelta(days=off)
        kt = bd + timedelta(days=dur) if dur else None
        status = "Hết hạn" if kt and kt < T else "Còn hiệu lực"
        db.execute("INSERT INTO HopDong(MaNV,LoaiHD,NgayBatDau,NgayKetThuc,LuongHD,TrangThai) VALUES(?,?,?,?,?,?)",
                   (manv, loai, bd, kt, luong, status))
        ct += 1
    print(f"Đã thêm {added} nhân viên mẫu và {ct} hợp đồng mẫu.")


if __name__ == "__main__":
    main()
