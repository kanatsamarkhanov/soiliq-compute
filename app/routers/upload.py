import shutil
import tempfile
import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.ingest import parse_and_ingest
from app.services.geocode import parse_and_geocode

router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("/soil-data")
async def upload_soil_data(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "Поддерживаются только .xlsx, .xls, .csv")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = parse_and_ingest(db, tmp_path, file.filename)
    finally:
        os.unlink(tmp_path)

    if result["status"] == "failed":
        raise HTTPException(422, result["error"])

    return result


@router.post("/coordinates")
async def upload_coordinates(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Привязывает координаты (lon/lat или WKT POINT) к уже существующим точкам
    по point_code. Используется когда координаты в отдельном файле от химанализов.
    """
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(400, "Поддерживаются только .xlsx, .xls, .csv")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = parse_and_geocode(db, tmp_path, file.filename)
    finally:
        os.unlink(tmp_path)

    if result["status"] == "failed":
        raise HTTPException(422, result["error"])

    return result
