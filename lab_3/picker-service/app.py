import json
import os
import threading
import time

from confluent_kafka import Consumer
from flask import Flask, render_template_string

KAFKA_BOOTSTRAP_SERVERS = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
KAFKA_TOPIC = os.environ["KAFKA_TOPIC"]
KAFKA_GROUP_ID = os.environ["KAFKA_GROUP_ID"]
INSTANCE_NAME = os.environ.get("INSTANCE_NAME", "picker-service")
PROCESSING_SECONDS = float(os.environ.get("PROCESSING_SECONDS", "2"))

app = Flask(__name__)

lock = threading.Lock()
processed_orders = []  # последние обработанные заказы (для показа на странице)
state = {"status": "стартую...", "assigned_partitions": []}

PAGE = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>{{ instance }}</title>
  <style>
    body { font-family: sans-serif; max-width: 900px; margin: 40px auto; }
    table { border-collapse: collapse; width: 100%; margin-top: 20px; }
    th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
    th { background: #f2f2f2; }
    .status { padding: 10px; background: #eef; border-radius: 6px; }
    h1 { margin-bottom: 4px; }
    .sub { color: #666; margin-top: 0; }
  </style>
  <meta http-equiv="refresh" content="3">
</head>
<body>
  <h1>picker-service</h1>
  <p class="sub">инстанс: {{ instance }} · группа: {{ group }} · топик: {{ topic }}</p>
  <div class="status">
    <b>Статус:</b> {{ status }}<br>
    <b>Назначенные партиции:</b> {{ partitions }}
  </div>
  <table>
    <tr><th>Order ID</th><th>Товары</th><th>Партиция</th><th>Offset</th><th>Инстанс</th></tr>
    {% for o in orders %}
    <tr>
      <td>{{ o.order_id }}</td>
      <td>{{ o["items"] | join(", ") }}</td>
      <td>{{ o.partition }}</td>
      <td>{{ o.offset }}</td>
      <td>{{ o.instance_name }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
"""


@app.get("/")
def index():
    with lock:
        orders = list(reversed(processed_orders[-100:]))
        status = state["status"]
        partitions = ", ".join(str(p) for p in state["assigned_partitions"]) or "(нет)"
    return render_template_string(
        PAGE,
        orders=orders,
        instance=INSTANCE_NAME,
        group=KAFKA_GROUP_ID,
        topic=KAFKA_TOPIC,
        status=status,
        partitions=partitions,
    )


def on_assign(consumer, partitions):
    with lock:
        state["assigned_partitions"] = sorted(p.partition for p in partitions)


def on_revoke(consumer, partitions):
    with lock:
        state["assigned_partitions"] = []


def consume_loop():
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "group.id": KAFKA_GROUP_ID,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([KAFKA_TOPIC], on_assign=on_assign, on_revoke=on_revoke)

    with lock:
        state["status"] = "жду сообщений"

    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            with lock:
                state["status"] = f"ошибка: {msg.error()}"
            continue

        order = json.loads(msg.value().decode("utf-8"))
        with lock:
            state["status"] = f"собираю заказ {order['order_id']}"

        time.sleep(PROCESSING_SECONDS)  # имитация сборки

        order["partition"] = msg.partition()
        order["offset"] = msg.offset()
        order["instance_name"] = INSTANCE_NAME

        with lock:
            processed_orders.append(order)
            state["status"] = "жду сообщений"

        consumer.commit(message=msg, asynchronous=False)


if __name__ == "__main__":
    threading.Thread(target=consume_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=8001)
