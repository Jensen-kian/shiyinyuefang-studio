#!/usr/bin/env bash
# 拾音乐坊 —— 一键部署（首次上线 / 重新部署均可执行）
# 前置：域名 @ 与 www 的 A 记录已指向本机公网 IP，且 80/443 可从公网访问
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "缺少 deploy/.env，请先执行： cp .env.example .env 并填写配置"; exit 1; }
set -a; . ./.env; set +a

DOMAIN="${DOMAIN:-shiyinyuefang.com}"
WWW="${WWW_DOMAIN:-www.$DOMAIN}"
EMAIL="${CERTBOT_EMAIL:-admin@$DOMAIN}"
STAGING="${STAGING:-0}"

DC="docker compose"
$DC version >/dev/null 2>&1 || DC="docker-compose"

echo "==> 目标域名：$DOMAIN / $WWW"

echo "==> [1/5] 检查 DNS 解析"
for h in "$DOMAIN" "$WWW"; do
  ip="$(getent ahostsv4 "$h" | awk 'NR==1{print $1}' || true)"
  if [ -z "$ip" ]; then
    echo "❌ $h 未解析。请先在注册商添加 A 记录指向本服务器公网 IP，等待生效后重试。"
    exit 1
  fi
  echo "    $h -> $ip"
done
PUBIP="$(curl -s --max-time 5 https://api.ipify.org || true)"
echo "    本机公网 IP：${PUBIP:-获取失败}（请确认与上面 A 记录一致）"

echo "==> [2/5] 以 HTTP 配置启动（供证书校验）"
sed -e "s/__DOMAIN__/$DOMAIN/g" -e "s/__WWW__/$WWW/g" nginx-http.conf > nginx-active.conf
mkdir -p ../data
$DC up -d --build app nginx

echo "    等待服务就绪…"
ok=0
for i in $(seq 1 30); do
  if curl -fsS -o /dev/null --max-time 3 "http://127.0.0.1/"; then ok=1; break; fi
  sleep 2
done
[ "$ok" = "1" ] || { echo "❌ 服务未就绪，请查看日志： $DC logs app"; exit 1; }

echo "==> [3/5] 申请 Let's Encrypt 证书"
STAGE_FLAG=""
[ "$STAGING" = "1" ] && STAGE_FLAG="--staging"
$DC run --rm certbot certonly --webroot -w /var/www/certbot \
    -d "$DOMAIN" -d "$WWW" \
    --email "$EMAIL" --agree-tos --no-eff-email --non-interactive \
    --keep-until-expiring $STAGE_FLAG

echo "==> [4/5] 切换到 HTTPS 配置"
sed -e "s/__DOMAIN__/$DOMAIN/g" -e "s/__WWW__/$WWW/g" nginx-https.conf > nginx-active.conf
$DC exec -T nginx nginx -t
$DC restart nginx
sleep 3

echo "==> [5/5] 验证本机 HTTPS（--resolve 绕过 NAT 回环限制）"
curl -fsSI --max-time 10 --resolve "$WWW:443:127.0.0.1" "https://$WWW/" | head -6
echo ""
echo "✅ 部署完成： https://$WWW/"
echo "   证书续期：把下面一行加入 crontab（crontab -e）"
echo "   0 3 1 * * $(pwd)/renew.sh >> /var/log/shiyinyuefang-renew.log 2>&1"
