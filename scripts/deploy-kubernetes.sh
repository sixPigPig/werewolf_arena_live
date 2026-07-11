#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: deploy-kubernetes.sh <staging|production> <image-tag> [--render-dir <directory>]

image-tag must be sha-<40 lowercase hex characters>.
Without --render-dir, the script applies bootstrap configuration, runs and waits
for the database migration, rolls out the application, then runs Admin smoke checks
when ADMIN_BASE_URL is set.
EOF
}

if [[ $# -lt 2 ]]; then
  usage
  exit 2
fi

environment="$1"
image_tag="$2"
shift 2
render_dir=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --render-dir)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      render_dir="$2"
      shift 2
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

case "$environment" in
  staging) namespace="werewolf-staging" ;;
  production) namespace="werewolf-production" ;;
  *) usage; exit 2 ;;
esac

if [[ ! "$image_tag" =~ ^sha-[0-9a-f]{40}$ ]]; then
  echo "invalid immutable image tag: ${image_tag}" >&2
  exit 2
fi

command -v kubectl >/dev/null || { echo "kubectl is required" >&2; exit 2; }

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
overlay_dir="$repo_root/deploy/kubernetes/overlays/$environment"
migration_dir="$overlay_dir/migration"
api_env="$overlay_dir/api.env"

if [[ -n "$render_dir" ]]; then
  mkdir -p "$render_dir"
  output_dir=$(cd "$render_dir" && pwd)
else
  output_dir=$(mktemp -d)
  trap 'rm -rf "$output_dir"' EXIT
fi

render_manifest() {
  local source_dir="$1"
  local output_file="$2"
  kubectl kustomize "$source_dir" | sed "s/sha-REPLACE_ME/${image_tag}/g" > "$output_file"
  if grep -q 'REPLACE_ME\|:latest' "$output_file"; then
    echo "rendered manifest still contains a mutable or placeholder image: ${output_file}" >&2
    exit 1
  fi
}

kubectl create namespace "$namespace" --dry-run=client --output=yaml \
  > "$output_dir/namespace.yaml"
kubectl create configmap werewolf-api-config \
  --namespace "$namespace" \
  --from-env-file="$api_env" \
  --dry-run=client \
  --output=yaml > "$output_dir/api-config.yaml"
render_manifest "$migration_dir" "$output_dir/migration.yaml"
render_manifest "$overlay_dir" "$output_dir/application.yaml"

if [[ -n "$render_dir" ]]; then
  echo "rendered deployment manifests: ${output_dir}"
  exit 0
fi

if grep -R -q 'example\.com' "$overlay_dir/api.env" "$overlay_dir/ingress.yaml"; then
  echo "refusing deployment while ${environment} still contains example.com domains" >&2
  exit 1
fi

kubectl apply --filename "$output_dir/namespace.yaml"
kubectl apply --filename "$output_dir/api-config.yaml"

if ! kubectl get secret werewolf-api-secrets --namespace "$namespace" >/dev/null 2>&1; then
  echo "required Secret werewolf-api-secrets is missing in namespace ${namespace}" >&2
  exit 1
fi

kubectl delete job werewolf-db-migrate --namespace "$namespace" --ignore-not-found
kubectl apply --filename "$output_dir/migration.yaml"
kubectl wait --for=condition=complete job/werewolf-db-migrate \
  --namespace "$namespace" --timeout="${MIGRATION_TIMEOUT:-5m}"

kubectl apply --server-side --field-manager=werewolf-release \
  --filename "$output_dir/application.yaml"
kubectl rollout status deployment/werewolf-api --namespace "$namespace" \
  --timeout="${ROLLOUT_TIMEOUT:-5m}"
kubectl rollout status deployment/werewolf-live-run-reaper --namespace "$namespace" \
  --timeout="${ROLLOUT_TIMEOUT:-5m}"
kubectl rollout status deployment/werewolf-admin-web --namespace "$namespace" \
  --timeout="${ROLLOUT_TIMEOUT:-5m}"

if [[ -n "${ADMIN_BASE_URL:-}" ]]; then
  "$repo_root/scripts/smoke-admin-deployment.sh" "$ADMIN_BASE_URL"
fi

echo "deployment completed: environment=${environment} image_tag=${image_tag}"
