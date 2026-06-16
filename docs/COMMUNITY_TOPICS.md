# Community setup — two groups + forum topics

## Layout overview

| Group | Purpose |
|-------|---------|
| **Welcome group** (`TELEGRAM_WELCOME_GROUP_ID`) | Entry group — Whop link, member chat in Members Community + Sign Up Support |
| **Main group** (`TELEGRAM_MAIN_GROUP_ID`) | Full community — all topics admin-only for members (Signals, Trading Talks, etc.) |

Rename the welcome supergroup in Telegram to **Fusion Strategy Members** (manual in Telegram settings).

## 1. Welcome group `.env`

```env
TELEGRAM_WELCOME_GROUP_ID=-1001234567890
TELEGRAM_WELCOME_GROUP_TOPIC_WELCOME=2
TELEGRAM_WELCOME_GROUP_TOPIC_NOTIFICATIONS=4
TELEGRAM_WELCOME_GROUP_TOPIC_MEMBERS_COMMUNITY=10
TELEGRAM_WELCOME_GROUP_TOPIC_SIGNUP_SUPPORT=11
TELEGRAM_WELCOME_GROUP_TOPIC_SIGNUP_INSTRUCTIONS=12
TELEGRAM_WELCOME_GROUP_TOPIC_RESULTS=13
TELEGRAM_WELCOME_GROUP_TOPIC_FEEDBACK=14
```

## 2. Main group `.env`

```env
TELEGRAM_COMMUNITY_LAYOUT=topics
TELEGRAM_MAIN_GROUP_ID=-1009876543210
TELEGRAM_TOPIC_TRADING_TALKS=20
TELEGRAM_TOPIC_MEMBERS_RESULTS=239
TELEGRAM_TOPIC_SIGNALS=5
TELEGRAM_TOPIC_COPYTRADING=6
TELEGRAM_TOPIC_SUPPORT=7
TELEGRAM_TOPIC_NOTIFICATIONS=4
TELEGRAM_TOPIC_PNL=
# Legacy — leave empty; Members Community moved to welcome group
TELEGRAM_TOPIC_EDUCATION=
```

Restart the bot after saving.

## 3. Get topic IDs

1. Open the topic in Telegram.
2. Send any message in that topic.
3. Run `/topicid` in that topic (admin only).
4. Copy the `message_thread_id` into the matching `.env` key.

Or use `/create_members_topic Sign Up Support` in the welcome group to create a topic and get the env line.

## 4. Bot moderation (automatic)

- **Main group:** deletes all non-admin member messages.
- **Welcome group:** allows member chat only in Members Community + Sign Up Support.
- **Link ban:** deletes messages with URLs/links in member-chat welcome topics.
- Bot must be group admin with **Delete messages**.

Optional overrides:

```env
GROUP_MODERATION_WELCOME_MEMBER_CHAT_TOPICS=10,11
GROUP_MODERATION_NO_LINKS_TOPICS=10,11
```

## 5. Private DM onboarding

Member flows run in private chat with the bot — not inside group topics.

Pin in **Sign Up Instructions**: “Open bot → /onboarding”.

Pin in **Feedback**: Airtable feedback form link.

## 6. After approval

Bot DMs the member a main group invite link. Topic permissions inside Telegram are set by admins — the bot enforces delete rules only.
