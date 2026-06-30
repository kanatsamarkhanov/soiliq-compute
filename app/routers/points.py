from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import SoilPoint, SoilSample
from app.services.kriging import compute_fertility_score

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
