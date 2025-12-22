# Troubleshooting

This is a practical list of the failures we’ve actually hit while deploying Baseliner.

## Fast triage checklist (2–3 commands)

1) **Container logs** (API + nginx + certbot)

```bash
docker compose logs -f --tail 200 api
```

If using the nginx/certbot overlay:

```bash
docker logs baseliner-nginx --tail 200
docker logs baseliner-certbot --tail 200
```

2) **Nginx config sanity** (overlay)

```bash
docker exec baseliner-nginx nginx -t
```

3) **Is the API alive?**

```bash
curl -i http://localhost:8000/health
```

---

## Common issues

### Compose env vars missing when using sudo

**Symptom**: Compose interpolation doesn’t pick up `BASELINER_DOMAIN` / `CERTBOT_EMAIL` (or other envs) when you run compose under `sudo`.

**Fix**:
- Prefer a `.env` file alongside your compose invocation, or
- run compose with environment preserved: `sudo -E docker compose ...`

---

### Certbot can’t issue a certificate (HTTP-01)

**Symptom**: certbot logs show challenge failures.

**Checklist**:
- DNS A/AAAA record points to the host
- Port 80 is reachable from the public Internet
- `/.well-known/acme-challenge/` is served by nginx (webroot volume mounted)

Useful commands:

```bash
# Show nginx site config as loaded
docker exec baseliner-nginx nginx -T | sed -n '1,200p'

# Verify challenge path served
curl -i http://$BASELINER_DOMAIN/.well-known/acme-challenge/test
```

---

### Nginx crash loops on first boot

This should not happen with the bootstrap-cert overlay, but if it does:

- Check the nginx logs:

```bash
docker logs baseliner-nginx --tail 200
```

- Confirm the bootstrap cert exists inside the container:

```bash
docker exec baseliner-nginx ls -la /etc/nginx/certs
```

---

## HTTP status codes you’ll see

### Device endpoints

- **401**: missing/invalid bearer token (unknown token)
- **403**: token is known but revoked OR device is deactivated
- **413**: request body too large (request-size middleware)
- **429**: rate limit exceeded
  - can come from nginx (edge) or the API (app-layer)

### Admin endpoints

- **401**: missing/invalid `X-Admin-Key`
- **409**: lifecycle conflict (e.g., restore an already-active device)

---

## Correlation IDs (trace a single action)

If you send `X-Correlation-ID` on a request, the server:

- echoes it back
- persists it on runs created by `POST /api/v1/device/reports`

Use this to correlate:
- agent logs → API logs → run detail in admin

---

## TODO

- Add examples for “nginx 429 vs API 429” identification
- Add a short section on support bundle contents (agent-side)
