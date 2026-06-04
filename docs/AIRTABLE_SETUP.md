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
5. **Access** — add the base you created in step 1.
6. Click **Create token**, copy the token (starts with `pat...`).
7. Paste into `.env` as `AIRTABLE_API_KEY`.

---

## 3. Create 4 Tables

Delete the default `Table 1` Airtable made, then create these four
tables. Field names must match **exactly** — they're case-sensitive.

### Table 1 — `Members`

| Field name | Type | Notes |
|---|---|---|
| Telegram User ID | Single line text | **Primary field** |
| Telegram Username | Single line text | |
| Name | Single line text | |
| Email | Email | |
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

### Table 2 — `Payments`

| Field name | Type | Notes |
|---|---|---|
| Payment ID | Single line text | **Primary field** |
| Member | Link to another record | Linked to `Members` |
| Whop User ID | Single line text | |
| Amount | Number (decimal) | |
| Currency | Single line text | e.g. USD, EUR |
| Plan | Single line text | |
| Date | Date (include time) | |
| Status | Single select | Options: Succeeded, Failed, Refunded |
| Notes | Long text | |

### Table 3 — `Expenses`

| Field name | Type | Notes |
|---|---|---|
| Date | Date (include time) | **Primary field** |
| Category | Single select | Options: Ads, Tools, Salary, Software, Hosting, Other |
| Amount | Number (decimal) | |
| Currency | Single line text | |
| Description | Long text | |
| Added By | Single line text | Telegram username of admin |
| Notes | Long text | |

### Table 4 — `Checklist`

| Field name | Type | Notes |
|---|---|---|
| Telegram User ID | Single line text | **Primary field** |
| Member | Link to another record | Linked to `Members` |
| Task ID | Single line text | |
| Task Title | Single line text | |
| Completed | Checkbox | |
| Completed At | Date (include time) | |

---

## 4. (Optional) Recommended Views

In Airtable each table can have multiple views. Useful presets:

### Members
- **Active members** — Filter: `Status = Active`
- **Onboarding pending** — Filter: `Onboarding Completed = false`
- **Churn list** — Filter: `Status = Expired` last 30 days

### Payments
- **This month** — Filter: `Date this month`
- **Failed only** — Filter: `Status = Failed`

### Expenses
- **This month** — Filter: `Date this month`
- **By category** — Group by `Category`

---

## 5. Auto-create tables (optional)

If the base is empty (only default `Table 1`), run:

```bash
python scripts/setup_airtable.py
```

This creates `Members`, `Payments`, `Expenses`, and `Checklist` with the
correct fields. You can delete `Table 1` and any test tables in the UI.

---

## 6. Verify Setup

Once `.env` has both `AIRTABLE_API_KEY` and `AIRTABLE_BASE_ID`, run the
bot and DM yourself:

```
/airtable_check
```

You should see ✅ next to each table. Any ❌ means a field name typo
or a missing table — fix it in Airtable and re-run.

---

## 7. Test the Pipeline

Once schema is green:

```
/expense 50 USD Ads Test entry
/revenue 30
/expenses 30
/pnl 30
```

These should all return data (zeroes are fine for an empty base).

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `❌ Airtable not configured` | `.env` missing keys |
| `Missing fields: X` | Field name typo in Airtable |
| `Permission denied` | API token lacks access to base or `data.records:write` |
| Empty revenue / expenses | No payments synced yet — make a test purchase |
| Records appear without member link | `/sync` has not run since `Member` was added |
