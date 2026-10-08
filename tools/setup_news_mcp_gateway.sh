#!/usr/bin/env bash
# Operator-authorized IP TLS gateway. Does not deploy/restart the application.
set -Eeuo pipefail
phase=${1:?Expected bootstrap or https}
stage=/root/news-mcp-https-20261008
test "$(id -u)" = 0
test -d "$stage"
case "$phase" in bootstrap|https) ;; *) exit 2 ;; esac
site=/etc/nginx/sites-available/space-news-mcp
enabled=/etc/nginx/sites-enabled/space-news-mcp
if [[ -f "$site" ]] && grep -Eq 'listen[[:space:]]+8080[[:space:]]+ssl' "$site"; then
    echo 'Website HTTPS on 8080 is already configured; do not replace it with the older MCP-only template.' >&2
    exit 2
fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
evidence="$stage/evidence-$phase-$stamp"
install -d -m 700 "$evidence"
cp -a /etc/nginx "$evidence/nginx-before"
printf '%s\n' "$evidence" > "$stage/latest-evidence-path"

install -d -m 755 /var/www/space-news-acme/.well-known/acme-challenge
if [[ "$phase" == bootstrap ]]; then
    # This package default was created during this authorized fresh installation.
    if [[ -L /etc/nginx/sites-enabled/default ]]; then
        mv /etc/nginx/sites-enabled/default "$evidence/package-default-link"
    fi
    install -m 644 "$stage/news-mcp-ip-acme.conf" "$site"
    printf 'space-news-acme-ready\n' > /var/www/space-news-acme/.well-known/acme-challenge/news-mcp-preflight
else
    test -s /etc/letsencrypt/live/8.137.164.100/fullchain.pem
    test -s /etc/letsencrypt/live/8.137.164.100/privkey.pem
    install -m 644 "$stage/news-mcp-ip-https.conf" "$site"
fi
if [[ -e "$enabled" || -L "$enabled" ]]; then
    test "$(readlink "$enabled")" = "$site"
else
    ln -s "$site" "$enabled"
fi
nginx -t
if [[ "$phase" == bootstrap ]]; then
    systemctl unmask --runtime nginx.service
    systemctl enable --now nginx.service
else
    systemctl reload nginx.service
    install -m 644 "$stage/news-mcp-certbot-renew.service" /etc/systemd/system/news-mcp-certbot-renew.service
    install -m 644 "$stage/news-mcp-certbot-renew.timer" /etc/systemd/system/news-mcp-certbot-renew.timer
    systemd-analyze verify /etc/systemd/system/news-mcp-certbot-renew.service /etc/systemd/system/news-mcp-certbot-renew.timer
    systemctl daemon-reload
    systemctl enable --now news-mcp-certbot-renew.timer
fi
curl --fail --silent --show-error --max-time 10 -H 'Host: 8.137.164.100' \
    http://127.0.0.1/.well-known/acme-challenge/news-mcp-preflight
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8080/api/health
printf '\nGateway phase complete. Evidence: %s\n' "$evidence"
