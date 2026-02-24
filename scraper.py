"""
scraper.py
Fetches articles from news sources and filters by keywords related to
feminist, LGBTQIA+, and global rights topics.
Uses a systems-of-power taxonomy with 9 primary system categories.
Supports both SQLite (local dev) and PostgreSQL (Render production).
"""

import feedparser
import sqlite3
import hashlib
import re
import os
from datetime import datetime, timedelta

# ── Postgres support (optional — only used when DATABASE_URL is set) ──────────
try:
    import psycopg2
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    USE_POSTGRES = bool(DATABASE_URL)
except ImportError:
    USE_POSTGRES = False
    DATABASE_URL = ""

DB_FILE = "news.db"
MAX_ARTICLES_PER_SOURCE = 30

# ─────────────────────────────────────────────────────────────────────────────
#  DATABASE CONNECTION
# ─────────────────────────────────────────────────────────────────────────────
def get_connection():
    if USE_POSTGRES:
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect(DB_FILE)


# ─────────────────────────────────────────────────────────────────────────────
#  NEWS SOURCES  — add or remove feeds here
#  Format: "Display Name": {"url": "RSS feed URL", "country": "XX"}
# ─────────────────────────────────────────────────────────────────────────────
FEEDS = {
    # ── General / World News (keyword-filtered) ─────────────────────────────
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

    # ── Women & Feminist Publications (all articles kept) ───────────────────
    "The Guardian Women":   {"url": "https://www.theguardian.com/lifeandstyle/women/rss",        "country": "UK"},
    "Ms. Magazine":         {"url": "https://msmagazine.com/feed/",                              "country": "US"},
    "Feministing":          {"url": "https://feministing.com/feed/",                             "country": "US"},
    "Jezebel":              {"url": "https://jezebel.com/rss",                                   "country": "US"},
    "Refinery29 Feminism":  {"url": "https://www.refinery29.com/en-us/feminism/rss.xml",         "country": "US"},
    "The Funambulist":      {"url": "https://thefunambulist.net/feed",                            "country": "France"},

    # ── LGBTQIA+ Publications (all articles kept) ───────────────────────────
    "Gay Times":            {"url": "https://www.gaytimes.co.uk/feed/",                          "country": "UK"},
    "PinkNews":             {"url": "https://www.pinknews.co.uk/feed/",                          "country": "UK"},
    "Out Magazine":         {"url": "https://www.out.com/rss.xml",                               "country": "US"},
    "LGBTQ Nation":         {"url": "https://www.lgbtqnation.com/feed/",                         "country": "US"},
    "Advocate":             {"url": "https://www.advocate.com/rss.xml",                          "country": "US"},
    "Autostraddle":         {"url": "https://www.autostraddle.com/feed/",                        "country": "US"},
    "Them":                 {"url": "https://www.them.us/feed/rss",                              "country": "US"},
    "Queerty":              {"url": "https://www.queerty.com/feed",                              "country": "US"},
    "Xtra Magazine":        {"url": "https://xtramagazine.com/feed/",                            "country": "Canada"},

    # ── Progressive & Investigative (keyword-filtered) ──────────────────────
    "AlterNet":             {"url": "https://www.alternet.org/feeds/feed.rss",                   "country": "US"},
    "Democracy Now":        {"url": "https://www.democracynow.org/podcast.xml",                  "country": "US"},
    "FSRN":                 {"url": "https://fsrn.org/feed",                                     "country": "US"},
    "Jewish Voice for Peace":{"url": "https://jewishvoiceforpeace.org/feed/",                   "country": "US"},
    "Le Monde Diplomatique":{"url": "https://mondediplo.com/rss/",                              "country": "France"},
    "The Progressive":      {"url": "https://progressive.org/feed/",                             "country": "US"},
    "Reveal News":          {"url": "https://revealnews.org/feed/",                              "country": "US"},
    "Accuracy in Media":    {"url": "https://www.aim.org/feed/",                                 "country": "US"},
    "Media Matters":        {"url": "https://www.mediamatters.org/rss/latest",                   "country": "US"},
}

