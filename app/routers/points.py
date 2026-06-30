from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from datetime import date as date_type
from typing import Optional

from app.core.db import get_db
from app.models.db_models import SoilPoint, SoilSample
from app.services.kriging import compute_fertility_score
from app.services.geocode import normalize_code

router = APIRouter(prefix="/api/points", tags=["points"])


@router.get("")
def list_points(db: Session = Depends(get_db)):
    points = db.query(SoilPoint).all()
    out = []
    for p in points:
        latest = (
            db.query(SoilSample)
            .filter(SoilSample.point_id == p.id)
            .order_by(SoilSample.sample_date.desc())
            .first()
        )
        out.append({
            "id": p.id,
            "point_code": p.point_code,
            "lon": p.lon,
            "lat": p.lat,
            "crop": p.crop,
            "latest_sample": {
                "date": str(latest.sample_date) if latest else None,
                "humus_pct": latest.humus_pct if latest else None,
                "nitrogen_mgkg": latest.nitrogen_mgkg if latest else None,
                "phosphorus_mgkg": latest.phosphorus_mgkg if latest else None,
                "potassium_mgkg": latest.potassium_mgkg if latest else None,
                "ph": latest.ph if latest else None,
                "moisture_pct": latest.moisture_pct if latest else None,
                "density_gcm3": latest.density_gcm3 if latest else None,
                "fertility_score": compute_fertility_score(latest) if latest else None,
            } if latest else None,
            "samples_count": len(p.samples),
        })
    return {"points": out, "count": len(out)}


@router.get("/{point_code}")
def get_point(point_code: str, db: Session = Depends(get_db)):
    point = db.query(SoilPoint).filter(SoilPoint.point_code == point_code).first()
    if not point:
        raise HTTPException(404, "Точка не найдена")

    samples = (
        db.query(SoilSample)
        .filter(SoilSample.point_id == point.id)
        .order_by(SoilSample.sample_date)
        .all()
    )
    return {
        "point_code": point.point_code,
        "lon": point.lon,
        "lat": point.lat,
        "crop": point.crop,
        "samples": [
            {
                "date": str(s.sample_date),
                "humus_pct": s.humus_pct,
                "nitrogen_mgkg": s.nitrogen_mgkg,
                "phosphorus_mgkg": s.phosphorus_mgkg,
                "potassium_mgkg": s.potassium_mgkg,
                "ph": s.ph,
                "carbonates_pct": s.carbonates_pct,
                "density_gcm3": s.density_gcm3,
                "moisture_pct": s.moisture_pct,
                "fertility_score": compute_fertility_score(s),
                "source_file": s.source_file,
            }
            for s in samples
        ],
    }


# ─── Ручной ввод через форму ────────────────────────────────────────────────

class ManualSampleInput(BaseModel):
    point_code: str = Field(..., description="Код точки, напр. 'Т1' или новый код")
    lon: Optional[float] = Field(None, description="Долгота WGS84 (если новая точка)")
    lat: Optional[float] = Field(None, description="Широта WGS84 (если новая точка)")
    crop: Optional[str] = None
    sample_date: date_type
    depth_cm: str = "0-20"

    humus_pct: Optional[float] = None
    nitrogen_mgkg: Optional[float] = None
    phosphorus_mgkg: Optional[float] = None
    potassium_mgkg: Optional[float] = None
    ph: Optional[float] = None
    carbonates_pct: Optional[float] = None
    density_gcm3: Optional[float] = None
    moisture_pct: Optional[float] = None


@router.post("/manual-sample")
def add_manual_sample(data: ManualSampleInput, db: Session = Depends(get_db)):
    """
    Создаёт или обновляет почвенную пробу, введённую вручную через форму на портале.
    Если точка с таким кодом уже существует — проба добавляется к ней (или обновляется,
    если на эту же дату уже есть запись). Если точки нет — создаётся новая (нужны lon/lat).
    """
    code = normalize_code(data.point_code)

    point = db.query(SoilPoint).filter(SoilPoint.point_code == code).first()
    if not point:
        if data.lon is None or data.lat is None:
            raise HTTPException(
                422,
                f"Точка '{code}' не найдена. Для новой точки укажите координаты (lon, lat)."
            )
        point = SoilPoint(point_code=code, lon=data.lon, lat=data.lat, crop=data.crop)
        db.add(point)
        db.flush()
    else:
        if data.lon is not None and data.lat is not None and point.lon == 0.0 and point.lat == 0.0:
            point.lon = data.lon
            point.lat = data.lat
        if data.crop and not point.crop:
            point.crop = data.crop

    sample = (
        db.query(SoilSample)
        .filter(SoilSample.point_id == point.id, SoilSample.sample_date == data.sample_date)
        .first()
    )
    is_new = sample is None
    if not sample:
        sample = SoilSample(point_id=point.id, sample_date=data.sample_date, source_file="manual-entry")
        db.add(sample)

    for field in ["humus_pct", "nitrogen_mgkg", "phosphorus_mgkg", "potassium_mgkg",
                  "ph", "carbonates_pct", "density_gcm3", "moisture_pct"]:
        value = getattr(data, field)
        if value is not None:
            setattr(sample, field, value)
    sample.depth_cm = data.depth_cm

    db.commit()
    db.refresh(sample)

    return {
        "status": "success",
        "action": "created" if is_new else "updated",
        "point_code": point.point_code,
        "sample_date": str(sample.sample_date),
        "fertility_score": compute_fertility_score(sample),
    }


@router.delete("/manual-sample/{point_code}/{sample_date}")
def delete_manual_sample(point_code: str, sample_date: date_type, db: Session = Depends(get_db)):
    """Удаляет ошибочно введённую пробу — для исправления опечаток."""
    code = normalize_code(point_code)
    point = db.query(SoilPoint).filter(SoilPoint.point_code == code).first()
    if not point:
        raise HTTPException(404, "Точка не найдена")

    sample = (
        db.query(SoilSample)
        .filter(SoilSample.point_id == point.id, SoilSample.sample_date == sample_date)
        .first()
    )
    if not sample:
        raise HTTPException(404, "Проба на эту дату не найдена")

    db.delete(sample)
    db.commit()
    return {"status": "deleted", "point_code": code, "sample_date": str(sample_date)}
