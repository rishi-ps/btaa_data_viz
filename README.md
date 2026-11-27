# What's Your Team's Personality?

**How did every NCAA Division I women's basketball team play from 2016–17 to 2025–26, and which playing styles reach the Final Four?**

An interactive data story built with Python (DuckDB, pandas) and plain JavaScript and SVG, on 10 seasons of official ESPN game data. Made for the Big Ten Academic Alliance Data Viz Student Championship (Love Data Week 2027), University of Maryland.

**[View the dashboard](https://rishi-ps.github.io/dashboards/team-personality.html)**

To run it locally, download [`dashboard/team_personality.html`](dashboard/team_personality.html) and open it in any browser. It is a single self-contained file with no server and no external data.

## The short version

Fans describe teams by style: "they run", "they live behind the arc". This project turns that into two simple measures for every team in every season, and uses them to sort teams into four personalities.

- **Pace:** how many possessions a team plays per game. A **possession** is one turn with the ball, so more possessions means a faster game.
- **Three-point share:** what share of a team's shots are three-pointers.

Both are measured against that season's average team, so a team is "fast" or "slow", "more threes" or "fewer threes", compared with everyone else that year.

| | More threes | Fewer threes |
|---|---|---|
| **Faster** | Fast Shooters | Fast Attackers |
| **Slower** | Slow Shooters | Slow Attackers |

**Results**, across 3,484 team-seasons and 9 NCAA tournaments (the 2020 tournament was canceled):
- **Fast Attackers win.** They make up 27% of team-seasons but filled 14 of 36 Final Four spots and won 4 titles.
- **Teams that take fewer threes dominate March.** Fast and Slow Attackers together filled 24 of 36 Final Four spots and won 7 of 9 titles.
- **Fast Shooters have never won a title** in this period. Their two trips to the final were Iowa in 2023 and 2024.
- **Maryland** was a Fast Attacker in all 10 seasons. **UCLA** won the 2026 title as a Slow Attacker.

Nine tournaments show a pattern, not proof. The page presents these as associations and lets readers explore their own team.

## Why these two measures

Both measure **style, not quality**, so any team, good or bad, can land in any of the four groups.

This is checked with **correlation**, which runs from −1 to 1. Values near 0 mean two things are unrelated.
- Correlation with **net rating** (points scored minus points allowed per 100 possessions, a standard measure of team strength): −0.01 for pace, 0.05 for three-point share.
- Correlation between the two measures: −0.07, so they capture different things.

## What's on the page

- **Personality map:** every team-season as a dot, with Final Four teams and champions marked. Filter by season and conference, or search for a team to see its path across seasons.
- **Meet the four personalities:** each style's share of all teams compared with its share of Final Four spots and titles.
- **Hot takes from the data:** short findings readers can check on the map.
- **How it was made:** method, data cleaning and sources.

**Accessibility:**
- Every control works with a keyboard and shows a visible focus state.
- Colors are checked for colorblind readers. Champions are marked by shape and outline, not only by color.
- Charts have text summaries.
- Light and dark themes.
- The layout adapts to phone screens.

## Method

1. **Clean** (`scripts/01_clean.py`): reads the official ESPN data files with DuckDB and writes clean Parquet tables.
   - Removes postponed, canceled, forfeited and exhibition games (183 in all).
   - Drops did-not-play and duplicate player rows.
   - Converts stats stored as text into numbers.
   - Estimates possessions from box-score stats.
   - Tags each team with the conference it was in at the time of the game.
   - Prints a log of every rule and how many rows it touched.
2. **Build** (`scripts/08_build_team_personality.py`):
   - Keeps only games between two Division I teams, and team-seasons with at least 15 games.
   - Drops 8 games with impossible possession counts (outside 45–110), such as a game logged with 727 turnovers.
   - Computes each team-season's pace and three-point share compared with the season average.
   - Adds NCAA tournament results.
   - Fills the HTML template (`scripts/templates/team_personality.html`, plain JavaScript and SVG with no libraries) with the pre-aggregated data.
3. **Test** (`tests/test_team_personality.py`): 12 unit tests covering:
   - the season-relative measures
   - which quadrant each team lands in
   - the tournament results (every Final Four team is in the sample, and there is one champion per year)
   - that both measures stay unrelated to team strength

## Limitations

- **"Attackers" means "takes mostly two-pointers".** Box scores can't tell shots at the rim from mid-range twos, so the page avoids saying "rim" or "paint".
- **Nine tournaments is a small sample.** The findings are associations. They don't show that a style causes winning.

## Project structure

```
scripts/01_clean.py                      raw ESPN files -> data/clean/*.parquet
scripts/08_build_team_personality.py     measures, quadrants, tournament results -> dashboard
scripts/templates/team_personality.html  page template (JavaScript + SVG, no data)
dashboard/team_personality.html          the built page
tests/test_team_personality.py           unit tests
```

## Reproduce

The competition data is not included in this repository. Place the official `NCAA Women's Basketball Data Files 2026/` folder in the project root, then:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/01_clean.py                  # about 15 s
.venv/bin/python scripts/08_build_team_personality.py
.venv/bin/python -m unittest discover -s tests -p 'test_team_personality.py'
```

## Data and credits

- NCAA women's basketball data (ESPN), provided by the Big Ten Academic Alliance for the 2027 Data Viz Student Championship.
- AI assistance (Claude) was used for research synthesis, analysis code, tests, and dashboard copy and implementation, as disclosed in the submission.
