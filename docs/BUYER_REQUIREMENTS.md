# Buyer Requirements Checklist

Send this list to the buyer to collect everything we need before Phase 2.
Organized by priority — Must-Have first.

---

## 🔴 MUST-HAVE (cannot start without these)

### Whop
- [ ] Existing Whop store URL or confirmation that we need to set it up
- [ ] List of products/plans and their prices (e.g. Monthly $X, Yearly $Y, VIP $Z)
- [ ] Confirmation that buyer can grant API access (some Whop tiers limit this)
- [ ] Should different plans get access to different Telegram groups?

### Telegram
- [ ] Group, Channel, or both?
- [ ] Private or Public?
- [ ] How many groups/channels in total? (list each one)
- [ ] Mapping: which plan → which group(s)?

### Onboarding
- [ ] Reference community/bot (optional, but very helpful)
- [ ] Welcome message — will buyer provide text, or should we draft?
- [ ] Language: English only, or multi-language?

### Checklist
- [ ] List of tasks the checklist should contain (sample)
- [ ] User self-marks vs. admin marks?
- [ ] Reward on completion? (badge, role upgrade, certificate, nothing)

### Airtable
- [ ] Existing Airtable workspace? (or we set up fresh)
- [ ] Currency for finance (USD/EUR/GBP/other)
- [ ] Expense categories (e.g. ads, tools, salary, software)
- [ ] Reporting frequency — weekly or monthly P&L?

---

## 🟡 SHOULD-HAVE (clarify before Phase 3)

### Business Logic
- [ ] Subscription expiry → auto-remove from group, or grace period?
- [ ] Refund → immediate removal?
- [ ] Failed payment → warning message?
- [ ] Manual ban/unban via bot?
- [ ] Broadcast / mass-message feature needed?

### Reporting
- [ ] Key metrics: MRR, churn %, active users, others?
- [ ] Daily/weekly email report?
- [ ] Threshold alerts (e.g. revenue goal hit)?

### Scaling
- [ ] Expected member count in 6 months
- [ ] Future expansion to Discord or other platforms?

---

## 🟢 ACCESS / CREDENTIALS (needed before deployment)

| # | Item | Who provides |
|---|---|---|
| 1 | Whop API Key | Buyer |
| 2 | Whop Company ID | Buyer |
| 3 | Whop Product IDs (per plan) | Buyer |
| 4 | Telegram Bot Token | Developer creates, buyer owns |
| 5 | Telegram Group/Channel IDs | Bot must be admin first |
| 6 | Airtable Personal Access Token | Buyer |
| 7 | Airtable Base ID | Buyer (or auto-created) |
| 8 | Hosting account (Railway/Render) | Buyer pays ~$5/mo |
| 9 | Domain for webhook URL (optional) | Buyer |

---

## ⚪ COMMERCIAL TERMS (confirm in writing)

- [ ] Hosting cost owner (buyer pays directly or reimburses)
- [ ] Airtable plan owner (Free vs Pro $20/mo)
- [ ] Revision window (e.g. 14 days post-delivery, free fixes)
- [ ] Source code ownership — buyer gets full repo?
- [ ] Documentation/handover video needed?
- [ ] Maintenance contract after delivery? (separate offer)

---

## 📨 Ready-to-Send Message (English, for the buyer)

```
Hi! Thanks for confirming both orders 🚀

Quick start guide before we begin — could you share the following?
This will let me lock the timeline and start building today.

1. WHOP
   • Existing store URL (or do we set up fresh?)
   • List of products/plans + prices
   • Will different plans get access to different Telegram groups?

2. TELEGRAM
   • Group, Channel, or both? Private or Public?
   • How many in total?
   • Should I create them, or will you add me as admin to existing ones?

3. ONBOARDING & CHECKLIST
   • Any reference community/bot you'd like to model after?
   • Welcome message — provide text, or want me to draft it?
   • What tasks should the checklist contain? (a sample helps)

4. AIRTABLE
   • Existing workspace, or fresh setup?
   • Currency for finance tracking?
   • Expense categories you want?
   • Weekly or monthly P&L report?

5. EDGE CASES
   • What should happen on subscription expiry / refund / failed payment?
   • Need broadcast (mass-message) feature?

ACCESS (needed when we kick off — not today)
   • Whop API key + product IDs
   • Telegram admin rights for groups/channels
   • Airtable API token
   • Hosting account (Railway, ~$5/mo)

Once I have these, I'll send a confirmed day-by-day timeline 👍
```
