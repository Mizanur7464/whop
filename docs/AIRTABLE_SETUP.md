# Airtable Setup Guide

This guide walks the buyer through creating the Airtable base that the
bot will write into. Total time: ~15 minutes.

---

## 1. Create a Base

1. Go to [airtable.com](https://airtable.com) and sign in.
2. Click **+ Add a base** → **Start from scratch**.
3. Name it something like *Whop Community CRM*.
4. Copy the **Base ID** from the URL:
   `https://airtable.com/appXXXXXXXXXXXXXX/...`
                     ^^^^^^^^^^^^^^^^^
   That's your `AIRTABLE_BASE_ID` — add it to `.env`.

---

## 2. Create an API Token

1. Open [airtable.com/create/tokens](https://airtable.com/create/tokens).
2. Click **Create new token**.
3. Name it *Whop Bot*.
4. **Scopes** — enable:
   - `data.records:read`
   - `data.records:write`
   - `schema.bases:read`
   - `schema.bases:write` (required for `/airtable_setup` and `setup_airtable.py`)
5. **Access** — add the base you created in step 1.
6. Click **Create token**, copy the token (starts with `pat...`).
7. Paste into `.env` as `AIRTABLE_API_KEY`.

---

## 3. Create 3 Tables (+ Checklist)

Delete the default `Table 1` Airtable made, then create these tables.
Field names must match **exactly** — they're case-sensitive.

Or run `python scripts/setup_airtable.py` to auto-create tables **and add missing columns**.

In Telegram (admin): `/airtable_setup` does the same — buyer does not need the Airtable UI.

### Table 1 — `Members`

| Field name | Type | Notes |
|---|---|---|
| Telegram User ID | Single line text | **Primary field** |
| Telegram Username | Single line text | |
| Name | Single line text | |
| Email | Email | |
| Phone | Single line text | From onboarding contact step |
| Platform | Single select | Options: **Vantage, Premier** (Inside UAE → Vantage, Outside UAE → Premier) |
| Platform User ID | Single line text | Trading platform username / account ID |
| Whop User ID | Single line text | |
| Whop Membership ID | Single line text | |
| Plan | Single select | Options: Basic, Premium, VIP, unknown |
| Status | Single select | Options: Active, Expired, Banned, Pending |
| Join Date | Date (include time) | |
| Onboarding Completed | Checkbox | |
| Onboarding Completed At | Date (include time) | |
| Last Activity | Date (include time) | |
| Reminders Sent | Number | |
| Cancel At Period End | Checkbox | |
| Notes | Long text | |

### Table 2 — `Finance` (payments + expenses combined)

All revenue and costs live here for easy P&amp;L (filter by **Type**).

| Field name | Type | Notes |
|---|---|---|
| Entry ID | Single line text | **Primary field** — Whop payment ID or `exp-…` |
| Type | Single select | **Payment** or **Expense** |
| Member | Link to another record | Linked to `Members` |
| Amount | Number (decimal) | Gross; **allow negative values** |
| Fees | Number (decimal) | Whop / transaction fees; **allow negative values** |
| Net Amount | Number (decimal) | Amount minus fees; **allow negative values** |
| Currency | Single select | Options: **EUR, USD, GBP** |
| Date | Date (include time) | |
| Whop User ID | Single line text | Payments only |
| Plan | Single line text | Payments only |
| Status | Single select | Payments: Succeeded, Failed, Refunded |
| Category | Single select | Expenses: Ads, Tools, Salary, Software, Hosting, Other |
| Description | Long text | Expenses only |
| Added By | Single line text | Expenses only — admin Telegram handle |
| Notes | Long text | |

Set `AIRTABLE_FINANCE_TABLE=Payments` in `.env` (default). Legacy name `Finance` also works.

### Table 3 — `Checklist`

| Field name | Type | Notes |
|---|---|---|
| Telegram User ID | Single line text | **Primary field** |
| Member | Link to another record | Linked to `Members` |
| Task ID | Single line text | |
| Task Title | Single line text | |
| Completed | Checkbox | |
| Completed At | Date (include time) | |

---

## 4. Recommended Views

### Members
- **Active members** — Filter: `Status = Active`
- **Onboarding pending** — Filter: `Onboarding Completed = false`
- **By platform** — Group by `Platform`

### Finance
- **Payments only** — Filter: `Type = Payment`
- **Expenses only** — Filter: `Type = Expense`
- **This month P&amp;L** — Group by `Type`, sum `Net Amount`

---

## 5. Auto-create tables (optional)

```bash
python scripts/setup_airtable.py
```

Creates `Members`, `Finance`, and `Checklist`. Delete unused tables like `Table 1` / old `Payments` / `Expenses` in the UI if you migrated.

---

## 6. Verify Setup

```
/airtable_check
```

You should see ✅ for **Members**, **Finance**, and **Checklist**.

---

## 7. Test Member Sync (status, plan, platform)

1. **Claim Whop** (or test purchase) → new row in **Members**, **Status = Active**
2. **`/onboarding`** → pick location (Inside UAE = Vantage PDF, Outside = Premier PDF)
3. Enter **email → phone → platform user ID** → check **Members** for Phone, Platform, Platform User ID
4. Complete checklist → T&amp;C → send screenshot → admin **Approve**
5. **Members** should show **Status = Active**, **Onboarding Completed = checked**, correct **Plan**

Quick bot checks: `/airtable_check`, `/pnl 30`, `/expense 10 USD Ads test`

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `❌ Airtable not configured` | `.env` missing keys |
| `Missing fields: X` | Field name typo in Airtable |
| Status stuck on Pending | Old bot version — redeploy latest |
| Plan = unknown | Set `WHOP_PRODUCT_*` in Railway or rely on Whop product title |
| Finance empty | No Whop payment webhook yet — try `/expense` to test writes |
