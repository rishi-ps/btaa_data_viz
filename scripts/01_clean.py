"""Clean the raw ESPN women's basketball files into analysis-ready tables.

Reads the raw parquet files (never modified) and writes cleaned tables to
data/clean/. Run from the project root:

    .venv/bin/python scripts/01_clean.py

Every cleaning rule is listed in the RULES dict and printed at the end with the
number of rows it touched, so the methods section of the final story can cite them.
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "NCAA Women's Basketball Data Files 2026"
OUT = ROOT / "data" / "clean"
OUT.mkdir(parents=True, exist_ok=True)

con = duckdb.connect()
con.execute("set threads = 8")
con.execute("set preserve_insertion_order = false")


def sql_path(path: Path) -> str:
    """Quote a file path for SQL (the data folder name contains an apostrophe)."""
    return "'" + str(path).replace("'", "''") + "'"


def raw(name: str) -> str:
    return f"read_parquet({sql_path(RAW / (name + '.parquet'))})"


def one(sql: str):
    return con.execute(sql).fetchall()[0][0]


log: list[tuple[str, str, int]] = []  # (table, rule, rows affected)

# ---------------------------------------------------------------------------
# Conferences: id -> short name (current names; one historical id is unmapped)
# ---------------------------------------------------------------------------
con.execute(f"""
create table conferences as
select distinct conference_id, conference_short_name as conference
from {raw('teams')}
""")

# ---------------------------------------------------------------------------
# games
# ---------------------------------------------------------------------------
con.execute(f"create table games_raw as select * from {raw('games')}")
n_raw = one("select count(*) from games_raw")

log.append(("games", "Dropped: not final (postponed, canceled, suspended, forfeit)",
            one("select count(*) from games_raw where status_type_name <> 'STATUS_FINAL'")))
log.append(("games", "Dropped: final with a 0-0 score (no game data)",
            one("select count(*) from games_raw where status_type_name = 'STATUS_FINAL' and home_score = 0 and away_score = 0")))
log.append(("games", "Dropped: exhibitions",
            one("select count(*) from games_raw where status_type_name = 'STATUS_FINAL' and not (home_score = 0 and away_score = 0) and type_abbreviation = 'EXH'")))
log.append(("games", "Attendance 0 set to missing",
            one("select count(*) from games_raw where attendance = 0")))
log.append(("games", "Attendance over 1.5x venue capacity set to missing (typos)",
            one("select count(*) from games_raw where venue_capacity > 0 and attendance > 1.5 * venue_capacity")))

con.execute("""
create table games as
with d1 as (select team_id from read_parquet($teams))
select
    g.game_id,
    g.season,
    case g.season_type when 3 then 'post' else 'regular' end              as season_type,
    g.game_date,
    g.game_date_time,
    g.neutral_site,
    g.conference_competition                                             as conference_game,
    g.home_id, g.home_location, g.home_display_name, g.home_abbreviation,
    g.home_conference_id, hc.conference                                  as home_conference,
    g.home_score, g.home_color, g.home_logo,
    g.away_id, g.away_location, g.away_display_name, g.away_abbreviation,
    g.away_conference_id, ac.conference                                  as away_conference,
    g.away_score, g.away_color, g.away_logo,
    case when g.home_score > g.away_score then g.home_id else g.away_id end as winner_id,
    abs(g.home_score - g.away_score)                                     as margin,
    case
        when g.attendance = 0 then null
        when g.venue_capacity > 0 and g.attendance > 1.5 * g.venue_capacity then null
        else g.attendance
    end                                                                  as attendance,
    nullif(g.venue_capacity, 0)                                          as venue_capacity,
    g.venue_id, g.venue_full_name, g.venue_address_city, g.venue_address_state,
    g.broadcast_name,
    g.notes_headline,
    g.home_current_rank, g.away_current_rank,
    (g.home_id in (select team_id from d1) and g.away_id in (select team_id from d1)) as both_d1,
    -- NCAA tournament (not the NIT / WBIT / conference tournaments)
    (g.season_type = 3
     and g.notes_headline ilike '%NCAA%Championship%'
     and g.notes_headline not ilike '%NIT%')                             as ncaa_tournament,
    case
        when not (g.season_type = 3 and g.notes_headline ilike '%NCAA%Championship%') then null
        when g.notes_headline ilike '%First Four%'                   then 'First Four'
        when g.notes_headline ilike '%1st Round%' or g.notes_headline ilike '%First Round%'   then 'Round of 64'
        when g.notes_headline ilike '%2nd Round%' or g.notes_headline ilike '%Second Round%'  then 'Round of 32'
        when g.notes_headline ilike '%Sweet 16%'  or g.notes_headline ilike '%Regional Semifinal%' then 'Sweet 16'
        when g.notes_headline ilike '%Elite 8%'   or g.notes_headline ilike '%Elite Eight%' or g.notes_headline ilike '%Regional Final%' or g.notes_headline ilike '%Region%Final' then 'Elite 8'
        when g.notes_headline ilike '%Final Four%' or g.notes_headline ilike '%Semifinal%'      then 'Final Four'
        when g.notes_headline ilike '%- National Championship%'      then 'Final'
    end                                                                  as ncaa_round,
    g.play_by_play_available                                            as pbp_available
