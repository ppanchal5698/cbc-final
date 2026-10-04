#!/usr/bin/env bash
# DocumentDB Local's own entrypoint, plus the read-only user MONGODB_READONLY_URI
# names - created in the background once PostgreSQL inside the container is up.
#
# The gateway's admin cannot create users in this emulator (its PostgreSQL role
# has no CREATEROLE), so the user is made the way the stock entrypoint makes the
# admin: documentdb_api.create_user as the PostgreSQL owner, with the SQL on stdin
# so the password stays out of /proc/<pid>/cmdline. Azure DocumentDB's admin runs
# createUser itself; this leans on the emulator's internals, which is one more
# reason its image tag is pinned. Idempotent: an existing user is left alone.
set -uo pipefail

create_readonly_user() {
  local doc out
  doc=$(jq -cn --arg pwd "${MONGODB_READONLY_PASSWORD:?}" \
    '{createUser: "cbc_catalog_ro", pwd: $pwd, roles: [{role: "readAnyDatabase", db: "admin"}]}')
  for _ in $(seq 1 90); do
    if out=$(printf "SELECT documentdb_api.create_user('%s');\n" "${doc//\'/\'\'}" \
      | psql -p "${POSTGRESQL_PORT:-9712}" -U "${OWNER:-documentdb}" -d postgres -X -tA -v ON_ERROR_STOP=1 2>&1); then
      echo "[cbc] created cbc_catalog_ro (readAnyDatabase)"
      return
    fi
    case "$out" in
      *"already exists"*) echo "[cbc] cbc_catalog_ro already exists"; return ;;
    esac
    sleep 2
  done
  echo "[cbc] could not create cbc_catalog_ro: $out" >&2
}

create_readonly_user &
exec /home/documentdb/gateway/scripts/emulator_entrypoint.sh "$@"
