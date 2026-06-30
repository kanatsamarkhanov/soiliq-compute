from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.services.forecast import run_forecast, run_forecast_all_points, SCENARIOS

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


@router.get("/scenarios")
def list_scenarios():
    return {"scenarios": list(SCENARIOS.keys())}


@router.get("/point/{point_code}")
def forecast_point(
    point_code: str,
    scenario: str = Query("baseline", regex="^(baseline|organic|npk|alp)$"),
    years: int = Query(10, ge=1, le=30),
    dose: float = Query(10.0, ge=0, le=50),
    station: str = Query("sarybastau"),
    db: Session = Depends(get_db),
):
    try:
        return run_forecast(db, point_code, scenario, years, dose, station)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/all")
def forecast_all(
    scenario: str = Query("baseline", regex="^(baseline|organic|npk|alp)$"),
    years: int = Query(10, ge=1, le=30),
    dose: float = Query(10.0, ge=0, le=50),
    db: Session = Depends(get_db),
):
    return run_forecast_all_points(db, scenario, years, dose)


@router.get("/compare")
def forecast_compare(
    years: int = Query(10, ge=1, le=30),
    dose: float = Query(10.0, ge=0, le=50),
    db: Session = Depends(get_db),
):
    """Сравнение всех 4 сценариев сразу — для графика на портале."""
    out = {}
    for sc in SCENARIOS:
        out[sc] = run_forecast_all_points(db, sc, years, dose)
    return out
