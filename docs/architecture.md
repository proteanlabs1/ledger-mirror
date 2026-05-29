# Protean Ledger architecture

UUPS proxy on Base mainnet. Single implementation. Eight roles enforce separation of authority between treasury (governance), operator (daily writes), and a Bankr automation wallet that is allowed exactly one role.

## Contracts

```
ERC1967Proxy (0x2a6f84fA0a09b1c04F9edAccCF6De58F11a4a364)
   │  delegatecall via implementation slot
   ▼
ProteanLedger (0x212Af224A03c3d2e9D07Db7299b1b34affBfEB3D)
   • Initializable
   • AccessControlUpgradeable
   • UUPSUpgradeable
```

Compiler: solc 0.8.24, `via_ir=true`, optimizer runs 200, evmVersion cancun. Both contracts verified on Basescan against the same settings.

## Storage layout

```
slot 0   : paused (bool, packed) + upgradesFrozen (bool, packed)
slot 1   : _records           (mapping)
slot 2   : _edges             (mapping)
slot 3   : _supersededBy      (mapping)
slot 4   : _retractedRecords  (mapping)
slot 5   : _retractionProposals (mapping)
slot 6–47: __gap[42] (reserved for additive fields)
```

Storage gap is conventional OpenZeppelin form; additive fields take from the gap before the gap shrinks.

## Role topology

See `docs/roles.md` for the matrix. The architectural invariant:

> The Bankr automation wallet holds exactly one role: `AUTOMATION_WRITER_ROLE`. It does not hold `DEFAULT_ADMIN`, `UPGRADER`, `PAUSER`, `OPERATOR_WRITER`, `RETRACTOR`, `LINEAGE_REVOKER`, or `IP_DECLARANT`.

This is verified by the deployment script's post-broadcast asserts, by the Foundry test suite (`SepoliaRehearsalTest` + `DeployProteanLedgerTopologyTest`), and by live `cast call` against the mainnet proxy.

## Upgradeability strategy

The contract is UUPS-upgradeable until `freezeUpgrades()` is called (one-way). The plan:

- Phase 1 (now): treasury holds `UPGRADER_ROLE`. Additive schema extensions are permitted.
- Phase 2 (months 3–12): role authority migrates to a treasury multi-sig. Upgrades remain possible but require multi-sig signatures.
- Phase 3 (year 1+): rare upgrades, community-signaled.
- Phase 4 (year 3+): `freezeUpgrades()`. Treasury renounces `UPGRADER_ROLE`. The contract is permanent.

The freeze is irreversible. Once frozen, schema fixes happen via the bicameral "deploy successor + anchor old state-root" pattern documented in the private repo's `protean_upgradeability_strategy.md`.

## What lives on chain vs off chain

| Layer | Holds | Trust model |
|---|---|---|
| Base mainnet (this contract) | Plaintext core fields, recordId, contentDigest, lifecycle/disclosure state, supersession + retraction pointers | Cryptographic; permanent as long as Base L1 settles |
| GitHub (this mirror) | Public-safe per-record JSON artifacts and indexer code | Supplemental distribution; useful for artifact checks but not canonical |
| The private Protean Labs repo | Research code, candidate sequences, Galen state, internal prompts | Not exposed; never published |

The `replayPointer` field on each record can point at a public artifact in this mirror. The sha256 anchor in the pointer commits to the artifact bytes. Anyone who can fetch the artifact at that commit can verify it has not been tampered with, but the artifact is supplemental. If mirror content and chain events disagree, the chain and reproduced Digest win.
