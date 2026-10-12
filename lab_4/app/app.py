import os
import random
import threading
import time

import psycopg2
from flask import Flask, redirect, render_template_string, request, url_for

PRIMARY_HOST = os.environ["PRIMARY_HOST"]
REPLICA_HOST = os.environ["REPLICA_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
LOAD_ROWS = int(os.environ.get("LOAD_ROWS", "3000"))
LOAD_BATCH = int(os.environ.get("LOAD_BATCH", "30"))
LOAD_PAUSE = float(os.environ.get("LOAD_PAUSE", "0.02"))

app = Flask(__name__)

WORDS = ["молоко", "хлеб", "сыр", "кофе", "чай", "яблоки", "печенье", "масло", "йогурт"]
load_state = {"running": False, "done": 0, "total": 0, "error": None}
load_lock = threading.Lock()
flash = {"text": None, "error": False}


def connect(host):
    return psycopg2.connect(
        host=host,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=3,
    )


def insert_notes(count):
    # запись ВСЕГДА идёт в primary
    conn = connect(PRIMARY_HOST)
    try:
        with conn, conn.cursor() as cur:
            for _ in range(count):
                cur.execute(
                    "INSERT INTO notes (title, body) VALUES (%s, %s)",
                    (f"заметка про {random.choice(WORDS)}", "x" * 200),
                )
    finally:
        conn.close()


def load_worker():
    # пачка записей батчами по LOAD_BATCH, каждый батч - отдельный коммит
    try:
        conn = connect(PRIMARY_HOST)
        try:
            while load_state["done"] < load_state["total"]:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO notes (title, body) "
                        "SELECT 'нагрузка #' || g, repeat('x', 200) FROM generate_series(1, %s) g",
                        (LOAD_BATCH,),
                    )
                load_state["done"] += LOAD_BATCH
                time.sleep(LOAD_PAUSE)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - показываем ошибку на странице
        load_state["error"] = str(exc).strip()
    finally:
        load_state["running"] = False


def read_state():
    """Читаем всё, что показываем на странице. Чтение идёт с реплики, статистика репликации - с primary."""
    info = {
        "replica_host": REPLICA_HOST,
        "primary_host": PRIMARY_HOST,
        "notes": [],
        "replica_count": None,
        "replica_in_recovery": None,
        "replica_error": None,
        "primary_count": None,
        "primary_error": None,
        "replication": [],
    }
    try:
        conn = connect(REPLICA_HOST)
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT pg_is_in_recovery()")
                info["replica_in_recovery"] = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM notes")
                info["replica_count"] = cur.fetchone()[0]
                cur.execute("SELECT id, title, created_at FROM notes ORDER BY id DESC LIMIT 15")
                info["notes"] = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        info["replica_error"] = str(exc).strip()

    try:
        conn = connect(PRIMARY_HOST)
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM notes")
                info["primary_count"] = cur.fetchone()[0]
                cur.execute(
                    "SELECT application_name, state, sync_state, "
                    "pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes, "
                    "round(EXTRACT(EPOCH FROM replay_lag)::numeric, 3) AS replay_lag_s "
                    "FROM pg_stat_replication"
                )
                info["replication"] = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        info["primary_error"] = str(exc).strip()
    return info


