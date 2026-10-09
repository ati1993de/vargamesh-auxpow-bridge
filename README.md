# VargaMesh AuxPoW Bridge

Reference tooling for Bitcoin-parent / VMESH-child merged mining.

## Mandatory VMESH developer fee — 1%

Every child block template created by this fork pays **1.00% of the VMESH
coinbase value**, rounded down to the smallest VMESH unit, directly to:

`vm1qsfsgj70pdv86nguvexzvsflmcknz4lrsj87wx9`

The remaining **99%** (subject to integer rounding) goes to the configured
`VMESH_PAYOUT_ADDRESS`. Transaction fees included in `coinbasevalue` are
part of the split. The witness-commitment output remains zero-valued.

The fee address and 100-basis-point rate are compiled into
`coordinator/vmesh_template_builder.py` and separately checked against the
**serialized child coinbase and transaction vector** in
`submitter/vmesh-submit`. There is **no runtime configuration** to disable
or redirect this fee; invalid/legacy child templates fail closed at submit.

**Not a consensus fee:** anyone can fork or edit the open-source code, run
a different child-template builder, or mine elsewhere. Only blocks built
and submitted by these unmodified components enforce this developer fee.

## Bitcoin parent fee — separate 1%

The companion [VargaMesh CKPool AuxPoW](https://github.com/ati1993de/vargamesh-ckpool-auxpow)
fork independently inserts a 1% BTC coinbase output to:

`bc1qdw2puj3g4ypqyxql7dy3jw2f29u5q7fkvd584m`

Finding a Bitcoin block pays the BTC fee; finding a VMESH AuxPoW block pays
the VMESH fee. They are **not** charged twice on the same chain. Neither
fee can be inferred from the other chain's block result.

## Operation and safety

- Set `VMESH_PAYOUT_ADDRESS` in the private `config/pool.env` (example under `examples/`).
- Keep RPC configuration and credentials private; no production addresses or
  per-miner SOLO payout binding are provided here.
- Rebuild and deploy the **bridge and CKPool** together and refresh child
  templates; existing templates without the required developer output are
  deliberately rejected.
- Verify a child block's three coinbase outputs before enabling live mining.
- This is a **fixed pool implementation policy**, not tamper-proof network
  consensus. Protect the deployed binary/scripts and production filesystem.

Included: child template generation, AuxPoW metadata validation, candidate
validation, proof construction, and `submitblock`.

VargaMesh: https://vargacoin.com/

VargaMesh Core: https://github.com/ati1993de/vargamesh-core

License: MIT. See `LICENSE`.
