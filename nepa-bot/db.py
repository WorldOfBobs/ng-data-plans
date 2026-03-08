import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "nepa.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                area_state TEXT,
                area_city TEXT,
                area_neighborhood TEXT,
                subscribed INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                area_city TEXT,
                area_neighborhood TEXT,
                status TEXT,
                reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def upsert_user(telegram_id, username, state, city, neighborhood):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO users (telegram_id, username, area_state, area_city, area_neighborhood)
            VALUES (?,?,?,?,?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                area_state=excluded.area_state,
                area_city=excluded.area_city,
                area_neighborhood=excluded.area_neighborhood
        """, (telegram_id, username, state, city, neighborhood))
        conn.commit()

def get_user(telegram_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        return dict(row) if row else None

def set_subscription(telegram_id, subscribed: bool):
    with get_conn() as conn:
        conn.execute("UPDATE users SET subscribed=? WHERE telegram_id=?", (int(subscribed), telegram_id))
        conn.commit()

def add_report(telegram_id, city, neighborhood, status):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reports (telegram_id, area_city, area_neighborhood, status) VALUES (?,?,?,?)",
            (telegram_id, city.lower(), neighborhood.lower() if neighborhood else "", status)
        )
        conn.commit()

def get_area_status(city, neighborhood=None, hours=2):
    """Get recent reports for an area, fuzzy matched."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) as cnt
            FROM reports
            WHERE (area_city LIKE ? OR area_neighborhood LIKE ?)
              AND reported_at >= datetime('now', ?)
            GROUP BY status
            ORDER BY cnt DESC
        """, (f"%{city.lower()}%", f"%{city.lower()}%", f"-{hours} hours")).fetchall()
        return [dict(r) for r in rows]

def get_subscribers_in_area(city, neighborhood=None, exclude_id=None):
    """Return telegram_ids of subscribed users in the same area."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT telegram_id FROM users
            WHERE subscribed=1
              AND (area_city LIKE ? OR area_neighborhood LIKE ?)
              AND telegram_id != ?
        """, (f"%{city.lower()}%", f"%{city.lower()}%", exclude_id or -1)).fetchall()
        return [r["telegram_id"] for r in rows]
