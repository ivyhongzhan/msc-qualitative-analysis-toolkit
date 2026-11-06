"""Executable QA checks for the qualitative coding analysis workflow."""
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qualitative_audit", ROOT / "qualitative_audit.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class QualitativeAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.codebook = ROOT / "examples" / "illustrative_codebook.csv"
        self.coding = ROOT / "examples" / "synthetic_coded_segments.csv"

    def csv_file(self, fields, rows):
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
        with f:
            writer = csv.writer(f)
            writer.writerow(fields)
            writer.writerows(rows)
        self.addCleanup(Path(f.name).unlink)
        return Path(f.name)

    def test_distinct_denominators(self):
        result = mod.analyze(self.codebook, self.coding)
        self.assertEqual(result["denominators"], {
            "distinct_interviews": 4, "distinct_segments": 8,
            "code_assignments": 10, "codebook_codes": 4
        })
        # Two example segments have two codes and appear in two theme counts.
        self.assertEqual(sum(item["distinct_segments"] for item in result["themes"]), 10)
        self.assertEqual(sum(item["distinct_segments"] for item in result["platform_tags"]), 8)

    def test_sha256_provenance_is_deterministic(self):
        self.assertEqual(mod.analyze(self.codebook, self.coding), mod.analyze(self.codebook, self.coding))
        self.assertEqual(len(mod.analyze(self.codebook, self.coding)["inputs"]["codebook_sha256"]), 64)

    def test_outputs_are_reproducible_and_fully_generated(self):
        report = mod.analyze(self.codebook, self.coding)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            mod.write_outputs(report, target)
            files = {p.name: p.read_bytes() for p in target.iterdir()}
            self.assertEqual(set(files), {
                "summary.json", "summary.md", "theme_coverage.svg", "themes.csv",
                "codes.csv", "platform_theme.csv", "cooccurrence.csv"
            })
            self.assertEqual(json.loads(files["summary.json"])["dataset_label"], "Synthetic example")
            mod.write_outputs(report, target)
            self.assertEqual(files, {p.name: p.read_bytes() for p in target.iterdir()})

    def test_cooccurrence_is_segment_level(self):
        result = mod.analyze(self.codebook, self.coding)
        pairs = {(item['theme_a'], item['theme_b']):item['distinct_segments'] for item in result['theme_cooccurrence']}
        self.assertEqual(pairs[("Information credibility", "Language and participation")], 1)
        self.assertEqual(pairs[("Cross-platform communication", "Information credibility")], 1)

    def test_no_transcript_or_unexpected_column(self):
        p = self.csv_file([*mod.ANNOTATION_COLUMNS, "quotation"],
                          [["SYN01", "SEG01", "Twitter", "C01", "PRIVATE TEXT"]])
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(self.codebook, p)

    def test_duplicate_assignment_rejected(self):
        p = self.csv_file(mod.ANNOTATION_COLUMNS, [
            ["SYN01", "SEG01", "Twitter", "C01"],
            ["SYN01", "SEG01", "Twitter", "C01"]])
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(self.codebook, p)

    def test_conflicting_platform_tags_rejected(self):
        p = self.csv_file(mod.ANNOTATION_COLUMNS, [
            ["SYN01", "SEG01", "Twitter", "C01"],
            ["SYN01", "SEG01", "WeChat", "C02"]])
        with self.assertRaisesRegex(mod.DataValidationError, "conflicting platform"):
            mod.analyze(self.codebook, p)

    def test_unknown_code_rejected(self):
        p = self.csv_file(mod.ANNOTATION_COLUMNS, [["SYN01", "SEG01", "Twitter", "UNKNOWN"]])
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(self.codebook, p)

    def test_invalid_platform_rejected(self):
        p = self.csv_file(mod.ANNOTATION_COLUMNS, [["SYN01", "SEG01", "Other", "C01"]])
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(self.codebook, p)

    def test_email_as_id_rejected(self):
        p = self.csv_file(mod.ANNOTATION_COLUMNS, [["x@example.test", "SEG01", "Twitter", "C01"]])
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(self.codebook, p)

    def test_missing_value_rejected(self):
        p = self.csv_file(mod.ANNOTATION_COLUMNS, [["SYN01", "SEG01", "", "C01"]])
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(self.codebook, p)

    def test_duplicate_codebook_key_rejected(self):
        p = self.csv_file(mod.CODEBOOK_COLUMNS, [["C01", "A", "def"], ["C01", "B", "def"]])
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(p, self.coding)

    def test_svg_escapes_theme_names(self):
        p = self.csv_file(mod.CODEBOOK_COLUMNS, [["C01", "Trust & <Other>", "def"]])
        q = self.csv_file(mod.ANNOTATION_COLUMNS, [["SYN01", "SEG01", "Twitter", "C01"]])
        chart = mod.svg_chart(mod.analyze(p, q))
        self.assertIn("Trust &amp; &lt;Other&gt;", chart)
        self.assertNotIn("<Other>", chart)

    def test_empty_and_extra_csv_columns_rejected(self):
        p = self.csv_file(["interview_id", "segment_id", "code_id"], [["SYN01", "SEG01", "C01"]])
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(self.codebook, p)

    def test_dataset_label_validated(self):
        with self.assertRaises(mod.DataValidationError):
            mod.analyze(self.codebook, self.coding, label="Unsafe\nLabel")


if __name__ == "__main__":
    unittest.main()
