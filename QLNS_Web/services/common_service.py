"""Shared request-independent HR helpers and authorization checks."""

from datetime import datetime, timezone, date

from flask import current_app, session

from permissions import role_can
import re


def admin():
    return session.get("user", {}).get("role") == "QuanTri"


def has_permission(permission):
    return role_can(session.get("user", {}).get("role"), permission)


def system_admin():
    return has_permission("accounts.manage")


def payroll_staff():
    return has_permission("payroll.view")


def is_manager():
    return session.get("user", {}).get("role") == "QuanLy"


def _utcnow():
    """Return a naive UTC datetime matching SQL Server SYSUTCDATETIME()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_iso_date(raw, label):
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        raise ValueError(f"{label} phải là ngày hợp lệ.") from None


def _safe_error(error, message="Không thể xử lý yêu cầu lúc này. Vui lòng thử lại."):
    if isinstance(error, ValueError):
        return str(error)
    current_app.logger.error(
        "Request failed",
        exc_info=(type(error), error, error.__traceback__),
    )
    return message


_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
