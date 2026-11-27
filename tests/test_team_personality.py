"""Tests for scripts/08_build_team_personality.py.

Run: .venv/bin/python -m unittest discover -s tests -p 'test_team_personality.py'
"""

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tp", ROOT / "scripts" / "08_build_team_personality.py")
tp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tp)

KEYS = [p["key"] for p in tp.PERSONALITIES]
FF = tp.ROUND_ORDER.index("Final Four")
FINAL = tp.ROUND_ORDER.index("Final")
CHAMP = tp.ROUND_ORDER.index("Champion")


class PersonalityIndex(unittest.TestCase):
    def test_quadrants(self):
        self.assertEqual(KEYS[tp.personality_index(2, 3)], "run")
        self.assertEqual(KEYS[tp.personality_index(2, -3)], "track")
        self.assertEqual(KEYS[tp.personality_index(-2, 3)], "snipers")
        self.assertEqual(KEYS[tp.personality_index(-2, -3)], "bruisers")

    def test_exact_average_counts_as_fast_and_outside(self):
        self.assertEqual(KEYS[tp.personality_index(0, 0)], "run")


class SeasonRelative(unittest.TestCase):
    def setUp(self):
        # two seasons with different league averages; same relative styles
        self.df = pd.DataFrame({
            "season":      [2017, 2017, 2026, 2026],
            "pace":        [68.0, 72.0, 70.0, 74.0],
            "three_share": [0.28, 0.32, 0.32, 0.36],
        })

    def test_differences_are_relative_to_own_season(self):
        out = tp.add_season_relative(self.df)
        self.assertEqual(out.pace_diff.tolist(), [-2.0, 2.0, -2.0, 2.0])
        for got, want in zip(out.three_diff, [-2.0, 2.0, -2.0, 2.0]):
            self.assertAlmostEqual(got, want)

    def test_league_drift_does_not_change_personality(self):
        out = tp.add_season_relative(self.df)
        self.assertEqual([KEYS[q] for q in out.quad], ["bruisers", "run", "bruisers", "run"])

    def test_input_not_modified(self):
        tp.add_season_relative(self.df)
        self.assertNotIn("quad", self.df.columns)


class Standings(unittest.TestCase):
    def test_counts_and_shares(self):
        df = pd.DataFrame({
            "quad":        [0, 0, 1, 1, 2, 3],
            "finish_rank": [FINAL, -1, CHAMP, FF, -1, FF],
        })
        st = {s["key"]: s for s in tp.standings(df)}
        self.assertEqual(st["run"]["team_seasons"], 2)
        self.assertEqual(st["run"]["final_four"], 1)
        self.assertEqual(st["run"]["finals"], 1)
        self.assertEqual(st["run"]["titles"], 0)
        self.assertEqual(st["track"]["titles"], 1)
        self.assertEqual(st["track"]["finals"], 1)
        self.assertEqual(st["track"]["final_four"], 2)
        self.assertEqual(st["snipers"]["final_four"], 0)
        self.assertAlmostEqual(sum(s["share_all"] for s in st.values()), 1.0)
        self.assertAlmostEqual(sum(s["share_ff"] for s in st.values()), 1.0)
        self.assertAlmostEqual(st["track"]["share_ff"], 2 / 4)

    def test_empty(self):
        df = pd.DataFrame({"quad": [], "finish_rank": []})
        self.assertTrue(all(s["share_all"] == 0 for s in tp.standings(df)))


class AxisLimit(unittest.TestCase):
    def test_rounds_up_to_step_and_is_symmetric(self):
        s = pd.Series([-7.3] + [0.0] * 999 + [3.0])
        self.assertEqual(tp.axis_limit(s, q=1.0, step=2.0), 8.0)


class FullBuild(unittest.TestCase):
    """Checks against the real cleaned data (skipped if it is missing)."""

    @classmethod
    def setUpClass(cls):
        if not (tp.CLEAN / "team_box.parquet").exists():
            raise unittest.SkipTest("cleaned data not built")
        cls.payload, cls.df = tp.build()

    def test_every_final_four_team_is_in_sample(self):
        log = self.payload["log"]
        self.assertEqual(log["final_four_expected"], log["final_four_in_sample"])

    def test_one_champion_per_tournament_and_none_in_2020(self):
        champs = self.df[self.df.finish_rank == CHAMP]
        self.assertEqual(champs.season.value_counts().max(), 1)
        self.assertNotIn(2020, champs.season.tolist())
        self.assertEqual(len(champs), len(self.payload["seasons"]) - 1)

    def test_axes_are_style_not_quality(self):
        log = self.payload["log"]
        self.assertLess(abs(log["corr_pace_net"]), 0.15)
        self.assertLess(abs(log["corr_three_net"]), 0.15)

    def test_plausible_ranges(self):
        self.assertTrue(self.df.pace.between(55, 95).all())
        self.assertTrue(self.df.three_share.between(0.0, 0.7).all())
        self.assertTrue((self.df.games >= tp.MIN_GAMES).all())
        self.assertFalse(self.df.duplicated(["season", "team_id"]).any())


if __name__ == "__main__":
    unittest.main()
