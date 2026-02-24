"""
server.py — Web server + API
Serves articles as JSON for your Lovable frontend (or any frontend).
Run with: python server.py
API available at: http://localhost:5000/api/articles
"""
import os
import threading
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from scraper import get_connection, setup_database, scrape_all_feeds, recategorize_all_articles, USE_POSTGRES
from datetime import datetime, timedelta, date
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__, static_folder=".")
CORS(app)

# Admin secret for paywall override endpoint — set in Render environment variables
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")

# Topic display metadata
TOPIC_META = {
    "Reproductive Rights":  {"icon": "🩺", "color": "#E91E8C"},
    "Gender Pay Gap":       {"icon": "💰", "color": "#FFA52C"},
    "LGBTQIA+":             {"icon": "🏳️‍🌈", "color": "#7B2FBE"},
    "Immigration":          {"icon": "🌍", "color": "#00BCD4"},
    "Human Rights":         {"icon": "⚖️", "color": "#FF0018"},
    "Health & Medicine":    {"icon": "🏥", "color": "#4CAF50"},
    "Law & Policy":         {"icon": "📜", "color": "#9C27B0"},
    "Politics & Government":{"icon": "🏛️", "color": "#3F51B5"},
    "Culture & Media":      {"icon": "🎭", "color": "#FF9800"},
    "Sports":               {"icon": "⚽", "color": "#008018"},
    "Violence & Safety":    {"icon": "🛡️", "color": "#F44336"},
    "Workplace & Economics":{"icon": "💼", "color": "#607D8B"},
}

# ── API Routes ────────────────────────────────────────────────────────────────

@app.route("/api/articles")
def articles():
    ph = "%s" if USE_POSTGRES else "?"

    locale       = request.args.get("locale", "en")
    limit        = min(int(request.args.get("limit", 30)), 200)
    offset       = max(int(request.args.get("offset", 0)), 0)
    search       = request.args.get("search", "").strip()
    time_r       = request.args.get("time", "")
    date_from    = request.args.get("date_from", "")
    date_to      = request.args.get("date_to", "")
    paywall      = request.args.get("paywall", "all")   # "all" | "free" | "paywalled"

    # Comma-separated multi-value params
    topics_raw   = request.args.get("topics", "")
    sources_raw  = request.args.get("sources", "")
    topics_list  = [t.strip() for t in topics_raw.split(",")  if t.strip()]
    sources_list = [s.strip() for s in sources_raw.split(",") if s.strip()]

    conditions = [f"locale = {ph}"]
    params     = [locale]

    # Topic filter (OR across list — each checked with LIKE)
    if topics_list:
        topic_clauses = " OR ".join([f"topics LIKE {ph}"] * len(topics_list))
        conditions.append(f"({topic_clauses})")
        for t in topics_list:
            params.append(f"%{t}%")

    # Source filter (OR across list)
    if sources_list:
        placeholders = ",".join([ph] * len(sources_list))
        conditions.append(f"source IN ({placeholders})")
        params.extend(sources_list)

    # Search (title + summary, case-insensitive)
    if search:
        conditions.append(f"(LOWER(title) LIKE {ph} OR LOWER(summary) LIKE {ph})")
        q = f"%{search.lower()}%"
        params += [q, q]

    # Date filtering — computed in Python for SQLite + Postgres compatibility
    date_col = "COALESCE(NULLIF(published_at, ''), scraped_at)"

    if time_r == "today":
        today_str = date.today().isoformat()
        conditions.append(f"{date_col} >= {ph}")
        params.append(today_str)

    if date_from:
        conditions.append(f"{date_col} >= {ph}")
        params.append(date_from)

    if date_to:
        try:
            dt_exclusive = (datetime.fromisoformat(date_to) + timedelta(days=1)).date().isoformat()
        except Exception:
            dt_exclusive = date_to
        conditions.append(f"{date_col} < {ph}")
        params.append(dt_exclusive)

    # Paywall filter — paywall_override takes priority over is_paywalled
    if paywall == "free":
        conditions.append(f"COALESCE(paywall_override, is_paywalled) = {ph}")
        params.append(False if USE_POSTGRES else 0)
    elif paywall == "paywalled":
        conditions.append(f"COALESCE(paywall_override, is_paywalled) = {ph}")
        params.append(True if USE_POSTGRES else 1)

    where_clause = "WHERE " + " AND ".join(conditions)

    conn   = get_connection()
    cursor = conn.cursor()

    # Total count for pagination
    cursor.execute(f"SELECT COUNT(*) FROM articles {where_clause}", params)
    total = cursor.fetchone()[0]

    # Paginated results
    cursor.execute(
        f"""SELECT id, title, link, summary, source, country, category,
                   tags, topics, scraped_at, published_at,
                   COALESCE(paywall_override, is_paywalled) AS is_paywalled,
                   locale
            FROM articles
            {where_clause}
            ORDER BY {date_col} DESC
            LIMIT {ph} OFFSET {ph}""",
        params + [limit, offset]
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    articles_list = []
    for row in rows:
        articles_list.append({
            "id":           row[0],
            "title":        row[1],
            "link":         row[2],
            "summary":      row[3],
            "source":       row[4],
            "country":      row[5],
            "category":     row[6],
            "tags":         row[7],
            "topics":       row[8],
            "scraped_at":   row[9],
            "published_at": row[10],
            "is_paywalled": bool(row[11]) if row[11] is not None else False,
            "locale":       row[12] if row[12] is not None else "en",
        })

    return jsonify({"articles": articles_list, "total": total})


@app.route("/api/sources")
def sources():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT source FROM articles ORDER BY source")
    result = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify(result)


@app.route("/api/countries")
def countries():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT country FROM articles WHERE country != '' ORDER BY country")
    result = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify(result)


@app.route("/api/topics")
def topics():
    ph = "%s" if USE_POSTGRES else "?"
    conn = get_connection()
    cursor = conn.cursor()
    result = []
    for topic_name, meta in TOPIC_META.items():
        cursor.execute(
            f"SELECT COUNT(*) FROM articles WHERE topics LIKE {ph}",
            [f"%{topic_name}%"]
        )
        count = cursor.fetchone()[0]
        result.append({
            "name":  topic_name,
            "count": count,
            "icon":  meta["icon"],
            "color": meta["color"],
        })
    conn.close()
    result.sort(key=lambda x: x["count"], reverse=True)
    return jsonify(result)


@app.route("/api/stats")
def stats():
    ph = "%s" if USE_POSTGRES else "?"
    locale = request.args.get("locale", "en")
    conn   = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM articles WHERE locale = {ph}", [locale])
    total = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM articles WHERE locale = {ph} AND tags LIKE {ph}",
        [locale, "%lgbtqia+%"]
    )
    lgbtq = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM articles WHERE locale = {ph} AND tags LIKE {ph}",
        [locale, "%women%"]
    )
    women = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT MAX(scraped_at) FROM articles WHERE locale = {ph}", [locale]
    )
    last_scraped = cursor.fetchone()[0]

    conn.close()
    return jsonify({
        "total":        total,
        "lgbtqia_plus": lgbtq,
        "women":        women,
        "last_scraped": last_scraped,
    })


