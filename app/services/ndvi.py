"""
Получение NDVI временного ряда из Google Earth Engine (Sentinel-2 SR).

Требует переменную окружения GEE_SERVICE_ACCOUNT_JSON — содержимое JSON-ключа
сервис-аккаунта Google Earth Engine (Settings → Service Accounts на console.cloud.google.com,
затем привязать аккаунт к GEE-проекту на code.earthengine.google.com/register).

Это нужно потому что сервер работает без интерактивного браузера — обычная
аутентификация `earthengine authenticate` тут не сработает.
"""

import json
import os
from datetime import date, datetime
from sqlalchemy.orm import Session

from app.models.db_models import SoilPoint, NdviRecord
from app.core.config import settings

_ee_initialized = False


def _init_ee():
    """Ленивая инициализация Earth Engine — только когда реально понадобится."""
    global _ee_initialized
    if _ee_initialized:
        return

    import ee

    sa_json = os.environ.get("GEE_SERVICE_ACCOUNT_JSON")
    if not sa_json:
        raise RuntimeError(
            "GEE_SERVICE_ACCOUNT_JSON не задан. Нужен JSON-ключ сервис-аккаунта, "
            "привязанного к проекту на code.earthengine.google.com/register"
        )

    creds_dict = json.loads(sa_json)
    credentials = ee.ServiceAccountCredentials(creds_dict["client_email"], key_data=sa_json)
    ee.Initialize(credentials, project=creds_dict.get("project_id"))
    _ee_initialized = True


def _mask_clouds(image):
    """Маска облаков по биту QA60 (Sentinel-2 SR)."""
    import ee
    qa = image.select("QA60")
    cloud_bit = 1 << 10
    cirrus_bit = 1 << 11
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(cirrus_bit).eq(0))
    return image.updateMask(mask)


def fetch_ndvi_series(lon: float, lat: float, start_date: str = "2015-01-01", end_date: str | None = None) -> list[dict]:
    """
    Возвращает список {date, ndvi, cloud_pct} для точки (lon, lat) по всем
    доступным безоблачным сценам Sentinel-2 SR за период.
    """
    _init_ee()
    import ee

    if end_date is None:
        end_date = date.today().isoformat()

    point = ee.Geometry.Point([lon, lat])
    buffer = point.buffer(15)  # 15м — половина пикселя Sentinel-2 (10м), точечная выборка

    collection = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(point)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 40))
        .map(_mask_clouds)
        .map(lambda img: img.addBands(img.normalizedDifference(["B8", "B4"]).rename("NDVI")))
    )

    def extract(image):
        stats = image.select("NDVI").reduceRegion(
            reducer=ee.Reducer.mean(), geometry=buffer, scale=10, maxPixels=1e6,
        )
        return ee.Feature(None, {
            "date": image.date().format("YYYY-MM-dd"),
            "ndvi": stats.get("NDVI"),
            "cloud_pct": image.get("CLOUDY_PIXEL_PERCENTAGE"),
        })

    features = collection.map(extract).filter(ee.Filter.notNull(["ndvi"]))
    result = features.getInfo()

    return [
        {
            "date": f["properties"]["date"],
            "ndvi": f["properties"]["ndvi"],
            "cloud_pct": f["properties"].get("cloud_pct"),
        }
        for f in result.get("features", [])
    ]


def sync_point_ndvi(db: Session, point_code: str, start_date: str = "2015-01-01") -> dict:
    """Тянет NDVI-ряд для одной точки из GEE и сохраняет в БД (без дублей по дате)."""
    point = db.query(SoilPoint).filter(SoilPoint.point_code == point_code).first()
    if not point:
        raise ValueError(f"Точка '{point_code}' не найдена")
    if point.lon == 0.0 and point.lat == 0.0:
        raise ValueError(f"У точки '{point_code}' нет координат")

    series = fetch_ndvi_series(point.lon, point.lat, start_date)

    inserted, skipped = 0, 0
    for row in series:
        d = datetime.fromisoformat(row["date"]).date()
        existing = (
            db.query(NdviRecord)
            .filter(NdviRecord.point_id == point.id, NdviRecord.date == d)
            .first()
        )
        if existing:
            skipped += 1
            continue
        db.add(NdviRecord(point_id=point.id, date=d, ndvi=row["ndvi"], cloud_pct=row.get("cloud_pct")))
        inserted += 1

    db.commit()
    return {"point_code": point_code, "fetched": len(series), "inserted": inserted, "skipped_existing": skipped}


def sync_all_points_ndvi(db: Session, start_date: str = "2015-01-01") -> dict:
    points = db.query(SoilPoint).filter(SoilPoint.lon != 0, SoilPoint.lat != 0).all()
    results = []
    for p in points:
        try:
            results.append(sync_point_ndvi(db, p.point_code, start_date))
        except Exception as e:
            results.append({"point_code": p.point_code, "error": str(e)})
    return {"points_processed": len(points), "results": results}


def get_ndvi_series(db: Session, point_code: str) -> list[dict]:
    point = db.query(SoilPoint).filter(SoilPoint.point_code == point_code).first()
    if not point:
        return []
    records = (
        db.query(NdviRecord)
        .filter(NdviRecord.point_id == point.id)
        .order_by(NdviRecord.date)
        .all()
    )
    return [{"date": str(r.date), "ndvi": r.ndvi, "cloud_pct": r.cloud_pct} for r in records]
