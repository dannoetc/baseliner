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

Troubleshooting:
```bash
docker logs baseliner-nginx --tail 200
docker logs baseliner-certbot --tail 200
```
