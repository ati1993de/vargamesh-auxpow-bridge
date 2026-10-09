#!/usr/bin/env python3
import hashlib, json, os, struct, subprocess, sys, tempfile, time
from pathlib import Path

BASE=Path("/opt/vargamesh-auxpow-bridge")
CFG=BASE/"config/pool.env"
RAW=BASE/"data/vmesh/raw"
STATE=BASE/"data/vmesh/state"
TEMPLATES=BASE/"data/vmesh/templates"

CLI="vargamesh-cli"
CONF="/etc/vargamesh-auxpow-bridge/vmesh-cli.conf"
DATADIR="/opt/vargamesh-auxpow-bridge/run/vmesh-cli-datadir"

CHAIN_ID=22093

# Fixed mainnet developer fee. Not configurable via pool.env.
VMESH_DEV_FEE_BPS=100  # 1.00%, integer basis points
VMESH_DEV_FEE_ADDRESS="vm1qsfsgj70pdv86nguvexzvsflmcknz4lrsj87wx9"

DIFF1=0x00000000FFFF0000000000000000000000000000000000000000000000000000

CHARSET="qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def dsha(b):
    return hashlib.sha256(
        hashlib.sha256(b).digest()
    ).digest()


def varint(n):
    if n < 0xfd:
        return bytes([n])
    if n <= 0xffff:
        return b'\xfd' + struct.pack('<H', n)
    if n <= 0xffffffff:
        return b'\xfe' + struct.pack('<I', n)
    return b'\xff' + struct.pack('<Q', n)


def cli(*args):
    p = subprocess.run(
        [
            CLI,
            f"-conf={CONF}",
            f"-datadir={DATADIR}",
            *args
        ],
        text=True,
        capture_output=True,
        timeout=60
    )

    if p.returncode:
        raise RuntimeError(
            p.stderr.strip()
            or p.stdout.strip()
            or "VMESH RPC failed"
        )

    return p.stdout.strip()


def env():
    out = {}

    for line in CFG.read_text().splitlines():
        line = line.strip()

        if (
            line
            and not line.startswith('#')
            and '=' in line
        ):
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip()

    return out


def atomic_json(path, obj):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    fd, tmp = tempfile.mkstemp(
        prefix=path.name + '.',
        dir=str(path.parent)
    )

    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(
                obj,
                f,
                sort_keys=True,
                indent=2
            )
            f.write('\n')

        os.chmod(tmp, 0o640)
        os.replace(tmp, path)

    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def polymod(values):
    chk = 1

    gen = (
        0x3b6a57b2,
        0x26508e6d,
        0x1ea119fa,
        0x3d4233dd,
        0x2a1462b3
    )

    for x in values:
        top = chk >> 25
        chk = ((chk & 0x1ffffff) << 5) ^ x

        for i, g in enumerate(gen):
            if (top >> i) & 1:
                chk ^= g

    return chk


def convertbits(data, fb=5, tb=8):
    acc = 0
    bits = 0
    out = []
    maxv = (1 << tb) - 1

    for x in data:
        if x < 0 or x >= (1 << fb):
            raise ValueError(
                "invalid bech32 data"
            )

        acc = (acc << fb) | x
        bits += fb

        while bits >= tb:
            bits -= tb
            out.append(
                (acc >> bits) & maxv
            )

    if (
        bits >= fb
        or ((acc << (tb - bits)) & maxv)
    ):
        raise ValueError(
            "invalid bech32 padding"
        )

    return bytes(out)


