# SoilIQ Compute — вычислительный сервис (Railway)

Python/FastAPI сервис: приём данных → PostgreSQL → RothC-прогноз, кригинг-интерполяция,
автосинхронизация с WeatherLink. Работает в паре с порталом на Vercel.

## Архитектура

```
Excel/CSV (онлайн загрузка)
        ↓
POST /api/upload/soil-data  →  PostgreSQL (Railway)
        ↓
GET /api/forecast/...   ← RothC-расчёт по реальным данным точки + климату
GET /api/kriging/run    ← пространственная интерполяция (pykrige)
        ↓
Vercel-портал (soiliq.vercel.app) ← запрашивает результаты через fetch()

WeatherLink v2 API
        ↓ (каждые 6 часов, APScheduler)
PostgreSQL.weather_records
```

## Деплой на Railway

### 1. Создать проект

```bash
railway login
railway init
```

Или через сайт: **railway.app → New Project → Deploy from GitHub repo**

### 2. Добавить PostgreSQL

В Railway: **+ New → Database → PostgreSQL**

Railway автоматически создаст переменную `DATABASE_URL` — в Variables этого сервиса добавьте:
```
DATABASE_URL = ${{Postgres.DATABASE_URL}}
```

### 3. Переменные окружения сервиса

**Settings → Variables:**
```
WEATHERLINK_API_KEY=mgxfgcyi2i9alathg****
WEATHERLINK_API_SECRET=nuregkpstcajd0d******
WL_STATION_SARYBASTAU=225071
WL_STATION_ZHOLAMAN=223356
API_SECRET=сгенерируйте_случайную_строку
ALLOWED_ORIGIN=https://soiliq.vercel.app
```

### 4. Деплой

```bash
git push   # Railway автодеплоит при пуше, если подключён GitHub
# или
railway up
```

Railway выдаст публичный URL вида `soiliq-compute-production.up.railway.app`.

## API Endpoints

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/upload/soil-data` | Загрузка Excel/CSV → парсинг → запись в БД |
| GET  | `/api/points` | Список всех точек с последними замерами |
| GET  | `/api/points/{code}` | История замеров по точке |
| GET  | `/api/forecast/point/{code}?scenario=organic&years=10` | RothC-прогноз для точки |
| GET  | `/api/forecast/all?scenario=alp` | Прогноз по всем точкам |
| GET  | `/api/forecast/compare?years=10` | Все 4 сценария сразу |
| POST | `/api/kriging/run?variable=humus` | Запустить интерполяцию |
| GET  | `/api/kriging/latest/humus` | Последняя сохранённая карта |
| GET  | `/api/weather/history?station=sarybastau&days=30` | История погоды из БД |
| POST | `/api/weather/sync` | Принудительная синхронизация (требует `X-Api-Secret`) |

Документация Swagger: `https://ваш-сервис.up.railway.app/docs`

## Интеграция с Vercel-порталом

В Next.js API routes на Vercel замените прямые вызовы WeatherLink/RothC на проксирование к Railway:

```typescript
// src/app/api/forecast/route.ts (на Vercel)
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const res = await fetch(
    `${process.env.COMPUTE_SERVICE_URL}/api/forecast/compare?${searchParams}`
  )
  return NextResponse.json(await res.json())
}
```

В Vercel добавить переменную:
```
COMPUTE_SERVICE_URL=https://soiliq-compute-production.up.railway.app
```

## Локальный запуск

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# заполнить .env

# Локальный Postgres через Docker
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=pass -e POSTGRES_DB=soiliq postgres:16

uvicorn app.main:app --reload
```

Откройте `http://localhost:8000/docs` — интерактивная документация.

## Загрузка первых данных

```bash
curl -X POST https://ваш-сервис.up.railway.app/api/upload/soil-data \
  -F "file=@Soil-properties-SaryOzek-2025-ff.xlsx"
```

Сервис автоматически распознаёт колонки на русском/казахском (гумус, азот, фосфор, калий, pH и т.д.)
и создаёт точки + замеры в БД.

## Первый запуск прогноза

```bash
# Прогноз для точки Т6, сценарий "органика", 10 лет
curl "https://ваш-сервис.up.railway.app/api/forecast/point/Т6?scenario=organic&years=10"

# Кригинг по гумусу
curl -X POST "https://ваш-сервис.up.railway.app/api/kriging/run?variable=humus"
```