from games_raw g
left join conferences hc on hc.conference_id = g.home_conference_id
left join conferences ac on ac.conference_id = g.away_conference_id
where g.status_type_name = 'STATUS_FINAL'
  and not (g.home_score = 0 and g.away_score = 0)
  and coalesce(g.type_abbreviation, '') <> 'EXH'
""", {"teams": str(RAW / "teams.parquet")})

# ---------------------------------------------------------------------------
# team_box
# ---------------------------------------------------------------------------
con.execute(f"create table tb_raw as select * from {raw('team_box')}")
log.append(("team_box", "Dropped: game not in cleaned games",
            one("select count(*) from tb_raw where game_id not in (select game_id from games)")))
log.append(("team_box", "Flagged: points != 2*FGM + 3PM + FTM (kept, flag stats_consistent=false)",
            one("select count(*) from tb_raw where team_score <> 2*field_goals_made + three_point_field_goals_made + free_throws_made")))

con.execute("""
create table team_box as
select
    t.game_id, t.season, g.season_type, t.game_date,
    t.team_id, t.team_location, t.team_display_name, t.team_abbreviation, t.team_color, t.team_logo,
    case when t.team_home_away = 'home' then g.home_conference else g.away_conference end as conference,
    t.team_home_away as home_away, g.neutral_site,
    t.opponent_team_id, t.opponent_team_location,
    case when t.team_home_away = 'home' then g.away_conference else g.home_conference end as opponent_conference,
    t.team_score, t.opponent_team_score, t.team_winner as won,
    t.field_goals_made fgm, t.field_goals_attempted fga,
    t.three_point_field_goals_made fg3m, t.three_point_field_goals_attempted fg3a,
    t.free_throws_made ftm, t.free_throws_attempted fta,
    t.offensive_rebounds oreb, t.defensive_rebounds dreb, t.total_rebounds reb,
    t.assists ast, t.steals stl, t.blocks blk, t.turnovers tov, t.total_turnovers total_tov,
    t.fouls pf,
    try_cast(t.largest_lead as integer)      as largest_lead,
    try_cast(t.fast_break_points as integer) as fast_break_points,
    try_cast(t.points_in_paint as integer)   as points_in_paint,
    try_cast(t.turnover_points as integer)   as turnover_points,
    try_cast(t.lead_changes as integer)      as lead_changes,
    try_cast(t.lead_percentage as double)    as lead_percentage,
    -- possessions estimate (standard formula)
    t.field_goals_attempted - t.offensive_rebounds + t.total_turnovers + 0.475 * t.free_throws_attempted as possessions,
    (t.team_score = 2*t.field_goals_made + t.three_point_field_goals_made + t.free_throws_made) as stats_consistent,
    g.both_d1, g.ncaa_tournament
