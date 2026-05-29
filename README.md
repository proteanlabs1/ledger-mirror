# Protean Ledger — public verification mirror

This repository exists for one purpose: to let any third party
independently verify the [Protean Ledger](https://www.protean.sh/ledger)
on Base Mainnet without trusting Protean Labs.

The chain is the source of truth. This repository is a public
distribution surface for the supporting artifacts (ABI, deployment
metadata, schema documentation, per-record JSON, the canonical
indexer) that the verification recipe references.

It is **not** the primary Protean Labs repository. It contains no
research code, no candidate sequences, no Galen state, no Bankr
credentials, no private scientific work. Everything here is
mechanically generated from a strict allowlist in the private repo and
re-published whenever the chain state advances.

## Canonical contract

```
chainId:  8453 (Base mainnet)
proxy:    0x2a6f84fA0a09b1c04F9edAccCF6De58F11a4a364
impl:     0x212Af224A03c3d2e9D07Db7299b1b34affBfEB3D
schema:   protean.ledger.v1
```

Basescan, verified source:

- Proxy: https://basescan.org/address/0x2a6f84fa0a09b1c04f9edacccf6de58f11a4a364#code
- Implementation: https://basescan.org/address/0x212af224a03c3d2e9d07db7299b1b34affbfeb3d#code

## How to verify (without trusting us)

The full recipe lives at [docs/reproducibility.md](docs/reproducibility.md).
In short:

1. **Chain identity** — read `getRecord(recordId)` from any Base RPC.
2. **Content digest** — recompute `keccak256(abi.encode(envelope))` and
   compare to the `contentDigest` field on the `RecordRegistered` event.
3. **Replay artifact** — fetch the JSON file from this mirror at the
   commit cited in `replayPointer`, recompute `sha256`, compare to
   the `sha256:` anchor in the pointer.
4. **Indexer reproduction** — run [scripts/index_ledger_from_genesis.py](scripts/index_ledger_from_genesis.py)
   against any Base mainnet RPC. The digest should match the one
   published at https://www.protean.sh/ledger.

Steps 1, 2, and 4 work for every record from genesis. Step 3 (this
mirror) is the public artifact path; the first four bootstrap records
predate this mirror and are marked as such in their artifacts and on
the explorer.

## What lives here

| Path | What it is |
|---|---|
| `contracts/ProteanLedger.abi.json` | The implementation ABI at the deployed commit. |
| `deployments/base-mainnet.json` | Proxy, implementation, deployer, role topology, deployment block range. |
| `artifacts/mainnet/*.json` | One JSON per record on chain, in canonical-bytes form. |
| `docs/schema.md` | The 14 RecordTypes, 14 RelationTypes, 10 LifecycleStates, 6 DisclosureStates, ordinal-pinned. |
| `docs/architecture.md` | UUPS proxy + role topology + Bankr-isolation invariant. |
| `docs/roles.md` | The 8 roles and who holds each. |
| `docs/events.md` | The 14 events the contract emits + their indexed parameters. |
| `docs/provenance.md` | What the chain anchors and what it doesn't. |
| `docs/reproducibility.md` | The 5-step recipe with concrete commands. |
| `diagrams/architecture.mmd` | Mermaid diagram of the architectural topology. |
| `diagrams/verification.mmd` | Mermaid diagram of the verification flow. |
| `manifests/export-manifest.json` | sha256 of every file in this export. |

## What does NOT live here

- No `.env`, no API keys, no GitHub tokens.
- No Galen state, OpenClaw config, or operator runbooks.
- No raw peptide sequences, candidate details, scoring internals.
- No autonomous-thesis source or prose-model output.
- No private pipeline code.
- No Bio repo at large.

If any of these appear, the build script that produces this mirror
should have failed closed before the push. Please [open an issue](https://github.com/proteanlabs1/ledger-mirror/issues/new)
if you find a leak.

## License

`CC0-1.0` (public domain) for the prose and JSON artifacts in this
repository. The contract source itself is `MIT` (see Basescan).

## Publication cadence

Republished on every push to `main` on the private Protean Labs repo,
and on every record event on Base mainnet. The
[`publish-verification-mirror`](https://github.com/MeltedMindz/protean-labs/actions/workflows/publish-verification-mirror.yml)
workflow generates this directory from the allowlist and force-pushes
to this repo. Git history is not preserved across publishes — each
commit is a complete snapshot.