@app.route("/api/paywall-override", methods=["POST"])
def paywall_override():
    """Manually correct a mis-detected paywall flag.
    Protected by X-Admin-Secret header. Set ADMIN_SECRET env var in Render.

    Body: { "id": <article_id>, "paywall_override": true | false | null }
    null resets to auto-detection (is_paywalled).
    """
    auth = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or auth != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    data       = request.get_json(silent=True) or {}
    article_id = data.get("id")
    override   = data.get("paywall_override")   # True | False | None

    if article_id is None:
        return jsonify({"error": "Missing id"}), 400

    ph     = "%s" if USE_POSTGRES else "?"
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE articles SET paywall_override = {ph} WHERE id = {ph}",
        (override, article_id)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({"ok": True, "id": article_id, "paywall_override": override})


@app.route("/api/scrape")
def trigger_scrape():
    """Manually trigger a scrape (visit this URL to refresh articles)."""
    def do_scrape():
        scrape_all_feeds()
    thread = threading.Thread(target=do_scrape)
    thread.start()
    return jsonify({"status": "Scraping started! Refresh in a few minutes."})


@app.route("/api/recategorize")
def trigger_recategorize():
    """Re-run topic detection on all existing articles using updated keyword rules."""
    def do_recategorize():
        recategorize_all_articles()
    thread = threading.Thread(target=do_recategorize)
    thread.start()
    return jsonify({"status": "Recategorization started! All existing articles will be updated with the new topic logic. Check Render logs for progress."})


# ── Serve the built-in frontend ───────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ── Startup: setup DB, initial scrape, scheduler ─────────────────────────────
def startup():
    """Run once on app startup: setup DB, initial scrape, daily scheduler."""
    setup_database()

    def initial_scrape():
        try:
            print("🚀 Running initial scrape...", flush=True)
            scrape_all_feeds()
            print("✅ Initial scrape complete!", flush=True)
        except Exception as e:
            print(f"❌ Initial scrape failed: {e}", flush=True)

    thread = threading.Thread(target=initial_scrape)
    thread.start()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: scrape_all_feeds(),
        "interval", hours=12,
        id="scheduled_scrape"
    )
    scheduler.start()
    print("📅 Scheduler active — will scrape every 12 hours.", flush=True)


startup()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n🌐 API running at http://localhost:{port}")
    print("   Endpoints: /api/articles  /api/sources  /api/countries  /api/topics  /api/stats  /api/paywall-override")
    print("   Press Ctrl+C to stop.\n")
    app.run(debug=False, host="0.0.0.0", port=port)
