# Deploying SmartPlateAI

Status (2026-10-27): **prepared, not deployed; the Docker image has never been built** (Docker is not installed on the
development laptop). Nothing has been published, no cloud resource or domain was created, and
no credentials were uploaded. Every step below that costs money, publishes the app or needs your accounts is marked
**[your approval / your account]**.

## 1. What the server has to run

| Need | Why |
|---|---|
| Linux x86-64, **2 GB RAM** recommended | Measured on 2026-10-27 (Windows, same code, both models loaded, 3 analyses): about **510 MB resident, 900 MB committed**; ~0.2–0.3 s per photo on a laptop CPU. Tesseract adds up to ~100 MB per parallel OCR process. 1 GB is too tight once the OS, Caddy and OCR are added; free 512 MB tiers will not work. |
| Persistent disk (a volume) | Accounts (`smartplate_users.db`), history and the HTTP cache (`smartplate.db`) are SQLite files. |
| Tesseract OCR | Packaged-label reading. Installed in the image. |
| HTTPS | Required for login cookies (`Secure`), the in-page camera (secure context) and installing the app on a phone. |
| ~9 MB reference data | Written by `backend/scripts/prepare_deploy_data.py`: the packaged-food CSVs as they are, and the food CSV reduced to `food`, `fdc_id` and nutrient columns (no image names or local paths). The reduced file gives identical nutrition for all 24 classes (verified). |
| ImageNet MobileNetV2 weights | Downloaded while the image is built, not at runtime. |

The image (`Dockerfile` at the project root) runs **one process** that serves both the API and the built React app from
the same origin. So no API URL is compiled into the frontend and CORS is not needed (cookies stay first-party).

## 2. Recommended architecture (cost-conscious)

