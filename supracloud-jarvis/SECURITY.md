# Security Notes — SupraCloud IRA

## TLS Setup

### Phase 1 (default): self-signed certificate

`scripts/setup.sh` generates a self-signed RSA-4096 certificate valid for 10 years,
stored at `nginx/certs/ira.crt` and `nginx/certs/ira.key`.

Browsers will show a security warning ("Your connection is not private") on first access.

#### Trust the certificate — per platform

**macOS**
```bash
# One-time — adds the cert to the System Keychain and trusts it for SSL
sudo security add-trusted-cert -d -r trustRoot \
    -k /Library/Keychains/System.keychain nginx/certs/ira.crt
```

**Linux (Debian/Ubuntu)**
```bash
sudo cp nginx/certs/ira.crt /usr/local/share/ca-certificates/ira.crt
sudo update-ca-certificates
```

**Linux (RHEL/Fedora/CentOS)**
```bash
sudo cp nginx/certs/ira.crt /etc/pki/ca-trust/source/anchors/ira.crt
sudo update-ca-trust extract
```

**Windows (PowerShell — as Administrator)**
```powershell
Import-Certificate -FilePath nginx\certs\ira.crt `
    -CertStoreLocation Cert:\LocalMachine\Root
```

**Chrome / Edge (manual override)**
Navigate to `https://<IRA_DOMAIN>`, click "Advanced → Proceed to <domain> (unsafe)".
This works for local development but is not recommended for shared machines.

**Firefox**
Firefox maintains its own certificate store.
Open `about:preferences#privacy`, scroll to "Certificates → View Certificates",
import `nginx/certs/ira.crt` under "Authorities" and check "Trust this CA to identify websites".

---

### Phase 2 (production): Let's Encrypt

Replace the self-signed certificate with a CA-signed certificate before exposing IRA to
the internet. The nginx configuration is already compatible — swap the cert/key files:

```bash
# Install certbot
sudo apt install certbot

# Obtain a certificate (ensure port 80 is open and IRA_DOMAIN points to this machine)
sudo certbot certonly --standalone -d "${IRA_DOMAIN}"

# Copy the issued cert into the nginx certs directory
sudo cp /etc/letsencrypt/live/${IRA_DOMAIN}/fullchain.pem nginx/certs/ira.crt
sudo cp /etc/letsencrypt/live/${IRA_DOMAIN}/privkey.pem  nginx/certs/ira.key
sudo chown $(id -u):$(id -g) nginx/certs/ira.{crt,key}
chmod 644 nginx/certs/ira.crt
chmod 600 nginx/certs/ira.key

# Reload nginx
docker compose exec nginx nginx -s reload
```

Enable OCSP stapling and uncomment the `ssl_stapling` lines in
`nginx/nginx.conf.template` when using a real CA certificate.

---

## Secrets rotation

| Secret                | Rotation cadence | How to rotate                                 |
|-----------------------|-----------------|----------------------------------------------|
| `IRA_SECRET_KEY`      | Annually        | Re-generate with `openssl rand -hex 32`; all existing JWTs are invalidated |
| `IRA_VOICE_API_TOKEN` | Annually        | Re-run `setup.sh` or generate a new JWT manually (see `.env.example`) |
| `WEBHOOK_SECRET`      | On compromise   | Change in `.env` and update all webhook senders |
| `LIVEKIT_API_SECRET`  | Annually        | Change in `.env`; update LiveKit server config |
| `POSTGRES_PASSWORD`   | Annually        | Requires `ALTER USER jarvis PASSWORD '…';` in psql + `.env` update |
| TLS certificate       | Before expiry   | Self-signed cert is valid 10 years; Let's Encrypt auto-renews every 90 days |
