from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import settings
from app.services.ndvi import sync_point_ndvi, sync_all_points_ndvi, get_ndvi_series

router = APIRouter(prefix="/api/ndvi", tags=["ndvi"])


@router.post("/sync/{point_code}")
def sync_one(
    point_code: str,
    start_date: str = Query("2015-01-01"),
    x_api_secret: str = Header(None),
    db: Session = Depends(get_db),
):
    if x_api_secret != settings.api_secret:
        raise HTTPException(401, "Unauthorized")
    try:
        return sync_point_ndvi(db, point_code, start_date)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/sync")
def sync_all(
    start_date: str = Query("2015-01-01"),
    x_api_secret: str = Header(None),
    db: Session = Depends(get_db),
):
    if x_api_secret != settings.api_secret:
        raise HTTPException(401, "Unauthorized")
    try:
        return sync_all_points_ndvi(db, start_date)
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.get("/{point_code}")
def get_series(point_code: str, db: Session = Depends(get_db)):
    return {"point_code": point_code, "series": get_ndvi_series(db, point_code)}
