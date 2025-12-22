## Optional: Nginx + Let's Encrypt (certbot) TLS overlay

This overlay exists for production-ish deployments where you want TLS termination in front of the FastAPI server.

### What it does

- Nginx always starts (even on first boot) using a **bootstrap self-signed cert** stored in `/etc/nginx/certs`.
  - This avoids the nginx crash-loop you get when nginx references LE cert files that don’t exist yet.
- Certbot obtains/renews the real Let’s Encrypt certs under `/etc/letsencrypt`.
- Nginx periodically re-renders config + reloads, switching to the LE cert once it exists.

### Required environment variables

- `BASELINER_DOMAIN=api.example.com`
- `CERTBOT_EMAIL=you@example.com`

### Bring up

```bash
BASELINER_DOMAIN=api.example.com CERTBOT_EMAIL=you@example.com \
  docker compose -f docker-compose.yml -f docker-compose.nginx-certbot.yml up -d --build
```

### Verify

- Bootstrap cert works immediately:

```bash
curl -k -i https://$BASELINER_DOMAIN/health
```

- After issuance, it should work without `-k`:

```bash
curl -i https://$BASELINER_DOMAIN/health
```

---

## Optional: nginx edge limiting (limit_req + limit_conn)

This overlay supports optional **per-IP** request rate limiting and concurrent connection limiting at the nginx layer.

This is defense-in-depth for overload protection. Baseliner also has **app-layer** request size + rate limits.

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

**Gotcha (NAT):** nginx limits are **per IP**. If many devices share one public IP (NAT), aggressive limits can throttle legitimate traffic.

---

## Optional: real client IP extraction (real_ip)

If your Baseliner nginx is **behind another proxy / load balancer** (Cloudflare, ALB, host nginx, etc.), then `$remote_addr` will often be the proxy/LB IP.
That breaks the usefulness of per-IP limiting and makes logs less informative.

Enable (typical `X-Forwarded-For` case):

```bash
BASELINER_DOMAIN=api.example.com CERTBOT_EMAIL=you@example.com \
NGINX_REALIP_ENABLED=true \
NGINX_REALIP_HEADER="X-Forwarded-For" \
# IMPORTANT: set this to your trusted proxies/LBs (the only IPs allowed to set the real client IP)
NGINX_REALIP_TRUSTED_CIDRS="10.0.0.0/8,172.16.0.0/12,192.168.0.0/16" \
  docker compose -f docker-compose.yml -f docker-compose.nginx-certbot.yml up -d --build
```

**Security gotcha:** `set_real_ip_from` is a trust list. If you set it too broad (e.g. `0.0.0.0/0`), any client can spoof their IP via headers.

---

## Troubleshooting (highest signal)

```bash
docker logs baseliner-nginx --tail 200
docker logs baseliner-certbot --tail 200

docker exec baseliner-nginx nginx -t

docker exec baseliner-nginx nginx -T | grep -E "limit_req_zone|limit_conn_zone|real_ip_header|set_real_ip_from" || true
```
