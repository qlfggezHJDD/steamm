# Steam Dead Game Ranker — Render + Discord

Runs weekly, scores your 4,878 Steam games for "deadness + dev need",
and posts the top results + a full Excel file to your Discord channel.

---

## Files

```
steam-ranker/
├── scorer.py          ← main script
├── steam_links.txt    ← your 4878 links (add this yourself)
├── requirements.txt
├── render.yaml        ← Render cron config
└── README.md
```

---

## Step 1 — Discord webhook

1. Open your Discord server → channel settings → **Integrations** → **Webhooks**
2. Click **New Webhook**, give it a name (e.g. `Steam Ranker`)
3. Copy the webhook URL — looks like:
   `https://discord.com/api/webhooks/1234567890/xxxxxxxxxxxx`

---

## Step 2 — GitHub repo

1. Create a **new private GitHub repo**
2. Push all files including `steam_links.txt`:
   ```bash
   git init
   git add .
   git commit -m "init"
   git remote add origin https://github.com/YOU/steam-ranker.git
   git push -u origin main
   ```

---

## Step 3 — Deploy on Render

1. Go to [render.com](https://render.com) → **New** → **Cron Job**
2. Connect your GitHub repo
3. Render auto-detects `render.yaml` — confirm the settings
4. Under **Environment Variables**, add:
   - `DISCORD_WEBHOOK_URL` → paste your webhook URL here (mark as secret)
5. Click **Save** and **Deploy**

Render will run the job every **Monday at 08:00 UTC**.
To run it immediately: go to your cron job → **Trigger Run**.

---

## Environment variables (all optional except DISCORD_WEBHOOK_URL)

| Variable            | Default          | Description                              |
|---------------------|------------------|------------------------------------------|
| `DISCORD_WEBHOOK_URL` | *(required)*   | Your Discord webhook URL                 |
| `LINKS_FILE`        | `steam_links.txt`| Path to your links file                  |
| `TOP_N`             | `30`             | How many top games to post to Discord    |
| `MAX_PER_RUN`       | `500`            | Max games per run (Render has a 15-min cron limit) |
| `BATCH_DELAY_S`     | `1.5`            | Delay between Steam API calls (seconds)  |

**Note on MAX_PER_RUN:** Steam rate-limits at ~200 req/min, and each game takes
~3 API calls (~4.5s). At `MAX_PER_RUN=500` each run takes ~37 minutes — fine for
a Render cron job (no time limit on cron, only on web services). You can set it
higher or to `9999` to process all games in one run.

---

## What Discord receives

Each Monday you'll get:

1. **Header message** — total stats (games processed, zero-review count, solo devs)
2. **Top 30 games** — listed with score, price, reviews, dev info, Steam link
3. **Full Excel file** — all games ranked, color-coded by score

### Score legend
| Color  | Score  | Meaning                                      |
|--------|--------|----------------------------------------------|
| 🟢 Green | 70–100 | Most dead + most needy → priority picks    |
| 🟡 Yellow| 40–69  | Moderately obscure                          |
| 🔴 Red   | 0–39   | Not very dead or dev has many other games   |

### Scoring breakdown
| Signal              | Weight | Logic                                         |
|---------------------|--------|-----------------------------------------------|
| Review count        | 30%    | Fewer reviews = more obscure                  |
| Days since release  | 20%    | Older = more abandoned                        |
| Dev's total games   | 25%    | Fewer games = more dependent on this one      |
| Price               | 15%    | Very cheap = possibly struggling              |
| Review ratio        | 10%    | Divisive or unknown = extra signal            |

---

## Changing the schedule

Edit `render.yaml` → `schedule` (standard cron syntax):

```
"0 8 * * 1"    → every Monday 08:00 UTC  (default)
"0 9 1 * *"    → 1st of every month
"0 18 * * 5"   → every Friday 18:00 UTC
```
