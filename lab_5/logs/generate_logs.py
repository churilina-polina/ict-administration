#!/usr/bin/env python3
"""
Генератор тестовых логов приложения в формате Elasticsearch Bulk API (NDJSON).

Каждая запись: timestamp, level (INFO/WARN/ERROR), service, message, trace_id.
Время записей - в пределах последних --spread минут от момента запуска, поэтому
запросы вида "за последний час" (now-60m) дают разные результаты на разных диапазонах.

Примеры:
    python3 logs/generate_logs.py                                  # 50 записей в индекс app-logs -> logs/bulk.ndjson
    python3 logs/generate_logs.py --index logs-app --count 40 --out logs/bulk-ilm.ndjson
"""
import argparse
import json
import random
from datetime import datetime, timedelta, timezone

# trace_id "сломанного" заказа: по нему в части 2 ищем всю цепочку событий через сервисы
INCIDENT_TRACE = "4f9a2c1be7d0"

SERVICES = ["auth", "checkout", "catalog", "payment", "delivery"]

MESSAGES = {
    "INFO": [
        ("auth", "User login successful"),
        ("auth", "Access token refreshed for session"),
        ("auth", "Password reset email queued"),
        ("checkout", "Order created"),
        ("checkout", "Cart updated: 3 items"),
        ("checkout", "Checkout started"),
        ("catalog", "Product search completed in 42 ms"),
        ("catalog", "Cache hit for product listing"),
        ("catalog", "Catalog index refreshed"),
        ("payment", "Payment authorized"),
        ("payment", "Refund processed"),
        ("payment", "3-D Secure challenge passed"),
        ("delivery", "Courier assigned to order"),
        ("delivery", "Delivery slot reserved"),
    ],
    "WARN": [
        ("payment", "Slow response from payment gateway (1800 ms), possible timeout"),
        ("checkout", "Retrying request to inventory service (attempt 2)"),
        ("catalog", "Cache miss ratio is high: 63%"),
        ("delivery", "Courier location is outdated, last update 5 minutes ago"),
        ("auth", "Too many failed login attempts from one IP address"),
        ("checkout", "Deprecated API version used by client"),
    ],
    "ERROR": [
        ("payment", "Payment timeout while calling bank gateway"),
        ("payment", "Card declined: insufficient funds"),
        ("checkout", "Failed to reserve stock: timeout waiting for inventory service"),
        ("checkout", "Unhandled exception in order processing: NullPointerException"),
        ("catalog", "Connection refused by search backend"),
        ("auth", "Database connection pool exhausted"),
        ("delivery", "Failed to notify courier: push service unavailable"),
    ],
}

LEVEL_WEIGHTS = [("INFO", 50), ("WARN", 28), ("ERROR", 22)]


def pick_level():
    levels, weights = zip(*LEVEL_WEIGHTS)
    return random.choices(levels, weights=weights, k=1)[0]


def hex_trace():
    return "".join(random.choice("0123456789abcdef") for _ in range(12))


def build_docs(count, spread_minutes, now):
    docs = []

    # 1. Цепочка одного "проблемного" заказа: четыре записи в разных сервисах с одним trace_id
    incident = [
        ("auth", "INFO", "User login successful", 38),
        ("checkout", "INFO", "Checkout started", 37),
        ("payment", "WARN", "Slow response from payment gateway (1800 ms), possible timeout", 36),
        ("payment", "ERROR", "Payment timeout while calling bank gateway", 35),
    ]
    if count >= 10:
        for service, level, message, minutes_ago in incident:
            docs.append((now - timedelta(minutes=minutes_ago, seconds=random.randint(0, 50)), level, service, message, INCIDENT_TRACE))

    # 2. Остальные записи: случайные, с общим пулом trace_id (часть записей делит один trace)
    trace_pool = [hex_trace() for _ in range(max(4, count // 4))]
    while len(docs) < count:
        level = pick_level()
        service, message = random.choice(MESSAGES[level])
        ts = now - timedelta(minutes=random.uniform(1, spread_minutes))
        docs.append((ts, level, service, message, random.choice(trace_pool)))

    docs.sort(key=lambda d: d[0])
    return docs


def main():
    parser = argparse.ArgumentParser(description="Генератор тестовых логов для Elasticsearch Bulk API")
    parser.add_argument("--count", type=int, default=50, help="сколько записей (по умолчанию 50)")
    parser.add_argument("--index", default="app-logs", help="имя индекса или alias, куда пойдут записи")
    parser.add_argument("--out", default="logs/bulk.ndjson", help="файл для результата")
    parser.add_argument("--spread", type=int, default=180, help="за сколько последних минут разбросать записи")
    parser.add_argument("--seed", type=int, default=21, help="seed генератора: одинаковый seed = одинаковый набор сообщений")
    args = parser.parse_args()

    random.seed(args.seed)
    now = datetime.now(timezone.utc)
    docs = build_docs(args.count, args.spread, now)

    with open(args.out, "w", encoding="utf-8") as f:
        for ts, level, service, message, trace_id in docs:
            f.write(json.dumps({"index": {"_index": args.index}}) + "\n")
            f.write(
                json.dumps(
                    {
                        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
                        "level": level,
                        "service": service,
                        "message": message,
                        "trace_id": trace_id,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    by_level = {}
    for _, level, *_ in docs:
        by_level[level] = by_level.get(level, 0) + 1
    print(f"Записано {len(docs)} записей в {args.out} (индекс/alias: {args.index}); по уровням: {by_level}")


if __name__ == "__main__":
    main()
