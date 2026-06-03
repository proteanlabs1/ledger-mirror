# Protean Ledger schema

Schema version: `protean.ledger.v1`
Ordinals are pinned. Adding ordinals is allowed; reordering them is not.

## RecordType (17)

| Ordinal | Name | Notes |
|---:|---|---|
| 0  | `Unknown` | sentinel; not constructible |
| 1  | `RuntimeCycle` | a cycle of the Protean runtime |
| 2  | `Hypothesis` | a falsifiable claim |
| 3  | `Experiment` | a planned or executed experimental procedure |
| 4  | `EvidenceBundle` | a curated collection of supporting evidence |
| 5  | `Candidate` | a candidate molecule; published records include full sequence plus hashes |
| 6  | `Thesis` | a published paper |
| 7  | `AssayResult` | a wet-lab result; review-gated publication |
| 8  | `Collection` | a publication-time grouping |
| 9  | `RetractionNotice` | the authoritative retraction artifact |
| 10 | `ExternalSignal` | a recorded external signal (literature, data) |
| 11 | `Governance` | a governance act (role grant, anchor, pause/unpause) |
| 12 | `ScientificAsset` | a citable aggregation of records |
| 13 | `IPAsset` | a provisional IP declaration; gated on `IP_DECLARANT_ROLE` |
| 14 | `CandidateFamily` | a published candidate family/cohort |
| 15 | `CandidateLineage` | candidate parent/child lineage |
| 16 | `FamilyLineage` | family parent/child lineage |

## RelationType (20)

| Ordinal | Name |
|---:|---|
| 0  | `Unknown` |
| 1  | `DerivedFrom` |
| 2  | `Tests` |
| 3  | `Supports` |
| 4  | `Contradicts` |
| 5  | `Supersedes` |
| 6  | `Retracts` |
| 7  | `Includes` |
| 8  | `Produces` |
| 9  | `Cites` |
| 10 | `ReviewedBy` |
| 11 | `Anchors` |
| 12 | `AssetOf` |
| 13 | `ProtectedBy` |
| 14 | `ParentOf` |
| 15 | `ChildOf` |
| 16 | `MemberOfFamily` |
| 17 | `VariantOf` |
| 18 | `FamilyDerivedFrom` |
| 19 | `PublishedAs` |

Reserved (documented, not enum-added): `LicensedTo`, `OwnedBy`, `WrappedBy`. See `docs/architecture.md` for the upgradeability strategy.

## LifecycleState (10)

| Ordinal | Name |
|---:|---|
| 0 | `Draft` |
| 1 | `ReviewReady` |
| 2 | `Anchored` |
| 3 | `AssayRequested` |
| 4 | `AssayReturned` |
| 5 | `IPReview` |
| 6 | `PatentFiled` |
| 7 | `Published` |
| 8 | `Superseded` (terminal) |
| 9 | `Disputed` (terminal) |

## DisclosureState (6)

| Ordinal | Name |
|---:|---|
| 0 | `PrivateCommitmentOnly` |
| 1 | `RedactedPublic` |
| 2 | `CounselReviewed` |
| 3 | `PatentPending` |
| 4 | `Public` |
| 5 | `Retracted` (terminal) |

## Record identity

```
recordId = keccak256(
  abi.encode(
    RECORD_DOMAIN,
    priorObjectId,
    uint8(recordType),
    uint8(lifecycleState),
    uint8(disclosureState),
    keccak256(bytes(title)),
    keccak256(bytes(summary)),
    keccak256(bytes(author)),
    keccak256(bytes(runtimeId)),
    keccak256(bytes(replayPointer)),
    keccak256(bytes(publicationUrl)),
    keccak256(abi.encode(references)),
    supersedes,
    retracts,
    publishedAt
  )
)
```

`RECORD_DOMAIN = keccak256("PROTEAN_LEDGER_RECORD_V1")`.

The identity vector is the `RecordInput` tuple after per-string hashing and references-list hashing, matching `contracts/ProteanLedger.sol`. Pinned identity vector for the Thesis baseline (verified across Solidity + Python + TypeScript implementations):

```
0x3e11469568b613ae0f1741e06e9d4043f563430e15d2f5c2aff220d8a400cab6
```

Any change to enum ordering, field ordering, or `RECORD_DOMAIN` invalidates the baseline. The Foundry test `test_python_record_id_parity_baseline` catches that drift.

## Edge identity

```
edgeId = keccak256(
  abi.encode(
    EDGE_DOMAIN,
    parentRecordId,
    childRecordId,
    uint8(relation),
    evidenceHash
  )
)
```

`EDGE_DOMAIN = keccak256("PROTEAN_LEDGER_EDGE_V1")`.

Edges are content-addressed too; the same `(parentRecordId, childRecordId, relation, evidenceHash)` always produces the same edgeId, which is what makes the indexer's idempotent upserts safe.

## Retraction timelock

```
RETRACTION_DELAY = 86_400 (seconds)
```

`proposeRetraction` stores the proposal; `executeRetraction` succeeds only after 24 hours have elapsed. `cancelRetraction` clears the proposal in the window. Retraction propagation across the lineage graph is explicitly NOT automatic.
