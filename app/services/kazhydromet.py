import pandas as pd
from sqlalchemy.orm import Session

from app.models.db_models import KazHydrometRecord

# Формат файлов КазГидромет:
#   Строки 0-1: заголовки таблицы ("МЕТЕОРОЛОГИЧЕСКАЯ БАЗА ДАННЫХ", "Табл. ...")
#   Строка 2: реальные заголовки колонок ("Станция", "Дата", "Сред"/"Сумма", ...)
#   Со строки 3: данные
# Температурный файл (t-*.xlsx): Станция | Дата | Сред | Макс | Мин
# Файл осадков (p-*.xlsx):       Станция | Дата | Сумма


def _find_header_row(df: pd.DataFrame) -> int:
    for r in range(min(6, len(df))):
        row_vals = [str(x) for x in df.iloc[r].tolist() if pd.notna(x)]
        if any("Станция" in v for v in row_vals):
            return r
    raise ValueError("Не найдена строка заголовка (ожидается колонка 'Станция')")


def _detect_file_type(df: pd.DataFrame) -> str:
    """Различает 3 типа файлов КазГидромет по заголовку таблицы (строка 1)."""
    title_row = " ".join(str(x) for x in df.iloc[1].tolist() if pd.notna(x)) if len(df) > 1 else ""
    if "почвы" in title_row.lower():
        return "soil_temp"
    if "воздуха" in title_row.lower():
        return "air_temp"
    if "осадк" in title_row.lower():
        return "precip"
    # Фоллбэк по заголовкам колонок, если строка названия таблицы не распознана
    header_row = _find_header_row(df)
    header_vals = [str(x) for x in df.iloc[header_row].tolist() if pd.notna(x)]
    if any("Сумма" in v for v in header_vals):
        return "precip"
    if any("Сред" in v for v in header_vals):
        return "air_temp"
    raise ValueError("Не удалось определить тип файла (воздух/почва/осадки)")


def parse_kazhydromet_file(db: Session, filepath: str, filename: str) -> dict:
    """
    Парсит один файл КазГидромет (температура воздуха / температура почвы / осадки)
    и записывает/обновляет суточные данные в kazhydromet_records. Все три типа файлов
    сливаются в одну запись на (станция, дата) — грузить можно в любом порядке.
    """
    df = pd.read_excel(filepath, header=None)
    file_type = _detect_file_type(df)
    header_row = _find_header_row(df)

    data = df.iloc[header_row + 1:].reset_index(drop=True)
    inserted, updated = 0, 0

    for _, row in data.iterrows():
        station = row.get(0)
        date_raw = row.get(1)
        if pd.isna(station) or pd.isna(date_raw):
            continue

        station = str(station).strip()
        try:
            date_val = pd.to_datetime(date_raw).date()
        except Exception:
            continue

        existing = (
            db.query(KazHydrometRecord)
            .filter(KazHydrometRecord.station == station, KazHydrometRecord.date == date_val)
            .first()
        )

        def num(v):
            if pd.isna(v):
                return None
            try:
                return float(v)
            except (ValueError, TypeError):
                return None

        if file_type == "air_temp":
            payload = {"temp_avg_c": num(row.get(2)), "temp_max_c": num(row.get(3)), "temp_min_c": num(row.get(4))}
        elif file_type == "soil_temp":
            payload = {"soil_temp_avg_c": num(row.get(2)), "soil_temp_max_c": num(row.get(3)), "soil_temp_min_c": num(row.get(4))}
        else:  # precip
            payload = {"precip_mm": num(row.get(2))}

        if existing:
            for k, v in payload.items():
                if v is not None:
                    setattr(existing, k, v)
            updated += 1
        else:
            db.add(KazHydrometRecord(station=station, date=date_val, **payload))
            inserted += 1

    db.commit()

    type_labels = {"air_temp": "температура воздуха", "soil_temp": "температура почвы", "precip": "осадки"}
    return {
        "status": "success",
        "filename": filename,
        "type": type_labels[file_type],
        "rows_parsed": len(data),
        "rows_inserted": inserted,
        "rows_updated": updated,
    }


def parse_kazhydromet_files(db: Session, filepaths: list[tuple[str, str]]) -> dict:
    """Пакетная загрузка нескольких файлов (path, filename) за один запрос."""
    results = []
    for path, filename in filepaths:
        try:
            results.append(parse_kazhydromet_file(db, path, filename))
        except Exception as e:
            results.append({"status": "failed", "filename": filename, "error": str(e)})

    succeeded = sum(1 for r in results if r.get("status") == "success")
    return {"total": len(filepaths), "succeeded": succeeded, "results": results}


def get_station_summary(db: Session) -> list[dict]:
    """Сводка по станциям: период покрытия, средние показатели — для UI."""
    from sqlalchemy import func

    rows = (
        db.query(
            KazHydrometRecord.station,
            func.min(KazHydrometRecord.date).label("first_date"),
            func.max(KazHydrometRecord.date).label("last_date"),
            func.count(KazHydrometRecord.id).label("records"),
            func.avg(KazHydrometRecord.temp_avg_c).label("avg_temp"),
            func.avg(KazHydrometRecord.soil_temp_avg_c).label("avg_soil_temp"),
            func.sum(KazHydrometRecord.precip_mm).label("total_precip"),
        )
        .group_by(KazHydrometRecord.station)
        .all()
    )

    return [
        {
            "station": r.station,
            "first_date": str(r.first_date) if r.first_date else None,
            "last_date": str(r.last_date) if r.last_date else None,
            "records": r.records,
            "avg_temp_c": round(r.avg_temp, 1) if r.avg_temp is not None else None,
            "avg_soil_temp_c": round(r.avg_soil_temp, 1) if r.avg_soil_temp is not None else None,
            "total_precip_mm": round(r.total_precip, 0) if r.total_precip is not None else None,
        }
        for r in rows
    ]
