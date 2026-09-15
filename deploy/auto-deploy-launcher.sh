#!/bin/sh
set -eu

service="${1:-}"
config_dir="${AUTO_DEPLOY_CONFIG_DIR:-/etc/battery-auto-deploy}"

case "${service}" in
  monitor|collector) ;;
  *)
    printf 'Usage: %s monitor|collector\n' "$0" >&2
    exit 2
    ;;
esac

repo_file="${config_dir}/${service}.repo"
branch_file="${config_dir}/${service}.branch"
remote_file="${config_dir}/${service}.remote"
arguments_file="${config_dir}/${service}.args"

test -r "${repo_file}" || {
  printf 'Missing repository configuration: %s\n' "${repo_file}" >&2
  exit 1
}

IFS= read -r repo < "${repo_file}"
branch="master"
remote="origin"
if test -r "${branch_file}"; then IFS= read -r branch < "${branch_file}"; fi
if test -r "${remote_file}"; then IFS= read -r remote < "${remote_file}"; fi

test -n "${repo}" || {
  printf 'Repository path is empty in %s\n' "${repo_file}" >&2
  exit 1
}

exec /usr/bin/env bash "${repo}/deploy/auto-deploy.sh" \
  --service "${service}" \
  --repo "${repo}" \
  --branch "${branch}" \
  --remote "${remote}" \
  --arguments-file "${arguments_file}"
