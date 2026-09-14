import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from evaluate_gold import CORPUS, _manifest, _pending_paths, evaluate_offline  # noqa: E402
from agent.business.rfq_extractor import deterministic_extract_rfq_fields  # noqa: E402
from channels.email.mock_source import MockEmailSource  # noqa: E402


class GoldCorpusTests(unittest.TestCase):
    def test_40_case_offline_acceptance(self):
        report = evaluate_offline()
        self.assertEqual(40, report["case_count"])
        self.assertEqual(1.0, report["mime_success_rate"])
        self.assertEqual(1.0, report["evidence_backreference_rate"])
        self.assertEqual(0, report["duplicate_pass_created"])
        self.assertTrue(report["passed"], report["failures"])

    def test_40_case_deterministic_fallback_is_conservative_and_consistent(self):
        cases = _manifest()["cases"]
        envelopes = MockEmailSource(CORPUS, account_id="fallback-gold").fetch_after(0, limit=100)
        for case, envelope in zip(cases, envelopes):
            with self.subTest(case=case["case_id"]):
                result = deterministic_extract_rfq_fields(
                    envelope.text_body,
                    {"subject": envelope.subject, "from_address": envelope.from_address},
                )
                self.assertEqual(case["item_count"], len(result["items"]))
                pending = _pending_paths(result)
                self.assertTrue(set(case["pending_fields"]).issubset(pending))
                self.assertEqual(set(result["missing_fields"]), pending)
                source = f"{envelope.subject}\n{envelope.text_body}"

                def assert_evidence(value):
                    if isinstance(value, dict):
                        if value.get("status") == "extracted":
                            self.assertIn(value.get("evidence"), source)
                        for child in value.values():
                            assert_evidence(child)
                    elif isinstance(value, list):
                        for child in value:
                            assert_evidence(child)

                assert_evidence(result)


if __name__ == "__main__":
    unittest.main()