def segwit_script(addr, hrp="vm"):
    if (
        not addr
        or (
            addr.lower() != addr
            and addr.upper() != addr
        )
    ):
        raise ValueError(
            "invalid mixed-case address"
        )

    a = addr.lower()
    pos = a.rfind('1')

    if (
        pos < 1
        or a[:pos] != hrp
        or pos + 7 > len(a)
    ):
        raise ValueError(
            f"expected {hrp}1... address"
        )

    try:
        data = [
            CHARSET.index(c)
            for c in a[pos + 1:]
        ]
    except ValueError:
        raise ValueError(
            "invalid bech32 character"
        )

    chk = polymod(
        [ord(c) >> 5 for c in hrp]
        + [0]
        + [ord(c) & 31 for c in hrp]
        + data
    )

    if chk not in (
        1,
        0x2bc830a3
    ):
        raise ValueError(
            "bad bech32 checksum"
        )

    ver = data[0]

    prog = convertbits(
        data[1:-6]
    )

    if (
        ver > 16
        or not 2 <= len(prog) <= 40
    ):
        raise ValueError(
            "bad witness program"
        )

    if (
        ver == 0
        and (
            chk != 1
            or len(prog) not in (20, 32)
        )
    ):
        raise ValueError(
            "bad v0 address"
        )

    if (
        ver > 0
        and chk != 0x2bc830a3
    ):
        raise ValueError(
            "v1+ requires bech32m"
        )

    op = (
        0
        if ver == 0
        else 0x50 + ver
    )

    return (
        bytes([
            op,
            len(prog)
        ])
        + prog
    )


def scriptnum(n):
    out = bytearray()

    while n:
        out.append(n & 255)
        n >>= 8

    if not out:
        out.append(0)

    if out[-1] & 0x80:
        out.append(0)

    return bytes(out)


def push(data):
    if len(data) >= 76:
        raise ValueError(
            "push too large"
        )

    return bytes([
        len(data)
    ]) + data


def merkle(txids):
    hashes = [
        bytes.fromhex(x)[::-1]
        for x in txids
    ]

    if not hashes:
        raise ValueError(
            "empty merkle tree"
        )

    while len(hashes) > 1:
        if len(hashes) & 1:
            hashes.append(
                hashes[-1]
            )

        hashes = [
            dsha(
                hashes[i]
                + hashes[i + 1]
            )
            for i
            in range(
                0,
                len(hashes),
                2
            )
        ]

    return hashes[0][::-1].hex()


def get_gbt():
    g = json.loads(
        cli(
            "getblocktemplate",
            '{"rules":["segwit"]}'
        )
    )

    required = (
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
        "default_witness_commitment"
    )

    missing = [
        k
        for k in required
        if k not in g
    ]

    if missing:
        raise RuntimeError(
            "GBT missing: "
            + ",".join(missing)
        )

    if (
        g["auxpow"] is not True
        or int(g["auxpow_chainid"])
        != CHAIN_ID
    ):
        raise RuntimeError(
            "wrong AuxPoW chain"
        )

    if (
        int(g["auxpow_childnonce"])
        != CHAIN_ID
        or g["auxpow_submit"]
        != "submitblock"
    ):
        raise RuntimeError(
            "wrong AuxPoW metadata"
        )

    if not (
        int(g["version"]) & 0x100
    ):
        raise RuntimeError(
            "VERSION_AUXPOW not set"
        )

    if (
        g.get("noncerange")
        and g["noncerange"].lower()
        != "0000564d0000564d"
    ):
        raise RuntimeError(
            "unexpected nonce range"
        )

    return g


def split_mining_reward(coinbasevalue):
    """Return (miner, developer) using integer base units; never float."""
    if type(coinbasevalue) is not int or coinbasevalue <= 0:
        raise RuntimeError("invalid VMESH coinbasevalue")
    fee = coinbasevalue * VMESH_DEV_FEE_BPS // 10000
    if fee <= 0 or fee >= coinbasevalue:
        raise RuntimeError("VMESH reward too small for mandatory 1% fee")
    return coinbasevalue - fee, fee


