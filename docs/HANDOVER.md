# Handover Document

This is the single source of truth for everything the buyer needs to
own, operate, and extend the system after delivery.

> **Read this end-to-end at least once.** It will save hours later.

---

## 1. What you've received

A fully-automated Telegram membership system that:

| Capability | Where it lives |
|---|---|
| Accepts payments via Whop | (your Whop store) |
| Auto-grants Telegram group access | bot + Whop webhook |
| Multi-step onboarding | Telegram bot |
| Trackable checklist per user | bot + Airtable |
| Member CRM | Airtable Members table |
| Payment ledger | Airtable Payments table |
| Manual expense logging | bot `/expense` → Airtable |
| Live P&L | bot `/pnl` |
| Daily digest at 08:00 UTC | bot scheduled job |

---

## 2. Project structure (1-minute tour)

```
whop netherlands/
├── bot/           # Telegram bot code
├── integrations/  # Whop API + webhook receiver
├── airtable/      # CRM + finance sync
├── data/          # onboarding.json (edit anytime)
├── docs/          # All documentation (this file lives here)
├── scripts/       # smoke_test.py
├── logs/          # Runtime logs + state (don't delete)
├── run.py         # Production entry point
└── .env           # Your secrets (NEVER commit)
```

---

## 3. Credentials map

| Credential | Where to get | Where it goes |
|---|---|---|
| Telegram Bot Token | @BotFather → `/newbot` | `.env` → `TELEGRAM_BOT_TOKEN` |
| Telegram Bot Username | BotFather output | `.env` → `TELEGRAM_BOT_USERNAME` |
| Your Telegram User ID | @userinfobot → `/start` | `.env` → `TELEGRAM_ADMIN_IDS` |
| Telegram Group/Channel IDs | Forward msg to @RawDataBot | `.env` → `TELEGRAM_*_GROUP_ID` |
| Whop API Key | Whop → Developer → API keys | `.env` → `WHOP_API_KEY` |
| Whop Company ID | Whop dashboard URL `biz_...` | `.env` → `WHOP_COMPANY_ID` |
| Whop Webhook Secret | Whop → Developer → Webhooks | `.env` → `WHOP_WEBHOOK_SECRET` |
| Whop Product IDs | Whop → Products | `.env` → `WHOP_PRODUCT_*` |
| Airtable PAT | airtable.com/create/tokens | `.env` → `AIRTABLE_API_KEY` |
| Airtable Base ID | Airtable URL `appXXX...` | `.env` → `AIRTABLE_BASE_ID` |

**Lost a credential?** Each provider lets you regenerate. Update `.env`
and redeploy.

---

## 4. Day-to-day operations

### How customers get access
1. Customer pays on your Whop store (you don't touch anything)
2. Whop sends a webhook to the bot
3. Bot creates a unique 8-character claim code
4. Whop's success page / email tells customer to DM the bot:
   `/claim XXXXXXXX`
5. Bot links accounts + sends one-time group invite link
6. Customer joins → automated welcome + checklist

### Whop receipt customization (do this once)
In Whop → your product → **Success page** / **Email**, paste:

```
Welcome! To activate your access, message our bot:

https://t.me/<YOUR_BOT_USERNAME>

Then send: /claim {{custom_claim_code}}

(If you don't see the code yet, refresh this page in 30 seconds.)
```

> Replace `{{custom_claim_code}}` with the variable Whop offers, or
> just instruct the user to wait for the email — the bot also accepts
> any code that exists in `pending_claims.json`.

If Whop doesn't support custom variables, instead say:
"You'll receive your claim code by email within 1 minute."
Then your bot's claim-code email is sent manually by you (or via an
email automation you set up later).

### Daily operations (your routine)

| Frequency | Task | How |
|---|---|---|
| Daily | Check digest DM | Look at your Telegram |
| Daily | Log expenses | `/expense 75 USD Ads ...` |
| Weekly | Run `/pnl 7` | Telegram |
| Weekly | Skim Airtable Members for churn risk | Airtable |
| Monthly | Run `/sync` (reconcile) | Telegram |
| As needed | Broadcast announcements | `/broadcast <message>` |
| As needed | Reload onboarding content | edit `data/onboarding.json` → `/reload_config` |

---

## 5. Telegram bot commands cheatsheet

### Public (any member)
- `/start` — main menu
- `/profile` — your account info
- `/checklist` — onboarding tasks
- `/onboarding` — restart the flow
- `/claim <code>` — link a Whop purchase
- `/support` — contact info
- `/help` — show commands

### Admin only
- `/stats` — member counts
- `/broadcast <message>` — message all active members
- `/ban <user_id>` / `/unban <user_id>`
- `/sync` — refresh memberships from Whop
- `/whop_test` — ping Whop API
- `/airtable_check` — validate Airtable schema
- `/claims` — list pending claim codes
- `/reload_config` — re-read `data/onboarding.json`
- `/expense <amount> <currency> <category> <description>`
- `/revenue [days]` / `/expenses [days]` / `/pnl [days]`
- `/status` — build phase status

