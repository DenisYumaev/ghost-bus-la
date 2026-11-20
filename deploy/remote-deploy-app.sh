#!/usr/bin/env bash
# Runs ON THE VM, as root, through SSM Run Command (sent by scripts/deploy_app.py).
# Inputs (environment): SHA (the API image's git SHA), API_DOMAIN, SITE_DOMAIN, COMPOSE_B64 and
# CADDY_B64 (the compose file and Caddyfile, base64). No secret travels in the command: the
# database passwords are read here from SSM with the instance role, written to a root-only .env,
# and never echoed.
#
# Steps (infra spec, section 6): Postgres up, migrations and role passwords, then the API, then
# Caddy. The API must report healthy and reach the database; otherwise the previous SHA is
# redeployed WITHOUT migrating: migrations are expand-only, so the previous code runs on the new
# schema, and the old image's Alembic wouldn't know the new revision anyway.
# Ingest is a separate compose project and is never touched here (hard rule 3).
#
# Every step is checked explicitly (`|| return 1`): bash ignores `set -e` inside a function
# called from an `if` or `&&`, which is how deploy() is called.
set -euo pipefail

: "${SHA:?}" "${API_DOMAIN:?}" "${SITE_DOMAIN:?}" "${COMPOSE_B64:?}" "${CADDY_B64:?}"
DIR=${APP_DIR:-/opt/ghost-bus-la/app} # overridable only for the script's own test
REGION=us-west-2
COMPOSE="docker compose --project-name ghost-bus-la-app -f $DIR/compose.app.yml --env-file $DIR/.env"
HEALTH_WAIT_S=${HEALTH_WAIT_S:-120}
POLL_S=${POLL_S:-5}

mkdir -p "$DIR"
echo "$COMPOSE_B64" | base64 -d > "$DIR/compose.app.yml"
echo "$CADDY_B64" | base64 -d > "$DIR/Caddyfile"
CADDYFILE_SHA=$(sha256sum "$DIR/Caddyfile" | cut -c1-16) # a change recreates caddy
PREVIOUS=$(cat "$DIR/api.tag" 2>/dev/null || true)

# The AWS CLI isn't in the base image; the snap is AWS's own build.
command -v aws >/dev/null || snap install aws-cli --classic >/dev/null

secret() {
  aws ssm get-parameter --region "$REGION" --with-decryption --name "/ghost-bus-la/db/$1" \
    --query Parameter.Value --output text
}

write_env() {
  local postgres api pipeline
  postgres=$(secret owner-password) || return 1
  api=$(secret api-password) || return 1
  pipeline=$(secret pipeline-password) || return 1
  if [ -z "$postgres" ] || [ -z "$api" ] || [ -z "$pipeline" ]; then
    echo "a database password is empty in SSM (run make init-secrets)"
    return 1
  fi
  (
    umask 077
    printf 'API_TAG=%s\nAPI_DOMAIN=%s\nSITE_DOMAIN=%s\nCADDYFILE_SHA=%s\nPOSTGRES_PASSWORD=%s\nAPI_DB_PASSWORD=%s\nPIPELINE_DB_PASSWORD=%s\n' \
      "$1" "$API_DOMAIN" "$SITE_DOMAIN" "$CADDYFILE_SHA" "$postgres" "$api" "$pipeline" > "$DIR/.env"
  ) || return 1
}

# deploy <sha> [migrate|no-migrate]
deploy() {
  write_env "$1" || return 1
  $COMPOSE pull --quiet || return 1
  $COMPOSE up --detach --wait postgres || return 1
  if [ "${2:-migrate}" = migrate ]; then
    $COMPOSE run --rm migrate || { echo "migrate failed"; return 1; }
  fi
  $COMPOSE up --detach --remove-orphans api caddy || return 1
}

# Healthy container, and /readyz either ready or "stale" (the database answered; fresh data is
# the pipeline's job). "Database unavailable" or no answer fails the deploy.
api_ready() {
  local waited=0 status answer
  while [ "$waited" -lt "$HEALTH_WAIT_S" ]; do
    status=$(docker inspect --format '{{.State.Health.Status}}' "$($COMPOSE ps --quiet api)" 2>/dev/null || echo missing)
    if [ "$status" = healthy ]; then
      answer=$($COMPOSE exec -T api python -c "
import json, urllib.error, urllib.request
try:
    r = urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3); print('ready')
except urllib.error.HTTPError as e:
    print(json.load(e).get('title', 'error'))
" 2>/dev/null || echo unreachable)
      echo "api after ${waited}s: $status, readyz: $answer"
      case "$answer" in ready | "Serving data is stale") return 0 ;; esac
    else
      echo "api after ${waited}s: $status"
      [ "$status" = unhealthy ] && return 1
    fi
    sleep "$POLL_S"
    waited=$((waited + POLL_S))
  done
  return 1
}

# Reported, not gated on: before DNS points here, or while Let's Encrypt is still issuing, the
# public URL can't answer yet. Resolved to this host, so it checks Caddy and the certificate.
tls_report() {
  local code
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
    --resolve "$API_DOMAIN:443:127.0.0.1" "https://$API_DOMAIN/healthz" 2>/dev/null || true)
  echo "TLS check https://$API_DOMAIN/healthz: ${code:-no answer}"
}

echo "deploying API $SHA (previous: ${PREVIOUS:-none})"
if deploy "$SHA" migrate && api_ready; then
  echo "$SHA" > "$DIR/api.tag"
  echo "RESULT: deployed $SHA"
  $COMPOSE ps --format '{{.Service}} {{.Status}}' || true
  tls_report
  exit 0
fi

echo "RESULT: $SHA failed; recent API logs:"
$COMPOSE logs --tail 30 api 2>/dev/null || true
if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$SHA" ]; then
  echo "rolling back to $PREVIOUS (no migration)"
  if deploy "$PREVIOUS" no-migrate && api_ready; then
    echo "RESULT: rolled back to $PREVIOUS"
  else
    echo "RESULT: rollback ALSO failed"
  fi
fi
exit 1
