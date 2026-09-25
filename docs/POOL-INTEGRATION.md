# Pool Integration Requirements

A compatible pool must preserve the exact VMESH child template associated with
each parent job and provide enough parent-chain data to construct the AuxPoW
proof.

Required candidate information includes:
- VMESH child hash
- Bitcoin parent header
- Bitcoin parent coinbase transaction
- parent coinbase merkle branch
- parent transaction index

Before submission, verify the child hash, parent hash, merkle branch,
VMESH commitment, VMESH target and template freshness.
