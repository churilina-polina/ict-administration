"""
Декларативное создание/обновление топика Kafka - часть конфигурации,
а не ручная команда. Запускается один раз при старте стека (сервис
topic-init в docker-compose), создаёт топик, если его нет, и подгоняет
число партиций и retention под текущие переменные окружения, если топик
уже существует.

Важно: Kafka не умеет уменьшать число партиций существующего топика
(нет операции, обратной create_partitions) - это осознанное ограничение,
а не баг скрипта. Скрипт такую ситуацию просто замечает и объясняет в логе.
"""

import os
import sys
import time

from confluent_kafka.admin import (
    AdminClient,
    AlterConfigOpType,
    ConfigEntry,
    ConfigResource,
    NewPartitions,
    NewTopic,
)

BOOTSTRAP_SERVERS = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
TOPIC_NAME = os.environ["TOPIC_NAME"]
TOPIC_PARTITIONS = int(os.environ["TOPIC_PARTITIONS"])
TOPIC_REPLICATION_FACTOR = int(os.environ["TOPIC_REPLICATION_FACTOR"])
TOPIC_RETENTION_MS = os.environ["TOPIC_RETENTION_MS"]
# сегмент лога должен закрыться (roll), прежде чем retention сможет его удалить -
# при низком потоке сообщений открытый сегмент сам не закроется неделями,
# поэтому держим TOPIC_SEGMENT_MS заметно меньше TOPIC_RETENTION_MS
TOPIC_SEGMENT_MS = os.environ.get("TOPIC_SEGMENT_MS", TOPIC_RETENTION_MS)
DESIRED_CONFIG = {"retention.ms": TOPIC_RETENTION_MS, "segment.ms": TOPIC_SEGMENT_MS}

admin = AdminClient({"bootstrap.servers": BOOTSTRAP_SERVERS})


def wait_for_kafka(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            admin.list_topics(timeout=5)
            print("Kafka is ready", flush=True)
            return
        except Exception as exc:  # noqa: BLE001 - брокер ещё не поднялся
            print(f"waiting for kafka... ({exc})", flush=True)
            time.sleep(2)
    print("Kafka did not become ready in time", flush=True)
    sys.exit(1)


def create_or_update_topic():
    metadata = admin.list_topics(timeout=10)

    if TOPIC_NAME not in metadata.topics:
        new_topic = NewTopic(
            TOPIC_NAME,
            num_partitions=TOPIC_PARTITIONS,
            replication_factor=TOPIC_REPLICATION_FACTOR,
            config=DESIRED_CONFIG,
        )
        futures = admin.create_topics([new_topic])
        futures[TOPIC_NAME].result(timeout=30)
        print(
            f"Created topic {TOPIC_NAME}: "
            f"partitions={TOPIC_PARTITIONS}, replication_factor={TOPIC_REPLICATION_FACTOR}, "
            f"config={DESIRED_CONFIG}",
            flush=True,
        )
        return

    print(f"Topic {TOPIC_NAME} already exists, checking config...", flush=True)
    current_partitions = len(metadata.topics[TOPIC_NAME].partitions)

    if TOPIC_PARTITIONS > current_partitions:
        futures = admin.create_partitions(
            [NewPartitions(TOPIC_NAME, TOPIC_PARTITIONS)]
        )
        futures[TOPIC_NAME].result(timeout=30)
        print(
            f"Increased partitions of {TOPIC_NAME}: {current_partitions} -> {TOPIC_PARTITIONS}",
            flush=True,
        )
    elif TOPIC_PARTITIONS < current_partitions:
        print(
            f"TOPIC_PARTITIONS={TOPIC_PARTITIONS} is less than current "
            f"({current_partitions}) - Kafka cannot shrink partitions of an "
            f"existing topic, skipping. To go down, create a new topic with "
            f"fewer partitions and switch producer/consumer to it.",
            flush=True,
        )
    else:
        print(f"Partitions already at {current_partitions}, nothing to do", flush=True)

    resource = ConfigResource(ConfigResource.Type.TOPIC, TOPIC_NAME)
    current_config = admin.describe_configs([resource])[resource].result(timeout=30)

    to_update = {
        name: value
        for name, value in DESIRED_CONFIG.items()
        if current_config[name].value != value
    }
    if to_update:
        # incremental_alter_configs (не alter_configs!) - легаси alter_configs
        # заменяет ВЕСЬ набор динамических конфигов ресурса, а не мержит его,
        # и предыдущим запуском тихо стирает конфиги, которые сейчас не меняются
        alter_resource = ConfigResource(
            ConfigResource.Type.TOPIC,
            TOPIC_NAME,
            incremental_configs=[
                ConfigEntry(name, value, incremental_operation=AlterConfigOpType.SET)
                for name, value in to_update.items()
            ],
        )
        admin.incremental_alter_configs([alter_resource])[alter_resource].result(timeout=30)
        for name, value in to_update.items():
            print(
                f"Updated {name} of {TOPIC_NAME}: {current_config[name].value} -> {value}",
                flush=True,
            )
    else:
        print("retention.ms/segment.ms already up to date, nothing to do", flush=True)


if __name__ == "__main__":
    wait_for_kafka()
    create_or_update_topic()
    print("topic-init done", flush=True)
