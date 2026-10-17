#!/usr/bin/env python3
"""Loopback-only, authenticated Namecoin-style AuxPoW compatibility RPC.

This is an adapter to the existing VargaMesh template builder and submitter;
it does not change VMESH consensus, coinbase fees or bridge payout policy.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import runpy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBMITTER = runpy.run_path(str(ROOT / "submitter" / "vmesh-submit"))
STATE = Path(os.environ.get("VMESH_AUXRPC_STATE", "/opt/vargamesh-auxpow-bridge/data/vmesh/state/latest.json"))
MAX_BODY = 600000
MAX_AUXPOW_BYTES = 256 * 1024
HASH_RE = re.compile(r"^[a-fA-F0-9]{64}$")


class CompatibilityError(ValueError):
    pass


def current_job():
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
        child_hash = st["child_hash"]
        if not isinstance(child_hash, str) or not HASH_RE.fullmatch(child_hash):
            raise CompatibilityError("invalid child hash in latest state")
        _, template = SUBMITTER["load_template"](child_hash)
        if st.get("status") != "ready":
            raise CompatibilityError("template not ready")
        tip = SUBMITTER["rpc"]("getbestblockhash").lower()
        if tip != str(template["previousblockhash"]).lower():
            raise CompatibilityError("stale template; VMESH tip changed")
        return template
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CompatibilityError("no valid active VMESH template") from exc


def getauxblock():
    t = current_job()
    if len(bytes.fromhex(t["child_header"])) != 80:
        raise CompatibilityError("invalid child header")
    return {
        "hash": t["child_hash"],
        "chainid": 22093,
        "previousblockhash": t["previousblockhash"],
        "height": t["height"],
        "bits": t["bits"],
        "target": t["target"],
        "coinbasevalue": t["coinbasevalue"]
    }


def submitauxblock(child_hash, proof_hex):
    if not isinstance(child_hash, str) or not HASH_RE.fullmatch(child_hash):
        raise CompatibilityError("invalid VMESH child block hash")
    if not isinstance(proof_hex, str) or len(proof_hex) % 2 or len(proof_hex) > MAX_AUXPOW_BYTES * 2:
        raise CompatibilityError("invalid AuxPoW proof length")
    try:
        proof = bytes.fromhex(proof_hex)
    except ValueError as exc:
        raise CompatibilityError("invalid AuxPoW proof encoding") from exc
    if len(proof) < 100:
        raise CompatibilityError("AuxPoW proof too short")
    try:
        _, t = SUBMITTER["load_template"](child_hash.lower())
        current_tip = SUBMITTER["rpc"]("getbestblockhash").lower()
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CompatibilityError("no valid template for child hash") from exc
    if current_tip != str(t["previousblockhash"]).lower():
        return False
    header = bytes.fromhex(t["child_header"])
    if len(header) != 80:
        raise CompatibilityError("bad child header length")
    block_hex = (header + proof + bytes.fromhex(t["tx_vector"])).hex()
    # Core performs authoritative structural and PoW validation.
    result = SUBMITTER["rpc"]("submitblock", block_hex).strip()
    return result in ("", "null")


def dispatch(method, params):
    if not isinstance(params, list):
        raise CompatibilityError("params must be an array")
    if method == "getauxblock":
        if not params:
            return getauxblock()
        if len(params) == 2:
            return submitauxblock(*params)
    if method == "submitauxblock" and len(params) == 2:
        return submitauxblock(*params)
    raise CompatibilityError("unsupported method or argument count")


class Handler(BaseHTTPRequestHandler):
    server_version = "VMESH-AuxRPC/0.1"

    def do_POST(self):
        # Never allow binding this RPC listener to a public interface.
        token = self.server.auth_token
        header = self.headers.get("Authorization", "")
        allowed = False
        if header.startswith("Basic "):
            try:
                raw = base64.b64decode(header[6:], validate=True).decode("utf-8")
                password = raw.split(":", 1)[1]
                allowed = hmac.compare_digest(password, token)
            except (ValueError, UnicodeError):
                pass
        if not allowed:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="VMESH AuxPoW"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_BODY:
                raise CompatibilityError("invalid request size")
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                raise CompatibilityError("invalid JSON-RPC request")
            answer = {"result": dispatch(request["method"], request.get("params", [])),
                      "error": None, "id": request.get("id")}
        except (CompatibilityError, ValueError, KeyError) as exc:
            answer = {"result": None, "error": {"code": -32602, "message": str(exc)}, "id": None}
        except Exception:
            # Do not disclose RPC credentials or filesystem details.
            answer = {"result": None, "error": {"code": -32603, "message": "backend unavailable"}, "id": None}
        data = json.dumps(answer, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # Do not log Authorization headers or mining proof contents.


def main():
    token = os.environ.get("VMESH_AUXRPC_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("VMESH_AUXRPC_TOKEN must contain at least 32 characters")
    port = int(os.environ.get("VMESH_AUXRPC_PORT", "29668"))
    if not 1024 <= port <= 65535:
        raise SystemExit("invalid RPC port")
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.auth_token = token
    print("VMESH AuxPoW compatibility RPC listening on 127.0.0.1:" + str(port), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
