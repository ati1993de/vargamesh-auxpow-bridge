# VMESH Mainnet AuxPoW Integration

Parent chain: Bitcoin
Child chain: VargaMesh (VMESH)
Algorithm: SHA-256d
Model: AuxPoW merged mining

Flow:

1. VargaMesh Core provides the current VMESH block template.
2. The template builder creates child state and the AuxPoW commitment.
3. The parent pool embeds the commitment in the Bitcoin coinbase.
4. Miners perform normal Bitcoin SHA-256d work.
5. VMESH-quality candidates are passed to `vmesh-submit`.
6. The submitter validates the parent proof and VMESH commitment.
7. The AuxPoW proof is built and the completed VMESH block is submitted.

VMESH does not require a fixed Stratum port. The parent pool operator chooses
their own listener and pool infrastructure.
