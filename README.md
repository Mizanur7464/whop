# Whop × Telegram × Airtable — Membership Automation

A turnkey automation system that turns a Whop paid product into a
fully-managed Telegram community with built-in CRM and finance tracking.

> **Status:** All 6 phases complete — production ready ✅

---

## What it does

```
   Customer pays on Whop
            │
            ▼
   Whop webhook fires
            │
            ▼
   Bot adds user to correct Telegram group
            │
            ▼
   Bot sends onboarding + checklist
            │
            ▼
   Airtable CRM auto-updates (member + revenue)
            │
            ▼
   Owner sees live dashboard (members, P&L, churn)
```

Zero manual work. Pay → Access → Track → Report.

---

## Project status

| Phase | Scope | Status |
|---|---|---|
| 1 | Setup & Requirements | ✅ Complete |
| 2 | Telegram Bot Build | ✅ Complete |
| 3 | Whop Integration | ✅ Complete |
| 4 | Onboarding + Checklist | ✅ Complete |
| 5 | Airtable CRM | ✅ Complete |
| 6 | Deployment & Handover | ✅ Complete |

---

## Documentation

| File | Purpose |
|---|---|
| `docs/HANDOVER.md` | **Start here** — full owner's manual |
| `docs/DEPLOYMENT.md` | Step-by-step Railway / Render / VPS deploy |
| `docs/TESTING.md` | Smoke tests + regression scenarios |
| `docs/AIRTABLE_SETUP.md` | One-time Airtable base + token creation |
| `docs/BUYER_REQUIREMENTS.md` | Original requirements checklist |
| `docs/PROJECT_PLAN.md` | Phase-by-phase implementation plan |

---

## Quick start

### 1. Install + configure
```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate    # Mac / Linux
pip install -r requirements.txt
copy .env.example .env
# Edit .env with your real credentials
```

### 2. Verify everything works
```bash
python scripts/smoke_test.py
```

### 3. Run locally
```bash
python run.py
```
Bot polling + webhook server start in one process.

### 4. Deploy to production
See `docs/DEPLOYMENT.md`. TL;DR: push to GitHub → connect Railway →
set env vars → done in 5 minutes.

---

## What's inside

```
whop netherlands/
├── bot/                       # Telegram bot
│   ├── main.py                # Entry point
│   ├── handlers/              # /start, /help, /claim, /broadcast, ...
│   ├── jobs.py                # Reminders + daily digest
│   ├── keyboards.py           # All inline keyboards
│   ├── onboarding_config.py   # Hot-reloadable buyer config
│   ├── storage.py             # In-memory + JSON snapshot
│   └── texts.py               # All user-facing strings
│
├── integrations/              # External services
│   ├── whop_api.py            # Whop REST client
│   ├── whop_webhook.py        # FastAPI webhook receiver
│   ├── whop_events.py         # Event dispatcher
│   ├── telegram_ops.py        # Invite links, kicks, DMs
│   └── plan_mapping.py        # Product ID → chat ID
│
├── airtable/                  # CRM
│   ├── client.py              # Pyairtable wrapper w/ retries
│   ├── sync.py                # High-level sync calls
│   └── schema.py              # Single source of truth for fields
│
├── data/onboarding.json       # Editable welcome / rules / tasks
├── docs/                      # All documentation
├── scripts/smoke_test.py      # Pre-flight verification
├── Dockerfile                 # Production container
├── railway.json               # Railway config
├── render.yaml                # Render config
├── Procfile                   # Generic PaaS
├── config.py                  # Pydantic settings loader
├── requirements.txt           # Python deps
├── run.py                     # Bot + webhook unified entry
└── .env.example               # Env template
```

---

## Tech stack

- **Python 3.10+** (3.12 in Docker)
- `python-telegram-bot[job-queue]` 21.x
- `fastapi` + `uvicorn` for webhooks
- `pyairtable` for CRM
- `httpx` for Whop API
- `pydantic-settings` for typed config
- `loguru` for logging

---

## Commands at a glance

**Members**
`/start` `/profile` `/checklist` `/onboarding` `/claim` `/support` `/help`

**Admin — members**
`/stats` `/broadcast` `/ban` `/unban`

**Admin — Whop**
`/sync` `/whop_test` `/claims`

**Admin — Airtable / finance**
`/airtable_check` `/expense` `/revenue` `/expenses` `/pnl`

**Admin — system**
`/reload_config` `/status`

---

## License

Private commercial project. All rights reserved.
