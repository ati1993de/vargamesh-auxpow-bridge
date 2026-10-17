# VargaMesh getauxblock/submitauxblock compatibility adapter

This **optional**, loopback-only JSON-RPC sidecar exposes a Namecoin-style
**subset** for Bitcoin parent-pool coordinators.

It reuses the existing VargaMesh immutable child templates and submitter's
coinbase fee validation. It does **not** change VMESH consensus, pool fee
distribution, SHA-256d, or the production builder/submitter loop.

## Deployment

Requirements: Python 3.12+, an operational coordinator refreshing
`data/vmesh/state/latest.json`, and VargaMesh Core RPC accessible to the
existing `vmesh-submit` script.

```bash
# Use a strong randomly generated token stored outside shell history.
export VMESH_AUXRPC_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export VMESH_AUXRPC_PORT=29668
python3 compat/auxrpc.py
```

The listener is **always** bound to `127.0.0.1`. Do not proxy to the
public Internet. A mining pool integration should run over a protected
local socket/tunnel and use Basic auth with its password set to the token.
Restrict service files and environment files to the service user.
The production template builder's pool-specific fee policy still applies
(see top-level README); this adapter is **not** a fee bypass.

## Request/response

Standard HTTP POST with JSON-RPC body:

```json
{"jsonrpc":"2.0","id":1,"method":"getauxblock","params":[]}
```

Returns the current child hash, chainid, height, target, bits and prior hash
(the pool must commit the child hash in its Bitcoin parent coinbase).
A pool submits an AuxPoW proof (hex serialized in VMESH's expected wire
format, **not** a full child block) through:

```json
{"jsonrpc":"2.0","id":2,"method":"submitauxblock","params":["<child_hash>","<auxpow_hex>"]}
```

or `getauxblock` with the same two arguments for legacy-compatible pools.
Submission reconstructs the complete VMESH child block from the immutable
stored header, supplied proof and original transaction vector, then
calls Core `submitblock`. A stale template returns `false`, and Core
remains the final validator of parent PoW, commitments and signatures.

**Compatibility is intentionally limited:** not all AuxPoW pools implement
the same RPC conventions. Confirm the pool's expected fields and proof
serialization before deployment. A suitable adapter test alone does not
demonstrate acceptance by any specific third-party pool.

## Tests

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile compat/auxrpc.py
```

Test cases include live-template mapping, stale-tip rejection, malformed
proof refusal and full-block reconstruction with a mocked Core backend.
They do not exercise a live VMESH Mainnet block.
