# Events

The contract emits 17 events. The indexer subscribes to thirteen record, lineage, retraction, and publication-attestation events; the remaining four are governance signals that the explorer surfaces but doesn't index into the state digest.

## Record lifecycle

### `RecordRegistered`

```
RecordRegistered(
  bytes32 indexed recordId,
  uint8   indexed recordType,
  address indexed writer,
  bytes32 priorObjectId,
  bytes32 contentDigest,
  uint64  publishedAt,
  uint64  registeredAt,
  uint8   lifecycleState,
  uint8   disclosureState
)
```

Emitted every time a record is created. `contentDigest = keccak256(abi.encode(envelope))` — recompute from the envelope you fetched in step 1 of the verify recipe; they must match.

### `RecordContentEmitted`

```
RecordContentEmitted(
  bytes32 indexed recordId,
  string  title,
  string  summary,
  string  author,
  string  runtimeId,
  string  replayPointer,
  string  publicationUrl,
  string[] references
)
```

Paired with `RecordRegistered`. The plaintext content travels in this event so off-chain consumers can index it without re-fetching the on-chain struct. The data in this event is what reproducibility tools hash for the canonical-bytes digest.

## Publication attestations

### `PublicationAttested`

```
PublicationAttested(
  bytes32 indexed recordId,
  uint8   indexed recordType,
  address indexed writer,
  string  candidateId,
  string  familyId,
  string  fullSequence,
  string  generationRunId,
  uint64  timestamp,
  address operatorAddress,
  string  schemaVersion,
  bytes32 attestationDigest
)
```

Emitted by `attestPublication`. This is the public full-sequence surface for intentionally published candidates, candidate families, candidate lineage records, and family lineage records.

### `PublicationAttestationHashes`

```
PublicationAttestationHashes(
  bytes32 indexed recordId,
  bytes32 provenanceHash,
  bytes32 dossierHash,
  bytes32 archiveHash,
  bytes   operatorSignature,
  string  contentUri,
  string  lineageUri,
  string  provenanceBundleUri
)
```

Carries the integrity anchors and permanent-storage URIs that accompany the full-sequence attestation.

### `PublicationAttestationReferences`

```
PublicationAttestationReferences(
  bytes32 indexed recordId,
  string[] parentCandidateIds,
  string[] childCandidateIds,
  string[] lineageReferences,
  string[] repositoryReferences,
  string[] publicationReferences
)
```

Carries queryable candidate/family lineage and the public repository/publication references attached to the record.

### `RecordSuperseded`

```
RecordSuperseded(
  bytes32 indexed priorRecordId,
  bytes32 indexed newRecordId,
  address indexed actor,
  string  reason
)
```

Idempotent. Same prior+new pair may be re-emitted; only the first updates state.

### `RecordRetracted`

```
RecordRetracted(
  bytes32 indexed recordId,
  address indexed actor,
  string  reason
)
```

Terminal. After this fires, `isRetracted(recordId)` returns true forever.

## State transitions

### `LifecycleChanged` / `DisclosureChanged`

```
LifecycleChanged (bytes32 indexed recordId, uint8 oldState, uint8 newState, address indexed actor)
DisclosureChanged(bytes32 indexed recordId, uint8 oldState, uint8 newState, address indexed actor)
```

Some states are terminal (see `docs/schema.md`).

## Retraction timelock

```
RetractionProposed (bytes32 indexed recordId, address indexed proposer, uint64 executableAfter, string reason)
RetractionCancelled(bytes32 indexed recordId, address indexed actor)
```

`executableAfter = block.timestamp + RETRACTION_DELAY` where `RETRACTION_DELAY = 86_400`. `executeRetraction` is only callable after that timestamp.

## Lineage

### `EdgeLinked`

```
EdgeLinked(
  bytes32 indexed edgeId,
  bytes32 indexed parentRecordId,
  bytes32 indexed childRecordId,
  uint8   relation,
  bytes32 evidenceHash,
  string  description,
  address actor
)
```

### `EdgeRevoked`

```
EdgeRevoked(
  bytes32 indexed edgeId,
  bytes32 indexed parentRecordId,
  bytes32 indexed childRecordId,
  address indexed actor,
  string  reason
)
```

Edges are content-addressed by `(parent, child, relation)`. Re-linking the same triple is idempotent; the same `edgeId` is returned.

## Governance

### `LedgerPaused` / `LedgerUnpaused`

```
LedgerPaused  (address indexed actor)
LedgerUnpaused(address indexed actor)
```

Pause halts writes. Reads continue. Unpause requires `DEFAULT_ADMIN_ROLE` (treasury-only).

### `UpgradesFrozenPermanently`

```
UpgradesFrozenPermanently(address indexed actor, uint64 frozenAt)
```

Emitted by `freezeUpgrades()`. After this, `_authorizeUpgrade` reverts forever. Phase 4 governance event.

### `LedgerInitialized`

```
LedgerInitialized(address indexed initialAdmin, string schemaVersion)
```

One-shot. Emitted by `initialize(initialAdmin)` from the proxy's deployment transaction.

## Event topics

Topic-0 (the event signature hash) for each:

| Event | Topic-0 |
|---|---|
| `RecordRegistered` | `0x67b3e76ae41b6ead6c183253fe438ca3cbfbad6dc6c79a4ba7dda65d06d34be8` |
| `RecordContentEmitted` | `0x7da545fcdedb56c3ad649b338af71c9a9195267ef123760e286463af4be71ee3` |
| `PublicationAttested` | `0x5cc67dd8671b7ebd5b51c26088473a363a6a16957d9bfe302504fd6dc753a3c1` |
| `PublicationAttestationHashes` | `0x6473bdb07f9299362ca9e6e9394b067f1a5ea38984c3dd9cf659b5adddfacc39` |
| `PublicationAttestationReferences` | `0x42eb0b479af2e08225b4c5498a8c6e8f4e0b5c59addda6752c581c2d132a2a40` |
| `EdgeLinked` | `0x23143bf0bcac03ebd7edcaaea6ddaf2e796eae848ef33e986e504bea9f7ab152` |
| `RecordSuperseded` | `0xac79c179cad32c220f5b33d0e61069783df7fe57348ddefaead4a5a60eb38319` |
| `LifecycleChanged` | `0x00dcc75b60c23c1ad455d8acdc23595a033c062e0d143d77eba2b132398c880a` |

(The remainder are derivable by `cast keccak "EventName(types)"` — the full ABI is at `contracts/ProteanLedger.abi.json`.)
