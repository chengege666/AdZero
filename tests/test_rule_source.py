"""Live-check error handling stays offline here; the live check runs separately."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_rule_source


class DownloadCheckTest(unittest.TestCase):
    def test_http_failure_is_not_accepted_as_a_rule_list(self):
        with patch.object(check_rule_source.subprocess, "run", side_effect=subprocess.CalledProcessError(22, "curl")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                check_rule_source.fetch("https://example.test/list", Path("not-created"))
        command = run.call_args.args[0]
        self.assertIn("--fail", command)
        self.assertIn("--max-time", command)
        self.assertNotIn("--insecure", command)


@unittest.skipUnless(os.environ.get("ADZERO_UCODE"), "requires real ucode")
class RuleParserCheckTest(unittest.TestCase):
    def test_domains_are_parsed_by_production_code(self):
        self.assertEqual(check_rule_source.parse_domains("# Title: test\nads.example\ntrack.example\n"),
                         ["ads.example", "track.example"])

    def test_html_error_page_and_empty_body_are_rejected(self):
        for raw in ("<html>Service Unavailable</html>\n", "", "# no domains\n"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                check_rule_source.parse_domains(raw)
