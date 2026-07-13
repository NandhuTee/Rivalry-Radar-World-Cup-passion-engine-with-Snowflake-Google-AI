-- ============================================================================
-- RIVALRY RADAR — Snowflake schema, Cortex AI functions, and analytics
-- ============================================================================
-- Run this in a Snowflake worksheet (or `snow sql -f schema.sql`) as a role
-- that has ACCOUNTADMIN or has been granted CORTEX_USER / AI_FUNCTIONS_USER.
-- ============================================================================

CREATE WAREHOUSE IF NOT EXISTS RIVALRY_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS RIVALRY_RADAR;
CREATE SCHEMA IF NOT EXISTS RIVALRY_RADAR.CORE;

USE WAREHOUSE RIVALRY_WH;
USE DATABASE RIVALRY_RADAR;
USE SCHEMA CORE;

-- A role calling AI_SENTIMENT / AI_COMPLETE needs the AI_FUNCTIONS_USER
-- (or legacy CORTEX_USER) database role plus USE AI FUNCTIONS privilege.
-- Uncomment and adjust ROLE_NAME for your account:
-- GRANT DATABASE ROLE SNOWFLAKE.AI_FUNCTIONS_USER TO ROLE <ROLE_NAME>;

-- ----------------------------------------------------------------------------
-- 1. Reference data: the 32 World Cup nations fans can rep
-- ----------------------------------------------------------------------------
CREATE OR REPLACE TABLE TEAMS (
  team_code   STRING PRIMARY KEY,   -- 'BRA', 'ARG', ...
  team_name   STRING NOT NULL,
  flag_emoji  STRING,
  primary_hex STRING                -- brand color used by the frontend
);

INSERT INTO TEAMS VALUES
  ('BRA','Brazil','🇧🇷','#FFD60A'),
  ('ARG','Argentina','🇦🇷','#6CA6D9'),
  ('FRA','France','🇫🇷','#0A2E6B'),
  ('ENG','England','🏴󠁧󠁢󠁥󠁮󠁧󠁿','#CE1126'),
  ('GER','Germany','🇩🇪','#111111'),
  ('ESP','Spain','🇪🇸','#C60B1E'),
  ('POR','Portugal','🇵🇹','#046A38'),
  ('NED','Netherlands','🇳🇱','#FF6600'),
  ('URU','Uruguay','🇺🇾','#5CB8E4'),
  ('MAR','Morocco','🇲🇦','#C1272D'),
  ('JPN','Japan','🇯🇵','#0033A0'),
  ('USA','United States','🇺🇸','#B22234');

-- ----------------------------------------------------------------------------
-- 2. Fan-submitted "Terrace Takes" — the raw passion data
-- ----------------------------------------------------------------------------
CREATE OR REPLACE TABLE FAN_TAKES (
  take_id           STRING DEFAULT UUID_STRING(),
  fan_handle        STRING NOT NULL,
  team_code         STRING NOT NULL REFERENCES TEAMS(team_code),
  rival_code        STRING NOT NULL REFERENCES TEAMS(team_code),
  take_text         STRING NOT NULL,       -- max 280 chars, enforced app-side
  passion_rating    NUMBER(2,0) NOT NULL,  -- fan's own 1-10 "how much this hurt/thrilled me"
  overall_sentiment STRING,                -- 'positive' | 'negative' | 'mixed' | 'neutral'
  sentiment_intensity NUMBER(3,2),         -- 0.0-1.0, derived from overall_sentiment
  submitted_at      TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP()
);

-- ----------------------------------------------------------------------------
-- 3. Sentiment scoring — Google AI (Gemini)
--    Snowflake Cortex's AI_SENTIMENT isn't available on every account tier
--    (some trial accounts block it outright), so this build scores each take
--    with Gemini directly from the FastAPI backend (see backend/app.py:
--    score_sentiment) the moment it's submitted, then writes the result
--    straight into overall_sentiment / sentiment_intensity above. Snowflake's
--    job here is storage + analytics, not the scoring itself — the Heat
--    Index math below is unaffected either way.
-- ----------------------------------------------------------------------------

-- ----------------------------------------------------------------------------
-- 4. Heat Index — the per-rivalry passion leaderboard
--    Combines: how many takes a rivalry generates, how emotionally intense
--    those takes are (via AI_SENTIMENT), and how hard fans self-rated the
--    pain/joy. RANK() gives every rivalry its live leaderboard position.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW RIVALRY_HEAT_INDEX AS
WITH rivalry_pairs AS (
  SELECT
    ARRAY_TO_STRING(ARRAY_SORT(ARRAY_CONSTRUCT(team_code, rival_code)), '-') AS rivalry_key,
    team_code, rival_code, sentiment_intensity, passion_rating
  FROM FAN_TAKES
)
SELECT
  rivalry_key,
  COUNT(*)                                   AS take_count,
  ROUND(AVG(passion_rating), 2)              AS avg_passion_rating,
  ROUND(AVG(sentiment_intensity), 2)         AS avg_sentiment_intensity,
  ROUND(
    (AVG(passion_rating) * 0.5)
    + (AVG(sentiment_intensity) * 3)
    + (LOG(2, COUNT(*) + 1) * 2)
  , 2)                                        AS heat_index,
  RANK() OVER (ORDER BY heat_index DESC)      AS heat_rank
FROM rivalry_pairs
GROUP BY rivalry_key;

-- ----------------------------------------------------------------------------
-- 5. The AI "Hype Verdict" — also Google AI (Gemini)
--    Given the most recent takes for a rivalry, backend/app.py:hype_verdict
--    calls Gemini directly to write a short, punchy, stadium-announcer
--    verdict. This runs on demand rather than living in a view, since it
--    should reflect the *latest* takes every time it's requested.
-- ----------------------------------------------------------------------------

-- ----------------------------------------------------------------------------
-- 6. Most Passionate Fanbase leaderboard (per team, across all rivalries)
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW FANBASE_LEADERBOARD AS
SELECT
  team_code,
  COUNT(*)                              AS take_count,
  ROUND(AVG(passion_rating), 2)         AS avg_passion_rating,
  ROUND(AVG(sentiment_intensity), 2)    AS avg_sentiment_intensity,
  RANK() OVER (ORDER BY AVG(passion_rating) * AVG(sentiment_intensity) DESC) AS passion_rank
FROM FAN_TAKES
GROUP BY team_code;
