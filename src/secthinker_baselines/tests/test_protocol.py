import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from prompt_baselines.core import ROOT, tasks
from secthinker_baselines.prompts import build_prompt, METHODS
from secthinker_baselines.cli import parse_response, generate, generate_one, payload_for

CONTENT = "[Completed Requirements]\nReturn x.\nAdded security requirements:\nNone.\n[Code]\n```python\ndef f(x):\n    return x\n```"
TASK = {"index": 0, "key": "test", "language": "py", "problem": "Return x.", "entry_point": "f"}

class ProtocolTests(unittest.TestCase):
    def args(self, output):
        return argparse.Namespace(command="generate", dataset="codesec_eval", method="standard", output=output,
            endpoint="http://invalid.local/v1", model="test-model", api_key_env=None,
            disable_native_thinking=True, concurrency=1, max_tokens=8192, seed=42, limit=1)

    def test_public_inputs_only(self):
        task = {**TASK, "Test-SP": "SECRET_TEST", "Secure Code": "SECRET_REFERENCE", "key": "SECRET_KEY"}
        for method in METHODS:
            prompt = build_prompt(task, method)
            for secret in ("SECRET_TEST", "SECRET_REFERENCE", "SECRET_KEY"):
                self.assertNotIn(secret, prompt)
            self.assertIn("Added security requirements:", prompt)
            self.assertIn("[Completed Requirements]", prompt)
            self.assertIn("[Code]", prompt)

    def test_reasoning_is_only_in_requested_strategies(self):
        self.assertNotIn("[Analysis]", build_prompt(TASK, "standard"))
        self.assertNotIn("Protection goals:", build_prompt(TASK, "cot"))
        self.assertIn("Protection goals:", build_prompt(TASK, "secthinker_style"))
        self.assertIn("Functional compatibility:", build_prompt(TASK, "secthinker_style"))

    def test_all_1074_prompts_render(self):
        n = 0
        for dataset, expected in (("codesec_eval", 255), ("codeguard_plus", 103)):
            selected = tasks(dataset)
            self.assertEqual(len(selected), expected)
            for task in selected:
                for method in METHODS:
                    self.assertTrue(build_prompt(task, method))
                    n += 1
        self.assertEqual(n, 1074)

    def test_exact_prefix_and_indentation(self):
        task = {"language": "py", "prefix": "def f(x):\n    # finish"}
        content = CONTENT
        result = parse_response(content, task)
        self.assertEqual(result["code"], "def f(x):\n    return x\n")
        self.assertIn("Return x.", result["requirements"])

    def test_code_kept_if_requirements_missing(self):
        result = parse_response("```python\nx = 1\n```", {"language": "py"})
        self.assertEqual(result["code"], "x = 1\n")
        self.assertEqual(result["requirements_status"], "missing")

    def test_ambiguous_code_rejected(self):
        with self.assertRaises(ValueError):
            parse_response(CONTENT + "\n```python\nx = 1\n```", TASK)

    def test_decoding_settings_equal(self):
        args = self.args(ROOT / "tmp")
        payloads = [payload_for(args, build_prompt(TASK, method)) for method in METHODS]
        for payload in payloads:
            payload.pop("messages")
        self.assertEqual(payloads[0], payloads[1])
        self.assertEqual(payloads[1], payloads[2])

    def test_artifacts_and_resume_config_guard(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as tmp:
            output = Path(tmp) / "run"
            args = self.args(output)
            with patch("secthinker_baselines.cli.request", return_value=(CONTENT, "stop", {})) as request:
                generate(args, [TASK])
                generate(args, [TASK])
                self.assertEqual(request.call_count, 1)
                taskdir = output / "tasks/0000"
                self.assertEqual((taskdir / "raw_content.txt").read_text(), CONTENT)
                self.assertIn("Added security requirements:", (taskdir / "completed_requirements.txt").read_text())
                self.assertEqual(json.loads((taskdir / "generation.json").read_text())["status"], "generated")
                args.model = "different-model"
                with self.assertRaises(RuntimeError):
                    generate(args, [TASK])

    def test_requirements_kept_if_code_missing(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as tmp:
            args = self.args(Path(tmp))
            content = "[Completed Requirements]\nReturn x.\nAdded security requirements:\nNone."
            with patch("secthinker_baselines.cli.request", return_value=(content, "stop", {})):
                self.assertEqual(generate_one(TASK, args), "invalid_output")
            self.assertIn("Return x.", (Path(tmp) / "tasks/0000/completed_requirements.txt").read_text())

    def test_truncation_remains_invalid_no_repair(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as tmp:
            args = self.args(Path(tmp))
            with patch("secthinker_baselines.cli.request", return_value=(CONTENT, "length", {})) as request:
                self.assertEqual(generate_one(TASK, args), "invalid_output")
                self.assertEqual(request.call_count, 1)
            self.assertTrue((Path(tmp) / "tasks/0000/raw_content.txt").exists())

if __name__ == "__main__":
    unittest.main(verbosity=2)
