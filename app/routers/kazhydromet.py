import shutil
import tempfile
import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
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
