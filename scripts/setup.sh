#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

gpu=false
skip_model_pull=false
for argument in "$@"; do
  case "$argument" in
    --gpu) gpu=true ;;
    --skip-model-pull) skip_model_pull=true ;;
    *) echo "Unknown option: $argument" >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || {
  echo "Docker with Compose v2 is required." >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  echo "Docker is installed but the engine is unavailable. Start it, then retry." >&2
  exit 1
}

compose_files=(-f docker-compose.yml -f docker-compose.local-ai.yml)
if [[ "$gpu" == true ]]; then
  compose_files+=(-f docker-compose.gpu.yml)
fi
compose() { docker compose "${compose_files[@]}" "$@"; }

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from safe local defaults."
fi

echo "Starting PostgreSQL and the self-contained Ollama service..."
compose up -d db ollama --wait --wait-timeout 180

if [[ "$skip_model_pull" == false ]]; then
  echo "Provisioning qwen3.5:4b. The first download is several gigabytes..."
  compose exec -T ollama ollama pull qwen3.5:4b
  echo "Provisioning qwen3-embedding:0.6b..."
  compose exec -T ollama ollama pull qwen3-embedding:0.6b
fi

echo "Building and starting DocIntel AI..."
compose up -d --build --wait --wait-timeout 600

curl --fail --silent --show-error http://localhost:8000/health/ready >/dev/null
curl --fail --silent --show-error http://localhost:3000 >/dev/null

cat <<EOF

DocIntel AI is ready.
Application: http://localhost:3000
API docs:    http://localhost:8000/docs
Samples:     $repo_root/sample-documents

Stop without deleting data:
docker compose -f docker-compose.yml -f docker-compose.local-ai.yml down
EOF
