import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "fuel.db")

SEED_STATIONS = [
    ("NNPC Mega Station Lekki", 6.4317, 3.4854),
    ("Total Energies - Victoria Island", 6.4280, 3.4219),
    ("Conoil - Ikeja GRA", 6.5891, 3.3427),
    ("Oando - Apapa", 6.4500, 3.3500),
    ("NNPC Station - Surulere", 6.5003, 3.3577),
    ("NNPC Abuja — Central District", 9.0579, 7.4951),
    ("Total Energies — Wuse 2 Abuja", 9.0683, 7.4836),
    ("Conoil — Maitama Abuja", 9.0831, 7.4780),
    ("Mobil — Port Harcourt Trans-Amadi", 4.8396, 7.0098),
    ("NNPC — Kano Bompai", 12.0022, 8.5919),
]

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                price_per_litre REAL,
                queue_length TEXT,
                reporter_nickname TEXT,
                reporter_ip TEXT,
                reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (station_id) REFERENCES stations(id)
            )
        """)
        conn.commit()
        # Seed if empty
        count = conn.execute("SELECT COUNT(*) as c FROM stations").fetchone()["c"]
        if count == 0:
            conn.executemany(
                "INSERT INTO stations (name, lat, lng) VALUES (?,?,?)",
                SEED_STATIONS
            )
            conn.commit()

def get_stations_with_latest():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.id, s.name, s.lat, s.lng,
                   r.status, r.price_per_litre, r.queue_length,
                   r.reporter_nickname, r.reported_at,
                   COUNT(r2.id) as report_count
            FROM stations s
            LEFT JOIN reports r ON r.id = (
                SELECT id FROM reports WHERE station_id=s.id AND reported_at >= datetime('now','-6 hours')
                ORDER BY reported_at DESC LIMIT 1
            )
            LEFT JOIN reports r2 ON r2.station_id=s.id AND r2.reported_at >= datetime('now','-6 hours')
            GROUP BY s.id
            ORDER BY s.name
        """).fetchall()
        return [dict(r) for r in rows]

def add_station(name, lat, lng):
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO stations (name, lat, lng) VALUES (?,?,?)", (name, lat, lng))
        conn.commit()
        return cur.lastrowid

def add_report(station_id, status, price, queue_length, nickname, ip):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO reports (station_id, status, price_per_litre, queue_length, reporter_nickname, reporter_ip)
            VALUES (?,?,?,?,?,?)
        """, (station_id, status, price, queue_length, nickname, ip))
        conn.commit()

def check_rate_limit(station_id, ip):
    """Return True if allowed (not rate-limited)."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) as c FROM reports
            WHERE station_id=? AND reporter_ip=?
              AND reported_at >= datetime('now','-30 minutes')
        """, (station_id, ip)).fetchone()
        return row["c"] == 0
