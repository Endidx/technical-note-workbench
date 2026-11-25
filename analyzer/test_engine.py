import unittest

from analyzer.engine import analyze_all


class ExampleReviewTests(unittest.TestCase):
    def test_four_outcomes_and_evidence(self):
        notes = analyze_all()
        self.assertEqual([n["kind"] for n in notes], ["change", "explicit", "history", "confirm"])
        for note in notes:
            self.assertIn(note["evidence"], note["original"])
            if note["kind"] in ("change", "confirm"):
                self.assertEqual(note["proposed"].replace(", n_init=10)", ")"), note["original"])
            else:
                self.assertIsNone(note["proposed"])

    def test_published_snapshot_matches_current_sources(self):
        import json
        from analyzer.engine import ROOT

        saved = json.loads((ROOT / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, analyze_all())
