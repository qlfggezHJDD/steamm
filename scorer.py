"""
Steam Dead Game Ranker — Render + Discord edition
Reads steam_links.txt, scores each game, sends top results to Discord webhook.
Designed to run as a cron job on Render.
"""

import json
import time
import re
import os
import io
import datetime
import requests
import pandas as pd
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

# ── CONFIG (from env vars) ────────────────────────────────────────────────────
DISCORD_WEBHOOK  = os.environ["DISCORD_WEBHOOK_URL"]
LINKS_FILE       = os.environ.get("LINKS_FILE", "steam_links.txt")
TOP_N            = int(os.environ.get("TOP_N", "30"))          # games sent to Discord
BATCH_DELAY_S    = float(os.environ.get("BATCH_DELAY_S", "1.5"))

# How many games to process per run (to stay within Render's 15-min cron limit)
# At ~4.5s/game → ~150 games / 11 min. Default: process everything but cap at 500 per run.
MAX_PER_RUN      = int(os.environ.get("MAX_PER_RUN", "500"))

PROGRESS_FILE    = "/tmp/steam_progress.json"   # resets between runs on Render (use for partial saves within one run)

# ── SCORING WEIGHTS ───────────────────────────────────────────────────────────
W = dict(
    review_count   = 0.30,
    review_ratio   = 0.10,
    last_update    = 0.20,
    dev_game_count = 0.25,
    price          = 0.15,
)

# ── HELPERS ───────────────────────────────────────────────────────────────────

def extract_appid(url: str) -> str | None:
    m = re.search(r'/app/(\d+)', url.strip())
    return m.group(1) if m else None

def steam_get(url: str, retries=3) -> dict | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 429:
                print(f"  Rate limited, sleeping 30s…")
                time.sleep(30)
                continue
            if r.status_code != 200:
                return None
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                print(f"  Request failed: {e}")
            time.sleep(2)
    return None

