#!/usr/bin/env bash
# Idempotent single-node rs0 init for local compose.
set -euo pipefail
AUTH=( -u cbc -p "${MONGO_ROOT_PASSWORD:-cbc_local_dev}" --authenticationDatabase admin --host mongo:27017 )
mongosh --quiet "${AUTH[@]}" --eval '
  try {
    if (rs.status().ok) { quit(0); }
  } catch (e) {}
  rs.initiate({_id: "rs0", members: [{_id: 0, host: "mongo:27017"}]});
'
for i in $(seq 1 30); do
  state=$(mongosh --quiet "${AUTH[@]}" --eval 'try { print(rs.status().myState) } catch (e) { print(0) }' || true)
  if [ "$state" = "1" ]; then
    exit 0
  fi
  sleep 1
done
echo "replica set did not become PRIMARY" >&2
exit 1
