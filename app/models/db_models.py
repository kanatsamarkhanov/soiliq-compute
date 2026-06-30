from sqlalchemy import Column, Integer, Float, String, DateTime, JSON, ForeignKey, Date
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.db import Base


class SoilPoint(Base):
    """Точка отбора почвенной пробы."""
    __tablename__ = "soil_points"

    id = Column(Integer, primary_key=True, index=True)
    point_code = Column(String, unique=True, index=True)   # 'Т1', 'Т2', ...
    lon = Column(Float, nullable=False)
    lat = Column(Float, nullable=False)
    crop = Column(String, nullable=True)
    region = Column(String, default="Sarуozek")
    created_at = Column(DateTime, default=datetime.utcnow)

    samples = relationship("SoilSample", back_populates="point", cascade="all, delete-orphan")
    forecasts = relationship("ForecastResult", back_populates="point", cascade="all, delete-orphan")


class SoilSample(Base):
    """Одно измерение (сезон) на точке — может быть несколько в год."""
    __tablename__ = "soil_samples"

    id = Column(Integer, primary_key=True, index=True)
    point_id = Column(Integer, ForeignKey("soil_points.id"))
    sample_date = Column(Date, nullable=False)
    depth_cm = Column(String, default="0-20")              # '0-20' или '20-40'

    humus_pct = Column(Float, nullable=True)
    nitrogen_mgkg = Column(Float, nullable=True)
    phosphorus_mgkg = Column(Float, nullable=True)
    potassium_mgkg = Column(Float, nullable=True)
    ph = Column(Float, nullable=True)
    carbonates_pct = Column(Float, nullable=True)
    density_gcm3 = Column(Float, nullable=True)
    moisture_pct = Column(Float, nullable=True)

    source_file = Column(String, nullable=True)            # имя загруженного файла
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    point = relationship("SoilPoint", back_populates="samples")


class WeatherRecord(Base):
    """Суточная агрегированная запись по станции WeatherLink."""
    __tablename__ = "weather_records"

    id = Column(Integer, primary_key=True, index=True)
    station = Column(String, index=True)                   # 'sarybastau' | 'zholaman'
    date = Column(Date, index=True)

    temp_max_c = Column(Float, nullable=True)
    temp_min_c = Column(Float, nullable=True)
    temp_avg_c = Column(Float, nullable=True)
    precip_mm = Column(Float, nullable=True)
    pressure_mb = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
    wind_kmh = Column(Float, nullable=True)
    solar_rad = Column(Float, nullable=True)
    et_mm = Column(Float, nullable=True)

    synced_at = Column(DateTime, default=datetime.utcnow)


class ForecastResult(Base):
    """Результат RothC/APSIM прогноза для точки и сценария."""
    __tablename__ = "forecast_results"

    id = Column(Integer, primary_key=True, index=True)
    point_id = Column(Integer, ForeignKey("soil_points.id"))
    scenario = Column(String)                              # 'baseline' | 'organic' | 'npk' | 'alp'
    model_type = Column(String, default="rothc")           # 'rothc' | 'apsim'

    years_ahead = Column(Integer)
    humus_series = Column(JSON)                             # [{year, humus_pct}, ...]
    yield_series = Column(JSON, nullable=True)               # APSIM output
    params = Column(JSON, nullable=True)                     # k, input, dose, freq...

    computed_at = Column(DateTime, default=datetime.utcnow)

    point = relationship("SoilPoint", back_populates="forecasts")


class KrigingMap(Base):
    """Сохранённый растр кригинг-интерполяции (как сетка значений)."""
    __tablename__ = "kriging_maps"

    id = Column(Integer, primary_key=True, index=True)
    variable = Column(String)                                # 'humus' | 'fertility_score'
    bounds = Column(JSON)                                     # {min_lon, max_lon, min_lat, max_lat}
    grid_shape = Column(JSON)                                 # {nx, ny}
    grid_values = Column(JSON)                                 # flattened array
    computed_at = Column(DateTime, default=datetime.utcnow)


class KazHydrometRecord(Base):
    """Суточная запись архива КазГидромет (2000/2013–2026) по станции."""
    __tablename__ = "kazhydromet_records"

    id = Column(Integer, primary_key=True, index=True)
    station = Column(String, index=True)     # 'Сарыозек', 'Талдыкорган', 'Баканас', ...
    date = Column(Date, index=True)

    temp_avg_c = Column(Float, nullable=True)
    temp_max_c = Column(Float, nullable=True)
    temp_min_c = Column(Float, nullable=True)
    precip_mm = Column(Float, nullable=True)

    synced_at = Column(DateTime, default=datetime.utcnow)


class UploadLog(Base):
    """История загрузок Excel/CSV файлов."""
    __tablename__ = "upload_logs"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    rows_parsed = Column(Integer)
    rows_inserted = Column(Integer)
    status = Column(String, default="success")             # success | partial | failed
    error_message = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