PAGE = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>notes-service</title>
  {% if auto %}<meta http-equiv="refresh" content="1; url=/?auto=1">{% endif %}
  <style>
    body { font-family: sans-serif; max-width: 980px; margin: 30px auto; }
    h1 { margin-bottom: 2px; }
    .sub { color: #666; margin-top: 0; }
    form { display: inline; }
    button { font-size: 15px; padding: 8px 16px; cursor: pointer; margin-right: 6px; }
    .box { border: 1px solid #ccc; border-radius: 6px; padding: 10px 14px; margin: 14px 0; background: #fafafa; }
    .err { background: #fdecea; border-color: #f5a9a3; color: #8a1c14; }
    .ok { background: #eaf7ea; border-color: #9bd09b; }
    .warn { background: #fff4e0; border-color: #f0c070; }
    table { border-collapse: collapse; width: 100%; margin-top: 8px; }
    th, td { border: 1px solid #ccc; padding: 5px 9px; text-align: left; }
    th { background: #f2f2f2; }
    a { margin-left: 10px; }
  </style>
</head>
<body>
  <h1>notes-service</h1>
  <p class="sub">запись → <b>{{ s.primary_host }}</b> · чтение → <b>{{ s.replica_host }}</b></p>

  <form method="post" action="/create"><button type="submit">Создать запись</button></form>
  <form method="post" action="/load"><button type="submit">Налить нагрузку ({{ load_rows }} записей)</button></form>
  <a href="/">Обновить</a>
  {% if auto %}<a href="/">Выключить автообновление</a>{% else %}<a href="/?auto=1">Автообновление (1 с)</a>{% endif %}

  {% if message %}<div class="box {{ 'err' if message_error else 'ok' }}">{{ message }}</div>{% endif %}

  {% if load.running or load.done %}
  <div class="box {{ 'warn' if load.running else 'ok' }}">
    Нагрузка: {{ [load.done, load.total]|min }} / {{ load.total }} {{ '(идёт...)' if load.running else '(завершена)' }}
    {% if load.error %}<br><b>Ошибка нагрузки:</b> {{ load.error }}{% endif %}
  </div>
  {% endif %}

  <div class="box {{ 'err' if (s.primary_error or s.replica_error) else ('warn' if lag and lag > 0 else 'ok') }}">
    <b>Записей в primary:</b>
    {% if s.primary_error %}<span>недоступен — {{ s.primary_error }}</span>{% else %}{{ s.primary_count }}{% endif %}
    <br>
    <b>Записей на реплике (то, что видит чтение):</b>
    {% if s.replica_error %}<span>недоступна — {{ s.replica_error }}</span>{% else %}{{ s.replica_count }}{% endif %}
    {% if s.replica_in_recovery is not none %}
      <small>(узел чтения {{ 'в режиме реплики' if s.replica_in_recovery else 'САМ ЯВЛЯЕТСЯ PRIMARY' }})</small>
    {% endif %}
    {% if lag is not none %}
    <br><b>Отставание реплики: {{ lag }} записей</b>
    {% endif %}
    {% for r in s.replication %}
    <br><small>pg_stat_replication: {{ r[0] }}, state={{ r[1] }}, sync={{ r[2] }}, lag={{ r[3] }} байт WAL, replay_lag={{ r[4] }} с</small>
    {% endfor %}
    {% if not s.replication and not s.primary_error %}
    <br><small>pg_stat_replication пуст: к primary не подключено ни одной реплики</small>
    {% endif %}
  </div>

  <h3>Записи (последние 15, чтение с реплики)</h3>
  <table>
    <tr><th>id</th><th>Заголовок</th><th>Создана</th></tr>
    {% for n in s.notes %}
    <tr><td>{{ n[0] }}</td><td>{{ n[1] }}</td><td>{{ n[2].strftime('%H:%M:%S.%f')[:-3] }}</td></tr>
    {% endfor %}
  </table>
</body>
</html>
"""


def render():
    message, message_error = flash["text"], flash["error"]
    flash["text"], flash["error"] = None, False
    s = read_state()
    lag = None
    if s["primary_count"] is not None and s["replica_count"] is not None:
        lag = s["primary_count"] - s["replica_count"]
    return render_template_string(
        PAGE,
        s=s,
        lag=lag,
        message=message,
        message_error=message_error,
        auto=request.args.get("auto") == "1",
        load=load_state,
        load_rows=LOAD_ROWS,
    )


@app.get("/")
def index():
    return render()


@app.post("/create")
def create():
    try:
        insert_notes(1)
        flash.update(text="Запись создана в primary.", error=False)
    except Exception as exc:  # noqa: BLE001
        flash.update(text=f"Запись НЕ прошла: {str(exc).strip()}", error=True)
    return redirect(url_for("index"))


@app.post("/load")
def load():
    with load_lock:
        if load_state["running"]:
            flash.update(text="Нагрузка уже идёт.", error=True)
            return redirect(url_for("index", auto=1))
        load_state.update(running=True, done=0, total=LOAD_ROWS, error=None)
    threading.Thread(target=load_worker, daemon=True).start()
    flash.update(text="Нагрузка запущена: записи льются в primary, страница обновляется сама раз в секунду.", error=False)
    return redirect(url_for("index", auto=1))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
