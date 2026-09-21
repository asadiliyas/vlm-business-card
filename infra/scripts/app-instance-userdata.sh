#!/bin/bash
# EC2 user-data for the APP TIER instance (free-tier t3.micro).
# Paste this whole file into the "User data" box when launching the
# instance (Amazon Linux 2023 AMI), or pass it via --user-data-file to
# `aws ec2 run-instances`. Runs once, automatically, on first boot as root.
#
# What it does:
#   1. Adds a 2 GB swap file — a t3.micro's 1 GB RAM is tight once Docker,
#      Caddy, and the app are all resident; swap is cheap insurance against
#      an OOM kill during a burst of uploads.
#   2. Installs Docker + the Compose plugin.
#   3. Clones this repo and starts `docker compose up -d` (app + Caddy).
#
# After boot, finish setup over SSH: create /opt/vlm-business-card/.env
# from .env.example with real values, then `docker compose up -d` again to
# pick it up (see docs/DEPLOY.md — this script intentionally does not bake
# secrets into the AMI/user-data, which is visible to anyone with
# DescribeInstanceAttribute permission on the instance).

set -euxo pipefail

# --- 1. Swap file (headroom on a 1 GB instance) ---
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- 2. Docker + Compose plugin ---
dnf update -y
dnf install -y docker git
systemctl enable --now docker
usermod -aG docker ec2-user

DOCKER_CONFIG_DIR=/usr/local/lib/docker/cli-plugins
mkdir -p "$DOCKER_CONFIG_DIR"
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o "$DOCKER_CONFIG_DIR/docker-compose"
chmod +x "$DOCKER_CONFIG_DIR/docker-compose"

# --- 3. Clone the repo ---
# Replace with your fork's URL if different from the one this was generated for.
REPO_URL="__REPO_URL__"
DEST=/opt/vlm-business-card

if [ ! -d "$DEST" ]; then
    git clone "$REPO_URL" "$DEST"
fi
cd "$DEST"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "!! .env created from .env.example with PLACEHOLDER values."
    echo "!! SSH in, edit /opt/vlm-business-card/.env with real values, then:"
    echo "!!   cd /opt/vlm-business-card && docker compose up -d"
fi

docker compose up -d || true  # first run will be degraded until .env is filled in; that's expected
