import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "fx_rates.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cbn_rate REAL,
                parallel_rate REAL,
                spread REAL,
                spread_pct REAL,
                source TEXT,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def save_rate(cbn_rate, parallel_rate, source):
    spread = parallel_rate - cbn_rate
    spread_pct = (spread / cbn_rate) * 100 if cbn_rate else 0
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO rates (cbn_rate, parallel_rate, spread, spread_pct, source) VALUES (?,?,?,?,?)",
            (cbn_rate, parallel_rate, spread, spread_pct, source)
        )
        conn.commit()
    return {"cbn_rate": cbn_rate, "parallel_rate": parallel_rate, "spread": spread, "spread_pct": spread_pct}

def get_latest_rate():
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM rates ORDER BY fetched_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

def get_rate_history(hours=24):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rates WHERE fetched_at >= datetime('now', ?) ORDER BY fetched_at ASC",
            (f"-{hours} hours",)
        ).fetchall()
        return [dict(r) for r in rows]

def add_subscriber(telegram_id, username):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO subscribers (telegram_id, username) VALUES (?,?)",
            (telegram_id, username)
        )
        conn.commit()

def remove_subscriber(telegram_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM subscribers WHERE telegram_id=?", (telegram_id,))
        conn.commit()

def get_subscribers():
    with get_conn() as conn:
        rows = conn.execute("SELECT telegram_id FROM subscribers").fetchall()
        return [r["telegram_id"] for r in rows]
