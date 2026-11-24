from __future__ import annotations

import hashlib
import hmac
import time
from datetime import timedelta

from flask import current_app, session

from database import db
from services.common_service import _utcnow

LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 300
_login_fails = {}


def _login_locked(key):
    n, ts = _login_fails.get(key, (0, 0))
    if n >= LOGIN_MAX_FAILS and time.time() - ts < LOGIN_LOCK_SECONDS:
        return int(LOGIN_LOCK_SECONDS - (time.time() - ts)) + 1
    if n >= LOGIN_MAX_FAILS:
        _login_fails.pop(key, None)
    return 0

def _otp_hash(code, manv, requester):
    payload = f"{requester}:{manv}:{code}".encode()
    return hmac.new(current_app.secret_key.encode(), payload, hashlib.sha256).hexdigest()

def _otp_can_send(manv):
    return not db.scalar(
        "SELECT COUNT(*) FROM TaiKhoanOTP WHERE MaNV=? AND SentAt>DATEADD(second,-30,SYSUTCDATETIME())",
        (manv,),
    )

def _otp_put(manv, code, channel):
    requester = session["user"]["user"]
    sent_at = _utcnow()
    code_hash = _otp_hash(code, manv, requester)
    db.execute(
        "IF EXISTS(SELECT 1 FROM TaiKhoanOTP WHERE MaNV=?) UPDATE TaiKhoanOTP SET RequestedBy=?,Channel=?,CodeHash=?,SentAt=?,ExpiresAt=?,Attempts=0 WHERE MaNV=? ELSE INSERT INTO TaiKhoanOTP(MaNV,RequestedBy,Channel,CodeHash,SentAt,ExpiresAt,Attempts) VALUES(?,?,?,?,?,?,0)",
        (
            manv,
            requester,
            channel,
            code_hash,
            sent_at,
            sent_at + timedelta(minutes=5),
            manv,
            manv,
            requester,
            channel,
            code_hash,
            sent_at,
            sent_at + timedelta(minutes=5),
        ),
    )

def _otp_get(manv):
    rows = db.query(
        "SELECT RequestedBy,Channel,CodeHash,ExpiresAt,Attempts FROM TaiKhoanOTP WHERE MaNV=?",
        (manv,),
    )[1]
    if not rows or rows[0][0] != session["user"]["user"]:
        return None
    row = rows[0]
    return {
        "manv": str(manv),
        "channel": row[1],
        "hash": row[2].strip(),
        "expires": row[3],
        "attempts": row[4],
    }

def _otp_fail(manv):
    db.execute(
        "UPDATE TaiKhoanOTP SET Attempts=Attempts+1 WHERE MaNV=? AND RequestedBy=?",
        (manv, session["user"]["user"]),
    )

def _otp_clear(manv):
    db.execute(
        "DELETE FROM TaiKhoanOTP WHERE MaNV=? AND RequestedBy=?",
        (manv, session["user"]["user"]),
    )
