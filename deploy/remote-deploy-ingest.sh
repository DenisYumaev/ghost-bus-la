#!/usr/bin/env bash
# Runs ON THE VM, as root, through SSM Run Command (sent by scripts/deploy_ingest.py).
# Inputs (environment): SHA (git SHA to deploy), BUCKET (data bucket), COMPOSE_B64 (the
# compose file, base64). Deploys the image tagged SHA, waits for Docker to report it healthy,
# and rolls back to the previously deployed SHA if it doesn't become healthy (infra spec, 6).
set -euo pipefail

: "${SHA:?}" "${BUCKET:?}" "${COMPOSE_B64:?}"
DIR=/opt/ghost-bus-la
COMPOSE="docker compose --project-name ghost-bus-la -f $DIR/compose.ingest.yml"
HEALTH_WAIT_S=180

mkdir -p "$DIR"
echo "$COMPOSE_B64" | base64 -d > "$DIR/compose.ingest.yml"
PREVIOUS=$(cat "$DIR/ingest.tag" 2>/dev/null || true)

deploy() {
  printf 'INGEST_TAG=%s\nGHOSTBUS_BUCKET=%s\n' "$1" "$BUCKET" > "$DIR/.env"
  $COMPOSE --env-file "$DIR/.env" pull --quiet
  $COMPOSE --env-file "$DIR/.env" up --detach --remove-orphans
}

wait_healthy() {
  local waited=0 status
  while [ "$waited" -lt "$HEALTH_WAIT_S" ]; do
    status=$(docker inspect --format '{{.State.Health.Status}}' \
      "$($COMPOSE --env-file "$DIR/.env" ps --quiet ingest)" 2>/dev/null || echo missing)
    echo "health after ${waited}s: $status"
    [ "$status" = healthy ] && return 0
    [ "$status" = unhealthy ] && return 1
    sleep 10
    waited=$((waited + 10))
  done
  return 1
}

echo "deploying $SHA (previous: ${PREVIOUS:-none})"
deploy "$SHA"
if wait_healthy; then
  echo "$SHA" > "$DIR/ingest.tag"
  echo "RESULT: deployed $SHA"
  $COMPOSE --env-file "$DIR/.env" logs --tail 5 ingest
  exit 0
fi

echo "RESULT: $SHA did not become healthy; recent logs:"
$COMPOSE --env-file "$DIR/.env" logs --tail 30 ingest || true
if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$SHA" ]; then
  echo "rolling back to $PREVIOUS"
  deploy "$PREVIOUS"
  if wait_healthy; then echo "RESULT: rolled back to $PREVIOUS"; else echo "RESULT: rollback ALSO unhealthy"; fi
fi
exit 1
