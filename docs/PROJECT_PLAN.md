# Project Plan — Whop × Telegram × Airtable

## Goal
Automate a Whop-powered paid Telegram community: payment → access →
onboarding → tracking → finance reporting.

## Orders
| Order | Scope | Price | Days |
|---|---|---|---|
| 1 | Telegram setup + Whop integration | $500 | 5–7 |
| 2 | Airtable CRM + automation | $800 | 4–6 |
| **Total** | | **$1,300** | **~10–14** |

---

## Phase Breakdown

### Phase 1 — Setup & Requirements (Day 1) ✅
- [x] Folder structure
- [x] `requirements.txt`
- [x] `.env.example` + `config.py`
- [x] `.gitignore` + `README.md`
- [x] Bot skeleton (`bot/main.py`)
- [x] Buyer requirements doc

### Phase 2 — Telegram Bot Build (Days 2–4) ✅
- [x] BotFather setup, set commands, set description
- [x] `/start` with inline-keyboard main menu
- [x] `/help`, `/profile`, `/checklist`, `/support`
- [x] Admin commands: `/broadcast`, `/ban`, `/unban`, `/stats`
- [x] Callback query routing
- [x] Conversation state for multi-step flows

### Phase 3 — Whop Integration (Days 5–6) ✅
- [x] `integrations/whop_api.py` — REST client
- [x] `integrations/whop_webhook.py` — FastAPI receiver
- [x] HMAC-SHA256 signature verification
- [x] Handlers: valid, invalid, cancel-at-period-end, payment success/fail
- [x] Auto add/remove user from correct Telegram group
- [x] Plan → Group mapping driven by `.env`
- [x] `/claim` flow for linking Whop ↔ Telegram

### Phase 4 — Onboarding + Checklist (Days 7–8) ✅
- [x] Multi-step onboarding (Welcome → Rules → Checklist)
- [x] Buyer-editable `data/onboarding.json` with hot reload
- [x] Per-user progress with live progress bar
- [x] Completion reward + admin notification
- [x] Reminder system (JobQueue, 24h cadence, max 2)

### Phase 5 — Airtable CRM (Days 9–11) ✅
- [x] Base schema: Members, Payments, Expenses, Checklist
- [x] `airtable/client.py` — typed wrapper with retry/backoff
- [x] Whop → Airtable sync (real-time on webhook)
- [x] Telegram activity → Airtable
- [x] `/expense`, `/revenue`, `/expenses`, `/pnl` admin commands
- [x] Daily digest job at 08:00 UTC
- [x] `/airtable_check` schema validator
- [x] `docs/AIRTABLE_SETUP.md` for buyer

### Phase 6 — Full Automation + Delivery (Days 12–14) ✅
- [x] Exponential backoff retries for Airtable
- [x] `scripts/smoke_test.py` pre-flight check
- [x] `Dockerfile` + `.dockerignore` + healthcheck
- [x] Railway, Render, Procfile configs
- [x] `docs/DEPLOYMENT.md` — Railway / Render / VPS
- [x] `docs/TESTING.md` — end-to-end scenarios + regression list
- [x] `docs/HANDOVER.md` — full owner's manual
- [x] README.md final polish
- [x] 14-day support window starts on delivery

---

## Risk & Mitigation

| Risk | Likelihood | Mitigation |
|---|---|---|
| Whop API access blocked by buyer's tier | Medium | Verify on Day 1 |
| Telegram bans bot for spam | Low | Rate-limit, use job queue |
| Airtable record limit (Free: 1000/base) | Medium | Buyer upgrades to Team plan if needed |
| Buyer changes requirements mid-build | High | Lock scope after Phase 1 sign-off |
| Webhook URL not reachable | Medium | Deploy early in Phase 3, use Railway HTTPS |

---

## Definition of Done (per phase)
1. All checklist items above complete
2. Manual smoke test passes
3. Code committed + pushed
4. Buyer notified with what was built

---

## Communication Cadence
- Daily progress update to buyer (1–2 lines + screenshot if relevant)
- End of each phase: short demo video
- Final delivery: walkthrough video + handover doc
