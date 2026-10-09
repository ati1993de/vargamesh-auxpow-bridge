import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# Extensionless submitter needs a source loader.
from importlib.machinery import SourceFileLoader
builder = load_module("vmesh_builder", ROOT / "coordinator" / "vmesh_template_builder.py")
spec = importlib.util.spec_from_loader("vmesh_submit", SourceFileLoader("vmesh_submit", str(ROOT / "submitter" / "vmesh-submit")))
submitter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(submitter)

ADDR = "vm1qsfsgj70pdv86nguvexzvsflmcknz4lrsj87wx9"

class FeeTests(unittest.TestCase):
    def test_address_and_basis_points(self):
        self.assertEqual(builder.segwit_script(ADDR).hex(), submitter.VMESH_DEV_FEE_SCRIPT.hex())
        self.assertEqual(builder.VMESH_DEV_FEE_BPS, 100)
        self.assertEqual(builder.split_mining_reward(2_500_000_000), (2_475_000_000, 25_000_000))
        for n in (0, 1, 99):
            with self.assertRaises(RuntimeError):
                builder.split_mining_reward(n)

    def test_real_serialization_and_tamper(self):
        old = (builder.CFG, builder.RAW, builder.STATE, builder.TEMPLATES, builder.get_gbt)
        try:
            with tempfile.TemporaryDirectory() as d:
                base = Path(d)
                builder.CFG = base / "pool.env"
                builder.CFG.write_text("VMESH_PAYOUT_ADDRESS=" + ADDR + "\n")
                builder.RAW = base / "raw"
                builder.STATE = base / "state"
                builder.TEMPLATES = base / "templates"
                builder.get_gbt = lambda: {
                    "height": 16888, "version": 0x20000100,
                    "previousblockhash": "11" * 32,
                    "bits": "207fffff", "target": "7f" + "ff" * 31,
                    "curtime": 1730000000, "coinbasevalue": 2_500_000_000,
                    "transactions": [], "coinbaseaux": {},
                    "default_witness_commitment": "6a24aa21a9ed" + "22" * 32
                }
                state = builder.build()
                t = __import__("json").loads(Path(state["template"]).read_text())
                submitter.validate_child_fee(t)
                tx = submitter.parse_tx(bytes.fromhex(t["coinbase"]))
                self.assertEqual(len(tx["outputs"]), 3)
                self.assertEqual(tx["outputs"][0][0], 2_475_000_000)
                self.assertEqual(tx["outputs"][1], (25_000_000, submitter.VMESH_DEV_FEE_SCRIPT))
                self.assertEqual(tx["outputs"][2][0], 0)
                oldfee = t["developer_fee_value"]
                t["developer_fee_value"] = oldfee - 1
                with self.assertRaises(RuntimeError):
                    submitter.validate_child_fee(t)
                t["developer_fee_value"] = oldfee
                t["tx_vector"] = "00"
                with self.assertRaises(RuntimeError):
                    submitter.validate_child_fee(t)
                t["tx_vector"] = __import__("json").loads(Path(state["template"]).read_text())["tx_vector"]
                cb = bytearray.fromhex(t["coinbase"])
                spk = submitter.VMESH_DEV_FEE_SCRIPT
                pos = bytes(cb).index(spk)
                cb[pos] ^= 1
                t["coinbase"] = cb.hex()
                with self.assertRaises(RuntimeError):
                    submitter.validate_child_fee(t)
        finally:
            builder.CFG, builder.RAW, builder.STATE, builder.TEMPLATES, builder.get_gbt = old

if __name__ == "__main__":
    unittest.main()