def build():
    payout = env().get(
        "VMESH_PAYOUT_ADDRESS",
        ""
    )

    if not payout:
        raise RuntimeError(
            "VMESH_PAYOUT_ADDRESS missing"
        )

    spk = segwit_script(
        payout
    )
    dev_spk = segwit_script(
        VMESH_DEV_FEE_ADDRESS
    )

    g = get_gbt()
    reward = int(g["coinbasevalue"])
    miner_reward, developer_reward = split_mining_reward(reward)

    height = int(
        g["height"]
    )

    tag = b"/VargaTech VMESH/"

    aux = b''.join(
        bytes.fromhex(v)
        for v
        in g.get(
            "coinbaseaux",
            {}
        ).values()
    )

    script_sig = (
        push(
            scriptnum(height)
        )
        + aux
        + push(tag)
    )

    if not (
        2
        <= len(script_sig)
        <= 100
    ):
        raise RuntimeError(
            "coinbase scriptSig length invalid"
        )

    vin = (
        b'\x01'
        + b'\x00' * 32
        + b'\xff' * 4
        + varint(
            len(script_sig)
        )
        + script_sig
        + b'\xff' * 4
    )

    witness_commitment = bytes.fromhex(
        g["default_witness_commitment"]
    )

    # Child-chain VMESH fee is paid directly in the child coinbase,
    # independently of the Bitcoin parent coinbase developer output.
    outputs = (
        varint(3)
        + struct.pack('<Q', miner_reward)
        + varint(len(spk))
        + spk
        + struct.pack('<Q', developer_reward)
        + varint(len(dev_spk))
        + dev_spk
        + struct.pack(
            '<Q',
            0
        )
        + varint(
            len(
                witness_commitment
            )
        )
        + witness_commitment
    )

    version = struct.pack(
        '<I',
        2
    )

    locktime = b'\x00' * 4

    coinbase_no_witness = (
        version
        + vin
        + outputs
        + locktime
    )

    coinbase = (
        version
        + b'\x00\x01'
        + vin
        + outputs
        + b'\x01\x20'
        + b'\x00' * 32
        + locktime
    )

    coinbase_txid = (
        dsha(
            coinbase_no_witness
        )[::-1].hex()
    )

    txids = (
        [coinbase_txid]
        + [
            tx["txid"]
            for tx
            in g["transactions"]
        ]
    )

    merkle_root = merkle(
        txids
    )

    header = (
        struct.pack(
            '<I',
            int(g["version"])
        )
        + bytes.fromhex(
            g["previousblockhash"]
        )[::-1]
        + bytes.fromhex(
            merkle_root
        )[::-1]
        + struct.pack(
            '<I',
            int(g["curtime"])
        )
        + struct.pack(
            '<I',
            int(
                g["bits"],
                16
            )
        )
        + struct.pack(
            '<I',
            CHAIN_ID
        )
    )

    if len(header) != 80:
        raise RuntimeError(
            "child header != 80 bytes"
        )

    child_hash = (
        dsha(header)[::-1].hex()
    )

    target = int(
        g["target"],
        16
    )

    if target <= 0:
        raise RuntimeError(
            "invalid target"
        )

    tx_vector = (
        varint(
            len(txids)
        )
        + coinbase
        + b''.join(
            bytes.fromhex(
                tx["data"]
            )
            for tx
            in g["transactions"]
        )
    )

    raw_path = (
        RAW
        / (
            f"{height}-"
            f"{g['previousblockhash']}-"
            f"{int(g['curtime'])}.json"
        )
    )

    if not raw_path.exists():
        atomic_json(
            raw_path,
            g
        )

    obj = {
        "format": 2,
        "created": int(time.time()),

        "height": height,
        "version": int(g["version"]),
        "version_hex":
            f"{int(g['version']):08x}",

        "previousblockhash":
            g["previousblockhash"],

        "curtime":
            int(g["curtime"]),

        "bits":
            g["bits"],

        "target":
            g["target"],

        "network_diff":
            float(
                DIFF1
                / target
            ),

        "nonce":
            CHAIN_ID,

        "child_hash":
            child_hash,

        "child_header":
            header.hex(),

        "coinbasevalue":
            int(
                g["coinbasevalue"]
            ),

        "vmesh_address":
            payout,

        "vmesh_scriptPubKey":
            spk.hex(),

        "developer_fee_bps": VMESH_DEV_FEE_BPS,
        "developer_fee_address": VMESH_DEV_FEE_ADDRESS,
        "developer_fee_scriptPubKey": dev_spk.hex(),
        "developer_fee_value": developer_reward,
        "miner_coinbase_value": miner_reward,

        "coinbase_scriptSig":
            script_sig.hex(),

        "coinbase_txid":
            coinbase_txid,

        "coinbase_no_witness":
            coinbase_no_witness.hex(),

        "coinbase":
            coinbase.hex(),

        "merkle_root":
            merkle_root,

        "tx_count":
            len(txids),

        "tx_vector":
            tx_vector.hex(),

        "witness_commitment":
            g[
                "default_witness_commitment"
            ],

        "commitment_hex":
            (
                "fabe6d6d"
                + child_hash
                + "01000000"
                + "00000000"
            ),

        "auxpow_chainid":
            CHAIN_ID,

        "auxpow_childnonce":
            CHAIN_ID,

        "auxpow_submit":
            "submitblock",

        "raw_template":
            str(raw_path)
    }

    template_path = (
        TEMPLATES
        / f"{child_hash}.json"
    )

    if template_path.exists():
        old = json.loads(
            template_path.read_text()
        )

        for key in (
            "child_header",
            "tx_vector",
            "target",
            "vmesh_scriptPubKey",
            "developer_fee_bps",
            "developer_fee_address",
            "developer_fee_scriptPubKey",
            "developer_fee_value",
            "miner_coinbase_value"
        ):
            if (
                old.get(key)
                != obj.get(key)
            ):
                raise RuntimeError(
                    "immutable template mismatch: "
                    + key
                )

        obj = old

    else:
        atomic_json(
            template_path,
            obj
        )

    state = {
        "format": 2,
        "status": "ready",

        "child_hash":
            obj["child_hash"],

        "network_diff":
            obj["network_diff"],

        "target":
            obj["target"],

        "height":
            obj["height"],

        "bits":
            obj["bits"],

        "template":
            str(template_path),

        "updated":
            int(time.time()),

        "commitment_hex":
            obj["commitment_hex"],

        "developer_fee_bps": VMESH_DEV_FEE_BPS,
        "developer_fee_address": VMESH_DEV_FEE_ADDRESS
    }

    atomic_json(
        STATE / "latest.json",
        state
    )

    return state


