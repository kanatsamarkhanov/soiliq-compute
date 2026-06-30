import pandas as pd
import re
from datetime import date
from sqlalchemy.orm import Session

from app.models.db_models import SoilPoint, SoilSample
from app.services.geocode import normalize_code

# Сопоставление названий листов отчёта КазНИИ почвоведения с полями нашей схемы.
# Только показатели, для которых в SoilSample есть соответствующее поле.
SHEET_TO_FIELD = {
    "Гумус общ":     "humus_pct",
    "N л.г.":        "nitrogen_mgkg",       # легкогидролизуемый азот, мг/кг — соответствует имеющимся данным
    "Фосфор подв":   "phosphorus_mgkg",     # подвижный P2O5
    "К2О":           "potassium_mgkg",      # обменный калий
    "pH":            "ph",
    "СО2 карбонаты": "carbonates_pct",
}

# Известные сезоны 2025 года и соответствующие даты
SEASON_DATES = {
    "may": date(2025, 5, 20),
    "aug": date(2025, 8, 8),
}


def _to_float(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        v = v.replace(",", ".").strip()
        if not v or v.lower() == "nan":
            return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _extract_season_block(df: pd.DataFrame, header_row: int, label_col: int, value_col: int) -> list[dict]:
    """
    Извлекает пары (точка, культура) из последовательных строк одного сезонного блока.
    Паттерн отчёта: первая строка пары — код точки + значение для глубины 0-20,
    вторая строка — название культуры + значение для глубины 20-40.
    Берём среднее по двум глубинам как представительное значение точки.
    """
    rows = []
    i = header_row + 1
    pending_code = None
    pending_val = None
    started = False
    blank_streak = 0

    while i < len(df):
        label = df.iat[i, label_col] if label_col < df.shape[1] else None
        val = df.iat[i, value_col] if value_col < df.shape[1] else None
        label_str = str(label).strip() if pd.notna(label) else ""
        is_blank_row = (label_str == "" or label_str.lower() == "nan") and pd.isna(val)

        if is_blank_row:
            blank_streak += 1
            # До начала данных пропускаем сколько угодно пустых строк (это шапка таблицы).
            # После того как данные начались — две пустые строки подряд означают конец блока.
            if started and blank_streak >= 2:
                break
            i += 1
            continue

        blank_streak = 0
        started = True

        is_point_code = bool(re.match(r"^Т\s*\d+", label_str, re.IGNORECASE))

        if is_point_code:
            pending_code = normalize_code(label_str)
            pending_val = _to_float(val)
        else:
            # Это строка культуры — закрывает пару точки
            v2 = _to_float(val)
            if pending_code:
                vals = [v for v in (pending_val, v2) if v is not None]
                avg_val = sum(vals) / len(vals) if vals else None
                rows.append({"point_code": pending_code, "crop": label_str, "value": avg_val})
            pending_code = None
            pending_val = None

        i += 1

    return rows


def parse_lab_report(db: Session, filepath: str, filename: str) -> dict:
    """
    Парсит многолистовой лабораторный отчёт КазНИИ почвоведения.
    Извлекает блоки май-2025 и август-2025 для листов из SHEET_TO_FIELD,
    создаёт/обновляет SoilPoint + SoilSample по точкам Т1...Т14.

    Данные профиля апреля 2026 ("Разрез N") пропускаются — это другой тип объекта
    (почвенный разрез с глубинами 0-8...110-120 см), не привязанный к точкам Т1-Т14.
    """
    xl = pd.ExcelFile(filepath)
    sheets_processed = []
    sheets_skipped = []
    points_touched = set()
    samples_created = 0

    for sheet_name, field in SHEET_TO_FIELD.items():
        if sheet_name not in xl.sheet_names:
            sheets_skipped.append(f"{sheet_name} (нет в файле)")
            continue

        df = xl.parse(sheet_name, header=None)

        # Ищем строку заголовка — там, где встречается "Варианты, точки" или "Глубина"
        header_row = None
        for r in range(min(8, len(df))):
            row_str = " ".join(str(x) for x in df.iloc[r].tolist() if pd.notna(x))
            if "Варианты" in row_str or "Глубина" in row_str:
                header_row = r
                break

        if header_row is None:
            sheets_skipped.append(f"{sheet_name} (не найден заголовок)")
            continue

        header_vals = [str(x) if pd.notna(x) else "" for x in df.iloc[header_row].tolist()]

        # Блок мая 2025: колонка "Варианты..." → значение через 2 колонки (после "Глубина")
        try:
            col_label_may = next(i for i, h in enumerate(header_vals) if "20.05" in h or "Варианты" in h)
        except StopIteration:
            sheets_skipped.append(f"{sheet_name} (блок май не найден)")
            continue
        col_value_may = col_label_may + 2  # label, глубина, значение

        # Блок августа 2025: следующая колонка "Варианты..." после майского значения
        col_label_aug = None
        for i in range(col_value_may + 1, len(header_vals)):
            if "08.08" in header_vals[i] or ("Варианты" in header_vals[i] and i > col_label_may):
                col_label_aug = i
                break
        col_value_aug = col_label_aug + 1 if col_label_aug is not None else None

        for season, label_col, value_col in [
            ("may", col_label_may, col_value_may),
            ("aug", col_label_aug, col_value_aug),
        ]:
            if label_col is None or value_col is None or value_col >= df.shape[1]:
                continue

            extracted = _extract_season_block(df, header_row, label_col, value_col)
            sample_date = SEASON_DATES[season]

            for item in extracted:
                code = item["point_code"]
                if item["value"] is None:
                    continue

                point = db.query(SoilPoint).filter(SoilPoint.point_code == code).first()
                if not point:
                    point = SoilPoint(point_code=code, lon=0.0, lat=0.0, crop=item["crop"])
                    db.add(point)
                    db.flush()
                elif not point.crop:
                    point.crop = item["crop"]

                sample = (
                    db.query(SoilSample)
                    .filter(SoilSample.point_id == point.id, SoilSample.sample_date == sample_date)
                    .first()
                )
                if not sample:
                    sample = SoilSample(point_id=point.id, sample_date=sample_date, source_file=filename)
                    db.add(sample)
                    samples_created += 1

                setattr(sample, field, item["value"])
                points_touched.add(code)

        sheets_processed.append(sheet_name)

    db.commit()

    return {
        "status": "success",
        "sheets_processed": sheets_processed,
        "sheets_skipped": sheets_skipped,
        "points_touched": sorted(points_touched),
        "samples_created_or_updated": samples_created,
        "note": "Профильные данные апреля 2026 ('Разрез N') не загружены — требуют отдельной модели данных (почвенный разрез по глубинам, не точки Т1-Т14).",
    }
