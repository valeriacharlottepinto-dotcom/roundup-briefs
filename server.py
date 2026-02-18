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
from scraper import get_all_articles, get_connection, setup_database, scrape_all_feeds, USE_POSTGRES
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__, static_folder=".")
CORS(app)

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


def resolve_time_range(label):
    now = datetime.now()
    if label == "today":
        return now.replace(hour=0, minute=0, second=0).isoformat()
    elif label == "this_week":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0).isoformat()
    elif label == "last_week":
        start = now - timedelta(days=now.weekday() + 7)
        return start.replace(hour=0, minute=0, second=0).isoformat()
    elif label == "last_month":
        return (now - timedelta(days=30)).isoformat()
    elif label == "last_year":
        return (now - timedelta(days=365)).isoformat()
    return None


# ── API Routes ────────────────────────────────────────────────────────────────

@app.route("/api/articles")
def articles():
    category = request.args.get("category")
    source   = request.args.get("source")
    country  = request.args.get("country")
    search   = request.args.get("search")
    topic    = request.args.get("topic")
    time_label = request.args.get("time")
    limit    = int(request.args.get("limit", 200))
    time_range = resolve_time_range(time_label) if time_label else None
    results = get_all_articles(
        category=category, source=source, search=search,
        topic=topic, country=country, time_range=time_range,
        limit=limit
    )
    return jsonify(results)


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
    conn = get_connection()
    cursor = conn.cursor()
    ph = "%s" if USE_POSTGRES else "?"

    result = []
    for topic_name, meta in TOPIC_META.items():
        cursor.execute(
            f"SELECT COUNT(*) FROM articles WHERE topics LIKE {ph}",
            [f"%{topic_name}%"]
        )
        count = cursor.fetchone()[0]
        result.append({
            "name": topic_name,
            "count": count,
            "icon": meta["icon"],
            "color": meta["color"],
        })

    conn.close()
    result.sort(key=lambda x: x["count"], reverse=True)
    return jsonify(result)


@app.route("/api/stats")
def stats():
    conn = get_connection()
    cursor = conn.cursor()
    ph = "%s" if USE_POSTGRES else "?"
    cursor.execute("SELECT COUNT(*) FROM articles")
    total = cursor.fetchone()[0]
    cursor.execute(f"SELECT COUNT(*) FROM articles WHERE tags LIKE {ph}", ['%lgbtqia+%'])
    lgbtq = cursor.fetchone()[0]
    cursor.execute(f"SELECT COUNT(*) FROM articles WHERE tags LIKE {ph}", ['%women%'])
    women = cursor.fetchone()[0]
    cursor.execute("SELECT MAX(scraped_at) FROM articles")
    last_scraped = cursor.fetchone()[0]
    conn.close()
    return jsonify({
        "total": total,
        "lgbtqia_plus": lgbtq,
        "women": women,
        "last_scraped": last_scraped
    })


@app.route("/api/scrape")
def trigger_scrape():
    """Manually trigger a scrape (visit this URL to refresh articles)."""
    def do_scrape():
        scrape_all_feeds()
    thread = threading.Thread(target=do_scrape)
    thread.start()
    return jsonify({"status": "Scraping started! Refresh in a few minutes."})


# ── Serve the built-in frontend ──────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ── Startup: setup DB, initial scrape, scheduler ─────────────────────────────
# This runs when gunicorn imports the app (production) AND when run directly

def startup():
    """Run once on app startup: setup DB, initial scrape, daily scheduler."""
    setup_database()

    # Run initial scrape in background thread so the server starts immediately
    def initial_scrape():
        try:
            print("🚀 Running initial scrape...", flush=True)
            scrape_all_feeds()
            print("✅ Initial scrape complete!", flush=True)
        except Exception as e:
            print(f"❌ Initial scrape failed: {e}", flush=True)

    thread = threading.Thread(target=initial_scrape)
    thread.start()

    # Start background scheduler for daily scrapes
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: scrape_all_feeds(),
        'interval', hours=24,
        id='daily_scrape'
    )
    scheduler.start()
    print("📅 Scheduler active — will scrape every 24 hours.")


# Run startup for both gunicorn and direct execution
startup()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n🌐 API running at http://localhost:{port}")
    print("   Endpoints: /api/articles  /api/sources  /api/countries  /api/topics  /api/stats")
    print("   Press Ctrl+C to stop.\n")
    app.run(debug=False, host="0.0.0.0", port=port)
