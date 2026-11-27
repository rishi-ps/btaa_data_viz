"""Build the "What's your team's personality?" dashboard.

Each Division I team-season from 2016-17 to 2025-26 is placed on two style
axes, both measured relative to that season's average team:

* Pace: possessions per game (faster or slower than average).
* Three-point share: share of field-goal attempts that are threes
  (more or fewer than average).

The two axes split teams into four personalities. Both measures are nearly
uncorrelated with team strength (net rating), so the quadrants describe style,
not quality. Tournament results are joined to show where Final Four teams and
champions land.

Run:  .venv/bin/python scripts/08_build_team_personality.py
Out:  dashboard/team_personality.html
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "clean"
OUT = ROOT / "dashboard" / "team_personality.html"

FIRST_SEASON = 2017          # team box scores are reliable from 2016-17
MIN_GAMES = 15               # D1-vs-D1 games needed for a team-season
POSS_RANGE = (45.0, 110.0)   # plausible possessions per team-game

# Quadrant order is fixed and shared with the page.
PERSONALITIES = [
    {"key": "run", "name": "Fast Shooters", "fast": True, "outside": True,
     "blurb": "Push the pace and fire threes early."},
    {"key": "track", "name": "Fast Attackers", "fast": True, "outside": False,
     "blurb": "Push the pace and score mostly inside the arc."},
    {"key": "snipers", "name": "Slow Shooters", "fast": False, "outside": True,
     "blurb": "Work the clock and hunt for open threes."},
    {"key": "bruisers", "name": "Slow Attackers", "fast": False, "outside": False,
     "blurb": "Work the clock and score mostly inside the arc."},
]

ROUND_ORDER = ["First Four", "Round of 64", "Round of 32", "Sweet 16",
               "Elite 8", "Final Four", "Final", "Champion"]


# ---------------------------------------------------------------- pure logic

def personality_index(pace_diff: float, three_diff: float) -> int:
    """Index into PERSONALITIES. Exactly average counts as fast / outside."""
    fast = pace_diff >= 0
    outside = three_diff >= 0
    for i, p in enumerate(PERSONALITIES):
        if p["fast"] == fast and p["outside"] == outside:
            return i
    raise AssertionError("unreachable")


def add_season_relative(df: pd.DataFrame) -> pd.DataFrame:
    """Add pace_diff (possessions) and three_diff (percentage points) vs the
    mean team-season of the same season, plus the personality index."""
    out = df.copy()
    pace_avg = out.groupby("season")["pace"].transform("mean")
    three_avg = out.groupby("season")["three_share"].transform("mean")
    out["pace_diff"] = out["pace"] - pace_avg
    out["three_diff"] = 100 * (out["three_share"] - three_avg)
    out["quad"] = [personality_index(p, t) for p, t in zip(out.pace_diff, out.three_diff)]
    return out


def standings(df: pd.DataFrame) -> list[dict]:
    """Team-seasons, Final Four spots, finals and titles per personality."""
    rows = []
    total = len(df)
    ff_total = int((df.finish_rank >= ROUND_ORDER.index("Final Four")).sum())
    for i, p in enumerate(PERSONALITIES):
        q = df[df.quad == i]
        ff = int((q.finish_rank >= ROUND_ORDER.index("Final Four")).sum())
        rows.append({
            "key": p["key"],
            "team_seasons": int(len(q)),
            "share_all": len(q) / total if total else 0.0,
            "final_four": ff,
            "share_ff": ff / ff_total if ff_total else 0.0,
            "finals": int((q.finish_rank >= ROUND_ORDER.index("Final")).sum()),
            "titles": int((q.finish_rank == ROUND_ORDER.index("Champion")).sum()),
        })
    return rows


def axis_limit(values: pd.Series, q: float = 0.995, step: float = 2.0) -> float:
    """Symmetric axis limit that covers the q-quantile of |values|."""
    lim = values.abs().quantile(q)
    return float(math.ceil(lim / step) * step)


# ---------------------------------------------------------------- data

def load_team_seasons(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict]:
    tb = (CLEAN / "team_box.parquet").as_posix()
    log: dict = {}

    con.sql(f"""
        create or replace temp table tg as
        select t.game_id, t.season, t.team_id, t.team_location, t.conference,
               t.won, t.fga, t.fg3a, t.possessions::double as poss,
               t.team_score, t.opponent_team_score,
               o.possessions::double as opp_poss
        from '{tb}' t
        join '{tb}' o on o.game_id = t.game_id and o.team_id = t.opponent_team_id
        where t.season >= {FIRST_SEASON} and t.both_d1
          and t.stats_consistent and o.stats_consistent
    """)
    log["team_games_start"] = con.sql("select count(*) from tg").fetchall()[0][0]

    lo, hi = POSS_RANGE
    bad = con.sql(f"""
        select count(distinct game_id) from tg
        where poss not between {lo} and {hi} or opp_poss not between {lo} and {hi}
    """).fetchall()[0][0]
    log["games_dropped_possessions"] = int(bad)
    con.sql(f"""
        delete from tg where game_id in (
          select game_id from tg
          where poss not between {lo} and {hi} or opp_poss not between {lo} and {hi})
    """)
    log["team_games_kept"] = con.sql("select count(*) from tg").fetchall()[0][0]

    df = con.sql(f"""
        select season, team_id,
               mode(team_location) as team,
               mode(conference) as conf,
               count(*) as games,
               sum(won::int) as wins,
               sum(poss) / count(*) as pace,
               sum(fg3a)::double / sum(fga) as three_share,
               100 * (sum(team_score) - sum(opponent_team_score)) / sum(poss) as net
        from tg
        group by season, team_id
    """).df()
    log["team_seasons_all"] = len(df)
    df = df[df.games >= MIN_GAMES].reset_index(drop=True)
    log["team_seasons_kept"] = len(df)
    return df, log


def load_tournament(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Furthest NCAA tournament round per team-season (Champion for the winner)."""
    g = (CLEAN / "games.parquet").as_posix()
    t = con.sql(f"""
        select season, ncaa_round, home_id as team_id, winner_id from '{g}'
        where ncaa_round is not null and season >= {FIRST_SEASON}
        union all
        select season, ncaa_round, away_id, winner_id from '{g}'
        where ncaa_round is not null and season >= {FIRST_SEASON}
    """).df()
    t["rank"] = t.ncaa_round.map(ROUND_ORDER.index)
    champ = t[(t.ncaa_round == "Final") & (t.team_id == t.winner_id)].copy()
    champ["rank"] = ROUND_ORDER.index("Champion")
    t = pd.concat([t, champ])
    return t.groupby(["season", "team_id"], as_index=False)["rank"].max()


