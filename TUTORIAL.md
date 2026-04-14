# Weekend Slackbot — Full Setup Tutorial

This guide walks you through everything from creating the Slack app to running the bot on your machine.

---

## Prerequisites

- Python 3.8 or higher installed on your computer
- Admin access to your Slack workspace
- The bot files in your Slackbot folder (`bot.py`, `requirements.txt`, `.env.example`, `slack_manifest.json`)

---

## Step 1 — Create the Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) and sign in with your Slack workspace account.
2. Click **Create New App** in the top right.
3. Select **From a manifest**.
4. Choose your workspace from the dropdown and click **Next**.
5. Select the **JSON** tab, delete any placeholder text, and paste in the entire contents of `slack_manifest.json`.
6. Click **Next**, review the summary, then click **Create**.

You now have a Slack app configured with the correct permissions and settings.

---

## Step 2 — Generate an App-Level Token

This token lets the bot connect via Socket Mode (no public server needed).

1. In your new app's dashboard, click **Basic Information** in the left sidebar.
2. Scroll down to the **App-Level Tokens** section and click **Generate Token and Scopes**.
3. Give the token any name (e.g. `socket-token`).
4. Click **Add Scope** and select `connections:write`.
5. Click **Generate**.
6. Copy the token — it starts with `xapp-`. **Save this somewhere safe**, you'll need it shortly.

---

## Step 3 — Install the App and Get the Bot Token

1. In the left sidebar, click **OAuth & Permissions**.
2. Scroll up and click **Install to Workspace**, then click **Allow**.
3. You'll be redirected back to the OAuth & Permissions page.
4. Copy the **Bot User OAuth Token** — it starts with `xoxb-`. **Save this too.**

---

## Step 4 — Find Your Channel IDs

The bot needs channel IDs (not channel names) to know which channels to monitor.

**To find a channel ID in Slack (desktop app):**

1. Right-click the channel name in the left sidebar.
2. Click **View channel details**.
3. Scroll to the very bottom of the panel that opens.
4. The Channel ID is listed there (e.g. `C08L123ABC`).

Repeat this for every channel you want the bot to monitor. Copy all the IDs.

---

## Step 5 — Configure Your `.env` File

1. In your Slackbot folder, make a copy of `.env.example` and rename it `.env`.
   - On Mac/Linux: open a terminal in the folder and run `cp .env.example .env`
   - On Windows: duplicate the file in Explorer and rename it
2. Open `.env` in any text editor and fill in the three values:

```
SLACK_BOT_TOKEN=xoxb-your-actual-bot-token
SLACK_APP_TOKEN=xapp-your-actual-app-token
MONITORED_CHANNEL_IDS=C08L123ABC,C08L456DEF
```

Use commas (no spaces) to separate multiple channel IDs. Save the file.

> ⚠️ Never share or commit your `.env` file — it contains sensitive credentials.

---

## Step 6 — Invite the Bot to Your Channels

The bot must be a member of each channel it monitors.

1. In Slack, navigate to the first channel you want to monitor.
2. Type the following message and send it:
   ```
   /invite @Weekend Auto-Reply
   ```
3. Repeat for every channel in your `MONITORED_CHANNEL_IDS` list.

---

## Step 7 — Install Python Dependencies

1. Open a terminal (Mac/Linux) or Command Prompt / PowerShell (Windows).
2. Navigate to your Slackbot folder:
   ```bash
   cd path/to/your/Slackbot
   ```
3. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

---

## Step 8 — Run the Bot

In the same terminal, run:

```bash
python bot.py
```

You should see output like:

```
INFO  Monitoring channels: ['C08L123ABC', 'C08L456DEF']
INFO  Bolt app is running!
```

The bot is now live. Send a message to one of your monitored channels — if it's a weekend, it will reply automatically. If it's a weekday, it will log the message but stay silent.

---

## Step 9 — Keep the Bot Running (Optional)

The bot only runs while the terminal is open. To keep it running in the background:

**Mac/Linux — using `screen`:**
```bash
screen -S slackbot
python bot.py
# Press Ctrl+A then D to detach and leave it running in the background
# To return to it later: screen -r slackbot
```

**Mac/Linux — using `nohup`:**
```bash
nohup python bot.py > bot.log 2>&1 &
```

**Windows — using a batch file:**
Create a file called `run.bat` in your Slackbot folder with:
```
@echo off
python bot.py
```
Then run it and minimize the window.

---

## Customizing the Weekend Message

Open `bot.py` in a text editor and find this line near the top:

```python
WEEKEND_MESSAGE = (
    "👋 Thanks for your message! Our team is currently out of the office for the weekend. "
    "We'll get back to you first thing on Monday. Have a great weekend! 😊"
)
```

Edit the text to anything you like, save the file, and restart the bot.

---

## Adding or Removing Channels Later

Simply open your `.env` file, update `MONITORED_CHANNEL_IDS` with the new list of channel IDs, and restart the bot. Remember to also `/invite @Weekend Auto-Reply` to any newly added channels.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `KeyError: SLACK_BOT_TOKEN` | Your `.env` file is missing or not in the same folder as `bot.py` |
| Bot joins channel but doesn't reply | Double-check the channel ID in `.env` matches exactly |
| Bot replies on weekdays | Check your system clock timezone — the bot uses UTC |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| Bot replies to its own messages | This is prevented by the code — if it happens, check for duplicate bot users |
