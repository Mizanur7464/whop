# Whop success page (activation code)

Set `WHOP_FREE_ACCESS=true` in `.env` / Railway while using a **free** Whop link
(tracking only — no “payment” wording in bot or success page).

After checkout, redirect customers to:

```
https://web-production-be26f.up.railway.app/whop/success?membership_id={membership_id}
```

Replace the host with your Railway domain. In Whop, use whatever variable they offer for
membership id (`{membership_id}`, `{id}`, etc.).

## What the customer sees

1. “Payment successful” page
2. Activation code appears within a few seconds (polls until the webhook runs)
3. **Open Telegram bot** button + `/claim CODE` instruction

## Env (Railway)

| Variable | Example |
|----------|---------|
| `PUBLIC_WEBHOOK_URL` | `https://your-app.up.railway.app/webhook/whop` |
| `PUBLIC_APP_BASE_URL` | `https://your-app.up.railway.app` (optional) |

## Fallback

If the code does not appear (webhook delay), the page tells the user to open the bot and
send `/claim`, then their Whop checkout email.
