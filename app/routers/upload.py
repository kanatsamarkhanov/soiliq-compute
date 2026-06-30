import shutil
import tempfile
import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.ingest import parse_and_ingest
from app.services.geocode import parse_and_geocode
from app.services.kazniish_parser import parse_lab_report

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


@router.post("/lab-report")
async def upload_lab_report(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Загрузка многолистового лабораторного отчёта КазНИИ почвоведения
    (Гумус общ, N л.г., Фосфор подв, К2О, pH, СО2 карбонаты — блоки май/август 2025).
    Профильные данные апреля 2026 ("Разрез N") не загружаются — другой тип объекта.
    """
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, "Поддерживается только .xlsx, .xls")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = parse_lab_report(db, tmp_path, file.filename)
    finally:
        os.unlink(tmp_path)

    return result