# Sources where ALL articles are kept (no keyword filter needed)
ALWAYS_INCLUDE_SOURCES = {
    "The Guardian Women",
    "Ms. Magazine",
    "Feministing",
    "Jezebel",
    "Refinery29 Feminism",
    "The Funambulist",
    "Gay Times",
    "PinkNews",
    "Out Magazine",
    "LGBTQ Nation",
    "Advocate",
    "Autostraddle",
    "Them",
    "Queerty",
    "Xtra Magazine",
}

LGBTQIA_SOURCES = {
    "Gay Times", "PinkNews", "Out Magazine", "LGBTQ Nation", "Advocate",
    "Autostraddle", "Them", "Queerty", "Xtra Magazine",
}

FEMINIST_SOURCES = {
    "Ms. Magazine", "Feministing", "Jezebel", "Refinery29 Feminism",
    "The Guardian Women", "The Funambulist",
}

# Sources that are paywalled at the source level
PAYWALLED_SOURCES = {"New York Times", "Financial Times", "Washington Post"}

# Phrases that signal a paywalled article in RSS content
PAYWALL_SIGNAL_PHRASES = [
    "subscribe to read", "subscription required", "subscribers only",
    "sign in to read", "create a free account", "this article is for subscribers",
    "exclusive to subscribers", "premium content", "member exclusive",
    "for full access", "to continue reading", "read more with a subscription",
    "register to read", "already a subscriber", "become a member",
]


# ─────────────────────────────────────────────────────────────────────────────
#  INCLUSION KEYWORDS
#  Articles from general sources must match at least one of these to be saved.
#  Covers both Gate A (identity signals) and Gate B (structural system signals).
# ─────────────────────────────────────────────────────────────────────────────
KEYWORDS = [
    # ── Gate A — Direct identity signals ─────────────────────────────────────
    # Women / Gender
    "women", "woman", "girl", "girls", "female", "feminine", "feminism",
    "feminist", "gender equality", "gender gap", "gender pay gap",
    "reproductive rights", "abortion", "maternity", "maternal",
    "women's rights", "sexism", "misogyny", "patriarchy", "period poverty",
    "menstrual", "women's health", "domestic violence", "gender violence",
    "sexual harassment", "metoo", "me too", "#metoo", "femicide",
    "gender-based violence", "women in leadership",

    # LGBTQIA+
    "lgbt", "lgbtq", "lgbtqia", "queer", "gay", "lesbian", "bisexual",
    "transgender", "trans ", "nonbinary", "non-binary", "intersex",
    "asexual", "pansexual", "pride", "drag", "same-sex", "gay rights",
    "trans rights", "coming out", "homophobia", "transphobia",
    "biphobia", "conversion therapy", "gender affirming", "gender identity",
    "pronouns", "deadnaming", "two-spirit", "marriage equality",

    # Migration / Displacement
    "refugee", "asylum", "migrant", "migration", "deportation",
    "undocumented", "detention", "displacement", "diaspora",
    "stateless", "asylum seeker", "forced displacement",

    # Rights / Justice
    "human rights", "civil rights", "civil liberties", "discrimination",
    "minority rights", "indigenous", "racial justice", "racism",

    # ── Gate B — Structural system signals ──────────────────────────────────
    # Bodily autonomy
    "bodily autonomy", "fgm", "female genital mutilation",
    "forced sterilisation", "forced sterilization", "obstetric violence",

    # Economic structure
    "care economy", "unpaid care", "domestic workers", "garment workers",
    "labour rights", "labor rights", "workers rights", "pay equity",

    # Climate / land
    "land dispossession", "climate displacement", "environmental racism",
    "climate justice", "environmental justice", "indigenous land",

    # Technology
    "surveillance", "facial recognition", "algorithmic discrimination",
    "internet shutdown", "digital rights", "spyware", "deepfake",

    # Anti-rights
    "gender ideology", "anti-trans", "book ban", "don't say gay",
    "bathroom bill", "parents rights", "anti-lgbtq",

    # Violence / accountability
    "trafficking", "forced marriage", "honour killing",
    "extrajudicial killing", "forced disappearance", "impunity",

    # Media / narrative
    "press freedom", "journalist arrested", "media freedom",
    "censorship", "academic freedom",
]


