from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import KrigingMap
from app.services.kriging import run_kriging

router = APIRouter(prefix="/api/kriging", tags=["kriging"])


@router.post("/run")
def compute_kriging(
    variable: str = Query("humus", regex="^(humus|fertility_score|nitrogen)$"),
    grid_size: int = Query(50, ge=10, le=200),
    db: Session = Depends(get_db),
):
    try:
        return run_kriging(db, variable, grid_size)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/latest/{variable}")
def latest_kriging(variable: str, db: Session = Depends(get_db)):
    result = (
        db.query(KrigingMap)
        .filter(KrigingMap.variable == variable)
        .order_by(KrigingMap.computed_at.desc())
        .first()
    )
    if not result:
        raise HTTPException(404, f"Нет сохранённых карт для '{variable}'. Запустите /api/kriging/run")

    return {
        "id": result.id,
        "variable": result.variable,
        "bounds": result.bounds,
        "grid_shape": result.grid_shape,
        "grid_values": result.grid_values,
        "computed_at": str(result.computed_at),
    }
