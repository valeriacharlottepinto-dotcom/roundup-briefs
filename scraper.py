"""
scraper.py
Fetches articles from news sources and filters by keywords related to
women, feminism, and LGBTQIA+ topics. Saves results to a database.
Supports both SQLite (local) and PostgreSQL (production on Render).
"""

import feedparser
import hashlib
import re
import os
from datetime import datetime

# ── Database setup: PostgreSQL if DATABASE_URL is set, else SQLite ────────────
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    USE_POSTGRES = True
else:
    import sqlite3
    USE_POSTGRES = False

DB_FILE = "news.db"  # Only used for SQLite fallback


def get_connection():
    """Return a database connection (PostgreSQL or SQLite)."""
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        return sqlite3.connect(DB_FILE)


# ─────────────────────────────────────────────────────────────────────────────
#  NEWS SOURCES  — add or remove feeds here
#  Format: "Display Name": {"url": "RSS feed URL", "country": "XX"}
# ─────────────────────────────────────────────────────────────────────────────
FEEDS = {
    # ── General / World News (filtered by keywords) ────────────────────────
    "BBC News":             {"url": "https://feeds.bbci.co.uk/news/rss.xml",                    "country": "UK"},
    "BBC News World":       {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",              "country": "UK"},
    "The Guardian":         {"url": "https://www.theguardian.com/world/rss",                     "country": "UK"},
    "Reuters":              {"url": "https://feeds.reuters.com/reuters/topNews",                  "country": "US"},
    "Reuters World":        {"url": "https://feeds.reuters.com/Reuters/worldNews",               "country": "US"},
    "Al Jazeera":           {"url": "https://www.aljazeera.com/xml/rss/all.xml",                 "country": "Qatar"},
    "NPR News":             {"url": "https://feeds.npr.org/1001/rss.xml",                        "country": "US"},
    "The Independent":      {"url": "https://www.independent.co.uk/news/rss",                    "country": "UK"},
    "HuffPost":             {"url": "https://www.huffpost.com/section/women/feed",                "country": "US"},
    "New York Times":       {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "country": "US"},
    "Associated Press":     {"url": "https://apnews.com/rss",                                    "country": "US"},
    "CNN World":            {"url": "http://rss.cnn.com/rss/edition_world.rss",                  "country": "US"},
    "Washington Post":      {"url": "https://feeds.washingtonpost.com/rss/world",                "country": "US"},
    "Financial Times":      {"url": "https://www.ft.com/world?format=rss",                       "country": "UK"},
    "CBC News World":       {"url": "https://www.cbc.ca/cmlink/rss-world",                       "country": "Canada"},
    "ABC News":             {"url": "https://abcnews.go.com/rss/headlines",                      "country": "US"},
    "SBS News World":       {"url": "https://www.sbs.com.au/news/topic/world/rss.xml",           "country": "Australia"},
    "Le Monde":             {"url": "https://www.lemonde.fr/international/rss.xml",              "country": "France"},
    "IPS News Agency":      {"url": "https://ipsnews.net/news/regional-categories/rss.xml",      "country": "International"},
    "The Conversation":     {"url": "https://theconversation.com/topics/world-news/rss",         "country": "International"},
    "Global Voices":        {"url": "https://globalvoices.org/feeds/",                            "country": "International"},
    "Fair Observer":        {"url": "https://www.fairobserver.com/category/world/feed",           "country": "US"},

    # ── Women & Feminist Publications (all articles kept) ────────────────────
    "The Guardian Women":   {"url": "https://www.theguardian.com/lifeandstyle/women/rss",        "country": "UK"},
    "Ms. Magazine":         {"url": "https://msmagazine.com/feed/",                              "country": "US"},
    "Feministing":          {"url": "https://feministing.com/feed/",                             "country": "US"},
    "Jezebel":              {"url": "https://jezebel.com/rss",                                   "country": "US"},
    "Refinery29 Feminism":  {"url": "https://www.refinery29.com/en-us/feminism/rss.xml",         "country": "US"},
    "The Funambulist":      {"url": "https://thefunambulist.net/feed",                            "country": "France"},

    # ── LGBTQIA+ Publications (all articles kept) ────────────────────────────
    "Gay Times":            {"url": "https://www.gaytimes.co.uk/feed/",                          "country": "UK"},
    "PinkNews":             {"url": "https://www.pinknews.co.uk/feed/",                          "country": "UK"},
    "Out Magazine":         {"url": "https://www.out.com/rss.xml",                               "country": "US"},
    "LGBTQ Nation":         {"url": "https://www.lgbtqnation.com/feed/",                         "country": "US"},
    "Advocate":             {"url": "https://www.advocate.com/rss.xml",                          "country": "US"},
    "Autostraddle":         {"url": "https://www.autostraddle.com/feed/",                        "country": "US"},
    "Them":                 {"url": "https://www.them.us/feed/rss",                              "country": "US"},
    "Queerty":              {"url": "https://www.queerty.com/feed",                              "country": "US"},
    "Xtra Magazine":        {"url": "https://xtramagazine.com/feed/",                            "country": "Canada"},
}

ALWAYS_INCLUDE_SOURCES = {
    "The Guardian Women", "Ms. Magazine", "Feministing", "Jezebel",
    "Refinery29 Feminism", "The Funambulist",
    "Gay Times", "PinkNews", "Out Magazine", "LGBTQ Nation",
    "Advocate", "Autostraddle", "Them", "Queerty", "Xtra Magazine",
}

# ─────────────────────────────────────────────────────────────────────────────
#  KEYWORDS
# ─────────────────────────────────────────────────────────────────────────────
KEYWORDS = [
    "women", "woman", "girl", "girls", "female", "feminine", "feminism",
    "feminist", "gender equality", "gender gap", "gender pay gap",
    "reproductive rights", "abortion", "maternity", "maternal",
    "women's rights", "sexism", "misogyny", "patriarchy", "period poverty",
    "menstrual", "women's health", "domestic violence", "gender violence",
    "sexual harassment", "metoo", "me too", "#metoo", "femicide",
    "gender-based violence", "women in leadership", "women in sport",
    "lgbt", "lgbtq", "lgbtqia", "queer", "gay", "lesbian", "bisexual",
    "transgender", "trans ", "nonbinary", "non-binary", "intersex",
    "asexual", "pansexual", "pride", "drag", "same-sex", "gay rights",
    "trans rights", "rainbow", "coming out", "homophobia", "transphobia",
    "biphobia", "conversion therapy", "gender affirming", "gender identity",
    "pronouns", "deadnaming", "two-spirit", "queer community",
    "marriage equality", "section 28", "don't say gay",
    "immigration", "immigrant", "refugee", "asylum", "migrant", "migration",
    "deportation", "border", "undocumented", "visa", "citizenship",
    "detention", "displacement", "diaspora",
    "human rights", "civil rights", "civil liberties", "discrimination",
    "equality", "justice", "freedom", "oppression", "persecution",
    "minority rights", "indigenous", "racial justice", "racism",
]

# ─────────────────────────────────────────────────────────────────────────────
#  TOPIC KEYWORDS (12 topics, multi-select)
# ─────────────────────────────────────────────────────────────────────────────
TOPIC_KEYWORDS = {
    "Reproductive Rights": [
        "reproductive", "abortion", "pro-choice", "pro-life", "roe v wade",
        "roe v. wade", "planned parenthood", "birth control", "contraception",
        "contraceptive", "fertility", "ivf", "pregnancy", "pregnant",
        "miscarriage", "stillbirth", "maternal mortality", "midwife",
        "midwifery", "gynecolog", "obstetric", "prenatal", "postnatal",
        "surrogacy", "reproductive justice", "bodily autonomy",
        "menstrual", "period poverty", "menstruation",
    ],
    "Gender Pay Gap": [
        "pay gap", "wage gap", "equal pay", "gender pay", "salary gap",
        "income inequality", "glass ceiling", "gender gap", "pay equity",
        "pay disparity", "compensation gap", "wage disparity",
        "women in leadership", "women on boards", "gender parity",
        "workplace equality", "career gap", "promotion gap",
        "motherhood penalty",
    ],
    "LGBTQIA+": [
        "lgbt", "lgbtq", "lgbtqia", "queer", "gay", "lesbian", "bisexual",
        "transgender", "trans ", "nonbinary", "non-binary", "intersex",
        "asexual", "pansexual", "pride", "drag", "same-sex", "gay rights",
        "trans rights", "coming out", "homophobia", "transphobia",
        "biphobia", "conversion therapy", "gender affirming", "gender identity",
        "pronouns", "deadnaming", "two-spirit", "queer community",
        "marriage equality", "don't say gay", "drag queen", "drag king",
    ],
    "Immigration": [
        "immigration", "immigrant", "refugee", "asylum", "migrant",
        "migration", "deportation", "border", "undocumented", "visa",
        "citizenship", "detention", "displacement", "diaspora",
        "sanctuary", "dreamers", "daca", "resettlement", "exile",
        "stateless", "trafficking", "smuggling", "xenophobia",
    ],
    "Human Rights": [
        "human rights", "civil rights", "civil liberties",
        "minority rights", "indigenous rights", "racial justice",
        "protest", "activist", "activism",
        "censorship", "free speech", "political prisoner", "genocide",
        "ethnic cleansing", "apartheid", "reparation", "dignity",
        "amnesty", "un human rights", "humanitarian",
    ],
    "Health & Medicine": [
        "health", "medical", "healthcare", "medication", "clinic",
        "mental health", "therapy", "therapist", "diagnosis", "treatment",
        "hormone", "hrt", "wellness", "eating disorder", "body image",
        "gender affirming care", "puberty blocker", "surgery",
        "hiv", "aids", "cancer", "breast cancer", "cervical",
        "pandemic", "vaccination", "disease",
    ],
    "Law & Policy": [
        "law", "legal", "court", "lawsuit", "legislation", "bill",
        "policy", "amendment", "constitution", "ruling",
        "supreme court", "judge", "attorney", "lawyer", "prosecut",
        "ban", "repeal", "overturn", "regulation",
        "executive order", "mandate", "ordinance", "statute",
        "section 28", "don't say gay",
    ],
    "Politics & Government": [
        "election", "vote", "voting", "politician", "congress",
        "senate", "parliament", "minister", "president", "governor",
        "campaign", "candidate", "political", "democrat", "republican",
        "liberal", "conservative", "progressive",
        "government", "administration", "white house", "cabinet",
        "appointment", "nomination", "inaugurat", "lobby",
    ],
    "Culture & Media": [
        "film", "movie", "cinema", "television", "tv show", "netflix",
        "book", "novel", "author", "writer", "poet", "poetry",
        "music", "singer", "album", "concert", "festival",
        "art", "artist", "exhibition", "gallery", "museum",
        "fashion", "documentary", "podcast", "interview", "celebrity",
        "drag race", "drag queen", "drag king", "performance",
        "theater", "theatre", "broadway", "award", "oscar", "emmy",
        "representation", "visibility", "icon",
    ],
    "Sports": [
        "sport", "athlete", "olympic", "competition", "championship",
        "football", "soccer", "basketball", "tennis", "swimming",
        "running", "marathon", "rugby", "cricket", "boxing",
        "world cup", "title ix", "women in sport", "team",
        "coach", "player", "league", "tournament", "medal",
        "transgender athlete", "inclusion in sport",
        "fifa", "ioc", "wta", "wnba",
    ],
    "Violence & Safety": [
        "violence", "assault", "attack", "murder", "killed",
        "domestic violence", "abuse", "abuser", "victim", "survivor",
        "rape", "sexual assault", "sexual violence", "harassment",
        "hate crime", "hate speech", "threat", "stalking",
        "trafficking", "femicide", "gender-based violence",
        "bullying", "discrimination", "bigotry", "prejudice",
        "safety", "shelter", "protection order", "restraining order",
    ],
    "Workplace & Economics": [
        "workplace", "employment", "employer", "employee", "job",
        "career", "hire", "hiring", "fired", "layoff",
        "ceo", "board", "leadership", "promotion",
        "discrimination at work", "harassment at work", "hostile work",
        "entrepreneurship", "startup", "business", "economy",
        "poverty", "welfare", "childcare", "parental leave",
        "maternity leave", "paternity leave", "work-life balance",
    ],
}

MAX_ARTICLES_PER_SOURCE = 30


# ─────────────────────────────────────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────────────────────────────────────
def setup_database():
    conn = get_connection()
    cursor = conn.cursor()

    if USE_POSTGRES:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id          SERIAL PRIMARY KEY,
                url_hash    TEXT    UNIQUE,
                title       TEXT,
                link        TEXT,
                summary     TEXT,
                source      TEXT,
                country     TEXT    DEFAULT '',
                category    TEXT,
                tags        TEXT,
                topics      TEXT    DEFAULT '',
                scraped_at  TEXT
            )
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash    TEXT    UNIQUE,
                title       TEXT,
                link        TEXT,
                summary     TEXT,
                source      TEXT,
                country     TEXT    DEFAULT '',
                category    TEXT,
                tags        TEXT,
                topics      TEXT    DEFAULT '',
                scraped_at  TEXT
            )
        """)

    conn.commit()
    conn.close()
    print("✅ Database ready.")


def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()


def strip_html(text):
    return re.sub(r'<[^>]+>', '', text or '').strip()


# ─────────────────────────────────────────────────────────────────────────────
#  KEYWORD MATCHING
# ─────────────────────────────────────────────────────────────────────────────
def get_matching_tags(text):
    text_lower = text.lower()
    matched = []
    women_terms  = ["women","woman","girl","girls","female","feminine","feminism",
                    "feminist","gender","reproductive","abortion","maternity",
                    "maternal","sexism","misogyny","patriarchy","period poverty",
                    "menstrual","domestic violence","sexual harassment","metoo",
                    "me too","femicide"]
    lgbtq_terms  = ["lgbt","lgbtq","lgbtqia","queer","gay","lesbian","bisexual",
                    "transgender","trans ","nonbinary","non-binary","intersex",
                    "asexual","pansexual","pride","drag","same-sex","homophobia",
                    "transphobia","biphobia","conversion therapy","gender affirming",
                    "pronouns","two-spirit","marriage equality"]
    if any(t in text_lower for t in women_terms):
        matched.append("women")
    if any(t in text_lower for t in lgbtq_terms):
        matched.append("lgbtqia+")
    return matched


def matches_keywords(title, summary):
    combined = (title + " " + summary).lower()
    return any(kw in combined for kw in KEYWORDS)


def get_topics(text):
    text_lower = text.lower()
    matched = []
    for topic_name, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            matched.append(topic_name)
    return matched


# ─────────────────────────────────────────────────────────────────────────────
#  SCRAPING
# ─────────────────────────────────────────────────────────────────────────────
def scrape_all_feeds():
    total_new = 0
    ph = "%s" if USE_POSTGRES else "?"

    for source_name, feed_info in FEEDS.items():
        feed_url = feed_info["url"]
        country  = feed_info["country"]
        print(f"  📡 Scraping: {source_name}...", flush=True)
        try:
            feed    = feedparser.parse(feed_url)
            entries = feed.entries[:MAX_ARTICLES_PER_SOURCE]
            new_count = 0

            # Fresh connection per source — prevents long-held connection timeouts
            conn   = get_connection()
            cursor = conn.cursor()

            for entry in entries:
                link    = entry.get("link", "")
                title   = strip_html(entry.get("title", "No title"))
                summary = strip_html(entry.get("summary", ""))
                hash_id = url_hash(link)

                always_keep = source_name in ALWAYS_INCLUDE_SOURCES
                if not always_keep and not matches_keywords(title, summary):
                    continue

                tags = get_matching_tags(title + " " + summary)
                if source_name in {"Gay Times","PinkNews","Out Magazine",
                                   "LGBTQ Nation","Advocate","Autostraddle",
                                   "Them","Queerty","Xtra Magazine"}:
                    tags = list(set(tags + ["lgbtqia+"]))
                elif source_name in {"Ms. Magazine","Feministing",
                                     "Jezebel","Refinery29 Feminism",
                                     "The Guardian Women","The Funambulist"}:
                    tags = list(set(tags + ["women"]))

                category = "lgbtqia+" if "lgbtqia+" in tags else "women"
                tags_str = ", ".join(sorted(set(tags))) if tags else "general"

                topics = get_topics(title + " " + summary)
                if source_name in {"Gay Times","PinkNews","Out Magazine",
                                   "LGBTQ Nation","Advocate","Autostraddle",
                                   "Them","Queerty","Xtra Magazine"}:
                    topics = list(set(topics + ["LGBTQIA+"]))
                topics_str = ", ".join(sorted(set(topics))) if topics else ""

                try:
                    if USE_POSTGRES:
                        cursor.execute(f"""
                            INSERT INTO articles
                              (url_hash, title, link, summary, source, country,
                               category, tags, topics, scraped_at)
                            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                            ON CONFLICT (url_hash) DO NOTHING
                        """, (hash_id, title, link, summary, source_name, country,
                              category, tags_str, topics_str, datetime.now().isoformat()))
                        if cursor.rowcount > 0:
                            new_count += 1
                    else:
                        cursor.execute(f"""
                            INSERT INTO articles
                              (url_hash, title, link, summary, source, country,
                               category, tags, topics, scraped_at)
                            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                        """, (hash_id, title, link, summary, source_name, country,
                              category, tags_str, topics_str, datetime.now().isoformat()))
                        new_count += 1
                except Exception:
                    pass  # Already saved (SQLite IntegrityError)

            conn.commit()
            conn.close()
            print(f"     ✔  {new_count} new articles from {source_name}", flush=True)
            total_new += new_count

        except Exception as e:
            print(f"     ❌  Error scraping {source_name}: {e}", flush=True)

    print(f"\n🎉 Done! {total_new} new articles saved in total.", flush=True)


def get_all_articles(category=None, source=None, search=None, topic=None,
                     country=None, time_range=None, limit=200):
    conn = get_connection()
    if USE_POSTGRES:
        import psycopg2.extras
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        ph = "%s"
    else:
        conn.row_factory = __import__('sqlite3').Row
        cursor = conn.cursor()
        ph = "?"

    query  = "SELECT * FROM articles WHERE 1=1"
    params = []

    if category:
        query += f" AND (category = {ph} OR tags LIKE {ph})"
        params += [category, f"%{category}%"]
    if source:
        query += f" AND source = {ph}"
        params.append(source)
    if country:
        query += f" AND country = {ph}"
        params.append(country)
    if search:
        if USE_POSTGRES:
            query += f" AND (title ILIKE {ph} OR summary ILIKE {ph})"
        else:
            query += f" AND (title LIKE {ph} OR summary LIKE {ph})"
        params += [f"%{search}%", f"%{search}%"]
    if topic:
        topic_list = [t.strip() for t in topic.split(",")]
        if USE_POSTGRES:
            topic_clauses = " OR ".join([f"topics ILIKE {ph}" for _ in topic_list])
        else:
            topic_clauses = " OR ".join([f"topics LIKE {ph}" for _ in topic_list])
        query += f" AND ({topic_clauses})"
        params += [f"%{t}%" for t in topic_list]
    if time_range:
        query += f" AND scraped_at >= {ph}"
        params.append(time_range)

    query += f" ORDER BY scraped_at DESC LIMIT {ph}"
    params.append(limit)

    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


if __name__ == "__main__":
    print("🗞️  News Scraper Starting...\n")
    setup_database()
    scrape_all_feeds()
