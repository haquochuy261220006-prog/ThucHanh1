import pyodbc

from config import conn_str


def _run(sql, params, fetch):
    conn = pyodbc.connect(conn_str())
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        if fetch:
            cols = [d[0] for d in cur.description]
            res = (cols, [list(r) for r in cur.fetchall()])
        else:
            res = cur.rowcount
        conn.commit()
        return res
    finally:
        conn.close()


def query(sql, params=()):
    """Trả về (danh_sách_cột, danh_sách_dòng)."""
    return _run(sql, params, True)


def execute(sql, params=()):
    """Chạy INSERT/UPDATE/DELETE, trả về số dòng ảnh hưởng."""
    return _run(sql, params, False)


def execute_batches(batches):
    """Chạy nhiều nhóm lệnh trong cùng một kết nối và transaction."""
    conn = pyodbc.connect(conn_str())
    try:
        cur = conn.cursor()
        for sql, params in batches:
            if params:
                cur.executemany(sql, params)
        conn.commit()
    finally:
        conn.close()


def scalar(sql, params=()):
    rows = query(sql, params)[1]
    return rows[0][0] if rows else None
