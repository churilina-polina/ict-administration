# Лаба 2 — Полный мониторинг маленького сервиса

**Курс:** Администрирование в инфокоммуникационных системах
**Авторы:** Чурилина Полина Олеговна, Арбузина Елена Романовна
**Группа:** К3320
**Репозиторий:** https://github.com/churilina-polina/ict-administration → папка `lab_2/`

---

## Оглавление

- [Цель работы](#цель-работы)
- [Что получилось](#что-получилось)
- [Архитектура стека](#архитектура-стека)
- [Как запустить и проверить](#как-запустить-и-проверить)
- [Часть 1. Сервис с интерактивными кнопками](#часть-1-сервис-с-интерактивными-кнопками)
- [Часть 2. Мониторинг метрик (Prometheus + Grafana)](#часть-2-мониторинг-метрик-prometheus--grafana)
- [Часть 3. Сбор логов (Loki + Promtail)](#часть-3-сбор-логов-loki--promtail)
- [Часть 4. Распределённые трейсы (OpenTelemetry + Jaeger)](#часть-4-распределённые-трейсы-opentelemetry--jaeger)
- [Часть 5. Оповещения (Prometheus + Alertmanager)](#часть-5-оповещения-prometheus--alertmanager)
- [Обоснование выбора метрик](#обоснование-выбора-метрик)
- [Обоснование выбора алертов](#обоснование-выбора-алертов)
- [Выводы](#выводы)
- [Использованные инструменты](#использованные-инструменты)

---

## Цель работы

Развернуть простой HTTP-сервис и полный стек наблюдаемости вокруг него:

- **метрики** — в Prometheus, визуализация в Grafana;
- **логи** — в Loki (доставка через Promtail), просмотр в Grafana;
- **трейсы** — через OpenTelemetry в Jaeger;
- **оповещения** — через Alertmanager.

Весь стек поднимается локально одной командой `docker compose up` и демонстрируется нажатием кнопок на странице сервиса.

---

## Что получилось

| Требование задания | Реализация |
|---|---|
| HTTP-сервис с эндпоинтами ошибки / задержки / нагрузки | `service/app.py` (FastAPI + uvicorn), эндпоинты `/error`, `/slow`, `/load` |
| Метрики Prometheus на `/metrics` по методу RED | счётчик `http_requests_total`, гистограмма `http_request_duration_seconds` |
| JSON-логирование с `trace_id` | `JsonFormatter`, вывод в stdout и в файл `/logs/app.log` |
| Инструментирование OpenTelemetry | авто-инструментирование FastAPI + ручные спаны `slow-operation` / `broken-operation` |
| Dockerfile | `service/Dockerfile` (образ `python:3.12-slim`) |
| Prometheus + Grafana + дашборд RED | `prometheus/prometheus.yml`, provisioning Grafana, дашборд `RED — demo-service` |
| Loki + Promtail + просмотр логов в Grafana | `loki/`, `promtail/`, источник данных Loki в Grafana |
| Jaeger all-in-one (OTLP 4317/4318) | контейнер `jaeger`, UI на `:16686` |
| 3 правила алертов + Alertmanager + доставка | `prometheus/alert.rules.yml`, `alertmanager/alertmanager.yml`, webhook-приёмник |
| Конфигурация — Docker Compose | `docker-compose.yml`, 8 сервисов |

Итого 8 контейнеров, всё поднимается и работает одной командой.

---

## Архитектура стека

```
                          ┌───────────────────────────┐
                          │        demo-service        │
   браузер ──HTTP──►      │  FastAPI, порт 8000        │
   (кнопки нагрузки)      │                            │
                          │  GET /            — страница│
                          │  GET /error       — 500     │
                          │  GET /slow        — 1..3 c   │
                          │  POST /load       — самонагрузка
                          │  GET /metrics     — метрики │
                          └───┬─────────┬─────────┬─────┘
             scrape /metrics  │         │ файл    │ OTLP :4317
             каждые 5 c       │         │ /logs/  │
                              ▼         ▼ app.log ▼
                       ┌────────────┐  ┌────────┐  ┌──────────┐
                       │ Prometheus │  │Promtail│  │  Jaeger  │
                       │  :9090     │  └───┬────┘  │  :16686  │
                       └──┬──────┬──┘      │ push  └──────────┘
              правила     │      │ query   ▼
              алертов     │      │    ┌────────┐
                          ▼      │    │  Loki  │
                   ┌──────────────┐   │ :3100  │
                   │ Alertmanager │   └───┬────┘
                   │    :9093     │       │ datasource
                   └──────┬───────┘       │
                          │ webhook       ▼
                          ▼        ┌─────────────┐
                   ┌────────────┐  │   Grafana   │
                   │  webhook   │  │   :3000     │
                   │ receiver   │  │ дашборд RED │
                   │  :8081     │  │ + логи Loki │
                   └────────────┘  └─────────────┘
```

**Состав (файл `docker-compose.yml`):**

| Контейнер | Образ | Порт (localhost) | Роль |
|---|---|---|---|
| `demo-service` | собирается из `./service` | 8000 | тестовый сервис: нагрузка, метрики, логи, трейсы |
| `prometheus` | `prom/prometheus:v3.1.0` | 9090 | сбор метрик, вычисление правил алертов |
| `alertmanager` | `prom/alertmanager:v0.28.0` | 9093 | приём сработавших алертов, доставка уведомлений |
| `webhook` | `mendhak/http-https-echo` | 8081 | приёмник уведомлений от Alertmanager (для проверки) |
| `grafana` | `grafana/grafana:11.4.0` | 3000 | дашборды по метрикам, просмотр логов |
| `loki` | `grafana/loki:3.3.2` | 3100 | хранилище логов |
| `promtail` | `grafana/promtail:3.3.2` | — | читает файл логов сервиса и отправляет в Loki |
| `jaeger` | `jaegertracing/all-in-one:1.65.0` | 16686 / 4317 / 4318 | приём и визуализация трейсов |

Контейнеры находятся в одной сети Docker и адресуют друг друга по именам (`service`, `prometheus`, `loki`, `jaeger` …). Файл логов передаётся между `demo-service` и `promtail` через общий том `applogs`.

---

## Как запустить и проверить

```bash
cd lab_2
docker compose up --build
```

Первый запуск занимает 2–4 минуты (сборка образа сервиса). Проверка состояния во втором окне терминала:

```bash
docker compose ps
```

Все 8 контейнеров должны быть в статусе `Up`.

![docker compose ps — все контейнеры подняты](images/01-compose-ps.png)

Страница управления сервисом — http://localhost:8000. Три кнопки создают нагрузку разного вида.

![Страница демо-сервиса с кнопками нагрузки](images/02-service-page.png)

Адреса веб-интерфейсов:

| Сервис | URL |
|---|---|
| Демо-сервис | http://localhost:8000 |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Grafana | http://localhost:3000 |
| Jaeger UI | http://localhost:16686 |

Остановка: `docker compose down` (с флагом `-v` — вместе с томами данных).

---

## Часть 1. Сервис с интерактивными кнопками

Весь сервис — файл `service/app.py` (Python, фреймворк FastAPI, веб-сервер uvicorn).

### Эндпоинты

| Эндпоинт | Поведение |
|---|---|
| `GET /` | HTML-страница с тремя кнопками нагрузки |
| `GET /error` | всегда возвращает HTTP **500**; создаёт спан `broken-operation` со статусом error |
| `GET /slow` | отвечает через случайные **1–3 секунды**; внутри — вложенный спан `slow-operation` (`asyncio.sleep`) |
| `POST /load?target=error\|slow\|fast&seconds=90` | запускает в фоне равномерную самонагрузку выбранного типа на N секунд |
| `GET /metrics` | метрики в формате Prometheus |
| `GET /healthz` | проверка живости |

Эндпоинт `/load` порождает фоновый поток (`_blast`), который в течение заданного времени сам шлёт запросы на свой же адрес (`/error`, `/slow` или `/healthz`) с равномерной паузой между ними. Нагрузка держится долго специально — чтобы соответствующий алерт успел перейти в `FIRING` и его можно было заскриншотить.

### Метрики RED

Объявлены две метрики (`prometheus_client`):

```python
REQUESTS = Counter(
    "http_requests_total", "Количество HTTP-запросов",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "http_request_duration_seconds", "Время обработки HTTP-запроса в секундах",
    ["method", "path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5),
)
```

- `http_requests_total` — счётчик всех запросов. Метка `status` даёт одновременно **Rate** (всё) и **Errors** (`status=~"5.."`).
- `http_request_duration_seconds` — гистограмма времени ответа, из неё считается **Duration** и перцентили.

Обе метрики обновляет middleware `observe`, который оборачивает **каждый** запрос: замеряет время, инкрементирует счётчик, кладёт наблюдение в гистограмму и пишет строку лога.

### JSON-логирование с trace_id

Каждая строка лога — JSON-объект (класс `JsonFormatter`). Пример строки из `/logs/app.log`:

```json
{"time": "2026-09-10T10:22:49", "level": "INFO", "message": "request handled",
 "method": "GET", "path": "/error", "status": 500, "duration_ms": 1.0,
 "trace_id": "0c35140ad507593d0bf123677f4f70a1"}
```

`trace_id` берётся из текущего спана OpenTelemetry — по нему строка лога связывается с трейсом в Jaeger. Логи пишутся в два приёмника: `stdout` контейнера и файл `/logs/app.log` (его читает Promtail).

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

Сначала копируются и ставятся зависимости (`requirements.txt`), потом код — так Docker кеширует слой с библиотеками и не переустанавливает их при каждом изменении `app.py`.

---

## Часть 2. Мониторинг метрик (Prometheus + Grafana)

### Prometheus

Конфиг `prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 5s        # частота сбора метрик
  evaluation_interval: 5s    # частота проверки правил алертов

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]

rule_files:
  - /etc/prometheus/alert.rules.yml

scrape_configs:
  - job_name: demo-service
    static_configs:
      - targets: ["service:8000"]
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]
```

Prometheus каждые 5 секунд ходит на `http://service:8000/metrics` и забирает метрики. Состояние целей — на странице **Status → Target health**: цель `demo-service` в состоянии `UP`.

![Prometheus Targets — цель demo-service в состоянии UP](images/03-prometheus-targets.png)

### Grafana (настройка через provisioning)

Grafana конфигурируется файлами при старте, без ручного кликанья:

- `grafana/provisioning/datasources/datasources.yml` — подключает два источника данных: **Prometheus** (`http://prometheus:9090`, uid `prometheus`) и **Loki** (`http://loki:3100`, uid `loki`).
- `grafana/provisioning/dashboards/dashboards.yml` — правило «загрузить все дашборды из папки».
- `grafana/provisioning/dashboards/red-dashboard.json` — сам дашборд `RED — demo-service`.

Для простоты демонстрации включён анонимный вход с ролью Admin (`GF_AUTH_ANONYMOUS_ENABLED`).

### Дашборд RED

Три панели:

| Панель | Запрос PromQL |
|---|---|
| **Request Rate** — запросов в секунду | `sum(rate(http_requests_total[1m]))` |
| **Error Rate** — доля ответов 5xx, % | `100 * sum(rate(http_requests_total{status=~"5.."}[1m])) / clamp_min(sum(rate(http_requests_total[1m])), 0.001)` |
| **Duration** — p50 / p95 / p99, c | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[1m])) by (le))` (и для 0.5, 0.99) |

- `rate(...[1m])` — средняя скорость роста счётчика за минуту (запросов/сек).
- `clamp_min(..., 0.001)` в знаменателе Error Rate — защита от деления на ноль, когда трафика нет.
- `histogram_quantile(0.95, ...)` — «95% запросов быстрее, чем …».

В спокойном состоянии Request Rate ≈ 0, а Error Rate показывает «No data» — это нормально: ошибок ещё не было, делить нечего.

![Дашборд RED в спокойном состоянии](images/04-grafana-calm.png)

После нажатия кнопок нагрузки (по одной, с паузами) на панелях видна реакция: всплеск Request Rate до ~65 rps, подъём Error Rate до 100%, рост p95 до ~3 секунд.

![Дашборд RED под нагрузкой — реакция всех трёх метрик](images/05-grafana-load.png)

---

## Часть 3. Сбор логов (Loki + Promtail)

Разделение труда:

- **Loki** (`loki/loki-config.yml`) — хранилище логов (аналог Prometheus, но для текста). Конфигурация single-binary: хранение на файловой системе, схема индекса `tsdb` v13, без аутентификации.
- **Promtail** (`promtail/promtail-config.yml`) — агент доставки:

```yaml
clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: demo-service-file
    static_configs:
      - targets: [localhost]
        labels:
          job: demo-service
          __path__: /logs/*.log
    pipeline_stages:
      - json:                       # каждая строка — JSON, разобрать поля
          expressions:
            level: level
            trace_id: trace_id
            path: path
            status: status
      - labels:                     # часть полей делаем метками для фильтрации
          level:
          path:
```

Файл `/logs/app.log` попадает к Promtail через общий том `applogs` (сервис пишет в него, Promtail читает в режиме `ro`).

### Проверка

Grafana → **Explore** → источник **Loki** → запрос:

```logql
{job="demo-service", path="/error"} |= "request handled"
```

В развёрнутой строке видны поля `status = 500` и `trace_id` — тот же идентификатор используется для поиска запроса в Jaeger.

![Grafana Explore — строка лога ошибочного запроса с trace_id](images/06-loki-logs.png)

---

## Часть 4. Распределённые трейсы (OpenTelemetry + Jaeger)

### Инструментирование приложения

Настройка экспортёра (`service/app.py`):

```python
resource = Resource.create({"service.name": "demo-service"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True))
)
trace.set_tracer_provider(provider)
```

Адрес Jaeger задаётся переменной окружения `OTEL_EXPORTER_OTLP_ENDPOINT` в `docker-compose.yml`.

Автоматические спаны на каждый входящий запрос и на исходящие запросы клиента:

```python
FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()
```

Ручные спаны:

- `slow-operation` в `/slow` — оборачивает искусственную задержку (`asyncio.sleep`), с атрибутом `planned_delay_seconds`;
- `broken-operation` в `/error` — помечается статусом ошибки и в него записывается исключение:

```python
span.record_exception(exc)
span.set_status(trace.Status(trace.StatusCode.ERROR, "synthetic failure"))
```

`trace_id` текущего спана прокидывается в JSON-логи (Часть 1) — это связывает логи и трейсы.

### Jaeger

Контейнер `jaeger` (`jaegertracing/all-in-one:1.65.0`) принимает трейсы по OTLP на портах 4317 (gRPC) и 4318 (HTTP), UI — на 16686. «All-in-one» объединяет приёмник, хранилище и интерфейс в одном контейнере (учебный вариант; в продакшене это раздельные компоненты, а между сервисом и Jaeger обычно ставят OpenTelemetry Collector — в задании помечено как опциональное, здесь не делали).

### Проверка

Список трейсов операции `GET /slow` — длительность 1.5–3 секунды, по 6 спанов:

![Jaeger — список трейсов GET /slow](images/07-jaeger-list.png)

«Водопад» медленного запроса. Видна вложенность `GET` → `GET /slow` → `slow-operation` (чёрная полоса почти на всю длительность — искусственная задержка), ниже — короткие спаны `http send` от httpx-клиента. `Depth 3`, `Total Spans 6`.

![Jaeger — водопад медленного запроса с вложенным спаном slow-operation](images/08-jaeger-slow.png)

Трейс ошибочного запроса, найден по `trace_id` из строки лога Loki. Все спаны помечены красным. У спана `broken-operation`: теги `error = true`, `otel.status_code = ERROR`; блок **Logs** с событием `exception`, `exception.message = synthetic failure for testing`; в разделе Process — `telemetry.sdk.language = python` (подтверждает, что трейс пришёл из нашего Python-сервиса через OpenTelemetry).

![Jaeger — трейс ошибочного запроса, красный спан broken-operation с событием exception](images/09-jaeger-error.png)

---

## Часть 5. Оповещения (Prometheus + Alertmanager)

### Правила алертов

Файл `prometheus/alert.rules.yml`, группа `red-alerts`:

```yaml
groups:
  - name: red-alerts
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[1m]))
          / clamp_min(sum(rate(http_requests_total[1m])), 0.001) > 0.10
        for: 30s
        labels: { severity: critical }
        annotations:
          summary: "Высокая доля ошибок (>10%)"
          description: "Доля ответов 5xx превысила 10% за последнюю минуту. Провоцируется кнопкой «Сгенерировать ошибки»."

      - alert: RequestSpike
        expr: sum(rate(http_requests_total[1m])) > 8
        for: 30s
        labels: { severity: warning }
        annotations:
          summary: "Всплеск числа запросов (>8 rps)"
          description: "Частота запросов превысила 8 запросов в секунду за последнюю минуту. Провоцируется кнопкой «Сгенерировать всплеск нагрузки»."

      - alert: HighLatency
        expr: |
          histogram_quantile(0.95,
            sum(rate(http_request_duration_seconds_bucket[1m])) by (le)) > 1.5
        for: 30s
        labels: { severity: warning }
        annotations:
          summary: "Высокая задержка p95 (>1.5 c)"
          description: "95-й перцентиль времени ответа превысил 1.5 секунды за последнюю минуту. Провоцируется кнопкой «Сгенерировать медленные запросы»."
```

Каждое правило соответствует одной букве метода RED. `for: 30s` — условие должно продержаться 30 секунд, только тогда алерт переходит `PENDING → FIRING` (защита от разовых пиков).

### Alertmanager

Файл `alertmanager/alertmanager.yml`:

```yaml
route:
  receiver: webhook-default
  group_by: ["alertname"]
  group_wait: 5s
  group_interval: 10s
  repeat_interval: 1h

receivers:
  - name: webhook-default
    webhook_configs:
      - url: http://webhook:8080/
        send_resolved: true
```

Выбран способ доставки **webhook** — не требует ни Slack-аккаунта, ни почтового сервера. Уведомления уходят на контейнер `webhook` (`mendhak/http-https-echo`), который печатает полученный JSON в свой лог; это служит «почтовым ящиком» для проверки. `send_resolved: true` — слать уведомление и когда алерт погас.

### Проверка

Три правила в спокойном состоянии (`INACTIVE (3)`), с раскрытыми выражениями:

![Prometheus Alerts — три правила в состоянии INACTIVE](images/10-alerts-rules.png)

Каждый алерт провоцировался **своей кнопкой по одному, с паузами** — иначе поток успешных запросов от одной кнопки искажает метрику другого правила (например, разбавляет долю ошибок и мешает `HighErrorRate`).

**HighErrorRate** — `FIRING`, `Value = 1` (доля ошибок = 100%):

![HighErrorRate в состоянии FIRING](images/11a-firing-errorrate.png)

**HighLatency** — `FIRING`, `Value ≈ 2.91` (p95 ≈ 2.9 c при пороге 1.5):

![HighLatency в состоянии FIRING](images/11b-firing-latency.png)

**RequestSpike** — `FIRING`, `Value ≈ 45.86` (≈46 rps при пороге 8):

![RequestSpike в состоянии FIRING](images/11c-firing-spike.png)

Уведомление реально доставлено: в логе контейнера `webhook` виден POST от Alertmanager с телом `"status": "firing"` и `"alertname"`:

![Лог webhook-приёмника — доставленное уведомление о срабатывании алерта](images/12-webhook-notification.png)

Полная цепочка: **сервис → Prometheus (собрал метрику, проверил правило) → Alertmanager (сгруппировал, применил маршрут) → webhook (доставка)**.

---

## Обоснование выбора метрик

На дашборд вынесены три метрики метода **RED** — Rate, Errors, Duration.

**Почему именно RED.** Это минимальный достаточный набор для любого сервиса, работающего по модели «запрос — ответ». Три числа отвечают на три независимых вопроса о здоровье сервиса:

- **Rate** (`sum(rate(http_requests_total[1m]))`) — какая сейчас нагрузка и как она меняется. Без этого показателя нельзя интерпретировать остальные: 5 ошибок в секунду при 10 rps и при 1000 rps — разные ситуации.
- **Errors** (доля ответов 5xx) — надёжность. Взята именно **доля**, а не абсолютное число: 1% ошибок при высоком трафике и 50% при низком — принципиально разные состояния, абсолютный счётчик их не различает.
- **Duration** — воспринимаемая пользователем скорость. Показаны **перцентили p50 / p95 / p99**, а не среднее: среднее маскирует «хвост». p50 (медиана) — типичный запрос; p95 — опыт худших 5% запросов, по нему обычно и судят о деградации; p99 — редкие выбросы.

RED удобен тем, что не зависит от предметной области сервиса — одинаково применим к API, веб-приложению, прокси. Именно поэтому в каждой следующей лабе курса требуется настроить мониторинг, и эти же три метрики переиспользуются.

---

## Обоснование выбора алертов

Три правила — по одному на каждую букву RED, каждое покрывает свой сценарий деградации.

### HighErrorRate — доля 5xx > 10%, `severity: critical`

Прямые отказы: пользователь видит ошибки вместо результата. Порог **10%** выбран так, чтобы единичные 5xx (сетевые сбои, рестарты подов, кратковременные проблемы зависимостей) не будили дежурного — они неизбежны и не являются инцидентом. Устойчивое превышение 10% означает сломанную функциональность. `severity: critical` — требует немедленной реакции.

### RequestSpike — Rate > 8 rps, `severity: warning`

Резкий рост трафика: наплыв пользователей, зациклившийся клиент, бот, нагрузка DDoS-подобного характера. Сам по себе не инцидент, но требует внимания — успеет ли сервис, хватит ли ресурсов, не пора ли масштабироваться. `severity: warning` — «посмотреть», а не «тушить». Порог **8 rps** подобран относительно базовой нагрузки демо-сервиса (в покое ≈ 0 rps, кнопка «медленные» даёт ≈ 0.5 rps, кнопка «всплеск» — десятки rps). В реальном проекте порог ставят от исторического baseline, например ×3 от обычного пикового трафика.

### HighLatency — p95 > 1.5 c, `severity: warning`

Сервис «тормозит»: деградация зависимостей (БД, внешний API), нехватка CPU, блокировки, рост очереди. Порог **1.5 секунды** — граница, за которой отклик ощущается пользователем как медленный. Берётся **p95**, чтобы заметить проблему на «хвосте» раньше, чем она затронет большинство запросов. `severity: warning` — пользователю неприятно, но сервис ещё отвечает.

### Общее: `for: 30s`

У всех трёх правил условие должно держаться 30 секунд подряд, только тогда `PENDING → FIRING`. Это убирает ложные срабатывания на секундных пиках (один медленный запрос, один всплеск из-за деплоя).

### Методика проверки

Каждый алерт провоцируется отдельной кнопкой по одному, с паузами 2–3 минуты между провокациями. Одновременная нагрузка искажает картину: поток успешных быстрых запросов от кнопки «всплеск» разбавляет долю ошибок (знаменатель растёт) и снижает общий p95, из-за чего `HighErrorRate` и `HighLatency` могут не сработать.

Наблюдаемые значения при срабатывании: `HighErrorRate` — 1.0 (100%), `HighLatency` — 2.91 c, `RequestSpike` — 45.9 rps. Все заметно выше порогов.

---

## Выводы

**Что дал каждый из трёх «столпов» наблюдаемости:**

- **Метрики** отвечают на вопрос «что-то не так и насколько», но не «почему». По графику видно, что доля ошибок выросла, но не видно, какой запрос падает и на какой строке кода.
- **Логи** дают текст конкретного события и, что важно, `trace_id`. Но по ним тяжело увидеть общую динамику и разложить запрос по времени.
- **Трейсы** показывают путь одного запроса и на каком шаге потрачено время — то, что не видно ни в метриках, ни в логах.

**Главное — связка через `trace_id`.** Именно она превращает три отдельных инструмента в один рабочий процесс: на дашборде замечаешь аномалию → в Loki находишь конкретную ошибочную строку и её `trace_id` → в Jaeger по этому `trace_id` открываешь ровно этот запрос и видишь, на каком спане и с какой ошибкой он упал. В работе это было проверено вручную: `trace_id` из строки лога `0c35140ad507593d0bf123677f4f70a1` открыл в Jaeger тот же самый запрос со статусом error.

**Что было сложно:**

- Развести провокацию алертов по времени — при одновременной нагрузке метрики искажают друг друга.
- Понять, что пустая панель Error Rate («No data») — это нормальное состояние «ошибок не было», а не поломка дашборда.
- Осознать, что вложенные спаны и пометку ошибки в трейсе нужно расставлять в коде вручную — авто-инструментирование даёт только спан на весь запрос.
- Настроить Loki/Promtail так, чтобы `trace_id` из JSON-лога стал доступен для поиска (pipeline-стадия `json` в конфиге Promtail).

**Чего не хватает для продакшена:**

- OpenTelemetry Collector как буфер между сервисом и Jaeger (отвязывает приложение от адреса и формата бэкенда трейсов).
- Хранение метрик и логов с ретеншеном, на постоянных дисках, с бэкапами (сейчас данные Loki/Jaeger живут в контейнере и теряются при `docker compose down -v`).
- Маршрутизация алертов по `severity` в Alertmanager: `critical` — звонок/пейджер, `warning` — сообщение в чат.
- Дашборды с разбивкой по эндпоинтам и по кодам ответа, а не только агрегат по сервису.

---

## Использованные инструменты

- **Языки и библиотеки:** Python 3.12, FastAPI, uvicorn, `prometheus_client`, `opentelemetry-sdk` + инструментирование FastAPI/httpx, экспортёр OTLP/gRPC.
- **Инфраструктура:** Docker, Docker Compose; Prometheus, Alertmanager, Grafana, Loki, Promtail, Jaeger.
- **Работа над лабой:** согласно политике курса (`AGENTS.md` / `CLAUDE.md`) использовался AI-ассистент — для генерации каркаса конфигов и кода сервиса и для пошагового разбора незнакомых компонентов. Разбор устройства каждого элемента стека, назначение файлов, PromQL-выражений, смысл метрик и обоснование порогов алертов прорабатывались отдельно и отражены в тексте этого отчёта.
