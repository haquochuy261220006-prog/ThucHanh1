import hashlib
import hmac
import os

import db


def hash_password(pw: str) -> str:
    if not isinstance(pw, str) or not 10 <= len(pw) <= 256:
        raise ValueError("Mật khẩu phải dài từ 10 đến 256 ký tự.")
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
    return salt.hex() + "$" + h.hex()


def check_password(pw: str, stored: str) -> bool:
    if not isinstance(pw, str) or len(pw) > 256 or not isinstance(stored, str):
        return False
    try:
        salt_hex, h_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(h_hex)
    except (ValueError, TypeError):
        return False
    if len(salt) != 16 or len(expected) != 32:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
    return hmac.compare_digest(actual, expected)


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