from tb_raw t
join games g using (game_id)
""")

# ---------------------------------------------------------------------------
# player_box
# ---------------------------------------------------------------------------
con.execute(f"create table pb_raw as select * from {raw('game_box')}")
log.append(("player_box", "Dropped: did not play / no minutes",
            one("select count(*) from pb_raw where did_not_play or minutes is null or minutes = 0")))
log.append(("player_box", "Dropped: missing athlete id",
            one("select count(*) from pb_raw where athlete_id is null")))
log.append(("player_box", "Dropped: exact duplicate (game, athlete) rows",
            one("select count(*) - count(distinct (game_id, athlete_id)) from pb_raw where athlete_id is not null")))
log.append(("player_box", "Minutes over 60 set to missing (impossible)",
            one("select count(*) from pb_raw where minutes > 60")))

con.execute("""
create table player_box as
select * exclude (rn) from (
    select
        p.game_id, p.season, g.season_type, p.game_date,
        p.athlete_id, p.athlete_display_name as athlete, p.athlete_position_name as position,
        p.athlete_jersey as jersey,
        p.team_id, p.team_location, p.opponent_team_id, p.opponent_team_location,
        p.home_away, p.starter, p.team_winner as won,
        case when p.minutes > 60 then null else p.minutes end as minutes,
        p.points, p.field_goals_made fgm, p.field_goals_attempted fga,
        p.three_point_field_goals_made fg3m, p.three_point_field_goals_attempted fg3a,
        p.free_throws_made ftm, p.free_throws_attempted fta,
        p.offensive_rebounds oreb, p.defensive_rebounds dreb, p.rebounds reb,
        p.assists ast, p.steals stl, p.blocks blk, p.turnovers tov, p.fouls pf,
        p.athlete_headshot_href as headshot,
        row_number() over (partition by p.game_id, p.athlete_id order by p.minutes desc nulls last) as rn
    from pb_raw p
    join games g using (game_id)
    where p.athlete_id is not null
      and not coalesce(p.did_not_play, false)
      and p.minutes > 0
) where rn = 1
""")

# ---------------------------------------------------------------------------
# play_by_play (2020 onward: full coverage starts here)
# ---------------------------------------------------------------------------
con.execute(f"""
create view pbp_raw as
select * from {raw('play_by_play')} where season >= 2020
""")
log.append(("pbp", "Dropped: seasons before 2020 (partial coverage)",
            one(f"select count(*) from {raw('play_by_play')} where season < 2020")))
log.append(("pbp", "Shot coordinates outside the court / placeholders set to missing",
            one("""select count(*) from pbp_raw where shooting_play and coalesce(points_attempted,0) > 0
                   and not (coordinate_x_raw between 0 and 50 and coordinate_y_raw between -5 and 94)""")))
log.append(("pbp", "Wall-clock values that fail to parse set to missing",
            one("select count(*) from pbp_raw where wallclock is not null and try_cast(wallclock as timestamp) is null")))

con.execute(f"""
copy (
select
    p.game_id, p.season, g.season_type, p.game_date,
    p.game_play_number                                  as play_no,
    p.period,
    -- game clock: seconds left in the period and seconds elapsed in the game
    (try_cast(p.clock_minutes as double) * 60 + try_cast(p.clock_seconds as double))              as period_secs_left,
    case when p.period <= 4 then (p.period - 1) * 600 + (600 - ((try_cast(p.clock_minutes as double) * 60 + try_cast(p.clock_seconds as double))))
         else 2400 + (p.period - 5) * 300 + (300 - ((try_cast(p.clock_minutes as double) * 60 + try_cast(p.clock_seconds as double)))) end
                                                        as game_secs_elapsed,
    try_cast(p.wallclock as timestamp)                  as wallclock,
    p.type_text                                         as play_type,
    p.text,
    p.team_id, p.home_team_id, p.away_team_id,
    p.athlete_id_1, p.athlete_id_2,
    p.home_score, p.away_score,
    p.scoring_play, p.score_value, p.shooting_play,
    case when p.shooting_play then p.points_attempted end as points_attempted,
    case when p.shooting_play and coalesce(p.points_attempted,0) > 0
              and p.coordinate_x_raw between 0 and 50 and p.coordinate_y_raw between -5 and 94
         then p.coordinate_x_raw end                    as shot_x,
    case when p.shooting_play and coalesce(p.points_attempted,0) > 0
              and p.coordinate_x_raw between 0 and 50 and p.coordinate_y_raw between -5 and 94
         then p.coordinate_y_raw end                    as shot_y
from pbp_raw p
join games g using (game_id)
) to '{OUT / 'play_by_play.parquet'}' (format parquet, compression zstd)
""")

# Per-game quality flags for the play-by-play
con.execute(f"""
create table pbp_games as
with p as (select * from read_parquet('{OUT / 'play_by_play.parquet'}')),
steps as (
    select game_id,
           epoch(wallclock - lag(wallclock) over (partition by game_id order by play_no)) as d
    from p where wallclock is not null
),
s as (
    select game_id, count(*) as n_steps, sum((d < 0)::int) as backwards_steps
    from steps where d is not null group by 1
),
last as (
    select game_id, season, count(*) as n_plays,
           arg_max(home_score, play_no) as last_home, arg_max(away_score, play_no) as last_away,
           max(period) as periods,
           count(wallclock) as n_wallclock,
           epoch(max(wallclock) - min(wallclock)) / 60 as wall_minutes,
           sum((play_type = 'Substitution')::int) as n_subs
    from p group by 1, 2
)
select l.*, s.backwards_steps,
       (l.last_home = g.home_score and l.last_away = g.away_score) as score_matches,
       (l.n_wallclock > 0.95 * l.n_plays
        and l.wall_minutes between 80 and 240
        and coalesce(s.backwards_steps, 0) <= 0.02 * l.n_plays)      as wallclock_ok
