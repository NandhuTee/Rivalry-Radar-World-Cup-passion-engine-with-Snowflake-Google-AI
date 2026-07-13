"""
Rivalry Radar — backend API


Two technologies split the work:
  - Google AI (Gemini, via the google-genai SDK) scores the sentiment of
    every fan "take" the instant it's submitted, and writes the "Hype
    Verdict" for a rivalry.
  - Snowflake stores every take and computes the Heat Index / leaderboards
    with real SQL analytics (aggregation, RANK() window functions).

If SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER env vars aren't set, the API falls
back to an in-memory DEMO MODE with pre-seeded data. If GEMINI_API_KEY isn't
set, sentiment scoring and the hype verdict fall back to a small local
heuristic instead of calling Gemini. Every place that would hit a real
service is clearly marked, so the whole flow works with zero external
dependencies for local exploration.
"""
import os
import uuid
import random

from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DEMO_MODE = not os.getenv("SNOWFLAKE_ACCOUNT")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_HYPE_TEMPLATES =[
    "{a} fans are still buzzing, {b} fans still fuming — this one's got no cure. 🔥",
    "The takes don't lie: {a} vs {b} isn't a match, it's a blood feud with a scoreboard.",
    "{a} brought the noise, {b} brought the nerve. Neither side is backing down. 🌡️",
    "Somewhere between heartbreak and glory, {a} and {b} keep finding new ways to hurt each other.",
]

