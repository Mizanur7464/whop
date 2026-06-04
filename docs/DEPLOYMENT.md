# Deployment Guide

Three supported deploy targets. Pick one — they're all production-ready.
**Railway** is the recommended default (easiest, cheapest, fastest).

---

## Option A — Railway (recommended)

### 1. Push the code to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### 2. Create a Railway project
1. Go to [railway.app](https://railway.app) → **New Project**
2. **Deploy from GitHub repo** → select your repo
3. Railway detects the `Dockerfile` automatically

### 3. Set environment variables
In the Railway project → **Variables** tab, add every key from `.env.example`:

```
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_ADMIN_IDS=<your Telegram user ID>
TELEGRAM_MAIN_GROUP_ID=<negative number, e.g. -1001234567890>
WHOP_API_KEY=<from Whop dashboard>
WHOP_WEBHOOK_SECRET=<from Whop dashboard>
WHOP_COMPANY_ID=<biz_XXXXX>
AIRTABLE_API_KEY=<pat...>
AIRTABLE_BASE_ID=<appXXXXX>
ENVIRONMENT=production
```

### 4. Generate a public URL
Railway → **Settings** → **Networking** → **Generate Domain**.
You'll get something like `whop-bot-production.up.railway.app`.

### 5. Configure the webhook in Whop
1. Whop dashboard → **Developer** → **Webhooks** → **Add Endpoint**
2. URL: `https://<your-railway-domain>/webhook/whop`
3. Events: subscribe to
   - `membership.went_valid`
   - `membership.went_invalid`
   - `membership.cancel_at_period_end_changed`
   - `payment.succeeded`
   - `payment.failed`
4. Copy the **signing secret** → paste into Railway as `WHOP_WEBHOOK_SECRET`
5. Save → Railway auto-redeploys

### 6. Verify
```bash
curl https://<your-railway-domain>/healthz
# → {"status":"ok"}
```

In Telegram, DM the bot:
- `/start` → should see welcome
- `/whop_test` → should ping Whop API successfully
- `/airtable_check` → all tables ✅

---

## Option B — Render

### 1. Connect repo
[render.com](https://render.com) → **New** → **Web Service** → connect GitHub repo.
Render reads `render.yaml` automatically.

### 2. Set environment variables
On the service page → **Environment** tab → paste every key from `.env.example`.

### 3. Get the public URL
Available on the service overview, e.g. `whop-telegram-bot.onrender.com`.

### 4. Configure Whop webhook
Same as Railway step 5 above. URL is `https://<your-render-domain>/webhook/whop`.

### 5. Verify
Same as Railway step 6.

---

## Option C — Self-hosted VPS (Docker)

### 1. SSH into your server
```bash
ssh user@your-server
```

### 2. Install Docker (if not already)
```bash
curl -fsSL https://get.docker.com | sh
```

### 3. Clone + build
```bash
git clone https://github.com/<you>/<repo>.git
cd <repo>
cp .env.example .env
# Edit .env with real values
nano .env
docker build -t whop-bot .
```

### 4. Run
```bash
docker run -d \
  --name whop-bot \
  --restart unless-stopped \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/data:/app/data \
  whop-bot
```

### 5. HTTPS (required for Whop webhooks)
Use Caddy or nginx + Let's Encrypt to put HTTPS in front of port 8000.

**Quick Caddy example** (`/etc/caddy/Caddyfile`):
```
yourdomain.com {
    reverse_proxy localhost:8000
}
```

### 6. Configure Whop webhook
URL: `https://yourdomain.com/webhook/whop`

### 7. Check logs
```bash
docker logs -f whop-bot
```

---

## Pre-deploy smoke test

Before pointing customers at the bot, run:
```bash
python scripts/smoke_test.py
```

Expected output: all green ✓.

If anything fails, fix it locally first — don't deploy a broken build.

---

## Post-deploy admin checklist

- [ ] Bot responds to `/start` in Telegram
- [ ] `/whop_test` returns ✅
- [ ] `/airtable_check` shows all tables OK
- [ ] Test webhook: trigger a Whop test event, check Airtable for the new row
- [ ] Make a real $1 test purchase, complete `/claim`, verify access
- [ ] Cancel the test membership, verify auto-removal
- [ ] Confirm daily digest arrives at 08:00 UTC

---

## Rolling back

### Railway / Render
Both keep deployment history. Open the **Deployments** tab and click
**Redeploy** on a previous successful build.

### Docker / VPS
```bash
docker stop whop-bot
docker rm whop-bot
git checkout <previous-good-commit>
docker build -t whop-bot .
docker run -d ...  # same flags as before
```

---

## Updating to a new version

1. `git pull` (or push from local)
2. Railway/Render auto-deploy on push
3. For VPS: `docker build` + `docker stop && docker rm && docker run`

Persistent files (`logs/`, `data/`) survive redeploys when mounted as volumes.

---

## Costs (estimated, monthly)

| Service | Plan | Cost |
|---|---|---|
| Railway | Hobby | $5 |
| Render | Starter | $7 |
| VPS (DigitalOcean, Hetzner) | smallest | $4–6 |
| Airtable | Free tier (1k records/base) | $0 |
| Airtable | Team (50k records) | $20/user |
| Whop API | Included with Whop account | $0 |

**Total minimum: ~$5/month** (Railway + Airtable free tier).