def build() -> tuple[dict, dict]:
    con = duckdb.connect()
    df, log = load_team_seasons(con)
    tour = load_tournament(con)
    df = df.merge(tour, on=["season", "team_id"], how="left")
    df["finish_rank"] = df["rank"].fillna(-1).astype(int)
    df = df.drop(columns="rank")
    df = add_season_relative(df)

    corr = df[["pace_diff", "three_diff", "net"]].corr()
    log["corr_pace_net"] = round(float(corr.loc["pace_diff", "net"]), 2)
    log["corr_three_net"] = round(float(corr.loc["three_diff", "net"]), 2)
    log["corr_pace_three"] = round(float(corr.loc["pace_diff", "three_diff"]), 2)

    # every champion/Final Four team in the tournament data must be in the sample
    expected_ff = int((tour["rank"] >= ROUND_ORDER.index("Final Four")).sum())
    got_ff = int((df.finish_rank >= ROUND_ORDER.index("Final Four")).sum())
    log["final_four_expected"], log["final_four_in_sample"] = expected_ff, got_ff

    seasons = sorted(int(s) for s in df.season.unique())
    season_avg = (df.groupby("season")
                    .agg(pace=("pace", "mean"), three=("three_share", "mean"))
                    .reset_index())

    teams = {int(r.team_id): r.team for r in
             df.sort_values("season").drop_duplicates("team_id", keep="last").itertuples()}

    rows = [[int(r.season), int(r.team_id), r.conf, int(r.wins), int(r.games - r.wins),
             round(float(r.pace_diff), 2), round(float(r.three_diff), 2),
             round(float(r.pace), 1), round(100 * float(r.three_share), 1),
             int(r.quad), int(r.finish_rank)]
            for r in df.itertuples()]

    payload = {
        "personalities": PERSONALITIES,
        "rounds": ROUND_ORDER,
        "seasons": seasons,
        "seasonAvg": {int(r.season): [round(float(r.pace), 1), round(100 * float(r.three), 1)]
                      for r in season_avg.itertuples()},
        "teams": teams,
        "conferences": sorted(df.conf.dropna().unique().tolist()),
        "rows": rows,
        "limits": {"pace": axis_limit(df.pace_diff, step=2.0),
                   "three": axis_limit(df.three_diff, step=5.0)},
        "standings": standings(df),
        "log": log,
    }
    return payload, df


def main() -> None:
    payload, df = build()
    log = payload["log"]
    print("Team personality build")
    for k, v in log.items():
        print(f"  {k}: {v}")
    print("  axis limits:", payload["limits"])
    print("  standings:")
    for s in payload["standings"]:
        print("   ", s)
    template = (ROOT / "scripts" / "templates" / "team_personality.html").read_text()
    html = template.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":")))
    OUT.write_text(html)
    print(f"  wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
