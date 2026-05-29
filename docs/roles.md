# Roles

Eight roles. Each is a keccak256 of a string constant declared in the contract source.

| Role | Constant | Phase-1 holder | Powers |
|---|---|---|---|
| `DEFAULT_ADMIN_ROLE` | `0x00…00` | Treasury | Grant/revoke any role; admin of all roles |
| `UPGRADER_ROLE` | `keccak256("PROTEAN_LEDGER_UPGRADER")` | Treasury | `_authorizeUpgrade`, `freezeUpgrades` |
| `PAUSER_ROLE` | `keccak256("PROTEAN_LEDGER_PAUSER")` | Treasury + Operator | `pause()` (unpause is `DEFAULT_ADMIN_ROLE` only) |
| `OPERATOR_WRITER_ROLE` | `keccak256("PROTEAN_LEDGER_OPERATOR_WRITER")` | Operator | Full daily-writes surface (excluding retraction) |
| `AUTOMATION_WRITER_ROLE` | `keccak256("PROTEAN_LEDGER_AUTOMATION_WRITER")` | Bankr | Same daily-writes surface (excluding retraction) |
| `RETRACTOR_ROLE` | `keccak256("PROTEAN_LEDGER_RETRACTOR")` | Treasury | `proposeRetraction`, `cancelRetraction`, `executeRetraction` (24h timelock) |
| `LINEAGE_REVOKER_ROLE` | `keccak256("PROTEAN_LEDGER_LINEAGE_REVOKER")` | Treasury + Operator | `revokeLineage` |
| `IP_DECLARANT_ROLE` | `keccak256("PROTEAN_LEDGER_IP_DECLARANT")` | Treasury + Operator | IPAsset register, lifecycle, disclosure (per-RecordType gate) |

## Bankr-isolation invariant

The Bankr wallet at `0x074abfb24d3fe2254672dc73f05c9696111033de` holds **exactly one role** — `AUTOMATION_WRITER_ROLE`. Verify directly:

```bash
PROXY=0x2a6f84fA0a09b1c04F9edAccCF6De58F11a4a364
BANKR=0x074abfb24d3fe2254672dc73f05c9696111033de
RPC=https://mainnet.base.org

cast call $PROXY "hasRole(bytes32,address)(bool)" \
  $(cast keccak "PROTEAN_LEDGER_AUTOMATION_WRITER") $BANKR --rpc-url $RPC
# expect: true

for ROLE in PROTEAN_LEDGER_RETRACTOR PROTEAN_LEDGER_UPGRADER \
            PROTEAN_LEDGER_IP_DECLARANT PROTEAN_LEDGER_OPERATOR_WRITER \
            PROTEAN_LEDGER_PAUSER PROTEAN_LEDGER_LINEAGE_REVOKER; do
  cast call $PROXY "hasRole(bytes32,address)(bool)" \
    $(cast keccak "$ROLE") $BANKR --rpc-url $RPC
done
# expect: all false (and the DEFAULT_ADMIN_ROLE = 0x00…00 also false)
```

This is the keystone of the Galen → approval → Bankr → contract write path. Galen never holds any role; Bankr never holds anything beyond `AUTOMATION_WRITER_ROLE`. Compromise of Bankr can produce at most idempotent register-record traffic — it cannot retract, upgrade, or declare IP.

## Treasury / Operator / Bankr / Declarant addresses (Phase 1)

```
treasury    : 0xbC67Dc0F61bcf941A81A2A043e3C855da0d77245
operator    : 0x827Ba988a05c47Ce94a37d7002c79a8B31a9C2C7
bankr       : 0x074abfb24d3fe2254672dc73f05c9696111033de
ip_declarant: 0x827Ba988a05c47Ce94a37d7002c79a8B31a9C2C7
```

Topology Case D — `deployer == operator == ip_declarant` — was the configuration used at deployment. The deploy script handles this case by conditionally retaining operator/declarant roles on the deployer address; see `deployments/base-mainnet.json` for the exact post-ceremony matrix.
