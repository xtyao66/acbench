"""Tests for the hardened code oracle: ID validation, forbidden paths, parsers."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from acbench.executors.local_code import (
    LocalCodeExecutor,
    canonical_test_id,
    forbidden_path_violations,
    patch_modified_paths,
)
from acbench.models.runtime import RunConfig
from acbench.models.scenario import ScenarioSpec

REPO_ROOT = Path(__file__).resolve().parents[1]


class CanonicalIdTests(unittest.TestCase):
    def test_scenario_and_parser_forms_canonicalize_equal(self) -> None:
        scenario_form = "test_pricing.PricingTests::test_bundle"
        parser_key = "test_pricing.PricingTests.test_bundle::test_bundle"
        plain = "test_pricing.PricingTests.test_bundle"
        canon = "test_pricing.PricingTests.test_bundle"
        self.assertEqual(canonical_test_id(scenario_form), canon)
        self.assertEqual(canonical_test_id(parser_key), canon)
        self.assertEqual(canonical_test_id(plain), canon)


class CompareStatusesTests(unittest.TestCase):
    def test_id_validation_uses_named_ids_only(self) -> None:
        # An unrelated test flips fail->pass; it must NOT earn FAIL_TO_PASS credit.
        pre = {
            "m.C.test_target::test_target": "fail",
            "m.C.test_unrelated::test_unrelated": "fail",
            "m.C.test_keep::test_keep": "pass",
        }
        post = {
            "m.C.test_target::test_target": "pass",
            "m.C.test_unrelated::test_unrelated": "pass",
            "m.C.test_keep::test_keep": "pass",
        }
        p2p_s, f2p_s, p2p_f, f2p_f, id_validated = LocalCodeExecutor._compare_statuses(
            pre, post,
            fail_to_pass_ids=["m.C::test_target"],
            pass_to_pass_ids=["m.C::test_keep"],
        )
        self.assertTrue(id_validated)
        self.assertEqual(f2p_s, ["m.C::test_target"])
        self.assertEqual(p2p_s, ["m.C::test_keep"])
        self.assertEqual(f2p_f, [])
        self.assertEqual(p2p_f, [])

    def test_id_validation_flags_named_regression(self) -> None:
        pre = {"m.C.test_keep::test_keep": "pass"}
        post = {"m.C.test_keep::test_keep": "fail"}
        _, _, p2p_f, _, id_validated = LocalCodeExecutor._compare_statuses(
            pre, post, fail_to_pass_ids=[], pass_to_pass_ids=["m.C::test_keep"],
        )
        self.assertTrue(id_validated)
        self.assertEqual(p2p_f, ["m.C::test_keep"])

    def test_falls_back_to_transitions_without_named_ids(self) -> None:
        pre = {"m.C.test_x::test_x": "fail"}
        post = {"m.C.test_x::test_x": "pass"}
        _, f2p_s, _, _, id_validated = LocalCodeExecutor._compare_statuses(pre, post)
        self.assertFalse(id_validated)
        self.assertEqual(len(f2p_s), 1)


class ParserTests(unittest.TestCase):
    def test_pytest_output_is_parsed(self) -> None:
        output = "\n".join([
            "tests/test_mod.py::TestX::test_a PASSED",
            "tests/test_mod.py::TestX::test_b FAILED",
            "PASSED tests/test_mod.py::TestX::test_c",
        ])
        statuses = LocalCodeExecutor._parse_pytest_output(output)
        self.assertEqual(statuses["tests/test_mod.py::TestX::test_a"], "pass")
        self.assertEqual(statuses["tests/test_mod.py::TestX::test_b"], "fail")
        self.assertEqual(statuses["tests/test_mod.py::TestX::test_c"], "pass")


class ForbiddenPathTests(unittest.TestCase):
    def test_patch_modified_paths_and_violations(self) -> None:
        diff = (
            "diff --git a/tests/test_pricing.py b/tests/test_pricing.py\n"
            "--- a/tests/test_pricing.py\n"
            "+++ b/tests/test_pricing.py\n"
            "@@ -1 +1 @@\n-x\n+y\n"
        )
        modified = patch_modified_paths(diff)
        self.assertIn("tests/test_pricing.py", modified)
        self.assertEqual(
            forbidden_path_violations(modified, ["tests/"]),
            ["tests/test_pricing.py"],
        )

    def test_forbidden_path_bypass_variants_are_caught(self) -> None:
        # All of these previously evaded the 'tests/' rule; they must now be caught.
        for evasion in [
            "./tests/test_x.py",
            "tests/../tests/test_x.py",
            "/tests/test_x.py",
            "tests\\test_x.py",
        ]:
            self.assertTrue(
                forbidden_path_violations([evasion], ["tests/"]),
                f"{evasion!r} should violate forbidden_paths ['tests/']",
            )
        # A legitimate source edit is not a violation.
        self.assertFalse(forbidden_path_violations(["src/app.py"], ["tests/"]))

    def test_executor_rejects_patch_that_edits_forbidden_tests(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="acbench-forbidden-"))
        self.addCleanup(shutil.rmtree, temp_dir, True)
        scenario = ScenarioSpec.from_file(
            REPO_ROOT / "tasks" / "scenarios" / "local" / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )
        bad_patch = temp_dir / "edit_tests.diff"
        bad_patch.write_text(
            "diff --git a/tests/test_pricing.py b/tests/test_pricing.py\n"
            "--- a/tests/test_pricing.py\n"
            "+++ b/tests/test_pricing.py\n"
            "@@ -1 +1 @@\n-assert False\n+assert True\n",
            encoding="utf-8",
        )
        result = LocalCodeExecutor().execute(
            scenario, temp_dir / "run",
            RunConfig(dry_run=False, code_patch_path=str(bad_patch)),
        )
        self.assertTrue(result.details["forbidden_paths_violation"])
        self.assertFalse(result.details["apply_success"])
        self.assertFalse(result.success)
        self.assertEqual(result.fail_to_pass_success, [])


class EndToEndGoldTests(unittest.TestCase):
    def test_gold_patch_is_id_validated_and_passes(self) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix="acbench-gold-"))
        self.addCleanup(shutil.rmtree, temp_dir, True)
        scenario = ScenarioSpec.from_file(
            REPO_ROOT / "tasks" / "scenarios" / "local" / "code"
            / "billing_pricing__bundle_discount_threshold.scenario.json"
        )
        result = LocalCodeExecutor().execute(
            scenario, temp_dir / "run",
            RunConfig(
                dry_run=False,
                code_patch_path=str(REPO_ROOT / "patches" / "billing_pricing_bundle_fix.diff"),
            ),
        )
        self.assertTrue(result.details["id_validated"])
        self.assertTrue(result.success)
        self.assertEqual(len(result.fail_to_pass_success), 1)
        self.assertEqual(len(result.pass_to_pass_success), 2)
        self.assertEqual(result.fail_to_pass_failure, [])


if __name__ == "__main__":
    unittest.main()
