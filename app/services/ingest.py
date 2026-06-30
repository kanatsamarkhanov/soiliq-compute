import pandas as pd
import re
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.db_models import SoilPoint, SoilSample, UploadLog
from app.services.geocode import normalize_code

# Маппинг возможных названий колонок (RU/KZ/EN) на поля схемы
COLUMN_ALIASES = {
    "point_code":      ["точка", "№ точки", "point", "id точки", "номер точки", "nuqta"],
    "lon":             ["долгота", "lon", "longitude", "x"],
    "lat":             ["широта", "lat", "latitude", "y"],
    "crop":            ["культура", "crop", "дакыл"],
    "sample_date":     ["дата", "date", "дата отбора"],
    "humus_pct":       ["гумус", "humus", "%гумус", "гумус, %"],
    "nitrogen_mgkg":   ["азот", "nitrogen", "n", "гидр.азот", "гидролизуемый азот"],
    "phosphorus_mgkg": ["фосфор", "phosphorus", "p", "p2o5"],
    "potassium_mgkg":  ["калий", "potassium", "k", "k2o"],
    "ph":              ["ph", "рн", "ph(h2o)"],
    "carbonates_pct":  ["карбонаты", "carbonates", "caco3"],
    "density_gcm3":    ["плотность", "density", "объемная масса"],
    "moisture_pct":    ["влажность", "moisture"],
}


def _normalize(col: str) -> str:
    return re.sub(r"[^\w]", "", str(col).strip().lower())


def _match_column(columns, aliases):
    norm_cols = {_normalize(c): c for c in columns}
    for alias in aliases:
        na = _normalize(alias)
        for nc, orig in norm_cols.items():
            if na in nc or nc in na:
                return orig
    return None


def detect_mapping(df: pd.DataFrame) -> dict:
    """Автоматически находит соответствие колонок файла нашей схеме."""
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        col = _match_column(df.columns, aliases)
        if col:
            mapping[field] = col
    return mapping


def parse_and_ingest(db: Session, filepath: str, filename: str) -> dict:
    """
    Читает xlsx/csv, определяет колонки, апсертит точки и создаёт SoilSample записи.
    Возвращает сводку для UI (сколько строк обработано/вставлено/пропущено).
    """
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(filepath)
    else:
        df = pd.read_excel(filepath)

    mapping = detect_mapping(df)
    if "point_code" not in mapping:
        log = UploadLog(filename=filename, rows_parsed=len(df), rows_inserted=0,
                         status="failed", error_message="Не найдена колонка с кодом точки")
        db.add(log)
        db.commit()
        return {"status": "failed", "error": "Не найдена колонка с идентификатором точки (Т1, Т2…)"}

    inserted = 0
    skipped = 0
    warnings = []

    for _, row in df.iterrows():
        code = normalize_code(str(row.get(mapping["point_code"], "")).strip())
        if not code or code.lower() == "nan":
            skipped += 1
            continue

        point = db.query(SoilPoint).filter(SoilPoint.point_code == code).first()
        if not point:
            lon = row.get(mapping.get("lon"), None)
            lat = row.get(mapping.get("lat"), None)
            if pd.isna(lon) or pd.isna(lat):
                warnings.append(f"{code}: нет координат — точка создана без геопривязки")
                lon, lat = None, None
            point = SoilPoint(
                point_code=code,
                lon=float(lon) if lon is not None and not pd.isna(lon) else 0.0,
                lat=float(lat) if lat is not None and not pd.isna(lat) else 0.0,
                crop=str(row.get(mapping.get("crop"), "")) if mapping.get("crop") else None,
            )
            db.add(point)
            db.flush()

        def num(field):
            col = mapping.get(field)
            if not col:
                return None
            v = row.get(col)
            return float(v) if pd.notna(v) else None

        sample_date = datetime.utcnow().date()
        if mapping.get("sample_date"):
            raw = row.get(mapping["sample_date"])
            try:
                sample_date = pd.to_datetime(raw).date()
            except Exception:
                pass

        sample = SoilSample(
            point_id=point.id,
            sample_date=sample_date,
            humus_pct=num("humus_pct"),
            nitrogen_mgkg=num("nitrogen_mgkg"),
            phosphorus_mgkg=num("phosphorus_mgkg"),
            potassium_mgkg=num("potassium_mgkg"),
            ph=num("ph"),
            carbonates_pct=num("carbonates_pct"),
            density_gcm3=num("density_gcm3"),
            moisture_pct=num("moisture_pct"),
            source_file=filename,
        )
        db.add(sample)
        inserted += 1

    log = UploadLog(
        filename=filename, rows_parsed=len(df), rows_inserted=inserted,
        status="success" if inserted > 0 else "partial",
        error_message="; ".join(warnings) if warnings else None,
    )
    db.add(log)
    db.commit()

    return {
        "status": "success",
        "rows_parsed": len(df),
        "rows_inserted": inserted,
        "rows_skipped": skipped,
        "mapping_detected": mapping,
        "warnings": warnings,
    }
