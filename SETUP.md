# Unanswered Message Alert Bot — Setup Guide

This bot watches specified Slack channels and posts an alert to a dedicated channel
whenever a message goes unanswered (no reply, no reaction) within the configured timeout.

---

## How it works

1. A human posts a message in a monitored channel.
2. The bot starts a timer for that message.
3. If **no reply** and **no reaction** arrives within the timeout (default: 2 hours), the bot posts
   an alert with a direct link to the unanswered message in the alert channel.
4. Any reply in the thread OR any emoji reaction cancels the timer immediately.

---

## Step 1: Create (or update) your Slack App

### If creating from scratch
1. Go to https://api.slack.com/apps and click **Create New App → From manifest**.
2. Paste the contents of `slack_manifest.json` from this repo.
3. Click **Next → Create**.

### If updating an existing app
1. Go to https://api.slack.com/apps and open your app.
2. In the left sidebar, click **App Manifest**.
3. Replace the entire manifest with the contents of `slack_manifest.json`.
4. Click **Save Changes**.

---

## Step 2: Enable Socket Mode

1. In the left sidebar, click **Socket Mode**.
2. Toggle **Enable Socket Mode** to ON.
3. When prompted, create an App-Level Token:
   - Name: `socket-token`
   - Scope: `connections:write`
   - Click **Generate**
4. Copy the token (starts with `xapp-`) — this is your `SLACK_APP_TOKEN`.

---

## Step 3: Verify Bot Scopes

Go to **OAuth & Permissions → Scopes → Bot Token Scopes** and confirm these four scopes are present:

| Scope | Purpose |
|---|---|
| `channels:history` | Read messages in public channels |
| `groups:history` | Read messages in private channels |
| `reactions:read` | Detect emoji reactions |
| `chat:write` | Post alert messages |

---

## Step 4: Verify Event Subscriptions

Go to **Event Subscriptions → Subscribe to bot events** and confirm these three events are listed:

- `message.channels`
- `message.groups`
- `reaction_added`

---

## Step 5: Install the App to your workspace

1. Go to **OAuth & Permissions** and click **Install to Workspace** (or **Reinstall** if updating).
2. Authorize the permissions.
3. Copy the **Bot User OAuth Token** (starts with `xoxb-`) — this is your `SLACK_BOT_TOKEN`.

---

## Step 6: Add the bot to channels

The bot must be a member of every channel it interacts with:

- **Each monitored channel** — invite with `/invite @Unanswered Alert`
- **The alert channel** — invite with `/invite @Unanswered Alert`

For private channels, you must do this manually from inside the channel.

---

## Step 7: Create your `.env` file

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```
SLACK_BOT_TOKEN=xoxb-...        # from Step 5
SLACK_APP_TOKEN=xapp-...        # from Step 2
MONITORED_CHANNEL_IDS=C...,C... # comma-separated IDs of channels to watch
ALERT_CHANNEL_ID=C...           # ID of the channel to post alerts in
RESPONSE_TIMEOUT_MINUTES=120    # 120 = 2 hours (change if needed)
```

**To find a channel ID:** Right-click the channel in Slack → View channel details → scroll to the bottom.

---

## Step 8: Install dependencies and run

```bash
pip install -r requirements.txt
python bot.py
```

You should see output like:

```
Monitoring channels : ['C12345678', 'C98765432']
Alert channel       : C00000000
Response timeout    : 120 minutes
⚡️ Bolt app is running!
```

---

## Keeping it running (optional)

To run continuously in the background on a server:

```bash
# Using nohup
nohup python bot.py > bot.log 2>&1 &

# Or with a process manager like pm2
pm2 start bot.py --interpreter python3 --name slack-alert-bot
```
