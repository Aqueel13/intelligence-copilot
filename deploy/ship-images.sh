#!/usr/bin/env bash
# For small servers (e.g. Oracle's 1 GB E2.1.Micro), where building the images is too slow or
# runs out of memory: build them on this machine and stream them to the server over SSH.
# The server's CPU architecture must match this machine's (both x86_64, or both arm64).
#
#   deploy/ship-images.sh ubuntu@<server-ip>
#
# Then on the server: make prod-start (starts the stack without building).
set -euo pipefail
target=${1:?usage: deploy/ship-images.sh ubuntu@<server-ip>}
cd "$(dirname "$0")/.."

remote_arch=$(ssh "$target" uname -m)
if [ "$remote_arch" != "$(uname -m)" ]; then
  echo "Server is $remote_arch, this machine is $(uname -m): build on the server instead." >&2
  exit 1
fi

echo "== building images (DOMAIN is not needed to build)"
DOMAIN=build.invalid ACME_EMAIL=x POSTGRES_PASSWORD=x LLM_DEFAULT_MODEL=x GROQ_API_KEY=x \
  OPERATIONS_MCP_BACKEND_TOKEN=x ENTERPRISE_API_KEY=x \
  docker compose -f docker-compose.prod.yml --env-file /dev/null build migrate caddy

echo "== sending to $target (compressed; a few hundred MB)"
docker save watchdog-backend:prod watchdog-web:prod | gzip -1 | ssh "$target" 'gunzip | docker load'
echo "Done. On the server: cd ~/intelligence-copilot && make prod-start"