**Option A, recommended: one small Linux VM + Docker Compose + Caddy** (`deploy/docker-compose.yml`, `deploy/Caddyfile`).
Caddy obtains and renews the Let's Encrypt certificate automatically and is the only thing listening on ports 80/443;
the app port is internal. Any provider's x86-64 VM with ≥ 2 GB RAM works (Hetzner, DigitalOcean, Linode, AWS Lightsail,
Google Compute Engine, …). Check current prices yourself. You need a domain name, or a free dynamic-DNS subdomain such as DuckDNS, pointing at the VM.
*ARM VMs (e.g. Oracle Cloud's free Ampere tier) also work if you change `tensorflow-cpu` to `tensorflow==2.19.1` in
`backend/requirements-deploy.txt` (tensorflow-cpu has no ARM wheel).*

Why not the alternatives:
- **Serverless containers (Google Cloud Run, AWS App Runner):** HTTPS URL included and they scale to zero, but their disk is
  temporary, so the SQLite accounts would be lost on every restart. Usable only after moving accounts/history to a
  managed database (not done).
- **Free PaaS tiers (Render, Railway, …):** 512 MB RAM is too small for TensorFlow; the 2 GB tiers are paid.
- **Static frontend host + separate API host:** possible (set `VITE_API_BASE_URL` at build time, `CORS_ORIGINS` and
  `AUTH_COOKIE_SAMESITE=none` on the API), but cross-site cookies are blocked by some phone browsers. Same-origin is simpler and safer.
- **Tunnelling your laptop (ngrok, Cloudflare Tunnel, Tailscale Funnel):** exposes your Windows machine; ruled out.

## 3. Abuse and paid-provider controls (implemented 2026-10-27; was the release blocker)

All of this is switched on by `ENVIRONMENT=production` (the image sets it) and off in local development, where the app
behaves as before. Code: `backend/app/services/usage_limits.py`, `backend/app/api/limits.py`; tests:
`backend/tests/test_security_limits.py` (providers mocked) and `backend/tests/test_deploy_config.py`.

| Area | What the app does |
|---|---|
| Access | Sign-in is unchanged. **Anonymous visitors get the image model only**: no OpenAI / Gemini / Google Vision call, no AI label reading, no chatbot (HTTP 401 "Sign in to use the chatbot"). Their results say "AI verification is available to signed-in users" and are decided exactly as with the providers switched off (the rules measured in `PACKAGED_EVALUATION.md`). `PAID_PROVIDERS_REQUIRE_LOGIN` (`auto`/`true`/`false`). |
| Rate limits (`RATE_LIMITS_ENABLED`) | Photo analyses (fresh and packaged): 10 / hour per client IP when anonymous; 30 / hour and 200 / day per signed-in account. Chatbot and meal planner: 30 / hour per account. Sign-ups 5 / hour and sign-in attempts 30 / hour per IP (the per-email failed-login lock is kept). Food confirmation, chemical data and Open Food Facts lookups 300 / hour per IP. Over a limit: HTTP 429 `RATE_LIMITED`, a `Retry-After` header and a message with the wait in minutes; the photo is not analysed. |
| Paid-provider caps (always on) | Global request caps per UTC day: `OPENAI_DAILY_LIMIT` 300, `GEMINI_DAILY_LIMIT` 300 (food identification + label reading), `GOOGLE_VISION_DAILY_LIMIT` 300, `CHAT_DAILY_LIMIT` 500 (chatbot + meal planner). Cached answers are not counted. At the cap the app falls back to the image model / Tesseract and says so; the chatbot answers 503 `CHAT_DAILY_LIMIT`. If the counter store fails, paid calls are refused (fail closed) while ordinary requests continue. **These cap requests, not money**: also set a budget alert and a spending limit in the OpenAI and Google Cloud consoles **[your account]**. |
| Request and image limits | Kept: 8 MB per photo, content-sniffed formats, 40 MP limit, decompression-bomb protection, max 3 photos per packaged scan. Added: whole request body ≤ `MAX_REQUEST_MB` (30) for uploads and ≤ `MAX_JSON_KB` (1024) otherwise, checked from Content-Length before parsing (413 `REQUEST_TOO_LARGE`; a body without a length gets 411). At most `MAX_CONCURRENT_ANALYSES` (3) photo analyses run at once; others wait up to 30 s, then 503 `SERVER_BUSY`. uvicorn `--limit-concurrency 32`. Caddy: 30 MB bodies, header/body read timeouts, 150 s upstream timeout. |
| Client address | Caddy overwrites `X-Forwarded-For` with the real peer; uvicorn trusts that header only from Caddy's fixed address on the private compose network (`FORWARDED_ALLOW_IPS=172.31.240.2`), so a client cannot fake its IP to dodge the limits. Addresses are never stored: counters use a salted hash (IPv6 grouped by /64). |
| Storage | Counters are in their own SQLite file, `smartplate_usage.db` next to `DATABASE_PATH` (`/data` volume), so they survive restarts and never touch accounts or history. Fixed hourly / daily windows: up to 2× a limit is possible across a window boundary. |
| Logging | Keys, photos, OCR text, chat messages and IPs are not logged; a rate-limit event logs the kind and an 8-character hash prefix. |
| Health | `/health` (process up, container health check) and `/api/models/status` (models and data loaded). Add external uptime monitoring of `https://<domain>/health` **[your account]**. |

Not done (optional): email verification for new accounts; CAPTCHA on sign-up; a shared counter store if you ever run
more than one app process or server (the SQLite counters are per server).

## 4. Deployment checklist

Everything marked **[server]** can only be done and verified on the real VM; nothing here has been run on one yet.
Replace `<domain>`, `<vm-ip>` and `<user>` throughout.

### A. Before creating anything: provider budgets **[your account]**
- [ ] OpenAI: set a monthly budget and an email alert for the project whose key the server will use.
- [ ] Google Cloud (Gemini / Vision): create a budget with alerts on the billing account. Budgets only alert; they do not stop
      spending. The app's daily caps (section 3) are the hard stop.
- [ ] Restrict each server key: Gemini key to the Generative Language API, Vision key to the Cloud Vision API, and both to the
      VM's IP address once you know it.
- [ ] Optional for the first days: lower caps in `deploy/smartplate.env` (e.g. `OPENAI_DAILY_LIMIT=50`), or leave the paid keys
      empty and add them after the free checks below pass.

### B. VM, firewall and Docker **[server]**
- [ ] VM: Ubuntu 24.04 LTS, x86-64, ≥ 2 GB RAM, ≥ 25 GB disk (the image is several GB: TensorFlow, Tesseract, Node build stage).
- [ ] Cloud firewall (security group): inbound TCP 22 **from your IP only**, TCP 80 and 443 from anywhere; nothing else.
      Ports published by Docker bypass `ufw`, so the cloud firewall is the one that counts. Only Caddy publishes ports.
- [ ] Swap (2 GB RAM is tight while TensorFlow loads):
  ```bash
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```
- [ ] Docker Engine + Compose plugin (Docker's official apt repository):
  ```bash
  sudo apt-get update && sudo apt-get install -y ca-certificates curl
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker $USER && newgrp docker      # or log out and in again
  docker run --rm hello-world && docker compose version
  ```

### C. Private network range (Caddy ↔ app) **[server]**
The compose file uses `172.31.240.0/24` (Caddy `.2`, app `.3`; the app trusts `X-Forwarded-For` only from `.2`). It must not
overlap a network the VM already routes. Known case: **AWS EC2 default VPCs are `172.31.0.0/16`**; their default subnets
(`172.31.0.0`–`172.31.95.255`) do not include `.240`, but a custom subnet might. Lightsail (`172.26.0.0/16`), DigitalOcean,
Hetzner, GCP and Oracle defaults (10.x) do not overlap. Check after installing Docker, before the first `up`:
```bash
python3 - <<'PY'
import ipaddress, re, subprocess
want = ipaddress.ip_network("172.31.240.0/24")
text = subprocess.run(["ip", "-4", "route"], capture_output=True, text=True).stdout
nets = {ipaddress.ip_network(n, strict=False) for n in re.findall(r"\d+\.\d+\.\d+\.\d+/\d+", text)}
clash = sorted(str(n) for n in nets if n.overlaps(want) and n.prefixlen > 0)
print("CLASH with " + ", ".join(clash) if clash else "172.31.240.0/24 is free")
PY
```
If it prints CLASH, pick a free /24 and set only its first three octets; the subnet, both addresses and the trusted proxy
follow: `echo "SMARTPLATE_NET=10.213.47" >> deploy/.env` (re-run the check with that range). If Compose later reports
"Pool overlaps with other one on this address space", another Docker network uses the range; same fix.

### D. Domain and DNS **[your account]**
- [ ] A record `<domain>` → `<vm-ip>`. Do **not** add an AAAA record unless the VM has working public IPv6 (Let's Encrypt
      uses IPv6 when it exists and issuance fails if it is unreachable).
- [ ] Verify: `dig +short A <domain>` prints `<vm-ip>`; `dig +short AAAA <domain>` prints nothing (or the VM's IPv6).

### E. Copy only what the server needs (from your laptop)
```powershell
cd D:\SmartPlateAI\backend
.\.venv\Scripts\python.exe scripts\prepare_deploy_data.py                       # deploy\reference_data
.\.venv\Scripts\python.exe scripts\make_deploy_bundle.py --out D:\smartplate-deploy.tar.gz
scp D:\smartplate-deploy.tar.gz <user>@<vm-ip>:~/
```
The bundle is an allowlist (Dockerfile, deploy files, `backend/app`, the two production model folders, reference data,
frontend sources): no `.env`, `.env.bak`, backups, databases or datasets, and it refuses to build if any file looks like it
contains a key. Do not copy the project folder itself (it contains `backend/.env` and `backend/.env.bak`).

### F. Configure, build, preflight, start **[server]**
```bash
tar -xzf smartplate-deploy.tar.gz && cd smartplate
cp deploy/smartplate.env.example deploy/smartplate.env && chmod 600 deploy/smartplate.env
nano deploy/smartplate.env          # CORS_ORIGINS=https://<domain>; keys (or leave empty); keep the limit lines
echo "SITE_DOMAIN=<domain>" > deploy/.env
docker compose -f deploy/docker-compose.yml config --quiet && echo "compose file OK"
docker compose -f deploy/docker-compose.yml build                       # first build downloads TensorFlow etc.
docker compose -f deploy/docker-compose.yml run --rm --no-deps app python -m app.core.preflight   # must end "0 FAIL"
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps                          # app "healthy" after ~1-2 min
docker compose -f deploy/docker-compose.yml logs caddy | grep -i "certificate obtained"
```
The preflight checks production mode, Secure cookies, sign-in for paid providers, rate limits and caps, the trusted proxy,
that `/data` is a writable mounted volume, reference data, model files, Tesseract and the frontend. It prints whether each
key is present, never its value.

### G. Verify (from your laptop, not the VM) **[server]**
Free checks (anonymous requests never reach a paid provider):
```bash
curl -sI http://<domain>/ | head -n 3                     # 308 redirect to https://
curl -s https://<domain>/health                           # {"status":"ok",...,"environment":"production"}
curl -sI https://<domain>/ | grep -i strict-transport     # HSTS present
curl -s https://<domain>/api/models/status                # "ready" (first call loads the models)
curl -s https://<domain>/api/chat/status                  # "requires_login":true,"signed_in":false
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<domain>/api/chat \
     -H "Content-Type: application/json" -d '{"message":"hi"}'              # 401
curl -s -m 5 http://<vm-ip>:8000/health || echo "app port closed (correct)"
# rate limit: the 11th anonymous analysis within the hour is refused (uses your IP's anonymous quota for an hour)
for i in $(seq 1 11); do curl -s -o /dev/null -w "%{http_code} " -F "file=@apple.jpg" https://<domain>/api/analyze/food; done; echo
# a fake X-Forwarded-For must not reset it (expect 429):
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Forwarded-For: 203.0.113.99" -F "file=@apple.jpg" https://<domain>/api/analyze/food
# body size: 31 MB is refused before the app parses it (expect 413)
head -c 31000000 /dev/zero > big.bin && curl -s -o /dev/null -w "%{http_code}\n" -F "file=@big.bin" https://<domain>/api/analyze/food
```
Persistence: sign up in the browser, then `docker compose -f deploy/docker-compose.yml up -d --force-recreate app` on the VM
and sign in again: the account must still exist.

Paid path (**only after your approval**; costs one or two provider requests): signed in, analyse one photo; the result's
"How this was identified" names OpenAI or Gemini. On the VM this prints the day's request counts:
`docker compose -f deploy/docker-compose.yml exec app python -c "from app.services import usage_limits as u; print({p: u.used('provider:'+p, 86400) for p in u.PROVIDER_CAPS})"`

### H. Phones **[server]**
On one Android phone (Chrome) and one iPhone (Safari), **on mobile data with Wi-Fi off**: open `https://<domain>/analyze`,
check the padlock, take a photo with the in-page camera (allow the permission), analyse, sign up / sign in, open the chat
panel (it must ask for sign-in when signed out), then install to the home screen (section 6) and reopen from the icon.

### Updating and backups **[server]**
Update: copy a new bundle, extract over the old folder (keep `deploy/smartplate.env` and `deploy/.env`), then
`docker compose -f deploy/docker-compose.yml up -d --build`. The volumes are kept.
Backup (consistent SQLite copies while running; repeat daily, e.g. from cron, and copy them off the VM):
```bash
docker compose -f deploy/docker-compose.yml exec app python -c "import sqlite3; [sqlite3.connect('/data/'+n).backup(sqlite3.connect('/tmp/'+n)) for n in ('smartplate.db','smartplate_users.db')]"
mkdir -p ~/backups/$(date +%F)
for n in smartplate.db smartplate_users.db; do docker compose -f deploy/docker-compose.yml cp app:/tmp/$n ~/backups/$(date +%F)/; done
```
Volumes are named `smartplate_smartplate-data` (app data) and `smartplate_caddy-data` (certificates). Never run
`docker compose down -v`: it deletes them.

## 5. Environment variables (production)

Set in `deploy/smartplate.env` on the server (names only here; see `deploy/smartplate.env.example`):

| Variable | Value / meaning |
|---|---|
| `ENVIRONMENT` | `production`. Enforces `Secure` cookies and adds HSTS. |
| `CORS_ORIGINS` | `https://<your-domain>` |
| `AUTH_COOKIE_SECURE` / `AUTH_COOKIE_SAMESITE` | `true` / `lax` |
| `USDA_FDC_API_KEY` | Free key from api.data.gov; without it, foods outside the 24 classes get no nutrition (stated in the result). |
| `GEMINI_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_VISION_API_KEY` | Optional, paid; see section 3. |
| `*_ENABLED` switches | `false` never sends photos to that provider. |
| `PAID_PROVIDERS_REQUIRE_LOGIN`, `RATE_LIMITS_ENABLED`, `RATE_LIMIT_*`, `*_DAILY_LIMIT`, `MAX_REQUEST_MB`, `MAX_JSON_KB`, `MAX_CONCURRENT_ANALYSES` | Abuse controls, section 3 (defaults in `deploy/smartplate.env.example`). |

Set by the image (do not change unless you move files): `ENVIRONMENT=production`, `SERVE_FRONTEND_DIR`,
`DATABASE_PATH=/data/smartplate.db`, `AUTH_DATABASE_PATH=/data/smartplate_users.db`, the four `*_CSV` paths, `TESSERACT_CMD`,
`MAX_UPLOAD_MB=8`. Set by `docker-compose.yml`: `FORWARDED_ALLOW_IPS` (Caddy's address). In `deploy/.env` (read by Compose,
not by the app): `SITE_DOMAIN` (required), `SMARTPLATE_NET` (optional, section 4C).
Sessions: accounts created with a name use 14-day bearer sessions (`SESSION_DAYS`); cookie sessions last `AUTH_SESSION_DAYS`
(default 30).

## 6. Phones

- **Install:** the site has a web-app manifest and icons. On Android Chrome use *Add to Home screen / Install app*; on iPhone
  Safari use *Share → Add to Home Screen*. There is deliberately no offline mode: analysis always needs the server.
  Checked 2026-10-27 in desktop Chrome (headless, via the DevTools protocol): the manifest loads with no errors and the only
  installability objection was "in incognito" (the test browser always is). Installation on a real phone over HTTPS has
  **not** been tested yet; do that after deployment on one Android phone and one iPhone.
- **Camera:** the in-page live camera needs HTTPS (a "secure context"); on the deployed HTTPS site it works after the browser's
  permission prompt. If permission is denied, or on plain-HTTP local testing, the app shows *Take or choose a photo*, which
  opens the phone's own camera app or gallery instead.
- **Uploads:** max 8 MB per photo (three for a packaged scan); format is checked from the file content (JPG, PNG, WebP, BMP),
  not the file name; decompression bombs and tiny images are rejected.

## 7. Security checklist

- Secrets only in server environment variables; `.dockerignore` keeps `.env` out of the build context; nothing secret in the frontend.
- The container runs as a non-root user; only Caddy publishes ports.
- Responses carry `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and HSTS in production.
- Authenticated routes keep their existing checks; nothing was disabled for deployment.
- Rate limits, sign-in for paid providers, daily provider caps and request-size limits are on in production (section 3).
- Logs are rotated (5 × 10 MB per container); photos, OCR text, chat messages, keys and IPs are not logged.
- `python -m app.core.preflight` must report 0 FAIL before the site is made public (section 4F).
- Not changed, low risk: FastAPI's interactive API docs (`/docs`, `/openapi.json`) stay public; they list endpoints but expose
  no data or keys. `/health` shows the Python version.
- `deploy/smartplate.env` must keep `ENVIRONMENT=production`; set `PAID_PROVIDERS_REQUIRE_LOGIN=true` and `RATE_LIMITS_ENABLED=true` explicitly (the template does).
