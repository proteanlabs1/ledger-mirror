# Provenance

What the chain proves and what it does not. The Protean Ledger is provenance-first by construction; this document maps each claim type to its evidence vector.

## What the chain records

| Claim | Anchored by | How to verify |
|---|---|---|
| "This record existed at block N" | `RecordRegistered` event log | `cast logs --address <proxy> --topic <event-topic> --topic <recordId>` |
| "This record's plaintext is X" | `RecordContentEmitted` event log | Same as above. The event payload IS the plaintext. |
| "This record's canonical digest is H" | `contentDigest` field on `RecordRegistered` | Recompute the contract's ABI-encoded `RecordInput` digest. Compare. |
| "This record is part of family F" | `EdgeLinked` events with `relation = AssetOf` | Walk the edge graph. |
| "This record supersedes prior X" | `RecordSuperseded(prior=X, new=this)` | `cast call <proxy> "supersededBy(bytes32)(bytes32)" X` |
| "This record has been retracted" | `RecordRetracted` event + `isRetracted(recordId)` | `cast call <proxy> "isRetracted(bytes32)(bool)" recordId` |
| "Treasury holds DEFAULT_ADMIN" | `hasRole(bytes32, address)` return | `cast call <proxy> "hasRole(bytes32,address)(bool)" 0x00…00 <treasury>` |

## What the chain does not record

- **Truth of the scientific claim itself.** The chain says "this hypothesis was registered at this block"; it does not say the hypothesis is correct. Falsification happens off chain through `Contradicts` lineage edges and through retraction.
- **Wet-lab integrity.** No assay result on chain is a guarantee of in-vitro reproducibility. The chain commits to the *recording* of the result.
- **Reviewer competence.** Records may carry `ReviewedBy` lineage edges; the chain anchors the edge, not the quality of the review.
- **Off-chain artifact integrity** if the artifact is unreachable. The `replayPointer` field may cite a sha256 of a supplemental source file; if that file becomes unreachable (private repo, deleted commit, taken-down mirror), the on-chain record and Digest remain verifiable, but artifact rehydration is limited. This mirror exists specifically to keep supplemental artifacts reachable.

## Replay pointer scheme

Each record carries a `replayPointer` field of the form:

```
git:<owner>/<repo>@<commit>:<path>#sha256:<hex>
```

Where:

- `<owner>/<repo>` — currently `proteanlabs1/ledger-mirror` (this repo) for records that postdate the mirror.
- `<commit>` — a full 40-char SHA pinning the artifact at a specific commit. Never `HEAD` or `main`.
- `<path>` — relative to the repo root.
- `<hex>` — sha256 of the file bytes at that path at that commit.

The verify recipe (`docs/reproducibility.md`) walks the chain read, event replay, Digest reproduction, and supplemental artifact check.

Alternative schemes the contract accepts (length-only validation):

- `https://…` — public HTTPS URL.
- `ipfs://<CID>` — content-addressed; CID is the digest.
- `ar://<txId>` — Arweave permanent storage.

The contract is scheme-agnostic; readers verify by fetching + hashing.

## Bootstrap records

The first four records on Base mainnet (`genesis`, `activation-cycle-1`, `reproducibility-hypothesis`, `launch-package-v1`) were registered before this mirror existed. Their `replayPointer` fields cite the private Protean Labs repo and use placeholder sha256 anchors (e.g. `sha256:genesis`).

For these four records:

- Chain identity verification: works (read `getRecord` from any RPC).
- Content digest verification: works (recompute keccak256 from the event payload).
- Lineage verification: works (walk `EdgeLinked` events).
- Indexer reproduction: works (the published canonical digest reproduces from any public Base RPC).
- Public artifact verification: **historically not available**. The artifacts published in this mirror at `artifacts/mainnet/genesis.json` etc. are honest reconstructions, not the original sha256-anchored sources.

This is documented on the explorer record pages and in each bootstrap artifact's `bootstrap` field. We do not rewrite on-chain history to hide it.

Records registered after mirror automation is active should carry mirror-rooted `replayPointer` fields with real sha256 anchors.

## What this mirror does not change

The chain is still the source of truth. If this mirror disappears, the verification properties above (rows 1–6, columns "Anchored by" and "How to verify") remain unchanged. The mirror exists to make the artifact rehydration step trivial; it is not on the trust path between the chain and a reader.