app = FastAPI(title="Rivalry Radar API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Google AI (Gemini) — real calls when GEMINI_API_KEY is set
# ---------------------------------------------------------------------------
_genai_client = None

def get_genai_client():
    global _genai_client
    if _genai_client is None:
        from google import genai
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
    return _genai_client


def gemini_score_sentiment(text: str) -> dict:
    """Ask Gemini to classify a take's sentiment. Falls back to a keyword
    heuristic if no GEMINI_API_KEY is configured."""
    if not GEMINI_API_KEY:
        return _heuristic_sentiment(text)
    client = get_genai_client()
    prompt = (
        "Classify the overall emotional sentiment of this football fan "
        "comment as exactly one word — positive, negative, mixed, or "
        f"neutral. Reply with only that one word.\n\nComment: {text}"
    )
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    word = response.text.strip().lower().split()[0].strip(".,!")
    overall = word if word in {"positive", "negative", "mixed", "neutral"} else "neutral"
    intensity = {"positive": 1.0, "negative": 1.0, "mixed": 0.85, "neutral": 0.2}[overall]
    return {"overall_sentiment": overall, "sentiment_intensity": intensity}


def gemini_hype_verdict(team_a_name: str, team_b_name: str, recent_takes: list) -> str:
    """Ask Gemini for a punchy stadium-announcer verdict on a rivalry.
    Falls back to a canned template if no GEMINI_API_KEY is configured."""
    if not GEMINI_API_KEY or not recent_takes:
        template = random.choice(_HYPE_TEMPLATES)
        return template.format(a=team_a_name, b=team_b_name)
    client = get_genai_client()
    joined = " | ".join(recent_takes[:8])
    prompt = (
        "You are a stadium hype announcer. In under 40 words, deliver a "
        f"punchy verdict on the {team_a_name} vs {team_b_name} World Cup "
        f"rivalry based on these fan takes: {joined}"
    )
    response =client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return response.text.strip()


def _heuristic_sentiment(text: str) -> dict:
    """Stand-in for gemini_score_sentiment when no API key is configured."""
    lowered = text.lower()
    negative_cues = ["fuming", "curse", "joke", "cost us", "heartbreak"]
    mixed_cues = ["but", "still", "however"]
    if any(c in lowered for c in negative_cues):
        overall = "negative"
    elif any(c in lowered for c in mixed_cues):
        overall = "mixed"
    else:
        overall = "positive"
    intensity = {"positive": 1.0, "negative": 1.0, "mixed": 0.85, "neutral": 0.2}[overall]
    return {"overall_sentiment": overall, "sentiment_intensity": intensity}


# ---------------------------------------------------------------------------
# Snowflake connection (real mode only) — storage + Heat Index analytics
# ---------------------------------------------------------------------------
def get_snowflake_conn():
    import snowflake.connector
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ.get("SNOWFLAKE_PASSWORD"),
        private_key_file=os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE"),
        role=os.environ.get("SNOWFLAKE_ROLE", "SYSADMIN"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "RIVALRY_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "RIVALRY_RADAR"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "CORE"),
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class TakeIn(BaseModel):
    fan_handle: str = Field(..., max_length=40)
    team_code: str
    rival_code: str
    take_text: str = Field(..., max_length=280)
    passion_rating: int = Field(..., ge=1, le=10)


TEAMS = {
    "BRA": ("Brazil", "🇧🇷", "#FFD60A"), "ARG": ("Argentina", "🇦🇷", "#6CA6D9"),
    "FRA": ("France", "🇫🇷", "#0A2E6B"), "ENG": ("England", "🏴", "#CE1126"),
    "GER": ("Germany", "🇩🇪", "#111111"), "ESP": ("Spain", "🇪🇸", "#C60B1E"),
    "POR": ("Portugal", "🇵🇹", "#046A38"), "NED": ("Netherlands", "🇳🇱", "#FF6600"),
    "URU": ("Uruguay", "🇺🇾", "#5CB8E4"), "MAR": ("Morocco", "🇲🇦", "#C1272D"),
    "JPN": ("Japan", "🇯🇵", "#0033A0"), "USA": ("United States", "🇺🇸", "#B22234"),
}

# ---------------------------------------------------------------------------
# DEMO MODE in-memory store, seeded so the leaderboard isn't empty on boot
# ---------------------------------------------------------------------------
_DEMO_TAKES = []

def _seed_demo():
    seeds =[
        ("nervous_torcedor", "BRA", "ARG", "Our midfield press turned their defense inside out, but the ref's whistle was a joke tonight.", 9),
        ("hincha_del_alma", "ARG", "BRA", "Absolute masterclass. Their keeper had no answer for us. This rivalry lives forever.", 8),
        ("terrace_ultra", "ENG", "FRA", "We dominated possession and still found a way to make it stressful. Classic us.", 6),
        ("le_supporter", "FRA", "ENG", "Ice in our veins. Their fans were louder but we let the football do the talking.", 7),
        ("gruener_fan", "GER", "ESP", "The manager's substitutions cost us the whole second half. Fuming.", 9),
        ("la_furia", "ESP", "GER", "Tiki-taka is back baby, we passed them into the ground.", 8),
        ("oranje_gek", "NED", "POR", "Their attack was relentless but our defense held strong when it mattered.", 6),
        ("celeste_fiel", "URU", "MAR", "Heartbreak again. This rivalry is cursed for us.", 10),
    ]
    for handle, team, rival, text, rating in seeds:
        _DEMO_TAKES.append({
            "take_id": str(uuid.uuid4()), "fan_handle": handle,
            "team_code": team, "rival_code": rival, "take_text": text,
            "passion_rating": rating,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            **_demo_sentiment(text),
        })

def _demo_sentiment(text: str) -> dict:
    return gemini_score_sentiment(text)

if DEMO_MODE:
    _seed_demo()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"status": "ok", "message": "Rivalry Radar API is running", "docs": "/docs"}


@app.get("/api/teams")
def list_teams():
    return [{"code": c, "name": n, "flag": f, "color": col} for c, (n, f, col) in TEAMS.items()]


@app.post("/api/takes")
def submit_take(take: TakeIn):
    if take.team_code == take.rival_code:
        raise HTTPException(400, "A team can't rival itself.")

    if DEMO_MODE:
        row = take.dict()
        row.update({
            "take_id": str(uuid.uuid4()),
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            **_demo_sentiment(take.take_text),
        })
        _DEMO_TAKES.append(row)
        return row

    # --- REAL MODE: score with Gemini, then store the result in Snowflake ---
    scored =gemini_score_sentiment(take.take_text)
    conn =get_snowflake_conn()
    try:
        cur = conn.cursor()
        take_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO FAN_TAKES
              (take_id, fan_handle, team_code, rival_code, take_text,
               passion_rating, overall_sentiment, sentiment_intensity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (take_id, take.fan_handle, take.team_code, take.rival_code,
             take.take_text, take.passion_rating,
             scored["overall_sentiment"], scored["sentiment_intensity"]),
        )
        return {**take.dict(), "take_id": take_id, **scored}
    finally:
        conn.close()


@app.get("/api/leaderboard/rivalries")
def rivalry_leaderboard():
    if DEMO_MODE:
        agg = {}
        for t in _DEMO_TAKES:
            key = "-".join(sorted([t["team_code"], t["rival_code"]]))
            a = agg.setdefault(key, {"takes": [], "passion": [], "intensity": []})
            a["takes"].append(t); a["passion"].append(t["passion_rating"])
            a["intensity"].append(t["sentiment_intensity"])
        rows = []
        for key, a in agg.items():
            n = len(a["takes"])
            avg_p = sum(a["passion"]) / n
            avg_i = sum(a["intensity"]) / n
            import math
            heat = round(avg_p * 0.5 + avg_i * 3 + math.log2(n + 1) * 2, 2)
            rows.append({"rivalry_key": key, "take_count": n,
                         "avg_passion_rating": round(avg_p, 2),
                         "avg_sentiment_intensity": round(avg_i, 2),
                         "heat_index": heat})
        rows.sort(key=lambda r: -r["heat_index"])
        for i, r in enumerate(rows):
            r["heat_rank"] = i + 1
        return rows

    conn = get_snowflake_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM RIVALRY_HEAT_INDEX ORDER BY heat_rank")
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/leaderboard/fanbases")
def fanbase_leaderboard():
    if DEMO_MODE:
        agg ={}
        for t in _DEMO_TAKES:
            a = agg.setdefault(t["team_code"], {"passion": [], "intensity": []})
            a["passion"].append(t["passion_rating"]); a["intensity"].append(t["sentiment_intensity"])
        rows = []
        for team, a in agg.items():
            n = len(a["passion"])
            avg_p = sum(a["passion"]) / n
            avg_i = sum(a["intensity"]) / n
            rows.append({"team_code": team, "take_count": n,
                         "avg_passion_rating": round(avg_p, 2),
                         "avg_sentiment_intensity": round(avg_i, 2),
                         "score": round(avg_p * avg_i, 2)})
        rows.sort(key=lambda r: -r["score"])
        for i, r in enumerate(rows):
            r["passion_rank"] = i + 1
        return rows

    conn = get_snowflake_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM FANBASE_LEADERBOARD ORDER BY passion_rank")
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/hype/{team_a}/{team_b}")
def hype_verdict(team_a: str, team_b: str):
    """Gemini-powered hype verdict for a rivalry, based on recent takes."""
    key = "-".join(sorted([team_a, team_b]))
    name_a = TEAMS.get(team_a, (team_a,))[0]
    name_b = TEAMS.get(team_b, (team_b,))[0]

    if DEMO_MODE:
        recent = [t for t in _DEMO_TAKES
                  if "-".join(sorted([t["team_code"], t["rival_code"]])) == key][-6:]
        verdict = gemini_hype_verdict(name_a, name_b, [t["take_text"] for t in recent])
        return {"rivalry_key": key, "hype_verdict": verdict, "based_on_takes": len(recent)}

    conn = get_snowflake_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT take_text FROM FAN_TAKES
            WHERE (team_code = %s AND rival_code = %s) OR (team_code = %s AND rival_code = %s)
            ORDER BY submitted_at DESC LIMIT 8
            """,
            (team_a, team_b, team_b, team_a),
        )
        recent_texts = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    verdict = gemini_hype_verdict(name_a, name_b, recent_texts)
    return {"rivalry_key": key, "hype_verdict": verdict, "based_on_takes": len(recent_texts)}


@app.get("/api/mode")
def mode():
    return {"demo_mode": DEMO_MODE}
