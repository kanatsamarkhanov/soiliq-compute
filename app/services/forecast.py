import numpy as np
from sqlalchemy.orm import Session
from datetime import date

from app.models.db_models import SoilPoint, SoilSample, WeatherRecord, ForecastResult

SCENARIOS = {
    "baseline": {"k_mult": 1.0,  "input_base": 0.0,  "yield_mult": 1.00},
    "organic":  {"k_mult": 0.43, "input_base": 0.06, "yield_mult": 1.28},
    "npk":      {"k_mult": 0.71, "input_base": 0.02, "yield_mult": 1.18},
    "alp":      {"k_mult": 0.29, "input_base": 0.08, "yield_mult": 1.35},
}

BASE_K = 0.035  # базовый коэффициент минерализации для светло-каштановых почв


def climate_modifier(db: Session, station: str = "sarybastau") -> float:
    """
    Климатический модификатор скорости минерализации на основе среднегодовой
    температуры и осадков (упрощённый аналог RothC rate modifiers a,b,c).
    Возвращает множитель ~0.7–1.3.
    """
    records = db.query(WeatherRecord).filter(WeatherRecord.station == station).all()
    if not records:
        return 1.0

    temps = [r.temp_avg_c for r in records if r.temp_avg_c is not None]
    precs = [r.precip_mm for r in records if r.precip_mm is not None]

    if not temps:
        return 1.0

    avg_temp = sum(temps) / len(temps)
    total_precip = sum(precs) if precs else 250

    # Температурный модификатор (растёт с температурой, эмпирическая формула RothC-like)
    temp_mod = 47.91 / (1 + np.exp(106.06 / (avg_temp + 18.27))) if avg_temp > -18 else 0.1
    temp_mod = max(0.3, min(temp_mod / 5.0, 1.5))

    # Модификатор влажности — засушливые условия Жетысу замедляют минерализацию
    moist_mod = 0.2 + 0.8 * min(total_precip / 300, 1.0)

    return round(temp_mod * moist_mod, 3)


def rothc_series(h0: float, k: float, input_rate: float, years: int) -> list:
    series = []
    for t in range(years + 1):
        h = h0 * np.exp(-k * t) + (input_rate / k) * (1 - np.exp(-k * t)) if k > 0 else h0
        series.append({"year": 2025 + t, "humus_pct": round(float(h), 3)})
    return series


def run_forecast(db: Session, point_code: str, scenario: str, years: int = 10,
                  dose: float = 10.0, station: str = "sarybastau") -> dict:
    point = db.query(SoilPoint).filter(SoilPoint.point_code == point_code).first()
    if not point:
        raise ValueError(f"Точка '{point_code}' не найдена")

    latest = (
        db.query(SoilSample)
        .filter(SoilSample.point_id == point.id, SoilSample.humus_pct.isnot(None))
        .order_by(SoilSample.sample_date.desc())
        .first()
    )
    if not latest:
        raise ValueError(f"Нет данных по гумусу для точки '{point_code}'")

    h0 = latest.humus_pct
    sc = SCENARIOS.get(scenario, SCENARIOS["baseline"])
    cmod = climate_modifier(db, station)

    k = BASE_K * sc["k_mult"] * cmod
    input_rate = sc["input_base"] * (dose / 10.0) * k  # доза масштабирует приток органики

    series = rothc_series(h0, k, input_rate, years)

    result = ForecastResult(
        point_id=point.id,
        scenario=scenario,
        model_type="rothc",
        years_ahead=years,
        humus_series=series,
        params={
            "h0": h0, "k": k, "input_rate": input_rate,
            "dose": dose, "climate_modifier": cmod, "station": station,
        },
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    return {
        "id": result.id,
        "point": point_code,
        "scenario": scenario,
        "climate_modifier": cmod,
        "humus_series": series,
        "final_humus": series[-1]["humus_pct"],
        "yield_multiplier": sc["yield_mult"],
    }


def run_forecast_all_points(db: Session, scenario: str, years: int = 10, dose: float = 10.0) -> dict:
    points = db.query(SoilPoint).all()
    results = []
    for p in points:
        try:
            r = run_forecast(db, p.point_code, scenario, years, dose)
            results.append(r)
        except ValueError:
            continue

    if not results:
        return {"scenario": scenario, "points": [], "avg_final_humus": None}

    avg_final = round(sum(r["final_humus"] for r in results) / len(results), 3)
    return {"scenario": scenario, "points": results, "avg_final_humus": avg_final}
