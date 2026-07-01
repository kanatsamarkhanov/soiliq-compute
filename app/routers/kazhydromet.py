import shutil
import tempfile
import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.kazhydromet import parse_kazhydromet_files, get_station_summary

router = APIRouter(prefix="/api/kazhydromet", tags=["kazhydromet"])


@router.post("/upload")
async def upload_kazhydromet(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """
    Принимает сразу несколько файлов КазГидромет (t-*.xlsx и p-*.xlsx вперемешку)
    и загружает их все за один запрос.
    """
    tmp_files = []
    try:
        for f in files:
            if not f.filename.lower().endswith((".xlsx", ".xls")):
                continue
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                shutil.copyfileobj(f.file, tmp)
                tmp_files.append((tmp.name, f.filename))

        if not tmp_files:
            raise HTTPException(400, "Не передано ни одного .xlsx файла")

        result = parse_kazhydromet_files(db, tmp_files)
        return result
    finally:
        for path, _ in tmp_files:
            if os.path.exists(path):
                os.unlink(path)


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    """Сводка покрытия по станциям — для отображения на странице климата."""
    return {"stations": get_station_summary(db)}


@router.post("/migrate")
def run_migration(x_api_secret: str = Header(None), db: Session = Depends(get_db)):
    """Одноразовая миграция — добавляет недостающие колонки в kazhydromet_records."""
    from app.core.config import settings
    if x_api_secret != settings.api_secret:
        raise HTTPException(401, "Unauthorized")
    from sqlalchemy import text
    db.execute(text("""
        ALTER TABLE kazhydromet_records
          ADD COLUMN IF NOT EXISTS soil_temp_avg_c FLOAT,
          ADD COLUMN IF NOT EXISTS soil_temp_max_c FLOAT,
          ADD COLUMN IF NOT EXISTS soil_temp_min_c FLOAT
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS ndvi_records (
          id SERIAL PRIMARY KEY,
          point_id INTEGER REFERENCES soil_points(id),
          date DATE NOT NULL,
          ndvi FLOAT,
          cloud_pct FLOAT,
          source VARCHAR DEFAULT 'Sentinel-2 SR',
          synced_at TIMESTAMP DEFAULT NOW()
        )
    """))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_ndvi_point ON ndvi_records(point_id)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_ndvi_date ON ndvi_records(date)"))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS apsim_jobs (
          id SERIAL PRIMARY KEY,
          point_code VARCHAR,
          scenario VARCHAR DEFAULT 'baseline',
          years INTEGER DEFAULT 1,
          sowing_date VARCHAR,
          crop VARCHAR DEFAULT 'Wheat',
          status VARCHAR DEFAULT 'pending',
          result JSONB,
          error_message TEXT,
          created_at TIMESTAMP DEFAULT NOW(),
          started_at TIMESTAMP,
          finished_at TIMESTAMP,
          worker_id VARCHAR
        )
    """))
    db.commit()
    return {"status": "migration complete"}
