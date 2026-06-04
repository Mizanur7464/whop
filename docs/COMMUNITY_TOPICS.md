# Community setup — one group + topics

## 1. `.env` values

```env
TELEGRAM_COMMUNITY_LAYOUT=topics
TELEGRAM_MAIN_GROUP_ID=-1001234567890
TELEGRAM_TOPIC_WELCOME=2
TELEGRAM_TOPIC_COPYTRADING=5
TELEGRAM_TOPIC_SUPPORT=9
TELEGRAM_TOPIC_NOTIFICATIONS=4
TELEGRAM_TOPIC_PNL=
```

Optional: `TELEGRAM_TOPIC_PNL` only if you have a dedicated PnL topic (not the same as notifications).

Restart the bot after saving.

## 2. Get `TELEGRAM_MAIN_GROUP_ID`

1. Add `@RawDataBot` or `@getidsbot` to the group (or use Telegram Web).
2. Forward any message from the group → bot replies with chat id (starts with `-100`).

Or: add your bot, send a message in the group, check bot logs / `getUpdates`.

## 3. Get topic IDs (`message_thread_id`)

**Easy way:**

1. Open the topic (e.g. “Welcome”) in Telegram.
2. Send any message in that topic.
3. While the bot is running, read `logs/bot_*.log` or temporarily log `update.message.message_thread_id`.

**Or** use @RawDataBot on a message **inside** the topic — look for `message_thread_id`.

General topic (main chat) often has no thread id or `0` — use a dedicated Welcome topic instead.

## 4. Private DM only (member flows)

Member flows **do not run inside group topics** (avoids public chat history).

| Topic | What to pin |
|-------|-------------|
| Welcome | “Tap Open bot → complete onboarding in private chat” |
| Copy Trading | “Open bot → /copytrading in DM” |
| Support | “Open bot → /support in DM” |

If a member types `/start` in a topic, the bot replies with an **Open bot** button.

Admins can still use `/topicid` in the group.

## 5. After approval

Bot DMs the member:

- One invite link to the **main group** (if not already inside)
- List of topics to open

Topic permissions (who sees which thread) are set in Telegram group settings — not by this bot.