# ─────────────────────────────────────────────────────────────────────────────
#  SYSTEM TOPIC KEYWORDS
#  Maps each article to 1–3 primary system categories.
#  Categories follow the systems-of-power taxonomy.
# ─────────────────────────────────────────────────────────────────────────────
TOPIC_KEYWORDS = {

    "Anti-Rights & Backlash Movements": [
        # Core anti-rights framing
        "gender ideology", "traditional values", "family values",
        "anti-trans", "anti-lgbtq", "anti-lgbtqia",
        "book ban", "banned books", "curriculum ban", "curriculum removal",
        "don't say gay", "bathroom bill", "bathroom law",
        "anti-abortion movement", "pro-life movement", "fetal personhood",
        "rollback", "rights rollback",
        # Conversion therapy
        "conversion therapy", "reparative therapy",
        # Religious freedom as rights-rollback vehicle
        "religious freedom exemption", "religious liberty exemption",
        "parents rights", "parental rights" , "parental override",
        # Named organisations / movements
        "alliance defending freedom", " adf ", "heritage foundation",
        "agenda europe", "fidesz", "orban",
        "anti-homosexuality act", "same-sex ban", "criminalise homosexuality",
        "criminalizes homosexuality", "gay propaganda law",
        "russia gay propaganda", "section 28",
        # Far-right framing
        "far-right", "ultra-conservative", "hard right",
        "backlash", "culture war",
    ],

    "Bodily Autonomy & Reproductive Justice": [
        # Reproductive
        "reproductive rights", "reproductive justice", "reproductive health",
        "abortion", "pro-choice", "planned parenthood",
        "birth control", "contraception", "contraceptive",
        "fertility", "ivf", "pregnancy", "pregnant",
        "miscarriage", "stillbirth", "maternal mortality", "maternal health",
        "midwife", "midwifery", "gynecolog", "obstetric", "prenatal", "postnatal",
        "surrogacy", "bodily autonomy",
        "menstrual", "period poverty", "menstruation",
        # Harmful practices
        "fgm", "female genital mutilation", "forced sterilisation",
        "forced sterilization", "obstetric violence",
        # Gender-affirming healthcare
        "gender affirming care", "gender affirming", "puberty blocker",
        "hormone therapy", "hrt",
        # Health with rights dimension
        "mental health", "eating disorder", "body image",
        "hiv", "aids", "sexual health", "healthcare access",
        "breast cancer", "cervical cancer", "health inequality",
    ],

    "Violence, Safety & Criminal Justice": [
        # Gender-based violence
        "femicide", "domestic violence", "gender-based violence", "gbv",
        "sexual violence", "sexual assault", "rape", "sexual harassment",
        "honour killing", "forced marriage", "dowry violence",
        # Trafficking & exploitation
        "trafficking", "human trafficking", "sex trafficking",
        "forced labour", "forced labor", "modern slavery",
        # State violence
        "police brutality", "police violence", "extrajudicial killing",
        "forced disappearance", "torture", "arbitrary detention",
        "political prisoner",
        # Hate & targeted violence
        "hate crime", "attack on", "assault", "murder",
        "stalking", "threat", "intimidation",
        # Justice / accountability
        "protection order", "restraining order", "shelter",
        "survivor", "impunity", "accountability", "prosecution",
        "prison conditions", "incarceration", "criminal justice",
    ],

    "State Power, Law & Governance": [
        # Courts & legislation
        "supreme court", "constitutional court", "high court", "federal court",
        "ruling", "landmark ruling", "landmark decision",
        "legislation", "law passed", "signed into law", "executive order",
        "amendment", "constitution", "criminalised", "decriminalised",
        "anti-discrimination law", "equality act", "hate crime law",
        "civil rights act", "human rights act",
        "ban", "repeal", "overturn", "reform", "policy change",
        # International law
        "treaty", "ratification", "un resolution", "international law",
        "un human rights", "special rapporteur", "universal periodic review",
        # Elections & political power
        "election", "vote", "ballot", "campaign",
        "parliament", "senate", "congress", "minister",
        "government policy", "administration", "cabinet",
        "appointment", "nomination",
    ],

    "Economic & Labour Justice": [
        # Pay & wealth
        "pay gap", "gender pay gap", "wage gap", "equal pay", "pay equity",
        "pay disparity", "income inequality", "wealth gap",
        # Care economy
        "care economy", "unpaid care", "care work", "care workers",
        "domestic workers", "childcare", "eldercare",
        # Labour rights
        "labour rights", "labor rights", "workers rights",
        "union", "collective bargaining", "strike",
        "garment workers", "gig economy", "gig workers",
        "minimum wage", "wage theft", "forced labour",
        # Employment
        "maternity leave", "paternity leave", "parental leave",
        "pension", "retirement", "workplace discrimination",
        "motherhood penalty", "glass ceiling",
        "women in leadership", "women on boards", "corporate diversity",
        # Poverty / welfare
        "poverty", "welfare", "food security", "food insecurity",
        "debt", "economic inequality", "land rights",
    ],

    "Migration, Borders & Citizenship": [
        # Status
        "refugee", "asylum", "asylum seeker", "stateless", "statelessness",
        "undocumented", "displaced", "displacement",
        "citizenship", "citizenship revoked", "naturalisation",
        "visa", "residency",
        # Borders & detention
        "deportation", "deportee", "detention centre", "immigration detention",
        "border violence", "border control", "migration policy",
        "forced return", "pushback",
        # Specific crises
        "rohingya", "mediterranean crossing", "channel crossing",
        "kafala", "kafala system",
        # Community
        "diaspora", "exile", "resettlement", "integration",
        "xenophobia", "anti-immigration",
        "sanctuary city", "dreamers", "daca",
        "migrant worker", "seasonal worker",
    ],

    "Climate & Environmental Justice": [
        # Displacement
        "climate displacement", "climate refugee", "climate migrant",
        "climate migration", "climate-displaced",
        # Land & resources
        "land dispossession", "land grab", "indigenous land",
        "land rights", "water rights", "resource extraction",
        "deforestation", "dam construction", "mining community",
        # Environmental justice framing
        "environmental racism", "sacrifice zone", "pollution community",
        "environmental justice", "climate justice", "just transition",
        "climate finance", "loss and damage",
        # Climate impacts
        "climate change", "global warming", "sea level",
        "flood", "drought", "wildfire", "extreme heat",
        "environmental health",
    ],

    "Technology & Digital Power": [
        # Surveillance
        "facial recognition", "mass surveillance", "surveillance technology",
        "biometric", "predictive policing", "spyware", "pegasus",
        # Censorship & shutdowns
        "internet shutdown", "social media ban", "content moderation",
        "platform ban", "vpn ban", "censorship online",
        "encrypted", "encryption ban",
        # Algorithmic harm
        "algorithmic discrimination", "algorithmic bias", "ai bias",
        "automated decision", "discriminatory algorithm",
        # Online violence
        "deepfake", "non-consensual imagery", "revenge porn",
        "cyber harassment", "online abuse", "digital violence",
        "doxing",
        # Digital rights
        "digital rights", "data privacy", "data protection",
        "tech worker", "gig platform",
        "artificial intelligence", "ai regulation",
    ],

    "Culture, Media & Narrative Power": [
        # Press freedom
        "press freedom", "journalist arrested", "media freedom",
        "reporter imprisoned", "journalist killed",
        # Books & education censorship
        "book ban", "banned book", "curriculum", "academic freedom",
        "education rights", "school policy",
        # Representation & storytelling
        "representation", "visibility", "storytelling", "narrative",
        "indigenous media", "language rights", "cultural rights",
        # Arts & entertainment (with rights dimension)
        "film", "documentary", "book", "novel", "author",
        "art", "artist", "museum", "performance", "theatre", "theater",
        "drag", "drag queen", "drag king", "drag race",
        "music", "singer", "award", "oscar", "emmy", "grammy",
        "icon", "podcast", "interview",
        # Censorship
        "censorship", "banned film", "cancelled",
        # Social media & influence
        "social media", "influencer", "content creator",
        "platform", "algorithm",
    ],
}