---

## 6. Customization

### Change welcome/rules/checklist text
1. Edit `data/onboarding.json` (any text editor — it's plain JSON)
2. Send `/reload_config` to the bot
3. New users see the updated content immediately

### Add a new checklist item
Inside `data/onboarding.json`:
```json
"checklist_items": [
  {
    "id": "join_intro_call",
    "title": "Join the intro call",
    "description": "Calendar link is in the pinned message.",
    "self_mark": true
  }
]
```
Run `/reload_config`.

### Change which plan goes to which Telegram group
1. Get the product ID from Whop → product details
2. Edit `.env`:
   ```
   WHOP_PRODUCT_VIP=prod_NEW_ID_HERE
   ```
3. Redeploy (Railway auto-redeploys on `.env` change)

### Add a new admin
1. Get their Telegram User ID (@userinfobot)
2. Edit `.env`:
   ```
   TELEGRAM_ADMIN_IDS=123456789,987654321
   ```
3. Redeploy

### Change the daily digest time
Edit `bot/main.py`:
```python
jobs.schedule_daily_report(app, hour_utc=14)  # 14:00 UTC
```
Redeploy.

---

## 7. Troubleshooting

### Bot doesn't respond
1. Check Railway/Render logs for crash
2. `/whop_test` from an admin — confirms bot is alive
3. Bot might be paused — restart the service

### Webhook not firing
1. Whop → Webhooks → check delivery log
2. Confirm URL is `https://<your-domain>/webhook/whop`
3. Confirm `WHOP_WEBHOOK_SECRET` matches Whop's setting

### Customer says they didn't get a claim code
1. Check `logs/pending_claims.json` for their `whop_user_id`
2. Use `/claims` (admin) to see all pending codes
3. Manually DM the customer the code

### Customer can't `/claim`
- Code might be expired or used — generate a new one by re-triggering
  the Whop webhook (terminate + re-create the membership)
- Or manually link: `/link <telegram_user_id> <whop_user_id>` (future feature)

### Group invite link doesn't work
- Bot might not be admin in the target group
- Or the bot lacks "invite users" permission
- Re-add the bot as admin with all permissions enabled

### Airtable rows missing
- Run `/airtable_check` — confirms schema
- Check Railway logs for "Airtable call failed"
- API token might be expired or scopes too narrow

---

## 8. Disaster recovery

### If the server crashes
- Railway auto-restarts on failure (configured in `railway.json`)
- For VPS: `docker restart whop-bot`
- All state (`data/`, `logs/`) is persisted on the host filesystem

### If you lose the `.env`
You can't — keep a backup in a password manager (1Password, Bitwarden).
Regenerating credentials is possible but cumbersome.

### If you lose Airtable data
- Airtable has 1-day record history on Free, 30-day on Team
- `/sync` re-populates Members from Whop's source of truth
- Payments rebuild from Whop webhooks (if you re-deliver them)

### If you need to migrate hosts
1. Tar up the project including `data/` and `logs/`
2. Deploy to new host (see DEPLOYMENT.md)
3. Update Whop webhook URL to point at new host
4. Done

---

## 9. Scaling thresholds

Built to comfortably handle:
- ~10,000 members
- ~1,000 events/day
- ~100 concurrent /commands

When you outgrow:
- **Airtable**: 1,000 records on Free tier. Upgrade to Team ($20/mo) at
  ~800 records to avoid surprises.
- **Storage JSON files**: ~50 MB before getting slow. At that point,
  migrate to Postgres (1-day job).
- **Webhook bursts**: BackgroundTasks queue prevents drops. If you see
  delays, switch to a real queue (RQ, Celery) — also a 1-day job.

---

## 10. Support & next steps

### What's included in delivery
- ✅ All code, committed and documented
- ✅ Production deployment configs (Railway/Render/Docker)
- ✅ This handover doc + 4 other docs in `docs/`
- ✅ Smoke test + regression checklist

### Free support window
14 days after final delivery, free fixes for:
- Bugs in delivered functionality
- Documentation gaps
- Deploy-blocking issues

Not included: new features, scope additions, UI redesigns.

### Future enhancement ideas (paid)
- Discord support alongside Telegram
- In-bot purchase upgrade (cross-sell from Basic → Premium)
- Web admin dashboard (vs. Airtable)
- AI assistant for Q&A inside the community
- Affiliate / referral program

---

## 11. Final checklist before going live

- [ ] All `.env` values filled in (no `YOUR_...` placeholders)
- [ ] `python scripts/smoke_test.py` passes
- [ ] Bot is added as admin in every target Telegram group/channel
- [ ] Whop webhook configured + secret matches `.env`
- [ ] Airtable schema verified with `/airtable_check`
- [ ] Tested one full purchase → claim → group → onboarding cycle
- [ ] Tested one cancellation → kick → Airtable update
- [ ] Deployed to Railway/Render with healthcheck green
- [ ] Daily digest scheduled and verified

When all 9 boxes are ticked, you're ready to take real customers.

Welcome to your fully-automated membership business 🚀
