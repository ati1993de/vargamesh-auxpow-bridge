#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

BASE = Path("/opt/vargamesh-auxpow-bridge")

CLI = "vargamesh-cli"
CONF = "/etc/vargamesh/vargamesh.conf"
DATADIR = "/var/lib/vargamesh"

RAW = BASE / "data/vmesh/raw"
STATE = BASE / "data/vmesh/state"
LATEST = STATE / "raw-latest.json"

EXPECTED_CHAIN_ID = 22093
EXPECTED_CHILD_NONCE = 22093
EXPECTED_SUBMIT = "submitblock"


def cli(*args):
    cmd = [
        CLI,
        f"-conf={CONF}",
        f"-datadir={DATADIR}",
        *args,
    ]

    p = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=30,
    )

    if p.returncode != 0:
        raise RuntimeError(
            "VMESH RPC failed: " +
            (p.stderr.strip() or p.stdout.strip())
        )

    return p.stdout.strip()


def get_template():
    raw = cli(
        "getblocktemplate",
        '{"rules":["segwit"]}'
    )

    gbt = json.loads(raw)

    required = [
        "height",
        "version",
        "previousblockhash",
        "bits",
        "target",
        "curtime",
        "coinbasevalue",
        "transactions",
        "auxpow",
        "auxpow_chainid",
        "auxpow_childnonce",
        "auxpow_submit",
    ]

    missing = [x for x in required if x not in gbt]

    if missing:
        raise RuntimeError(
            "GBT missing fields: " + ", ".join(missing)
        )

    if gbt["auxpow"] is not True:
        raise RuntimeError("VMESH template is not AuxPoW")

    if int(gbt["auxpow_chainid"]) != EXPECTED_CHAIN_ID:
        raise RuntimeError(
            f"Unexpected chain ID: {gbt['auxpow_chainid']}"
        )

    if int(gbt["auxpow_childnonce"]) != EXPECTED_CHILD_NONCE:
        raise RuntimeError(
            f"Unexpected child nonce: {gbt['auxpow_childnonce']}"
        )

    if gbt["auxpow_submit"] != EXPECTED_SUBMIT:
        raise RuntimeError(
            f"Unexpected submit method: {gbt['auxpow_submit']}"
        )

    return gbt


def atomic_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_name(path.name + ".tmp")

    tmp.write_text(
        json.dumps(
            obj,
            sort_keys=True,
            indent=2
        ) + "\n"
    )

    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def snapshot():
    gbt = get_template()

    now = int(time.time())

    name = (
        f"{int(gbt['height'])}-"
        f"{gbt['previousblockhash']}-"
        f"{int(gbt['curtime'])}.json"
    )

    raw_path = RAW / name

    if not raw_path.exists():
        atomic_json(raw_path, gbt)

    state = {
        "format": 1,
        "service": "VargaMesh MergePool Coordinator",
        "pool_mode": "shared-pplns",
        "public_host": "mergedmining.vargacoin.com",

        "updated": now,

        "height": int(gbt["height"]),
        "version": int(gbt["version"]),
        "previousblockhash": gbt["previousblockhash"],
        "bits": gbt["bits"],
        "target": gbt["target"],
        "curtime": int(gbt["curtime"]),
        "coinbasevalue": int(gbt["coinbasevalue"]),
        "tx_count": len(gbt["transactions"]),

        "auxpow": True,
        "auxpow_chainid": int(gbt["auxpow_chainid"]),
        "auxpow_childnonce": int(gbt["auxpow_childnonce"]),
        "auxpow_submit": gbt["auxpow_submit"],

        "raw_template": str(raw_path),

        "status": "raw-template-ready",
        "child_template_finalized": False,
        "reason": "VMESH payout script not configured yet",
    }

    atomic_json(LATEST, state)

    return state


def selftest():
    gbt = get_template()

    print("VMESH AUXPOW SELFTEST PASS")
    print("height           :", gbt["height"])
    print("version          :", gbt["version"])
    print("bits             :", gbt["bits"])
    print("target           :", gbt["target"])
    print("coinbasevalue    :", gbt["coinbasevalue"])
    print("transactions     :", len(gbt["transactions"]))
    print("auxpow           :", gbt["auxpow"])
    print("auxpow_chainid   :", gbt["auxpow_chainid"])
    print("auxpow_childnonce:", gbt["auxpow_childnonce"])
    print("auxpow_submit    :", gbt["auxpow_submit"])


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--selftest",
        action="store_true"
    )

    ap.add_argument(
        "--once",
        action="store_true"
    )

    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    if args.once:
        print(
            json.dumps(
                snapshot(),
                indent=2
            )
        )
        return

    ap.error("use --selftest or --once")


if __name__ == "__main__":
    main()