def fetch_app_details(appid: str) -> dict | None:
    data = steam_get(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=en")
    if not data or str(appid) not in data:
        return None
    entry = data[str(appid)]
    if not entry.get("success"):
        return None
    return entry.get("data", {})

def fetch_reviews(appid: str) -> dict:
    data = steam_get(
        f"https://store.steampowered.com/appreviews/{appid}"
        f"?json=1&language=all&purchase_type=all&num_per_page=0"
    )
    if not data:
        return {"total_reviews": 0, "total_positive": 0, "review_score_desc": ""}
    qs = data.get("query_summary", {})
    return {
        "total_reviews":     qs.get("total_reviews", 0),
        "total_positive":    qs.get("total_positive", 0),
        "review_score_desc": qs.get("review_score_desc", ""),
    }

def fetch_dev_game_count(developer: str) -> int:
    if not developer:
        return 1
    data = steam_get(
        f"https://store.steampowered.com/search/results/"
        f"?developer={requests.utils.quote(developer)}&json=1"
    )
    if not data:
        return 1
    return max(1, data.get("total_count", 1))

def parse_price(app_data: dict) -> float:
    po = app_data.get("price_overview", {})
    return po.get("final", 0) / 100.0 if po else 0.0

def parse_days_since_release(app_data: dict) -> int:
    rd = app_data.get("release_date", {})
    date_str = rd.get("date", "")
    if not date_str or rd.get("coming_soon"):
        return 9999
    for fmt in ("%b %d, %Y", "%d %b, %Y", "%Y", "%b %Y"):
        try:
            dt = datetime.datetime.strptime(date_str.strip(), fmt)
            return max(0, (datetime.datetime.now() - dt).days)
        except ValueError:
            continue
    return 9999

def score_game(g: dict) -> float:
    reviews   = g.get("total_reviews", 0)
    positive  = g.get("total_positive", 0)
    dev_games = g.get("dev_game_count", 1)
    price     = g.get("price_usd", 0.0)
    days      = g.get("days_since_release", 9999)

    review_score = 100 * max(0, 1 - reviews / 10_000)

    if reviews > 0:
        ratio = positive / reviews
        ratio_score = 100 * (1 - abs(ratio - 0.5) / 0.5) if ratio > 0.5 else 100 * (1 - ratio)
    else:
        ratio_score = 80

    update_score = min(100, days / (365 * 3) * 100)
    dev_score    = 100 * max(0, 1 - (dev_games - 1) / 9)

    if price == 0:
        price_score = 70
    elif price <= 5:
        price_score = 100
    elif price <= 15:
        price_score = 60
    elif price <= 30:
        price_score = 30
    else:
        price_score = 10

    return round(
        W["review_count"]   * review_score +
        W["review_ratio"]   * ratio_score  +
        W["last_update"]    * update_score +
        W["dev_game_count"] * dev_score    +
        W["price"]          * price_score,
        2
    )

# ── DISCORD ───────────────────────────────────────────────────────────────────

def send_discord_message(content: str):
    """Send a plain text message (≤2000 chars) to Discord."""
    requests.post(DISCORD_WEBHOOK, json={"content": content}, timeout=10)
    time.sleep(0.5)

def send_discord_file(file_bytes: bytes, filename: str, content: str = ""):
    """Upload a file to Discord."""
    requests.post(
        DISCORD_WEBHOOK,
        data={"content": content},
        files={"file": (filename, file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        timeout=60,
    )

def build_excel(rows: list[dict]) -> bytes:
    """Build and return the Excel file as bytes."""
    cols = [
        "support_score", "name", "developer", "genres",
        "release_date", "days_since_release", "price_usd",
        "total_reviews", "total_positive", "review_score_desc",
        "dev_game_count", "url",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df.index = range(1, len(df) + 1)
    df.index.name = "Rank"
    df.rename(columns={
        "support_score":     "Score",
        "name":              "Game",
        "developer":         "Developer",
        "genres":            "Genres",
        "release_date":      "Release Date",
        "days_since_release":"Days Old",
        "price_usd":         "Price $",
        "total_reviews":     "Reviews",
        "total_positive":    "Positive",
        "review_score_desc": "Review Label",
        "dev_game_count":    "Dev Games",
        "url":               "Steam URL",
    }, inplace=True)

    buf = io.BytesIO()
    df.to_excel(buf, sheet_name="Ranked", index=True)
    buf.seek(0)

    wb = openpyxl.load_workbook(buf)
    ws = wb.active

    hdr_fill = PatternFill("solid", fgColor="1F3864")
    hdr_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    for cell in ws[1]:
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 28

    score_col = next(
        (cell.column for cell in ws[1] if cell.value == "Score"), None
    )
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.font = Font(name="Arial", size=9)
            cell.alignment = Alignment(vertical="center")
        if score_col:
            s = row[score_col - 1].value or 0
            if s >= 70:
                row[score_col - 1].fill = PatternFill("solid", fgColor="C6EFCE")
                row[score_col - 1].font = Font(name="Arial", size=9, bold=True, color="276221")
            elif s >= 40:
                row[score_col - 1].fill = PatternFill("solid", fgColor="FFEB9C")
                row[score_col - 1].font = Font(name="Arial", size=9, color="9C5700")
            else:
                row[score_col - 1].fill = PatternFill("solid", fgColor="FFC7CE")
                row[score_col - 1].font = Font(name="Arial", size=9, color="9C0006")

    widths = [7, 9, 34, 22, 20, 12, 10, 9, 10, 9, 20, 10, 45]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

def post_top_n_to_discord(rows: list[dict], top_n: int, total_processed: int):
    """Post a summary embed + top games list + Excel file to Discord."""
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    top = rows[:top_n]

    # Header message
    header = (
        f"## 🎮 Steam Dead Game Report — {now}\n"
        f"**{total_processed}** games processed · "
        f"**{sum(1 for r in rows if r['total_reviews'] == 0)}** have zero reviews · "
        f"**{sum(1 for r in rows if r['dev_game_count'] == 1)}** from solo-game devs\n"
        f"Showing top **{top_n}** by Support Score (deadness + dev need)\n"
        f"─────────────────────────────────"
    )
    send_discord_message(header)
    time.sleep(1)

    # Send games in chunks of 10 (Discord 2000-char limit)
    chunk = []
    for i, g in enumerate(top, 1):
        price_str = "Free" if g["price_usd"] == 0 else f"${g['price_usd']:.2f}"
        reviews   = g["total_reviews"]
        dev_games = g["dev_game_count"]
        score     = g["support_score"]
        medal     = "🟢" if score >= 70 else "🟡" if score >= 40 else "🔴"

        line = (
            f"{medal} **#{i} {g['name']}** — Score: `{score}`\n"
            f"   {price_str} · {reviews} reviews · Dev has {dev_games} game(s) · "
            f"{g.get('release_date','?')}\n"
            f"   <{g['url']}>"
        )
        chunk.append(line)

        if len(chunk) == 10 or i == len(top):
            send_discord_message("\n".join(chunk))
            chunk = []
            time.sleep(0.5)

    # Send Excel
    excel_bytes = build_excel(rows)
    date_str = datetime.datetime.utcnow().strftime("%Y%m%d")
    send_discord_file(
        excel_bytes,
        filename=f"steam_dead_ranked_{date_str}.xlsx",
        content=f"📊 Full ranked list ({len(rows)} games)",
    )

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print(f"=== Steam Dead Ranker starting at {datetime.datetime.utcnow()} ===")

    with open(LINKS_FILE) as f:
        appids = [extract_appid(line) for line in f if line.strip()]
    appids = [a for a in appids if a]
    print(f"Total links: {len(appids)}")

    # Load any partial progress from this run
    progress = {}
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            progress = json.load(f)
        print(f"Resuming — {len(progress)} already done this run")

    processed = 0
    for i, appid in enumerate(appids):
        if appid in progress:
            continue
        if processed >= MAX_PER_RUN:
            print(f"Reached MAX_PER_RUN={MAX_PER_RUN}, stopping.")
            break

        print(f"[{i+1}/{len(appids)}] {appid}", end=" — ")

        app_data = fetch_app_details(appid)
        time.sleep(BATCH_DELAY_S)

        if not app_data:
            progress[appid] = {"appid": appid, "status": "not_found"}
            print("not found")
            processed += 1
            continue

        developer = (app_data.get("developers") or [""])[0]
        reviews   = fetch_reviews(appid)
        time.sleep(BATCH_DELAY_S)
        dev_games = fetch_dev_game_count(developer)
        time.sleep(BATCH_DELAY_S)

        rec = {
            "appid":             appid,
            "status":            "ok",
            "name":              app_data.get("name", ""),
            "developer":         developer,
            "genres":            ", ".join(g["description"] for g in app_data.get("genres", [])),
            "release_date":      app_data.get("release_date", {}).get("date", ""),
            "days_since_release":parse_days_since_release(app_data),
            "price_usd":         parse_price(app_data),
            "total_reviews":     reviews["total_reviews"],
            "total_positive":    reviews["total_positive"],
            "review_score_desc": reviews["review_score_desc"],
            "dev_game_count":    dev_games,
            "url":               f"https://store.steampowered.com/app/{appid}",
        }
        rec["support_score"] = score_game(rec)
        progress[appid] = rec
        processed += 1
        print(f"{rec['name'][:40]!r} → {rec['support_score']}")

        # Save partial progress every 50 games
        if processed % 50 == 0:
            with open(PROGRESS_FILE, "w") as f:
                json.dump(progress, f)

    # Save final progress
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)

    rows = [v for v in progress.values() if v.get("status") == "ok"]
    rows.sort(key=lambda x: x.get("support_score", 0), reverse=True)

    print(f"\nDone! {len(rows)} valid games. Sending to Discord…")
    post_top_n_to_discord(rows, TOP_N, len(rows))
    print("✓ Discord notified.")

if __name__ == "__main__":
    main()
