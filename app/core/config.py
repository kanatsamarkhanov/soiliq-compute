from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL — Railway автоматически подставит DATABASE_URL при подключении плагина Postgres
    database_url: str = "postgresql://user:pass@localhost:5432/soiliq"

    # WeatherLink v2
    weatherlink_api_key: str = ""
    weatherlink_api_secret: str = ""
    wl_station_sarybastau: str = ""
    wl_station_zholaman: str = ""

    # Anthropic (опционально — для AI-интерпретации прямо в сервисе)
    anthropic_api_key: str = ""

    # Защита внутренних / cron эндпоинтов
    api_secret: str = "change-me"

    # Google Earth Engine (NDVI) — JSON-ключ сервис-аккаунта, см. app/services/ndvi.py
    gee_service_account_json: str = ""

    # CORS — домен Vercel-портала
    allowed_origin: str = "https://soiliq.vercel.app"

    class Config:
        env_file = ".env"


settings = Settings()
