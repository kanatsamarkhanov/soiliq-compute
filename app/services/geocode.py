import pandas as pd
import re
from sqlalchemy.orm import Session

from app.models.db_models import SoilPoint

WKT_POINT_RE = re.compile(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", re.IGNORECASE)

COORD_ALIASES = {
    "point_code": ["точка", "№ точки", "point", "id точки", "номер точки", "варианты", "варианты, точки"],
    "lon":        ["долгота", "lon", "longitude", "x"],
    "lat":        ["широта", "lat", "latitude", "y"],
    "wkt":        ["wkt", "геометрия", "geometry", "координаты"],
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


def parse_and_geocode(db: Session, filepath: str, filename: str) -> dict:
    """
    Читает файл с координатами (lon/lat колонками или WKT POINT(...))
    и привязывает их к уже существующим SoilPoint по point_code.
    """
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(filepath)
    else:
        df = pd.read_excel(filepath)

    code_col = _match_column(df.columns, COORD_ALIASES["point_code"])
    lon_col  = _match_column(df.columns, COORD_ALIASES["lon"])
    lat_col  = _match_column(df.columns, COORD_ALIASES["lat"])
    wkt_col  = _match_column(df.columns, COORD_ALIASES["wkt"])

    if not code_col:
        return {"status": "failed", "error": "Не найдена колонка с кодом точки"}
    if not (lon_col and lat_col) and not wkt_col:
        return {"status": "failed", "error": "Не найдены колонки координат (lon/lat или WKT)"}

    updated, not_found = 0, []

    for _, row in df.iterrows():
        code = str(row.get(code_col, "")).strip()
        if not code or code.lower() == "nan":
            continue

        lon, lat = None, None
        if lon_col and lat_col:
            lon_v, lat_v = row.get(lon_col), row.get(lat_col)
            if pd.notna(lon_v) and pd.notna(lat_v):
                lon, lat = float(lon_v), float(lat_v)
        elif wkt_col:
            m = WKT_POINT_RE.search(str(row.get(wkt_col, "")))
            if m:
                lon, lat = float(m.group(1)), float(m.group(2))

        if lon is None or lat is None:
            continue

        point = db.query(SoilPoint).filter(SoilPoint.point_code == code).first()
        if not point:
            not_found.append(code)
            continue

        point.lon = lon
        point.lat = lat
        updated += 1

    db.commit()
    return {
        "status": "success",
        "rows_parsed": len(df),
        "points_updated": updated,
        "points_not_found": not_found,
    }
