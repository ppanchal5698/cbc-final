#!/usr/bin/env bash
# Auth + replica set requires a keyFile. Bind mounts from Windows often lack
# mode 400 / mongodb ownership, so copy into the container FS before mongod.
set -euo pipefail
KEY_SRC="${MONGO_KEYFILE_SRC:-/mongo-keyfile}"
KEY_DST="/data/keyfile"
if [ -f "$KEY_SRC" ]; then
  cp "$KEY_SRC" "$KEY_DST"
else
  head -c 756 /dev/urandom | base64 > "$KEY_DST"
fi
chmod 400 "$KEY_DST"
chown mongodb:mongodb "$KEY_DST"
exec docker-entrypoint.sh mongod --replSet rs0 --bind_ip_all --keyFile "$KEY_DST"