# Default fallback topics when no keyword matches
# Used for always-include sources to ensure every article gets at least one tag
SOURCE_DEFAULT_TOPIC = {
    # LGBTQIA+ sources → Culture by default (community content)
    "Gay Times":     "Culture, Media & Narrative Power",
    "PinkNews":      "Culture, Media & Narrative Power",
    "Out Magazine":  "Culture, Media & Narrative Power",
    "LGBTQ Nation":  "Culture, Media & Narrative Power",
    "Advocate":      "Culture, Media & Narrative Power",
    "Autostraddle":  "Culture, Media & Narrative Power",
    "Them":          "Culture, Media & Narrative Power",
    "Queerty":       "Culture, Media & Narrative Power",
    "Xtra Magazine": "Culture, Media & Narrative Power",
    # Feminist sources → Bodily Autonomy by default
    "Ms. Magazine":        "Bodily Autonomy & Reproductive Justice",
    "Feministing":         "Bodily Autonomy & Reproductive Justice",
    "Jezebel":             "Bodily Autonomy & Reproductive Justice",
    "Refinery29 Feminism": "Bodily Autonomy & Reproductive Justice",
    "The Guardian Women":  "Bodily Autonomy & Reproductive Justice",
    "The Funambulist":     "State Power, Law & Governance",
}


