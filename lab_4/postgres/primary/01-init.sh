#!/bin/bash
# Выполняется один раз при первом создании тома primary (docker-entrypoint-initdb.d)
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  -- пользователь для репликации: только REPLICATION, больше ничего
  CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD}';

  -- пользователь для мониторинга: pg_monitor - встроенная роль "только читать статистику"
  CREATE ROLE exporter WITH LOGIN PASSWORD '${EXPORTER_PASSWORD}';
  GRANT pg_monitor TO exporter;

  -- пользователь сервиса: принцип наименьших привилегий (см. лекцию 4)
  CREATE ROLE app WITH LOGIN PASSWORD '${APP_PASSWORD}';

  CREATE TABLE notes (
    id         BIGSERIAL PRIMARY KEY,
    title      TEXT        NOT NULL,
    body       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  GRANT SELECT, INSERT ON notes TO app;
  GRANT USAGE ON SEQUENCE notes_id_seq TO app;
  -- чтобы сервис мог показывать статистику репликации (pg_stat_replication) - только чтение статистики
  GRANT pg_read_all_stats TO app;
EOSQL

# по умолчанию pg_hba.conf не пускает replicator на "виртуальную" базу replication
echo "host replication replicator all scram-sha-256" >> "$PGDATA/pg_hba.conf"
