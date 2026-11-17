#!/usr/bin/env bash
# Let's Encrypt 证书续期（配合 crontab 每月执行一次）
set -euo pipefail
cd "$(dirname "$0")"
DC="docker compose"
$DC version >/dev/null 2>&1 || DC="docker-compose"
$DC run --rm certbot renew --webroot -w /var/www/certbot --quiet --non-interactive
$DC exec -T nginx nginx -s reload
echo "$(date '+%F %T') 证书续期完成"
