#!/usr/bin/env python3
"""Dependency-free tests for the compatibility layer. No mainnet RPC required."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "compat" / "auxrpc.py"
spec = importlib.util.spec_from_file_location("vmesh_auxrpc", SOURCE)
rpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rpc)


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.template = {
            "child_hash": "aa" * 32,
            "child_header": "01" * 80,
            "previousblockhash": "bb" * 32,
            "tx_vector": "0100",
            "height": 100, "bits": "1d00ffff", "target": "cc" * 32,
            "coinbasevalue": 2500000000
        }
        self.old_submitter = rpc.SUBMITTER
        rpc.SUBMITTER = {
            "load_template": lambda _: (None, self.template),
            "rpc": lambda method, *args: "bb" * 32 if method == "getbestblockhash" else "null"
        }

    def tearDown(self):
        rpc.SUBMITTER = self.old_submitter

    def test_getauxblock_returns_required_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "latest.json"
            p.write_text(json.dumps({"status": "ready", "child_hash": "aa" * 32}))
            with patch.object(rpc, "STATE", p):
                job = rpc.dispatch("getauxblock", [])
        self.assertEqual(job["chainid"], 22093)
        self.assertEqual(job["hash"], "aa" * 32)
        self.assertEqual(job["target"], "cc" * 32)

    def test_submit_builds_block_and_calls_core(self):
        seen = []
        rpc.SUBMITTER["rpc"] = lambda method, *args: (
            seen.append((method, args)) or ("bb" * 32 if method == "getbestblockhash" else "null")
        )
        self.assertTrue(rpc.dispatch("submitauxblock", ["aa" * 32, "ff" * 120]))
        self.assertEqual(seen[-1][0], "submitblock")
        self.assertEqual(seen[-1][1][0], "01" * 80 + "ff" * 120 + "0100")

    def test_refuses_stale_templates(self):
        rpc.SUBMITTER["rpc"] = lambda *_: "dd" * 32
        self.assertFalse(rpc.submitauxblock("aa" * 32, "ff" * 120))

    def test_refuses_bad_proofs(self):
        for proof in ["xy", "00" * 50, "a" * (rpc.MAX_AUXPOW_BYTES * 2 + 2)]:
            with self.assertRaises(rpc.CompatibilityError):
                rpc.submitauxblock("aa" * 32, proof)

    def test_rejects_unsupported_methods(self):
        with self.assertRaises(rpc.CompatibilityError):
            rpc.dispatch("getblocktemplate", [])


if __name__ == "__main__":
    unittest.main()
