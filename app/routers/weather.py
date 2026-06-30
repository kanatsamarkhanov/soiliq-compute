from fastapi import APIRouter, Depends, Query, Header, HTTPException
from sqlalchemy.orm import Session
from datetime import date, timedelta

from app.core.db import get_db
from app.core.config import settings
from app.models.db_models import WeatherRecord
from app.services.weather_sync import sync_all_stations, sync_station

router = APIRouter(prefix="/api/weather", tags=["weather"])


@router.get("/history")
def get_history(
    station: str = Query("sarybastau"),
    days: int = Query(14, ge=1, le=365),
    db: Session = Depends(get_db),
):
    since = date.today() - timedelta(days=days)
    records = (
        db.query(WeatherRecord)
        .filter(WeatherRecord.station == station, WeatherRecord.date >= since)
        .order_by(WeatherRecord.date)
        .all()
    )
    return {
        "station": station,
        "count": len(records),
        "records": [
            {
                "date": str(r.date), "temp_max_c": r.temp_max_c, "temp_min_c": r.temp_min_c,
                "temp_avg_c": r.temp_avg_c, "precip_mm": r.precip_mm, "pressure_mb": r.pressure_mb,
                "humidity": r.humidity, "wind_kmh": r.wind_kmh, "solar_rad": r.solar_rad, "et_mm": r.et_mm,
            }
            for r in records
        ],
    }


@router.post("/sync")
async def trigger_sync(
    days_back: int = Query(1, ge=1, le=30),
    x_api_secret: str = Header(None),
    db: Session = Depends(get_db),
):
    if x_api_secret != settings.api_secret:
        raise HTTPException(401, "Unauthorized")
    results = await sync_all_stations(db, days_back)
    return {"synced": True, "results": results}


@router.post("/sync/{station}")
async def trigger_sync_station(
    station: str,
    days_back: int = Query(7, ge=1, le=90),
    x_api_secret: str = Header(None),
    db: Session = Depends(get_db),
):
    if x_api_secret != settings.api_secret:
        raise HTTPException(401, "Unauthorized")
    result = await sync_station(db, station, days_back)
    return result
