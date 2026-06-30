from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.db import Base, engine, SessionLocal
from app.routers import upload, points, forecast, kriging, weather, kazhydromet
from app.services.weather_sync import sync_all_stations

scheduler = AsyncIOScheduler()


async def scheduled_sync():
    db = SessionLocal()
    try:
        await sync_all_stations(db, days_back=1)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создаём таблицы при старте (для прод — использовать Alembic-миграции)
    Base.metadata.create_all(bind=engine)

    # Автосинхронизация погоды каждые 6 часов
    scheduler.add_job(scheduled_sync, "interval", hours=6, id="weather_sync")
    scheduler.start()

    yield
    scheduler.shutdown()


app = FastAPI(
    title="SoilIQ Compute Service",
    description="Вычислительный сервис: загрузка данных, RothC-прогноз, кригинг, синхронизация WeatherLink",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(points.router)
app.include_router(forecast.router)
app.include_router(kriging.router)
app.include_router(weather.router)
app.include_router(kazhydromet.router)


@app.get("/")
def root():
    return {"service": "SoilIQ Compute", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}
