#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu 24.04 server (tested target: Oracle Cloud Always
# Free, Ampere A1). Run as the default user with sudo rights:  bash deploy/setup-server.sh
# Safe to run again.
set -euo pipefail

echo "== packages: Docker, Compose, make, git"
sudo apt-get update -q
sudo apt-get install -y -q docker.io docker-compose-v2 make git openssl iptables-persistent
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

echo "== host firewall: allow HTTP and HTTPS"
# Oracle's Ubuntu images ship iptables rules that reject everything except SSH, in addition
# to the cloud security list (which must also allow 80 and 443: see docs/DEPLOYMENT.md).
for rule in "-p tcp --dport 80" "-p tcp --dport 443" "-p udp --dport 443"; do
  # shellcheck disable=SC2086
  sudo iptables -C INPUT $rule -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 1 $rule -j ACCEPT
done
sudo netfilter-persistent save

echo "== directories the containers write to (owned by uid 1000, the app user)"
# Only git-ignored directories: a tracked file in a directory you do not own cannot be updated
# by git pull (your login user is not always uid 1000; on Oracle's Ubuntu image it is not).
cd "$(dirname "$0")/.."
mkdir -p datasets/generated .cache backups
sudo chown -R 1000:1000 datasets/generated .cache

echo
echo "Done. Log out and back in (so the docker group applies), then continue with"
echo "'Configure' in docs/DEPLOYMENT.md."
