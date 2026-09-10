"""
Демо-сервис для лабы по наблюдаемости.

Что он умеет:
  * отдаёт HTML-страницу с тремя кнопками (нагрузка);
  * эндпоинты /error (код 500), /slow (задержка 1-3 c), /load (сам себя нагружает);
  * метрики Prometheus на /metrics (метод RED: Rate, Errors, Duration);
  * JSON-логи с trace_id по каждому запросу (пишутся в stdout и в /logs/app.log);
  * трейсы OpenTelemetry, которые уезжают в Jaeger по протоколу OTLP.
"""

import asyncio
import json
import logging
import os
import random
import sys
import threading
import time

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from starlette.responses import Response as StarletteResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# ---------------------------------------------------------------------------
# Настройки берём из переменных окружения (их задаёт docker-compose)
# ---------------------------------------------------------------------------
SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "demo-service")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
LOG_FILE = os.getenv("LOG_FILE", "/logs/app.log")
SELF_URL = os.getenv("SELF_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# OpenTelemetry: куда и как отправлять трейсы
# ---------------------------------------------------------------------------
resource = Resource.create({"service.name": SERVICE_NAME})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(SERVICE_NAME)

# ---------------------------------------------------------------------------
# JSON-логирование: одна строка = один JSON-объект
# ---------------------------------------------------------------------------
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # добавляем поля, которые передали через extra=...
        for key in ("method", "path", "status", "duration_ms", "trace_id"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


logger = logging.getLogger("app")
logger.setLevel(logging.INFO)

_stdout = logging.StreamHandler(sys.stdout)
_stdout.setFormatter(JsonFormatter())
logger.addHandler(_stdout)

_file = logging.FileHandler(LOG_FILE)
_file.setFormatter(JsonFormatter())
logger.addHandler(_file)

# ---------------------------------------------------------------------------
# Метрики Prometheus (метод RED)
#   Rate     -> считаем все запросы счётчиком http_requests_total
#   Errors   -> тот же счётчик, но с меткой status="500"
#   Duration -> гистограмма времени ответа http_request_duration_seconds
# ---------------------------------------------------------------------------
REQUESTS = Counter(
    "http_requests_total",
    "Количество HTTP-запросов",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "Время обработки HTTP-запроса в секундах",
    ["method", "path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5),
)

app = FastAPI(title="Observability demo service")


# ---------------------------------------------------------------------------
# Middleware — код, который выполняется вокруг КАЖДОГО запроса.
# Здесь мы замеряем время, пишем метрики и лог с trace_id.
# ---------------------------------------------------------------------------
@app.middleware("http")
async def observe(request: Request, call_next):
    if request.url.path == "/metrics":
        # сам эндпоинт метрик не считаем, чтобы не зашумлять графики
        return await call_next(request)

    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    method = request.method
    path = request.url.path
    status = response.status_code

    REQUESTS.labels(method, path, str(status)).inc()
    LATENCY.labels(method, path).observe(duration)

    span = trace.get_current_span()
    ctx = span.get_span_context() if span else None
    trace_id = format(ctx.trace_id, "032x") if ctx and ctx.trace_id else "-"

    logger.info(
        "request handled",
        extra={
            "method": method,
            "path": path,
            "status": status,
            "duration_ms": round(duration * 1000, 1),
            "trace_id": trace_id,
        },
    )
    return response


PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Демо-сервис наблюдаемости</title>
<style>
  body{font-family:-apple-system,system-ui,Segoe UI,Roboto,sans-serif;
       max-width:680px;margin:40px auto;padding:0 16px;color:#1d1d1f}
  h1{font-size:22px}
  button{font-size:15px;padding:12px 16px;margin:6px 8px 6px 0;border-radius:10px;
         border:1px solid #c7c7cc;background:#f5f5f7;cursor:pointer}
  button:hover{background:#e8e8ed}
  #log{white-space:pre-wrap;background:#f5f5f7;padding:14px;border-radius:10px;
       margin-top:18px;min-height:48px;font-size:14px}
  a{margin-right:14px}
  .links{margin-top:22px;font-size:14px}
</style>
</head>
<body>
  <h1>Демо-сервис наблюдаемости</h1>
  <p>Каждая кнопка создаёт нагрузку определённого вида. Мониторинг должен её заметить.</p>

  <button onclick="fire('error')">Сгенерировать ошибки (500)</button>
  <button onclick="fire('slow')">Сгенерировать медленные запросы</button>
  <button onclick="fire('fast')">Сгенерировать всплеск нагрузки</button>

  <div id="log">готово к работе</div>

  <div class="links">
    Прямые ссылки:
    <a href="/error" target="_blank">/error</a>
    <a href="/slow" target="_blank">/slow</a>
    <a href="/metrics" target="_blank">/metrics</a>
  </div>

<script>
async function fire(target){
  const log = document.getElementById('log');
  log.textContent = 'запускаю нагрузку: ' + target + ' ...';
  try {
    const r = await fetch('/load?target=' + target, {method: 'POST'});
    const j = await r.json();
    log.textContent = 'нагрузка "' + j.target + '" запущена на ' + j.duration_seconds +
      ' секунд.\\nПодожди ~40-60 секунд и смотри графики в Grafana и алерты в Prometheus.';
  } catch (e) {
    log.textContent = 'ошибка запроса: ' + e;
  }
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return PAGE


@app.get("/healthz", response_class=PlainTextResponse)
async def healthz():
    return "ok"


@app.get("/error")
async def error():
    """Всегда отвечает кодом 500 и помечает свой спан как ошибочный."""
    with tracer.start_as_current_span("broken-operation") as span:
        exc = RuntimeError("synthetic failure for testing")
        span.record_exception(exc)
        span.set_status(trace.Status(trace.StatusCode.ERROR, "synthetic failure"))
        logger.error("handled synthetic error", extra={"path": "/error", "status": 500})
        return Response(
            content=json.dumps({"detail": "synthetic error"}),
            status_code=500,
            media_type="application/json",
        )


@app.get("/slow")
async def slow():
    """Отвечает через случайные 1-3 секунды. Внутри — вложенный спан."""
    delay = random.uniform(1, 3)
    with tracer.start_as_current_span("slow-operation") as span:
        span.set_attribute("planned_delay_seconds", round(delay, 2))
        await asyncio.sleep(delay)
    return {"slept_seconds": round(delay, 2)}


def _blast(target: str, duration_seconds: int) -> None:
    """Фоновая функция: РАВНОМЕРНО нагружает сервис в течение duration_seconds.

    Нагрузка держится долго специально — чтобы соответствующий алерт успел
    перейти в состояние firing и его можно было спокойно заскриншотить.
    """
    url_map = {
        "error": f"{SELF_URL}/error",
        "slow": f"{SELF_URL}/slow",
        "fast": f"{SELF_URL}/healthz",
    }
    url = url_map.get(target, url_map["fast"])
    # пауза между запросами:
    #   error — умеренный поток ошибок (доля 5xx стремится к 100%)
    #   fast  — очень частые запросы (растёт RPS), но без ошибок
    #   slow  — паузы не нужно, сам запрос длится 1-3 с (растёт p95)
    gap = {"error": 0.3, "fast": 0.01, "slow": 0.0}.get(target, 0.01)
    deadline = time.time() + duration_seconds
    with httpx.Client(timeout=15) as client:
        while time.time() < deadline:
            try:
                client.get(url)
            except Exception:
                pass
            if gap:
                time.sleep(gap)


@app.api_route("/load", methods=["GET", "POST"])
async def load(target: str = "fast", seconds: int = 90):
    """Запускает самонагрузку в фоне на N секунд и сразу возвращает ответ."""
    if target not in ("error", "slow", "fast"):
        target = "fast"
    seconds = max(5, min(seconds, 600))
    threading.Thread(target=_blast, args=(target, seconds), daemon=True).start()
    return {"target": target, "duration_seconds": seconds}


@app.get("/metrics")
async def metrics():
    return StarletteResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Включаем автоматическое трейсирование входящих запросов и httpx-клиента
# ---------------------------------------------------------------------------
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()
