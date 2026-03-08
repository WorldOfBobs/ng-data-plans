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
                currency TEXT DEFAULT 'USD',
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
                active INTEGER DEFAULT 1,
                alert_threshold_pct REAL DEFAULT 2.0,
                alert_direction TEXT DEFAULT 'both',
                briefing_hour INTEGER DEFAULT 8,
                update_interval_min INTEGER DEFAULT 0,
                last_interval_push TIMESTAMP DEFAULT NULL,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                active INTEGER DEFAULT 1,
                briefing_hour INTEGER DEFAULT 8,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

# ── Rates ─────────────────────────────────────

def save_rate(cbn_rate, parallel_rate, source, currency="USD"):
    spread = parallel_rate - cbn_rate
    spread_pct = (spread / cbn_rate) * 100 if cbn_rate else 0
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO rates (currency, cbn_rate, parallel_rate, spread, spread_pct, source) VALUES (?,?,?,?,?,?)",
            (currency, cbn_rate, parallel_rate, spread, spread_pct, source)
        )
        conn.commit()
    return {"currency": currency, "cbn_rate": cbn_rate, "parallel_rate": parallel_rate,
            "spread": spread, "spread_pct": spread_pct}

def get_latest_rate(currency="USD"):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM rates WHERE currency=? ORDER BY fetched_at DESC LIMIT 1", (currency,)
        ).fetchone()
        return dict(row) if row else None

def get_rate_history(hours=24, currency="USD"):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM rates WHERE currency=? AND fetched_at >= datetime('now', ?) ORDER BY fetched_at ASC",
            (currency, f"-{hours} hours")
        ).fetchall()
        return [dict(r) for r in rows]

def get_daily_history(days=7, currency="USD"):
    """Return daily high/low/avg for the past N days."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT date(fetched_at) as day,
                   MAX(parallel_rate) as high,
                   MIN(parallel_rate) as low,
                   AVG(parallel_rate) as avg,
                   MAX(cbn_rate) as cbn
            FROM rates
            WHERE currency=? AND fetched_at >= datetime('now', ?)
            GROUP BY date(fetched_at)
            ORDER BY day ASC
        """, (currency, f"-{days} days")).fetchall()
        return [dict(r) for r in rows]

# ── Subscribers ───────────────────────────────

def add_subscriber(telegram_id, username):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO subscribers (telegram_id, username, active, alert_threshold_pct, alert_direction, briefing_hour)
            VALUES (?,?,1,2.0,'both',8)
            ON CONFLICT(telegram_id) DO UPDATE SET active=1, username=excluded.username
        """, (telegram_id, username))
        conn.commit()

def remove_subscriber(telegram_id):
    with get_conn() as conn:
        conn.execute("UPDATE subscribers SET active=0 WHERE telegram_id=?", (telegram_id,))
        conn.commit()

def get_subscribers():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM subscribers WHERE active=1").fetchall()
        return [dict(r) for r in rows]

def get_subscriber(telegram_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM subscribers WHERE telegram_id=?", (telegram_id,)).fetchone()
        return dict(row) if row else None

def update_settings(telegram_id, threshold_pct=None, direction=None, briefing_hour=None,
                    update_interval_min=None):
    with get_conn() as conn:
        if threshold_pct is not None:
            conn.execute("UPDATE subscribers SET alert_threshold_pct=? WHERE telegram_id=?",
                         (threshold_pct, telegram_id))
        if direction is not None:
            conn.execute("UPDATE subscribers SET alert_direction=? WHERE telegram_id=?",
                         (direction, telegram_id))
        if briefing_hour is not None:
            conn.execute("UPDATE subscribers SET briefing_hour=? WHERE telegram_id=?",
                         (briefing_hour, telegram_id))
        if update_interval_min is not None:
            conn.execute(
                "UPDATE subscribers SET update_interval_min=?, last_interval_push=NULL WHERE telegram_id=?",
                (update_interval_min, telegram_id)
            )
        conn.commit()

def get_subscribers_due_interval():
    """Return subscribers whose interval update is due right now."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM subscribers
            WHERE active=1
              AND update_interval_min > 0
              AND (
                last_interval_push IS NULL
                OR last_interval_push <= datetime('now', '-' || update_interval_min || ' minutes')
              )
        """).fetchall()
        return [dict(r) for r in rows]

def mark_interval_pushed(telegram_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE subscribers SET last_interval_push=datetime('now') WHERE telegram_id=?",
            (telegram_id,)
        )
        conn.commit()

# ── Groups ────────────────────────────────────

def register_group(chat_id, title):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO groups (chat_id, title, active, briefing_hour)
            VALUES (?,?,1,8)
            ON CONFLICT(chat_id) DO UPDATE SET active=1, title=excluded.title
        """, (chat_id, title))
        conn.commit()

def deregister_group(chat_id):
    with get_conn() as conn:
        conn.execute("UPDATE groups SET active=0 WHERE chat_id=?", (chat_id,))
        conn.commit()

def get_active_groups():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM groups WHERE active=1").fetchall()
        return [dict(r) for r in rows]
