from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

from app.core.db import get_db
from app.core.config import settings
from app.models.db_models import ApsimJob, SoilPoint, SoilSample, KazHydrometRecord

router = APIRouter(prefix="/api/apsim", tags=["apsim"])


def check_worker_auth(x_api_secret: str | None):
    if x_api_secret != settings.api_secret:
        raise HTTPException(401, "Unauthorized — неверный X-Api-Secret")


class CreateJobInput(BaseModel):
    point_code: str
    scenario: str = "baseline"
    years: int = 1
    sowing_date: Optional[str] = None
    crop: str = "Wheat"


@router.post("/run")
def create_job(data: CreateJobInput, db: Session = Depends(get_db)):
    """Ставит задачу APSIM в очередь. Воркер на Hetzner подхватит её через /jobs/next."""
    point = db.query(SoilPoint).filter(SoilPoint.point_code == data.point_code).first()
    if not point:
        raise HTTPException(404, f"Точка '{data.point_code}' не найдена")

    job = ApsimJob(
        point_code=data.point_code, scenario=data.scenario, years=data.years,
        sowing_date=data.sowing_date, crop=data.crop, status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"job_id": job.id, "status": job.status}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Клиентский опрос статуса задачи (для UI — поллинг каждые 3-5 сек)."""
    job = db.query(ApsimJob).filter(ApsimJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Задача не найдена")
    return {
        "job_id": job.id, "status": job.status, "point_code": job.point_code,
        "scenario": job.scenario, "result": job.result, "error": job.error_message,
        "created_at": str(job.created_at), "finished_at": str(job.finished_at) if job.finished_at else None,
    }


@router.get("/jobs")
def list_jobs(status: Optional[str] = None, limit: int = 50, db: Session = Depends(get_db)):
    q = db.query(ApsimJob).order_by(ApsimJob.created_at.desc())
    if status:
        q = q.filter(ApsimJob.status == status)
    jobs = q.limit(limit).all()
    return {"jobs": [
        {"job_id": j.id, "status": j.status, "point_code": j.point_code, "scenario": j.scenario, "created_at": str(j.created_at)}
        for j in jobs
    ]}


# ─── Эндпоинты для воркера (требуют X-Api-Secret) ──────────────────────────

@router.get("/jobs/next")
def claim_next_job(
    worker_id: str = Query(...),
    x_api_secret: str = Header(None),
    db: Session = Depends(get_db),
):
    """
    Атомарно забирает следующую задачу из очереди (SELECT ... FOR UPDATE SKIP LOCKED
    предотвращает гонку, если запущено несколько воркеров параллельно).
    """
    check_worker_auth(x_api_secret)

    job = db.execute(
        text("""
            SELECT id FROM apsim_jobs
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
    ).first()

    if not job:
        return {"job": None}

    job_obj = db.query(ApsimJob).filter(ApsimJob.id == job.id).first()
    job_obj.status = "running"
    job_obj.started_at = datetime.utcnow()
    job_obj.worker_id = worker_id
    db.commit()

    point = db.query(SoilPoint).filter(SoilPoint.point_code == job_obj.point_code).first()
    latest_sample = (
        db.query(SoilSample)
        .filter(SoilSample.point_id == point.id)
        .order_by(SoilSample.sample_date.desc())
        .first()
        if point else None
    )

    # Климат для генерации .met — берём архив КазГидромет (Сарыозек) как основной источник
    weather_rows = (
        db.query(KazHydrometRecord)
        .filter(KazHydrometRecord.station == "Сарыозек")
        .order_by(KazHydrometRecord.date)
        .all()
    )

    return {
        "job": {
            "job_id": job_obj.id,
            "point_code": job_obj.point_code,
            "scenario": job_obj.scenario,
            "years": job_obj.years,
            "sowing_date": job_obj.sowing_date,
            "crop": job_obj.crop,
            "point": {
                "lon": point.lon, "lat": point.lat, "crop": point.crop,
            } if point else None,
            "soil": {
                "humus_pct": latest_sample.humus_pct if latest_sample else None,
                "nitrogen_mgkg": latest_sample.nitrogen_mgkg if latest_sample else None,
                "phosphorus_mgkg": latest_sample.phosphorus_mgkg if latest_sample else None,
                "potassium_mgkg": latest_sample.potassium_mgkg if latest_sample else None,
                "ph": latest_sample.ph if latest_sample else None,
                "density_gcm3": latest_sample.density_gcm3 if latest_sample else None,
            } if latest_sample else None,
            "weather": [
                {
                    "date": str(w.date), "temp_max_c": w.temp_max_c, "temp_min_c": w.temp_min_c,
                    "precip_mm": w.precip_mm,
                }
                for w in weather_rows
            ],
        }
    }


class CompleteJobInput(BaseModel):
    status: str  # 'done' | 'failed'
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@router.post("/jobs/{job_id}/complete")
def complete_job(
    job_id: int, data: CompleteJobInput,
    x_api_secret: str = Header(None),
    db: Session = Depends(get_db),
):
    """Воркер сообщает результат завершённой (или упавшей) симуляции."""
    check_worker_auth(x_api_secret)

    job = db.query(ApsimJob).filter(ApsimJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Задача не найдена")

    job.status = data.status
    job.result = data.result
    job.error_message = data.error
    job.finished_at = datetime.utcnow()
    db.commit()

    return {"status": "updated", "job_id": job_id}
