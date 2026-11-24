"""Run the idempotent schema upgrade with a dedicated migration identity."""

import os
import secrets
import sys


def _add_sql_error_context(db):
    for function_name in ("execute", "query"):
        original = getattr(db, function_name)

        def run(sql, params=(), _original=original, _name=function_name):
            try:
                return _original(sql, params)
            except Exception as error:
                statement = " ".join(str(sql).split())[:240]
                raise RuntimeError(
                    f"{_name} failed ({error}); SQL starts with: {statement}"
                ) from error

        setattr(db, function_name, run)


def main():
    web_principal = os.environ.get("DB_WEB_USER") or os.environ.get("DB_USER", "")
    migration_windows_auth = os.environ.get("DB_MIGRATION_WINDOWS_AUTH", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if not migration_windows_auth:
        migration_user = os.environ.get("DB_MIGRATION_USER", "")
        migration_password = os.environ.get("DB_MIGRATION_PASSWORD", "")
        if not migration_user or not migration_password:
            raise SystemExit(
                "Set DB_MIGRATION_USER and DB_MIGRATION_PASSWORD, or use "
                "DB_MIGRATION_WINDOWS_AUTH=true with a dedicated Windows identity."
            )
        os.environ["DB_USER"] = migration_user
        os.environ["DB_PASSWORD"] = migration_password
        os.environ["DB_WINDOWS_AUTH"] = "false"
    else:
        os.environ["DB_WINDOWS_AUTH"] = "true"

    if not web_principal and (
        not migration_windows_auth or os.environ.get("APP_ENV", "").lower() == "production"
    ):
        raise SystemExit(
            "Set DB_WEB_USER to the existing database principal used by the web app."
        )

    os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_hex(32))

    import db
    from schema_setup import ensure_schema
    from schema_migrations import (
        CURRENT_SCHEMA_VERSION,
        begin_migration,
        finish_migration,
        grant_web_read,
    )

    _add_sql_error_context(db)
    begin_migration(db)
    ensure_schema()
    grant_web_read(db, web_principal)
    finish_migration(db)
    print(f"Schema migration {CURRENT_SCHEMA_VERSION} completed.")
    print("Restart all web workers so they recheck the migrated schema.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(f"Schema migration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
