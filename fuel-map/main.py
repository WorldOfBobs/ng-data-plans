"""
Nigeria Fuel Queue Crowdsource Map — FastAPI backend
Run: python main.py
Serves the map at http://localhost:8000
"""
import os
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import uvicorn
import db

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "8000"))
app = FastAPI(title="Nigeria Fuel Map API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────

class NewStation(BaseModel):
    name: str = Field(..., min_length=3, max_length=120)
    lat: float = Field(..., ge=4.0, le=14.0)   # Nigeria lat range
    lng: float = Field(..., ge=2.5, le=15.0)   # Nigeria lng range

class NewReport(BaseModel):
    station_id: int
    status: str = Field(..., pattern="^(available|long_queue|dry)$")
    price_per_litre: float | None = Field(None, ge=0, le=10000)
    queue_length: str | None = Field(None, pattern="^(none|short|long|very_long)$")
    reporter_nickname: str | None = Field(None, max_length=40)

# ──────────────────────────────────────────────
# API routes
# ──────────────────────────────────────────────

@app.get("/api/stations")
async def list_stations():
    stations = db.get_stations_with_latest()
    return JSONResponse(stations)

@app.post("/api/stations", status_code=201)
async def create_station(data: NewStation):
    sid = db.add_station(data.name, data.lat, data.lng)
    return {"id": sid, "name": data.name, "lat": data.lat, "lng": data.lng}

@app.post("/api/reports", status_code=201)
async def submit_report(data: NewReport, request: Request):
    ip = request.client.host
    if not db.check_rate_limit(data.station_id, ip):
        raise HTTPException(status_code=429, detail="You already reported this station in the last 30 minutes.")
    db.add_report(
        data.station_id,
        data.status,
        data.price_per_litre,
        data.queue_length,
        data.reporter_nickname,
        ip
    )
    return {"ok": True}

# ──────────────────────────────────────────────
# Frontend
# ──────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse("static/index.html")

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    logger.info(f"🗺️  Nigeria Fuel Map starting on http://localhost:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
