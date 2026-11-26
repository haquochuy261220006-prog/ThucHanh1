from database.migrate_db import _add_sql_error_context, main

if __name__ == "__main__":
    from database.migrate_db import main as _main
    try:
        _main()
    except SystemExit:
        raise
    except Exception as error:
        import sys
        print(f"Schema migration failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
