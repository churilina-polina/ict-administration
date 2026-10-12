#!/bin/bash
# Точка входа реплики: если данных ещё нет - снимаем полную копию с primary
# (pg_basebackup -R сам кладёт standby.signal и primary_conninfo), потом запускаем обычный postgres.
set -e

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "standby: каталог данных пуст -> pg_basebackup с $UPSTREAM_HOST"
  until pg_isready -h "$UPSTREAM_HOST" -p 5432 -U "$REPLICATION_USER"; do
    echo "standby: жду primary..."
    sleep 2
  done

  mkdir -p "$PGDATA"
  chown postgres:postgres "$PGDATA"
  chmod 700 "$PGDATA"

  # -R  записать настройки реплики, -X stream  тянуть WAL во время копирования,
  # -C -S  создать physical replication slot, чтобы primary не удалял WAL, который реплика ещё не получила
  gosu postgres env PGPASSWORD="$REPLICATION_PASSWORD" \
    pg_basebackup -h "$UPSTREAM_HOST" -U "$REPLICATION_USER" -D "$PGDATA" \
    -R -X stream -C -S standby1 --progress --verbose
  echo "standby: базовая копия готова"
fi

exec docker-entrypoint.sh "$@"
