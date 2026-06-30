import httpx
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.db_models import WeatherRecord

BASE = "https://api.weatherlink.com/v2"

STATIONS = {
    "sarybastau": settings.wl_station_sarybastau,
    "zholaman":   settings.wl_station_zholaman,
}

F_TO_C = lambda f: round((f - 32) * 5 / 9, 1)
INHG_TO_MB = lambda h: round(h * 33.8639, 1)
MPH_TO_KMH = lambda m: round(m * 1.60934, 1)


async def _fetch_day(client: httpx.AsyncClient, station_id: str, day_start_ts: int) -> dict | None:
    url = f"{BASE}/historic/{station_id}"
    params = {"api-key": settings.weatherlink_api_key, "start-timestamp": day_start_ts,
              "end-timestamp": day_start_ts + 86400}
    headers = {"X-Api-Secret": settings.weatherlink_api_secret}
    resp = await client.get(url, params=params, headers=headers, timeout=20)
    if resp.status_code != 200:
        return None
    return resp.json()


def _parse_day(raw: dict) -> list[dict]:
    if not raw:
        return []
    sensors = raw.get("sensors", [])
    iss = next((s for s in sensors if s.get("data_structure_type") == 23), None) \
        or next((s for s in sensors if s.get("data_structure_type") == 1), None) \
        or (sensors[0] if sensors else None)
    baro = next((s for s in sensors if s.get("data_structure_type") == 19), None)

    if not iss:
        return []

    baro_by_ts = {b["ts"]: b for b in (baro.get("data", []) if baro else [])}
    out = []
    for d in iss.get("data", []):
        b = baro_by_ts.get(d["ts"], {})
        out.append({
            "date": datetime.utcfromtimestamp(d["ts"]).date(),
            "temp_avg_c": F_TO_C(d["temp"]) if d.get("temp") is not None else None,
            "temp_max_c": F_TO_C(d["temp_hi"]) if d.get("temp_hi") is not None else None,
            "temp_min_c": F_TO_C(d["temp_lo"]) if d.get("temp_lo") is not None else None,
            "precip_mm": d.get("rainfall_mm") or d.get("rainfall_day_mm") or 0,
            "pressure_mb": INHG_TO_MB(b["bar_sea_level"]) if b.get("bar_sea_level") is not None else None,
            "humidity": d.get("hum_last") or d.get("hum"),
            "wind_kmh": MPH_TO_KMH(d["wind_speed_avg"]) if d.get("wind_speed_avg") is not None else None,
            "solar_rad": d.get("solar_rad_avg") or d.get("solar_rad"),
            "et_mm": d.get("et_day"),
        })
    return out


async def sync_station(db: Session, station: str, days_back: int = 7) -> dict:
    station_id = STATIONS.get(station)
    if not station_id:
        return {"station": station, "error": "Station ID не задан"}

    inserted, updated = 0, 0
    today = datetime.utcnow().date()

    async with httpx.AsyncClient() as client:
        for i in range(days_back):
            day = today - timedelta(days=i)
            day_start_ts = int(datetime(day.year, day.month, day.day).timestamp())
            raw = await _fetch_day(client, station_id, day_start_ts)
            records = _parse_day(raw)

            # Группируем по дате (в одном дне может быть несколько записей при суб-суточной выборке)
            by_date: dict[date, list[dict]] = {}
            for r in records:
                by_date.setdefault(r["date"], []).append(r)

            for rec_date, recs in by_date.items():
                def avg(field):
                    vals = [r[field] for r in recs if r[field] is not None]
                    return round(sum(vals) / len(vals), 2) if vals else None

                def agg_max(field):
                    vals = [r[field] for r in recs if r[field] is not None]
                    return max(vals) if vals else None

                def agg_min(field):
                    vals = [r[field] for r in recs if r[field] is not None]
                    return min(vals) if vals else None

                def agg_sum(field):
                    vals = [r[field] for r in recs if r[field] is not None]
                    return round(sum(vals), 2) if vals else 0

                existing = db.query(WeatherRecord).filter(
                    WeatherRecord.station == station, WeatherRecord.date == rec_date
                ).first()

                payload = dict(
                    temp_avg_c=avg("temp_avg_c"), temp_max_c=agg_max("temp_max_c"),
                    temp_min_c=agg_min("temp_min_c"), precip_mm=agg_sum("precip_mm"),
                    pressure_mb=avg("pressure_mb"), humidity=avg("humidity"),
                    wind_kmh=avg("wind_kmh"), solar_rad=avg("solar_rad"), et_mm=agg_sum("et_mm"),
                )

                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                    existing.synced_at = datetime.utcnow()
                    updated += 1
                else:
                    db.add(WeatherRecord(station=station, date=rec_date, **payload))
                    inserted += 1

    db.commit()
    return {"station": station, "inserted": inserted, "updated": updated, "days_checked": days_back}


async def sync_all_stations(db: Session, days_back: int = 1) -> list[dict]:
    results = []
    for station in STATIONS:
        results.append(await sync_station(db, station, days_back))
    return results
