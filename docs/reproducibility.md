# Reproducibility

The verification recipe. Five steps. Two for-real CLI commands. No login. No wallet connect. No trust in Protean Labs.

## Step 1 — Read the record from the chain

```bash
PROXY=0x2a6f84fA0a09b1c04F9edAccCF6De58F11a4a364
RECORD_ID=0xdcda8ebec2501afcd69041fd2269b07749e27c32d7b95f01776e473df05f4c57
RPC=https://mainnet.base.org

cast call $PROXY "getRecord(bytes32)" $RECORD_ID --rpc-url $RPC
```

This returns the on-chain `Record` struct in raw bytes. The fields are: `recordId, priorObjectId, recordType, lifecycleState, disclosureState, writer, title, summary, author, runtimeId, replayPointer, publicationUrl, references, supersedes, retracts, publishedAt, registeredAt, contentDigest, version, exists`.

If you do not have `cast` installed, the same call works through Basescan's "Read Contract" tab on the proxy address.

## Step 2 — Recompute and compare the content digest

The contract stores `contentDigest = keccak256(abi.encode(envelope))`. The `envelope` is the `RecordInput` struct passed to `registerRecord`. The plaintext fields you need are emitted in the paired `RecordContentEmitted` event log.

```bash
# Fetch the RecordContentEmitted log for this recordId:
TOPIC0=0x7da545fcdedb56c3ad649b338af71c9a9195267ef123760e286463af4be71ee3
cast logs --address $PROXY --from-block 46612390 \
  --topic $TOPIC0 --topic $RECORD_ID --rpc-url $RPC
```

Reconstruct the `RecordInput` tuple from the event payload + the indexed fields on `RecordRegistered`, ABI-encode, and `keccak256`. Compare to `contentDigest` from step 1. Equal → the chain is honest about what was registered.

## Step 3 — Reproduce the Digest from chain events

```bash
# Get the canonical Python indexer
curl -sL https://raw.githubusercontent.com/proteanlabs1/ledger-mirror/main/scripts/index_ledger_from_genesis.py \
  -o index_ledger.py

# Run against any Base mainnet RPC
python3 index_ledger.py \
  --rpc $RPC \
  --proxy $PROXY \
  --db /tmp/protean.db \
  --from-block 46612390 \
  --once

# Compute the digest
python3 index_ledger.py --digest-only --db /tmp/protean.db
```

The digest output should match the one served at https://www.protean.sh/ledger/api/v1/indexer/digest. If they match, you have just reproduced the entire ledger state from chain events using only a public RPC.

Reference digest for the launch state (block range 46612390 -> 46613079, the four bootstrap records confirmed):

```
sha256:6049438bd0527c25270ce6cbd0e7bac7912a735e5e0e95ca65fc703910f747f6
```

## Step 4 — Fetch the supplemental replay artifact

For records that postdate this mirror (the dated-after-genesis records), the `replayPointer` field has the form:

```
git:proteanlabs1/ledger-mirror@<commit>:artifacts/mainnet/<id>.json#sha256:<hex>
```

Fetch from the cited commit (not `main`):

```bash
COMMIT=<the 40-char commit from the replayPointer>
PATH_IN_REPO=artifacts/mainnet/<id>.json
curl -sL "https://raw.githubusercontent.com/proteanlabs1/ledger-mirror/$COMMIT/$PATH_IN_REPO" -o artifact.json
```

For the four bootstrap records (`genesis`, `activation-cycle-1`, `reproducibility-hypothesis`, `launch-package-v1`) the on-chain `replayPointer` uses a placeholder sha256 anchor and predates this mirror — the corresponding `artifacts/mainnet/*.json` files in this repo are honest reconstructions but do not match the placeholder anchor. The artifact files document this explicitly in their `bootstrap` field.

## Step 5 — Recompute the supplemental artifact sha256

```bash
shasum -a 256 artifact.json
```

Compare to the `sha256:<hex>` suffix in the `replayPointer`. Equal -> the supplemental artifact at that commit is byte-identical to the pointer. The chain record and Digest remain the primary verification path.

(For the four bootstrap records, expect a mismatch. Their content digests from step 2 still verify; the artifact-side anchor is the affected one.)

## What this proves

- Step 1 + 2: the chain has not been rewritten between registration and your read.
- Step 3: the indexer state digest is a pure function of chain events. No Protean infrastructure is required to reach it.
- Step 4 + 5: the supplemental public artifact mirror has not been swapped under you between commit and your fetch (for records that have a real anchor).

## What you should NOT do

- **Do not trust this mirror as a primary source.** If you find a discrepancy between the mirror and the chain, the chain wins. Open an issue.
- **Do not run an old indexer commit.** The canonical-bytes spec evolves additively; pin the script to the same commit that produced the reference digest you're comparing against.
- **Do not assume `main` is the verified version.** Always pin to the commit cited in the `replayPointer`.