def selftest():
    state = json.loads(
        (
            STATE
            / "latest.json"
        ).read_text()
    )

    template = json.loads(
        Path(
            state["template"]
        ).read_text()
    )

    header = bytes.fromhex(
        template["child_header"]
    )

    if (
        len(header) != 80
        or dsha(header)[::-1].hex()
        != template["child_hash"]
    ):
        raise RuntimeError(
            "child header/hash selftest failed"
        )

    if (
        dsha(
            bytes.fromhex(
                template[
                    "coinbase_no_witness"
                ]
            )
        )[::-1].hex()
        != template["coinbase_txid"]
    ):
        raise RuntimeError(
            "coinbase txid selftest failed"
        )

    if (
        len(
            bytes.fromhex(
                template[
                    "commitment_hex"
                ]
            )
        )
        != 44
    ):
        raise RuntimeError(
            "commitment != 44 bytes"
        )

    if (template.get("developer_fee_bps") != VMESH_DEV_FEE_BPS
            or template.get("developer_fee_address") != VMESH_DEV_FEE_ADDRESS):
        raise RuntimeError("mandatory VMESH developer fee metadata missing")

    if (template.get("developer_fee_value") !=
            split_mining_reward(int(template["coinbasevalue"]))[1]):
        raise RuntimeError("VMESH developer fee amount mismatch")

    print(
        "VMESH TEMPLATE SELFTEST PASS"
    )

    for key in (
        "height",
        "child_hash",
        "network_diff",
        "vmesh_scriptPubKey",
        "coinbase_txid",
        "merkle_root",
        "tx_count"
    ):
        print(
            f"{key:18}: "
            f"{template[key]}"
        )


if __name__ == "__main__":
    if (
        len(sys.argv) == 2
        and sys.argv[1] == "--once"
    ):
        print(
            json.dumps(
                build(),
                indent=2
            )
        )

    elif (
        len(sys.argv) == 2
        and sys.argv[1] == "--selftest"
    ):
        selftest()

    else:
        raise SystemExit(
            "usage: "
            "vmesh_template_builder.py "
            "--once | --selftest"
        )
