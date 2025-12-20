## Optional: Nginx + Let's Encrypt (certbot) TLS

If you want to expose the API only via HTTPS (and *not* bind the API directly to host port 8000), use the certbot-enabled nginx override.

### Requirements
- A real domain name (`BASELINER_DOMAIN`) that resolves to this host
- Ports **80** and **443** reachable from the internet
- An email address for Let's Encrypt registration (`CERTBOT_EMAIL`)

### Bring up
```bash
BASELINER_DOMAIN=api.example.com CERTBOT_EMAIL=you@example.com \
  docker compose -f docker-compose.yml -f docker-compose.nginx-certbot.yml up -d --build
```

Windows convenience:
```powershell
.\tools\dev-scripts\Dev-UpTls.ps1 -Domain "api.example.com" -Email "you@example.com" -Detached
```

### Verify
- `https://api.example.com/health` should return OK
- `http://api.example.com/health` should redirect to HTTPS (after allowing ACME challenge paths)

### Notes
- This configuration uses the HTTP-01 challenge under `/.well-known/acme-challenge/`.
- Nginx reloads periodically (every ~6 hours) to pick up renewed certs. You can also manually restart it:
  `docker compose restart nginx`
