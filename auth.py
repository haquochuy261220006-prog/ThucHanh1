import hashlib
import hmac
import os

import db


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
    return salt.hex() + "$" + h.hex()


def check_password(pw: str, stored: str) -> bool:
    salt_hex, h_hex = stored.split("$")
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), 100_000)
    return hmac.compare_digest(h.hex(), h_hex)


def login(username: str, password: str):
    """Trả về dict {user, role, manv} nếu đúng, ngược lại None."""
    rows = db.query("SELECT TenDN, MatKhau, VaiTro, MaNV FROM TaiKhoan WHERE TenDN=?", (username,))[1]
    if rows and check_password(password, rows[0][1]):
        return {"user": rows[0][0], "role": rows[0][2], "manv": rows[0][3]}
    return None


def change_password(username: str, new_pw: str):
    db.execute("UPDATE TaiKhoan SET MatKhau=? WHERE TenDN=?", (hash_password(new_pw), username))


def create_account(username, password, role, manv=None):
    db.execute("INSERT INTO TaiKhoan(TenDN, MatKhau, VaiTro, MaNV) VALUES(?,?,?,?)",
               (username, hash_password(password), role, manv))