# ─────────────────────────────────────────────────────────────────────────────
#  DATABASE SETUP
# ─────────────────────────────────────────────────────────────────────────────
def setup_database():
    conn   = get_connection()
    cursor = conn.cursor()
    ph     = "%s" if USE_POSTGRES else "?"

    if USE_POSTGRES:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id               SERIAL PRIMARY KEY,
                url_hash         TEXT UNIQUE,
                title            TEXT,
                link             TEXT,
                summary          TEXT,
                source           TEXT,
                country          TEXT    DEFAULT '',
                category         TEXT,
                tags             TEXT,
                topics           TEXT    DEFAULT '',
                scraped_at       TEXT,
                published_at     TEXT    DEFAULT '',
                is_paywalled     BOOLEAN DEFAULT FALSE,
                locale           TEXT    DEFAULT 'en',
                paywall_override BOOLEAN DEFAULT NULL
            )
        """)
        conn.commit()
        for col_sql in [
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS country TEXT DEFAULT ''",
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS topics TEXT DEFAULT ''",
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS published_at TEXT DEFAULT ''",
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS is_paywalled BOOLEAN DEFAULT FALSE",
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS locale TEXT DEFAULT 'en'",
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS paywall_override BOOLEAN DEFAULT NULL",
        ]:
            try:
                cursor.execute(col_sql)
                conn.commit()
            except Exception:
                conn.rollback()
        cursor.execute("UPDATE articles SET locale = 'en' WHERE locale IS NULL")
        conn.commit()
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash         TEXT UNIQUE,
                title            TEXT,
                link             TEXT,
                summary          TEXT,
                source           TEXT,
                country          TEXT    DEFAULT '',
                category         TEXT,
                tags             TEXT,
                topics           TEXT    DEFAULT '',
                scraped_at       TEXT,
                published_at     TEXT    DEFAULT '',
                is_paywalled     INTEGER DEFAULT 0,
                locale           TEXT    DEFAULT 'en',
                paywall_override INTEGER DEFAULT NULL
            )
        """)
        for col, default in [
            ("country",          "''"),
            ("topics",           "''"),
            ("published_at",     "''"),
            ("is_paywalled",     "0"),
            ("locale",           "'en'"),
            ("paywall_override", "NULL"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE articles ADD COLUMN {col} TEXT DEFAULT {default}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

    # Purge articles older than 180 days
    cutoff = (datetime.now() - timedelta(days=180)).isoformat()
    cursor.execute(f"DELETE FROM articles WHERE scraped_at < {ph}", [cutoff])
    conn.commit()
    conn.close()
    print("✅ Database ready.", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()


def strip_html(text):
    return re.sub(r'<[^>]+>', '', text or '').strip()


def extract_published_at(entry) -> str:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6]).isoformat()
            except Exception:
                pass
    return ""


# ─────────────────────────────────────────────────────────────────────────────
#  PAYWALL DETECTION
# ─────────────────────────────────────────────────────────────────────────────
def detect_paywall(entry, source: str) -> bool:
    if source in PAYWALLED_SOURCES:
        return True
    title   = strip_html(entry.get("title",   "") or "").lower()
    summary = strip_html(entry.get("summary", "") or "")
    combined = title + " " + summary.lower()
    for phrase in PAYWALL_SIGNAL_PHRASES:
        if phrase in combined:
            return True
    if source not in ALWAYS_INCLUDE_SOURCES and 0 < len(summary.strip()) < 120:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
#  KEYWORD MATCHING
# ─────────────────────────────────────────────────────────────────────────────
def matches_keywords(title, summary):
    """Gate check: return True if this article is relevant to the feed."""
    combined = (title + " " + summary).lower()
    return any(kw in combined for kw in KEYWORDS)


def get_identity_tags(text, source):
    """Return identity tags (women / lgbtqia+) based on text + source type."""
    text_lower = text.lower()
    tags = set()

    women_terms = [
        "women", "woman", "girl", "girls", "female", "feminine", "feminism",
        "feminist", "gender", "reproductive", "abortion", "maternity",
        "maternal", "sexism", "misogyny", "patriarchy", "period poverty",
        "menstrual", "domestic violence", "sexual harassment", "metoo",
        "me too", "femicide",
    ]
    lgbtq_terms = [
        "lgbt", "lgbtq", "lgbtqia", "queer", "gay", "lesbian", "bisexual",
        "transgender", "trans ", "nonbinary", "non-binary", "intersex",
        "asexual", "pansexual", "pride", "drag", "same-sex", "homophobia",
        "transphobia", "biphobia", "conversion therapy", "gender affirming",
        "pronouns", "two-spirit", "marriage equality",
    ]

    if source in FEMINIST_SOURCES or any(t in text_lower for t in women_terms):
        tags.add("women")
    if source in LGBTQIA_SOURCES or any(t in text_lower for t in lgbtq_terms):
        tags.add("lgbtqia+")

    return sorted(tags)


def get_system_topics(text, source):
    """
    Assign 1–3 primary system topic tags to an article.
    Returns an ordered list: strongest match first.
    Falls back to SOURCE_DEFAULT_TOPIC if no keywords match.
    """
    text_lower = text.lower()
    matched = []

    for topic_name, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            matched.append(topic_name)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for t in matched:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    matched = unique[:3]  # cap at 3 system tags

    # Fallback for always-include sources that matched no keyword
    if not matched and source in SOURCE_DEFAULT_TOPIC:
        matched = [SOURCE_DEFAULT_TOPIC[source]]

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

        conn   = get_connection()
        cursor = conn.cursor()
        new_count = 0

        try:
            feed    = feedparser.parse(feed_url)
            entries = feed.entries[:MAX_ARTICLES_PER_SOURCE]

            for entry in entries:
                link    = entry.get("link", "")
                title   = strip_html(entry.get("title", "No title"))
                summary = strip_html(entry.get("summary", ""))
                hash_id = url_hash(link)

                # Inclusion gate — skip for always-include sources
                always_keep = source_name in ALWAYS_INCLUDE_SOURCES
                if not always_keep and not matches_keywords(title, summary):
                    continue

                combined_text = title + " " + summary

                # Identity tags (women / lgbtqia+)
                identity_tags = get_identity_tags(combined_text, source_name)
                tags_str = ", ".join(identity_tags) if identity_tags else "general"

                # Category field (legacy — kept for backward compat)
                category = "lgbtqia+" if "lgbtqia+" in identity_tags else "women"

                # System topics (new taxonomy)
                system_topics = get_system_topics(combined_text, source_name)
                topics_str = ", ".join(system_topics) if system_topics else ""

                # Publication date + paywall
                published_at = extract_published_at(entry)
                is_paywalled = detect_paywall(entry, source_name)
                scraped_at   = datetime.now().isoformat()

                try:
                    cursor.execute(f"""
                        INSERT INTO articles
                          (url_hash, title, link, summary, source, country,
                           category, tags, topics, scraped_at, published_at,
                           is_paywalled, locale)
                        VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})
                    """, (
                        hash_id, title, link, summary, source_name, country,
                        category, tags_str, topics_str, scraped_at, published_at,
                        is_paywalled,
                        "en",
                    ))
                    new_count += 1
                except Exception:
                    if USE_POSTGRES:
                        conn.rollback()

            conn.commit()
            print(f"     ✔  {new_count} new articles from {source_name}", flush=True)
            total_new += new_count

        except Exception as e:
            print(f"     ❌  Error scraping {source_name}: {e}", flush=True)
        finally:
            conn.close()

    print(f"\n🎉 Done! {total_new} new articles saved in total.", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
#  RECATEGORIZE  — re-tag all existing articles with the new taxonomy
# ─────────────────────────────────────────────────────────────────────────────
def recategorize_all_articles():
    """Re-run system topic + identity tag detection on every existing article."""
    conn   = get_connection()
    cursor = conn.cursor()
    ph     = "%s" if USE_POSTGRES else "?"

    cursor.execute("SELECT id, title, summary, source FROM articles")
    rows    = cursor.fetchall()
    updated = 0

    for row in rows:
        article_id, title, summary, source = row[0], row[1], row[2], row[3]
        text = (title or "") + " " + (summary or "")

        # New system topics
        system_topics = get_system_topics(text, source)
        topics_str = ", ".join(system_topics) if system_topics else ""

        # Identity tags
        identity_tags = get_identity_tags(text, source)
        tags_str = ", ".join(identity_tags) if identity_tags else "general"

        cursor.execute(
            f"UPDATE articles SET topics = {ph}, tags = {ph} WHERE id = {ph}",
            (topics_str, tags_str, article_id)
        )
        updated += 1

    conn.commit()
    conn.close()
    print(f"✅ Recategorized {updated} articles with new taxonomy.", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
#  QUERY (kept for backward compatibility / standalone use)
# ─────────────────────────────────────────────────────────────────────────────
def get_all_articles(category=None, source=None, search=None, topic=None,
                     country=None, time_range=None, date_to=None,
                     limit=200, free_only=False):
    conn   = get_connection()
    ph     = "%s" if USE_POSTGRES else "?"

    if not USE_POSTGRES:
        conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
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
        query += f" AND (title LIKE {ph} OR summary LIKE {ph})"
        params += [f"%{search}%", f"%{search}%"]
    if topic:
        topic_list    = [t.strip() for t in topic.split(",")]
        topic_clauses = " OR ".join([f"topics LIKE {ph}" for _ in topic_list])
        query        += f" AND ({topic_clauses})"
        params       += [f"%{t}%" for t in topic_list]
    if time_range:
        query += f" AND scraped_at >= {ph}"
        params.append(time_range)
    if date_to:
        query += f" AND scraped_at <= {ph}"
        params.append(date_to)
    if free_only:
        query += f" AND COALESCE(paywall_override, is_paywalled) = {ph}"
        params.append(False if USE_POSTGRES else 0)

    query += f" ORDER BY scraped_at DESC LIMIT {ph}"
    params.append(limit)

    cursor.execute(query, params)

    if USE_POSTGRES:
        cols = [desc[0] for desc in cursor.description]
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
    else:
        rows = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return rows


if __name__ == "__main__":
    print("🗞️  News Scraper Starting...\n")
    setup_database()
    scrape_all_feeds()
