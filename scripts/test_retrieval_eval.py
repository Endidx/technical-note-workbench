import unittest

from scripts import retrieval_eval as evaluation


class RetrievalMetrics(unittest.TestCase):
    def test_multiple_passages_do_not_take_extra_document_slots(self):
        hits = [{"filename": f} for f in ["wrong.md", "wrong.md", "a.md", "b.md", "c.md", "d.md", "e.md"]]
        record = evaluation.assess(hits, ["a.md", "e.md"])
        self.assertEqual(record["recallAt5"], 0.5)
        self.assertEqual(record["reciprocalRank"], 0.5)
        self.assertEqual(record["documents"][5], "e.md")

    def test_empty_gold_counts_candidates_separately(self):
        empty = evaluation.assess([], [])
        near_miss = evaluation.assess([{"filename": "wrong.md"}], [])
        missing = evaluation.assess([], ["target.md"])
        self.assertIsNone(near_miss["recallAt5"])
        self.assertEqual(missing["recallAt5"], 0)
        self.assertEqual(missing["reciprocalRank"], 0)
        summary = evaluation.summarize([empty, near_miss, missing], [1, 5, 2])
        self.assertEqual(summary["emptyGoldWithCandidates"], 1)
        self.assertEqual(summary["emptyGoldCandidateDocumentsAt5"], 1)
        self.assertEqual(summary["positiveQueries"], 1)
        self.assertEqual(summary["rankP95Ms"], 5)
