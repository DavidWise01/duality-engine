# The Duality Engine

A completed, self-contained module: two symmetric halves of the ACI
(Artfully Crafted Intelligence) protocol family, each validated to the
identical standard.

```
                    THE DUALITY ENGINE
                          │
          ┌───────────────┴───────────────┐
          │                               │
        HACI                            MACI
     (human side)                  (machine side)
   document dialect              message protocol
       .haci                         .maci
          │                               │
   ┌──────┼──────┐                 ┌──────┼──────┐
   │      │      │                 │      │      │
validator torture brutal       validator torture brutal
          suite  auditor                 suite  auditor
```

## The two halves

| | HACI (human) | MACI (machine) |
|---|---|---|
| **Form** | document dialect, line-oriented | message protocol, JSON Lines |
| **Extension** | `.haci` | `.maci` |
| **Authority** | ownership by case (human/ai/shared) | explicit field (sovereign/delegated/advisory/observer) |
| **Operators** | `! ? >` prefix/suffix duality | roles: COMMAND/PROPOSAL/QUESTION/EVIDENCE/DECISION/DELEGATE/CODE |
| **Core guarantee** | committed human declarations are immutable | authority cannot be forged or exceeded |
| **Decision tracking** | adjacency + commit-gating | explicit refs forming a verifiable DAG |

The split is principled. HACI is for humans reading and writing documents,
so authority is carried by typography (case) — but trimmed to only what's
load-bearing. MACI is for machines exchanging messages, so authority is an
explicit field, because machines parse fields, not casing. Each half uses
the affordance that fits its reader.

## Symmetric validation

Both halves are held to the identical three-artifact standard:

1. **Validator** — the reference implementation. Deterministic, hashable.
2. **Torture suite** — curated adversarial + seeded fuzz + property tests,
   forward/reverse order, deterministic result hash.
3. **Brutal auditor** — tiered `3 | [2.1, 2.9] | 3` scaffold:
   - **Tier 1** — foundation: crashes, determinism, pathological input
   - **Tier 2.1 (FSS)** — Forward Static Scan: should-accept probes,
     catches false negatives (over-strictness)
   - **Tier 2.9 (BSS)** — Backward Semantic Stress: should-reject probes,
     catches false positives (silent acceptance — the dangerous direction)
   - **Tier 3** — verdict + pos/neg feedback loop: every BSS hole becomes
     an FSS guard, every FSS alarm narrows the BSS net

## Current status

```
HACI : torture 1108/1108  ·  brutal 40/40  ·  PASS
MACI : torture 3929/3929  ·  brutal 44/44  ·  PASS
ENGINE: STABLE — both halves symmetric and passing
```

Both torture suites are deterministic (fixed hashes across runs). Both
validators survived brutal adversarial audit to failure with zero crashes,
zero false-positive holes, zero false-negative alarms. The MACI torture
suite was additionally mutation-tested: deliberately breaking the validator
nine different ways produced nine caught failures, confirming the suite has
real teeth rather than rubber-stamping.

## Layout

```
duality-engine/
├── run_duality_engine.py      one command, full verification
├── MANIFEST.md                this file
├── haci/
│   ├── haci_validator.py      reference validator (v2.6, trimmed)
│   ├── haci_torture.py        1108-case torture suite
│   └── haci_brutal_audit.py   tiered FSS/BSS auditor
├── maci/
│   ├── maci_validator.py      reference validator (v0.1)
│   ├── maci_torture.py        3929-case torture suite
│   └── maci_brutal_audit.py   tiered FSS/BSS auditor
└── shared/                    (reserved for cross-half tooling:
                                 HACI↔MACI converter, conformance suite)
```

## Run it

```bash
python3 run_duality_engine.py
```

Exits 0 if both halves pass, 1 otherwise. Writes `duality_engine_status.json`.

## What this module is

This is the completed validation core of the ACI family — the puzzle piece
that proves both protocol halves are sound and held to the same standard.
It does not include the editor extension, the defensive publications, or
the converters; those build *on top of* this stable core. The engine's job
is singular: guarantee that anything claiming to be HACI or MACI is checked
the same brutal way, on both sides of the human/machine boundary.

---
David Lee Wise / Bridge-Burners LLC · ACI family
