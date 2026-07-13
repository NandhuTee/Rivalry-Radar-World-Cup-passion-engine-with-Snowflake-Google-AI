*This is a submission for [Weekend Challenge: Passion Edition](https://dev.to/challenges/weekend-2026-07-09)*

## What I Built

**Rivalry Radar** — a live "Heat Index" for World Cup rivalries. Fans drop
280-character **Terrace Takes** on any matchup (Brazil vs Argentina, England
vs France, whatever's got you shouting at the TV), rate how much the moment
hurt or thrilled them from 1–10, and the app does the rest:

- **Google AI (Gemini)** scores every take's sentiment the instant it lands —
  positive, negative, mixed, or neutral — and separately writes a short
  "Hype Verdict" in the voice of a stadium announcer, based on the latest
  takes for a matchup.
- That sentiment score feeds a **Heat Index**, computed and ranked in
  **Snowflake** with `RANK() OVER (ORDER BY heat_index DESC)`, combining take
  volume, sentiment intensity, and self-rated passion into one live number
  per rivalry.
- Two leaderboards: which **rivalry** is hottest right now, and which
  **fanbase** is bringing the most passion overall.

Passion is usually a vibe — this turns it into a number you can rank.

## Demo

`frontend/index.html` is fully self-contained: open it in a browser and you
can submit takes, watch the Heat Index flip digit-by-digit like an airport
departure board, and see the leaderboards re-rank in real time. It ships with
seed takes from eight classic rivalries so it's not empty on first load.

*(Screen recording )*

## Code

*(Embed GitHub repo  )*

```
rivalry-radar/
├── frontend/index.html   # self-contained demo UI
├── backend/app.py        # FastAPI service — real Gemini + Snowflake calls, with a demo-mode fallback
├── backend/requirements.txt
└── sql/schema.sql         # Snowflake DDL and the Heat Index / leaderboard views
```

## How I Built It

I started from the Heat Index formula, because that's the number the whole
app orbits around: `avg_passion * 0.5 + avg_sentiment_intensity * 3 +
log2(take_count + 1) * 2`. Volume matters (a rivalry with one take isn't
"hot"), but so does how emotionally loaded the language is — and that's
where Google AI comes in.

**Gemini** reads each take and classifies its sentiment:

```python
prompt = (
    "Classify the overall emotional sentiment of this football fan "
    "comment as exactly one word — positive, negative, mixed, or "
    f"neutral. Reply with only that one word.\n\nComment: {text}"
)
response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
```

I mapped that categorical result to a numeric intensity — fury counts
exactly as much as joy, both are passion — so it drops straight into the
Heat Index math.

For the fun part, Gemini also turns the most recent takes for a rivalry into
a punchy one-liner:

```python
prompt = (
    "You are a stadium hype announcer. In under 40 words, deliver a "
    f"punchy verdict on the {team_a_name} vs {team_b_name} World Cup "
    f"rivalry based on these fan takes: {joined}"
)
```

**Snowflake** handles the other half of the job: storing every take and
computing the leaderboards with real SQL — aggregation, a derived metric,
and a `RANK()` window function per rivalry and per fanbase. It's a clean
split: Gemini reads the emotion, Snowflake turns it into a ranking.

The backend is a small FastAPI service with two independent fallbacks, so
the whole flow is explorable without handing out API keys for a weekend
project: no `GEMINI_API_KEY` → sentiment scoring falls back to a keyword
heuristic; no `SNOWFLAKE_ACCOUNT` → the whole API runs in demo mode with
seed data.

The frontend leaned into the subject: a split-flap "departure board" digit
animation for the Heat Index, a scrolling terrace-chant ticker, and a
submission form styled like a stadium chalkboard — trying to make the data
feel like the thing it's measuring.


## Prize Categories

Submitting for **Best Use of Google AI** — Gemini does the real intelligence
work in this project: reading the emotion behind every fan take and writing
the Hype Verdict. Snowflake plays an honest supporting role as the data
warehouse, storing every take and doing the ranking analytics that turn
Gemini's scores into a live leaderboard.
