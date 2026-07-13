# 🔥 Rivalry Radar — World Cup Passion Engine

Fans drop 280-character **Terrace Takes** on any World Cup matchup. **Google AI
(Gemini)** scores the emotion behind every word and writes a stadium-announcer
**Hype Verdict**; **Snowflake** stores every take and computes a live **Heat
Index** that ranks exactly which rivalry is boiling hottest right now.

> Built for the DEV **Weekend Challenge: Passion Edition** 🏆 Best Use of Google AI and Best Use of Snowflake 

## Why this exists

Passion is easy to feel and hard to measure. Every World Cup rivalry generates
an ocean of unstructured text — chants, rants, one-line hot takes — that
traditionally just... disappears into group chats. Rivalry Radar treats that
text as data: Gemini reads the emotion in it the moment it's written, and
Snowflake turns that into a live, rankable leaderboard.

## How the work is split

| | Does what |
|---|---|
| **Google AI (Gemini)** | Scores each take's sentiment (positive/negative/mixed/neutral) the instant it's submitted, and writes the punchy "Hype Verdict" from the latest takes on a matchup. |
| **Snowflake** | Stores every take, and computes the Heat Index and leaderboards with real SQL — aggregation, a derived metric, and `RANK() OVER (ORDER BY heat_index DESC)`. |
| **FastAPI** | The glue — receives requests, calls Gemini, reads/writes Snowflake, returns JSON. |

## What's inside

```
rivalry-radar/
├── frontend/index.html   # Self-contained demo UI (open directly in a browser)
├── backend/app.py        # FastAPI service — real Gemini + Snowflake calls, with a demo-mode fallback
├── backend/requirements.txt
└── sql/schema.sql         # Snowflake DDL and the Heat Index / leaderboard views
```

### Try it in 10 seconds

Open `frontend/index.html` in any browser. It ships with seed data and a
JavaScript stand-in for the scoring logic, so you can submit takes, watch the
Heat Index flip like an airport departure board, and see the leaderboards
re-rank — no API keys or accounts required.

### Run it for real (Gemini + Snowflake)

1. **Get a free Gemini API key** — no credit card required:
   [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. **Set up Snowflake** — open a Snowflake worksheet and run `sql/schema.sql`.
   This creates the `RIVALRY_WH` warehouse, the `RIVALRY_RADAR.CORE` schema,
   the `TEAMS` and `FAN_TAKES` tables, and the `RIVALRY_HEAT_INDEX` /
   `FANBASE_LEADERBOARD` views.
3. `cd backend && pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and fill in your Gemini key + Snowflake
   details, or export the same variables directly:
   ```bash
   export GEMINI_API_KEY=your_gemini_api_key
   export SNOWFLAKE_ACCOUNT=xxxxx-xxxxx
   export SNOWFLAKE_USER=your_user
   export SNOWFLAKE_PASSWORD=your_password
   export SNOWFLAKE_ROLE=SYSADMIN
   ```
5. `uvicorn app:app --reload` — the API now scores real takes with Gemini and
   stores/ranks them in real Snowflake.

You don't need both configured — the app degrades gracefully:
- No `GEMINI_API_KEY` → sentiment scoring and the hype verdict fall back to a
  small local keyword heuristic.
- No `SNOWFLAKE_ACCOUNT` → the whole API runs in **demo mode** with the same
  seed data as the frontend.

## How the passion gets measured

**Gemini** scores each take's overall sentiment — positive, negative, mixed,
or neutral — via `backend/app.py:gemini_score_sentiment`, which is mapped to
a numeric intensity (fury counts exactly as much as joy — both are passion):

```python
prompt = (
    "Classify the overall emotional sentiment of this football fan "
    "comment as exactly one word — positive, negative, mixed, or "
    f"neutral. Reply with only that one word.\n\nComment: {text}"
)
response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
```

That intensity, combined with each fan's own 1–10 passion rating and the
log-scaled volume of takes, becomes the **Heat Index** — computed and ranked
entirely in Snowflake SQL:

```sql
ROUND(
  (AVG(passion_rating) * 0.5)
  + (AVG(sentiment_intensity) * 3)
  + (LOG(2, COUNT(*) + 1) * 2)
, 2) AS heat_index,
RANK() OVER (ORDER BY heat_index DESC) AS heat_rank
```

**Gemini** also turns the most recent takes for a matchup into the Hype
Verdict, written in the voice of a stadium announcer:

```python
prompt = (
    "You are a stadium hype announcer. In under 40 words, deliver a "
    f"punchy verdict on the {team_a_name} vs {team_b_name} World Cup "
    f"rivalry based on these fan takes: {joined}"
)
```

## Prize category

**Best Use of Google AI** — Gemini does the real intelligence work behind
this project: reading the emotion in every fan take and writing the Hype
Verdict. Snowflake plays an honest, secondary role as the data warehouse —
storing every take and doing the ranking analytics (`RANK() OVER`,
aggregation) that turns Gemini's scores into a leaderboard.
