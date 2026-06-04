# Testing Guide

End-to-end test scenarios. Run these before delivering to the buyer
and again after any major change.

---

## Quick Reference

| Test | Estimated time | Reset needed? |
|---|---|---|
| Smoke test (automated) | 30 seconds | No |
| Bot commands | 2 minutes | No |
| Onboarding flow | 5 minutes | Yes (`/onboarding`) |
| Whop → Telegram link | 10 minutes | Yes (new claim code) |
| Subscription cancellation | 5 minutes | Yes |
| Failed payment | 3 minutes | Yes |
| Airtable end-to-end | 10 minutes | No |
| Broadcast | 2 minutes | No |
| Daily digest | wait until 08:00 UTC | No |

---

## 1. Pre-flight smoke test

```bash
python scripts/smoke_test.py
```

Expected:
```
✓ TELEGRAM_BOT_TOKEN set
✓ WHOP_API_KEY set
✓ Bot token @YourBot (id=...)
✓ Whop API reachable
✓ Table 'Members' schema OK
...
All checks passed. Ready to deploy.
```

If any ✗ appears, fix before continuing.

---

## 2. Bot is alive

In Telegram, DM the bot:

| Step | Expected |
|---|---|
| `/start` | Welcome screen + Next/Skip buttons |
| `/help` | Command list (admin sees extra commands) |
| Tap *Profile* | Your profile shows |
| Tap *Support* | Support contacts |
| Tap *Back* | Returns to main menu |

---

## 3. Onboarding flow (fresh user)

1. Use a second Telegram account (or `/onboarding` to restart)
2. DM the bot `/start`
3. **Screen 1**: Welcome → tap *Next*
4. **Screen 2**: Rules → tap *Next*
5. **Screen 3**: Checklist appears (e.g. 4 items, 0 done)
6. Tap each checklist item → progress bar updates ▰▰▰▱▱▱▱▱▱▱
7. Tap the last item → completion message appears
8. **Admin** receives DM: "✅ Onboarding completed"
9. Run `/onboarding` → can restart anytime

---

## 4. Whop → Telegram link (full purchase flow)

### Sandbox (recommended first)
1. In Whop dashboard → enable sandbox mode if available
2. Make a test purchase
3. Watch logs: `Webhook received: membership.went_valid`
4. Watch logs: `Created pending claim ABC12345 ...`
5. Customer DMs bot: `/claim ABC12345`
6. Bot DMs invite link(s)
7. Click invite → joins group
8. Check Airtable Members table → new row with plan + Active status

### Production (real $1 test)
Same as above but with a real (cheap) product.

---

## 5. Subscription cancellation

1. Cancel the test membership in Whop dashboard
2. Watch logs: `Webhook received: membership.went_invalid`
3. Bot kicks user from group (clean kick, not permanent ban)
4. Customer receives DM: "Your access has been removed (membership ended)"
5. Airtable Members table → Status changes to *Expired*

---

## 6. Failed payment

1. In Whop, simulate a failed renewal
2. Customer receives DM: "⚠️ Your most recent payment failed..."
3. User stays in group (no immediate removal — they get a chance to update card)

---

## 7. Airtable end-to-end

### Schema validation
```
/airtable_check
```
Expected: all 4 tables ✅, no missing fields.

### Manual expense
```
/expense 75 USD Ads Test campaign May
```
Open Airtable Expenses table → new row with amount, currency, category.

### Revenue summary
```
/revenue 30
```
Output: total revenue last 30 days, grouped by currency.

### Full P&L
```
/pnl 30
```
Output: 🟢 USD → rev X, exp Y, net Z (per currency).

---

## 8. Admin commands

### /stats
Shows live counts: total, active, banned, new today.

### /broadcast
```
/broadcast Test announcement
```
- Confirm with inline buttons
- Tap *Send* → bot DMs all active users
- Result: "✅ Broadcast sent to N members"

### /ban / /unban
```
/ban 123456789
/unban 123456789
```
Status updates in Airtable + storage.

### /sync
Pulls all valid memberships from Whop, refreshes Airtable.

### /reload_config
Edit `data/onboarding.json` → `/reload_config` → no restart needed.

---

## 9. Daily digest

Wait until 08:00 UTC the next day, or temporarily change the hour in
`bot/main.py`:
```python
jobs.schedule_daily_report(app, hour_utc=<current_hour + 1>)
```
Restart the bot, wait one hour. All admins receive the digest DM.

---

## 10. Failure modes (what should NOT crash the bot)

| Scenario | Expected behavior |
|---|---|
| Airtable API down | Sync silently fails, log warning, Telegram still works |
| Whop API down | `/sync` returns clear error, bot still works |
| User blocked the bot | DM fails silently, logged, no crash |
| Bot kicked from group | revoke_access logs warning, no crash |
| Bad webhook signature | Returns 401, doesn't process |
| Webhook missing fields | Logs warning, no crash |
| Onboarding config typo | Bot refuses to start with clear error (caught at boot) |
| User runs `/claim` with bad code | Friendly "code not found" message |

---

## 11. Recovery test

Stop the bot mid-session → restart → verify:
- User snapshot loaded
- Pending claims preserved
- Whop ID links preserved
- Reminders re-scheduled on next user interaction

```bash
# Stop
docker stop whop-bot
# Or kill the process

# Restart
docker start whop-bot
# Or: python run.py
```

User state persists via JSON files in `logs/`.

---

## Regression checklist (run before every release)

- [ ] Smoke test passes
- [ ] `/start` welcomes new user
- [ ] Onboarding can be completed end-to-end
- [ ] Test purchase → claim code → group invite delivered
- [ ] Test cancellation → user kicked
- [ ] `/expense` writes to Airtable
- [ ] `/pnl` returns sensible numbers
- [ ] `/broadcast` reaches all active users
- [ ] Admin gets error alert when something crashes
