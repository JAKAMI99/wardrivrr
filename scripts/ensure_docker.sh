#!/usr/bin/env bash
# Ensure Docker Engine + Compose v2 plugin are installed and usable.
# Sourced by ./deploy.sh and ./run.sh — one-shot "just works" bootstrap.
#
# Usage:
#   source scripts/ensure_docker.sh
#   ensure_docker   # install if needed, verify docker compose + daemon

COMPOSE_PLUGIN_VERSION="${COMPOSE_PLUGIN_VERSION:-v2.29.7}"

_ensure_docker_arch() {
  case "$(uname -m)" in
    x86_64 | amd64) echo x86_64 ;;
    aarch64 | arm64) echo aarch64 ;;
    armv7l | armhf) echo armv7 ;;
    *) echo "" ;;
  esac
}

_install_compose_plugin() {
  local arch dest user_dest
  arch="$(_ensure_docker_arch)"
  if [[ -z "$arch" ]]; then
    echo "Cannot install Compose plugin: unsupported arch $(uname -m)"
    return 1
  fi
  dest=/usr/local/lib/docker/cli-plugins/docker-compose
  echo "Installing Docker Compose plugin ${COMPOSE_PLUGIN_VERSION} (${arch})…"
  sudo mkdir -p "$(dirname "$dest")"
  sudo curl -fsSL \
    "https://github.com/docker/compose/releases/download/${COMPOSE_PLUGIN_VERSION}/docker-compose-linux-${arch}" \
    -o "$dest"
  sudo chmod +x "$dest"
  # Per-user plugin path (docker CLI looks here too)
  user_dest="${HOME}/.docker/cli-plugins/docker-compose"
  mkdir -p "$(dirname "$user_dest")"
  ln -sfn "$dest" "$user_dest" 2>/dev/null || cp -f "$dest" "$user_dest"
  if ! docker compose version >/dev/null 2>&1; then
    echo "Compose plugin installed but 'docker compose' still fails."
    return 1
  fi
  echo "Compose: $(docker compose version --short 2>/dev/null || docker compose version)"
}

_install_docker_engine() {
  echo "Installing Docker Engine (get.docker.com)…"
  if ! command -v curl >/dev/null 2>&1; then
    sudo apt-get update -qq
    sudo apt-get install -y curl ca-certificates
  fi
  curl -fsSL https://get.docker.com | sudo sh
  local who="${SUDO_USER:-$USER}"
  if [[ -n "$who" && "$who" != "root" ]]; then
    sudo usermod -aG docker "$who" 2>/dev/null || true
    echo "Added $who to the docker group (re-login or: newgrp docker)."
  fi
  sudo systemctl enable --now docker 2>/dev/null || true
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]] || sudo -n true 2>/dev/null || sudo -v; then
      _install_docker_engine
    else
      echo "Docker is not installed and sudo is unavailable."
      echo "Install Docker Engine: https://docs.docker.com/engine/install/"
      return 1
    fi
  fi

  if ! docker compose version >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]] || sudo -n true 2>/dev/null || sudo -v; then
      _install_compose_plugin || return 1
    else
      echo "Docker Compose v2 plugin is missing (need: docker compose)."
      return 1
    fi
  fi

  if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but not usable (permission or daemon down)."
    sudo systemctl enable --now docker 2>/dev/null || true
    if ! docker info >/dev/null 2>&1; then
      echo "Fix once: sudo usermod -aG docker \"\$USER\" && newgrp docker"
      echo "Or start the daemon: sudo systemctl enable --now docker"
      return 1
    fi
  fi

  echo "Docker: ok ($(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unknown))"
  echo "Compose: $(docker compose version --short 2>/dev/null || echo ok)"
  return 0
}
