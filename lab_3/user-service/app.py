import json
import os
import random
import uuid
from datetime import datetime, timezone

from confluent_kafka import Producer
from flask import Flask, redirect, render_template_string, url_for

KAFKA_BOOTSTRAP_SERVERS = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
KAFKA_TOPIC = os.environ["KAFKA_TOPIC"]
INSTANCE_NAME = os.environ.get("INSTANCE_NAME", "user-service")

app = Flask(__name__)
producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})

# заказы храним только в памяти процесса - для наглядности на странице,
# не как источник истины (источник истины - сама Kafka)
sent_orders = []

CATALOG = ["кофе", "молоко", "хлеб", "яблоки", "сыр", "чай", "печенье"]

PAGE = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>user-service</title>
  <style>
    body { font-family: sans-serif; max-width: 900px; margin: 40px auto; }
    button { font-size: 16px; padding: 10px 20px; cursor: pointer; }
    table { border-collapse: collapse; width: 100%; margin-top: 20px; }
    th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
    th { background: #f2f2f2; }
    h1 { margin-bottom: 4px; }
    .sub { color: #666; margin-top: 0; }
  </style>
</head>
<body>
  <h1>user-service</h1>
  <p class="sub">инстанс: {{ instance }} · топик: {{ topic }}</p>
  <form method="post" action="{{ url_for('create_order') }}">
    <button type="submit">Создать заказ</button>
  </form>
  <table>
    <tr><th>Order ID</th><th>Товары</th><th>Партиция</th><th>Offset</th><th>Время</th></tr>
    {% for o in orders %}
    <tr>
      <td>{{ o.order_id }}</td>
      <td>{{ o["items"] | join(", ") }}</td>
      <td>{{ o.partition }}</td>
      <td>{{ o.offset }}</td>
      <td>{{ o.created_at }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(
        PAGE, orders=list(reversed(sent_orders)), instance=INSTANCE_NAME, topic=KAFKA_TOPIC
    )


@app.post("/orders")
def create_order():
    order_id = str(uuid.uuid4())[:8]
    order = {
        "order_id": order_id,
        "items": random.sample(CATALOG, k=random.randint(1, 3)),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    delivery = {}

    def on_delivery(err, msg):
        if err is not None:
            delivery["error"] = str(err)
        else:
            delivery["partition"] = msg.partition()
            delivery["offset"] = msg.offset()

    producer.produce(
        topic=KAFKA_TOPIC,
        key=order_id.encode("utf-8"),
        value=json.dumps(order, ensure_ascii=False).encode("utf-8"),
        callback=on_delivery,
    )
    producer.flush(10)  # ждём подтверждения от брокера, чтобы показать partition/offset

    order["partition"] = delivery.get("partition", "?")
    order["offset"] = delivery.get("offset", delivery.get("error", "?"))
    sent_orders.append(order)

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
