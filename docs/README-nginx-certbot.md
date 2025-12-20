## Optional: Nginx + Let's Encrypt (certbot) TLS (fixed bootstrap)

This fixes the nginx crash-loop when the Let's Encrypt cert files don't exist yet.

- Nginx starts immediately using a bootstrap self-signed cert in `/etc/nginx/certs`
- Certbot obtains/renews the real LE certs under `/etc/letsencrypt`
- Nginx re-renders config and reloads periodically, switching to the real cert automatically

Bring up:
```bash
BASELINER_DOMAIN=api.example.com CERTBOT_EMAIL=you@example.com \
  docker compose -f docker-compose.yml -f docker-compose.nginx-certbot.yml up -d --build
```

Verify:
- `curl -k https://$BASELINER_DOMAIN/health` works immediately (bootstrap cert)
- After issuance, `curl https://$BASELINER_DOMAIN/health` works without `-k`

---

## Optional: nginx edge limiting (limit_req + limit_conn)

This overlay supports **optional** per-IP request rate limiting and concurrent connection limiting at the nginx layer.
This is defense-in-depth for overload protection (Issue #23). You still want the **app-layer** limits for device-key-aware behavior.

Enable:
```bash
BASELINER_DOMAIN=api.example.com CERTBOT_EMAIL=you@example.com \
NGINX_LIMITS_ENABLED=true \
docker compose -f docker-compose.yml -f docker-compose.nginx-certbot.yml up -d --build
```

Tune (examples):
```bash
# nginx rate syntax: "5r/s" or "60r/m"
NGINX_LIMIT_REQ_REPORTS_RATE="2r/s" \
NGINX_LIMIT_REQ_REPORTS_BURST=10 \
NGINX_LIMIT_REQ_GENERAL_RATE="10r/s" \
NGINX_LIMIT_REQ_GENERAL_BURST=40 \
NGINX_LIMIT_CONN_REPORTS_PER_IP=10 \
NGINX_LIMIT_CONN_GENERAL_PER_IP=50 \
BASELINER_DOMAIN=api.example.com CERTBOT_EMAIL=you@example.com \
docker compose -f docker-compose.yml -f docker-compose.nginx-certbot.yml up -d --build
```

**Gotcha (NAT):** nginx limits here are **per IP**. If many devices share one public IP (NAT), aggressive limits can throttle legitimate traffic.

---

## Optional: real client IP extraction (real_ip)

If your Baseliner nginx is **behind another proxy / load balancer** (Cloudflare, ALB, host nginx, etc.), then `$remote_addr` will often be the proxy/LB IP.
That breaks the usefulness of per-IP limiting and makes logs less informative.

This overlay can optionally enable nginx's `real_ip` module so `$remote_addr` reflects the **actual client IP**.

Enable (typical X-Forwarded-For case):
```bash
BASELINER_DOMAIN=api.example.com CERTBOT_EMAIL=you@example.com \
NGINX_REALIP_ENABLED=true \
NGINX_REALIP_HEADER="X-Forwarded-For" \
# IMPORTANT: set this to your *trusted proxies/LBs* (the only IPs allowed to set the real client IP)
NGINX_REALIP_TRUSTED_CIDRS="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16" \
docker compose -f docker-compose.yml -f docker-compose.nginx-certbot.yml up -d --build
```

Enable (Cloudflare example):
- Set `NGINX_REALIP_HEADER="CF-Connecting-IP"`
- Set `NGINX_REALIP_TRUSTED_CIDRS` to Cloudflare's published IP ranges

**Security gotcha:** `set_real_ip_from` is a *trust list*. If you set it too broad (e.g. `0.0.0.0/0`), any client can spoof their IP via the header.

Default behavior when `NGINX_REALIP_ENABLED=true` and `NGINX_REALIP_TRUSTED_CIDRS` is empty:
- nginx trusts common private ranges + loopback (useful for docker/host reverse-proxy setups)

---

## Troubleshooting (highest signal)

Tail logs:
```bash
docker logs baseliner-nginx --tail 200
docker logs baseliner-certbot --tail 200
```

Validate config:
```bash
docker exec baseliner-nginx nginx -t
```

Inspect rendered config + generated includes:
```bash
docker exec baseliner-nginx sh -lc 'ls -la /etc/nginx/includes && sed -n "1,200p" /etc/nginx/conf.d/baseliner.conf'
```
