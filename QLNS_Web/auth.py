import hashlib
import hmac
import os

import db

_SCHEME = "pbkdf2_sha256"
_ITERATIONS = 600_000  # khuyến nghị OWASP cho PBKDF2-HMAC-SHA256
_LEGACY_ITERATIONS = 100_000  # định dạng cũ "salt$hash" không ghi số vòng lặp


def hash_password(pw: str) -> str:
    """Băm mật khẩu theo định dạng `pbkdf2_sha256$<vòng lặp>$<salt>$<hash>`."""
    if not isinstance(pw, str) or not 10 <= len(pw) <= 256:
        raise ValueError("Mật khẩu phải dài từ 10 đến 256 ký tự.")
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _ITERATIONS)
    return f"{_SCHEME}${_ITERATIONS}${salt.hex()}${h.hex()}"


def _parse_stored(stored: str):
    """Trả về (số vòng lặp, salt, hash) hoặc None nếu bản ghi không hợp lệ."""
    parts = stored.split("$")
    try:
        if len(parts) == 2:  # định dạng cũ
            iterations, salt_hex, h_hex = _LEGACY_ITERATIONS, parts[0], parts[1]
        elif len(parts) == 4 and parts[0] == _SCHEME:
            iterations, salt_hex, h_hex = int(parts[1]), parts[2], parts[3]
        else:
            return None
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(h_hex)
    except (ValueError, TypeError):
        return None
    if not 1 <= iterations <= 5_000_000 or len(salt) != 16 or len(expected) != 32:
        return None
    return iterations, salt, expected


def check_password(pw: str, stored: str) -> bool:
    if not isinstance(pw, str) or len(pw) > 256 or not isinstance(stored, str):
        return False
    parsed = _parse_stored(stored)
    if parsed is None:
        return False
    iterations, salt, expected = parsed
    actual = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, iterations)
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    parsed = _parse_stored(stored)
    return parsed is not None and parsed[0] < _ITERATIONS


def login(username: str, password: str):
    """Trả về thông tin tài khoản hợp lệ; tài khoản nhân viên đã nghỉ bị từ chối."""
    rows = db.query(
        """SELECT t.TenDN,t.MatKhau,t.VaiTro,t.MaNV,t.SecurityVersion,n.TrangThai
           FROM TaiKhoan t LEFT JOIN NhanVien n ON n.MaNV=t.MaNV WHERE t.TenDN=?""",
        (username,),
    )[1]
    if rows and check_password(password, rows[0][1]):
        if rows[0][3] is not None and rows[0][5] != "Đang làm":
            return None
        if rows[0][2] == "NhanVien" and rows[0][3] is None:
            return None
        if needs_rehash(rows[0][1]) and 10 <= len(password) <= 256:
            # Nâng cấp băm cũ ngay khi đăng nhập đúng; lỗi ở bước này không được chặn đăng nhập.
            try:
                db.execute(
                    "UPDATE TaiKhoan SET MatKhau=? WHERE TenDN=?",
                    (hash_password(password), rows[0][0]),
                )
            except Exception:
                pass
        return {
            "user": rows[0][0],
            "role": rows[0][2],
            "manv": rows[0][3],
            "security_version": rows[0][4],
        }
    return None


def verify_password(username: str, password: str) -> bool:
    rows = db.query("SELECT MatKhau FROM TaiKhoan WHERE TenDN=?", (username,))[1]
    return bool(rows and check_password(password, rows[0][0]))


def change_password(username: str, new_pw: str):
    db.execute(
        "UPDATE TaiKhoan SET MatKhau=?,SecurityVersion=SecurityVersion+1 WHERE TenDN=?",
        (hash_password(new_pw), username),
    )


def create_account(username, password, role, manv=None):
    db.execute(
        "INSERT INTO TaiKhoan(TenDN, MatKhau, VaiTro, MaNV) VALUES(?,?,?,?)",
        (username, hash_password(password), role, manv),
    )
