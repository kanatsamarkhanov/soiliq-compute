import numpy as np
from pykrige.ok import OrdinaryKriging
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.db_models import SoilPoint, SoilSample, KrigingMap


def compute_fertility_score(sample: SoilSample) -> float:
    """Простой композитный индекс плодородия 0–10 на основе ключевых показателей."""
    if not sample:
        return 0.0
    score = 0.0
    weight_sum = 0.0

    if sample.humus_pct is not None:
        score += min(sample.humus_pct / 2.0, 1.0) * 4.0
        weight_sum += 4.0
    if sample.nitrogen_mgkg is not None:
        score += min(sample.nitrogen_mgkg / 40.0, 1.0) * 2.0
        weight_sum += 2.0
    if sample.phosphorus_mgkg is not None:
        score += min(sample.phosphorus_mgkg / 25.0, 1.0) * 2.0
        weight_sum += 2.0
    if sample.moisture_pct is not None:
        score += min(sample.moisture_pct / 15.0, 1.0) * 2.0
        weight_sum += 2.0

    return round((score / weight_sum) * 10, 2) if weight_sum > 0 else 0.0


def run_kriging(db: Session, variable: str = "humus", grid_size: int = 50) -> dict:
    """
    Берёт последние пробы по всем точкам, выполняет ordinary kriging
    и сохраняет результат в KrigingMap.
    """
    points = db.query(SoilPoint).filter(SoilPoint.lon != 0, SoilPoint.lat != 0).all()
    if len(points) < 3:
        raise ValueError("Недостаточно точек с координатами для кригинга (нужно минимум 3)")

    lons, lats, values = [], [], []
    for p in points:
        latest = (
            db.query(SoilSample)
            .filter(SoilSample.point_id == p.id)
            .order_by(SoilSample.sample_date.desc())
            .first()
        )
        if not latest:
            continue

        if variable == "humus":
            v = latest.humus_pct
        elif variable == "fertility_score":
            v = compute_fertility_score(latest)
        elif variable == "nitrogen":
            v = latest.nitrogen_mgkg
        else:
            v = latest.humus_pct

        if v is not None:
            lons.append(p.lon)
            lats.append(p.lat)
            values.append(v)

    if len(values) < 3:
        raise ValueError(f"Недостаточно данных по переменной '{variable}' (нужно минимум 3 точки)")

    lons_arr = np.array(lons)
    lats_arr = np.array(lats)
    vals_arr = np.array(values)

    ok = OrdinaryKriging(
        lons_arr, lats_arr, vals_arr,
        variogram_model="spherical",
        verbose=False, enable_plotting=False,
    )

    margin = 0.02
    grid_lon = np.linspace(lons_arr.min() - margin, lons_arr.max() + margin, grid_size)
    grid_lat = np.linspace(lats_arr.min() - margin, lats_arr.max() + margin, grid_size)

    z, ss = ok.execute("grid", grid_lon, grid_lat)

    result = KrigingMap(
        variable=variable,
        bounds={
            "min_lon": float(grid_lon.min()), "max_lon": float(grid_lon.max()),
            "min_lat": float(grid_lat.min()), "max_lat": float(grid_lat.max()),
        },
        grid_shape={"nx": grid_size, "ny": grid_size},
        grid_values=z.filled(np.nan).tolist() if hasattr(z, "filled") else z.tolist(),
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    return {
        "id": result.id,
        "variable": variable,
        "bounds": result.bounds,
        "grid_shape": result.grid_shape,
        "points_used": len(values),
        "value_range": {"min": float(vals_arr.min()), "max": float(vals_arr.max())},
    }