from last l
join games g using (game_id)
left join s using (game_id)
""")

# ---------------------------------------------------------------------------
# teams (current D1 list) - copied as is, trimmed
# ---------------------------------------------------------------------------
con.execute(f"""
create table teams as
select team_id, display_name, short_name, abbreviation, mascot, color, alternate_color,
       logo, logo_dark, conference_id, conference_short_name as conference
from {raw('teams')}
""")

# ---------------------------------------------------------------------------
# write everything
# ---------------------------------------------------------------------------
for t in ["games", "team_box", "player_box", "pbp_games", "teams"]:
    con.execute(f"copy {t} to '{OUT / (t + '.parquet')}' (format parquet, compression zstd)")
con.execute(f"copy (select * from {raw('rankings')}) to '{OUT / 'rankings.parquet'}' (format parquet)")

# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
print("\nCleaning log")
print("-" * 92)
for table, rule, n in log:
    print(f"{table:<11} {n:>10,}  {rule}")
print("-" * 92)
print(f"{'games':<11} {n_raw:>10,} raw -> {one('select count(*) from games'):,} clean")
for t in ["team_box", "player_box", "pbp_games"]:
    print(f"{t:<11} {one(f'select count(*) from {t}'):>10,} rows")
n_plays = one(f"select count(*) from read_parquet('{OUT / 'play_by_play.parquet'}')")
print(f"{'pbp':<11} {n_plays:>10,} plays")
print()
print("Play-by-play game quality:")
print(con.execute("""
    select season, count(*) games,
           round(avg(score_matches::int), 3) as score_matches,
           round(avg(wallclock_ok::int), 3)  as wallclock_ok
    from pbp_games group by 1 order by 1
""").df().to_string(index=False))
print()
print("NCAA tournament games by round (check: 63 or 67 per year):")
print(con.execute("""
    select season, count(*) n, count(ncaa_round) with_round,
           sum((ncaa_round = 'Final')::int) finals
    from games where ncaa_tournament group by 1 order by 1
""").df().to_string(index=False))
