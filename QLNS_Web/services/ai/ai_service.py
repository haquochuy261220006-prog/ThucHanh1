"""Shared, privacy-minimizing calls to the configured language model."""

import hashlib

from database import db


class AIRateLimitError(ValueError):
    pass


class AIUnavailableError(RuntimeError):
    pass


def call_ai(*, actor, feature, system_prompt, user_prompt, max_tokens=1200, web=False):
    """Call the configured provider, recording metadata but never prompt contents."""
    from contracts import _ai_available, _call_ai, ai_model

    if not _ai_available():
        raise AIUnavailableError("Chưa cấu hình API key cho dịch vụ AI.")
    if len(system_prompt) > 10000 or len(user_prompt) > 50000:
        raise ValueError("Nội dung yêu cầu AI vượt giới hạn cho phép.")

    actor = str(actor or "")[:50]
    if not actor:
        raise ValueError("Không xác định được tài khoản thực hiện.")
    prompt_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()
    request_id = db.scalar(
        "SET XACT_ABORT ON; BEGIN TRAN; DELETE FROM AI_RequestLog WHERE ThoiDiem<DATEADD(day,-180,SYSUTCDATETIME()); DECLARE @Recent INT; "
        "SELECT @Recent=COUNT(*) FROM AI_RequestLog WITH(UPDLOCK,HOLDLOCK,INDEX(IX_AI_RequestLog_User_Time)) "
        "WHERE NguoiDung=? AND ThoiDiem>=DATEADD(minute,-60,SYSUTCDATETIME()); "
        "IF @Recent>=10 BEGIN SELECT CAST(0 AS BIGINT) AS MaYeuCau; END "
        "ELSE BEGIN INSERT INTO AI_RequestLog(NguoiDung,ChucNang,TenModel,MaBamYeuCau,TrangThai) "
        "OUTPUT INSERTED.MaYeuCau VALUES(?,?,?,?,N'Đang xử lý'); END; COMMIT;",
        (actor, actor, feature[:40], ai_model()[:100], prompt_hash),
    )
    if not request_id:
        raise AIRateLimitError("Đã đạt giới hạn 10 yêu cầu AI mỗi giờ cho tài khoản này.")
    try:
        result = _call_ai(system_prompt, user_prompt, max_tokens=max_tokens, web=web)
    except Exception:
        db.execute(
            "UPDATE AI_RequestLog SET TrangThai=N'Lỗi' WHERE MaYeuCau=?", (request_id,)
        )
        raise
    db.execute(
        "UPDATE AI_RequestLog SET TrangThai=N'Hoàn tất' WHERE MaYeuCau=?", (request_id,)
    )
    return result
