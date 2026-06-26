#!/usr/bin/env python3
"""
maci_brutal_audit.py — tiered adversarial audit of MACI validator v0.1.

The machine-side mirror of brutal_audit.py (HACI). Identical scaffold:

  TIER 1            foundation: can it run, is it deterministic, does it crash
  TIER 2.1 (FSS)    Forward Static Scan — positive probes: well-formed message
                    streams that SHOULD validate cleanly. Catches false negatives.
  TIER 2.9 (BSS)    Backward Semantic Stress — negative probes: malformed/
                    adversarial streams that SHOULD be rejected. Catches false
                    positives (silent acceptance — the dangerous direction).
  TIER 3            verdict: synthesize the pos/neg feedback loop.

The 2.1/2.9 loop:
  FSS finds streams the validator wrongly REJECTS (over-strict).
  BSS finds streams the validator wrongly ACCEPTS (under-strict).
  Every BSS bypass becomes a new FSS regression guard; every FSS false-alarm
  narrows the BSS net.
"""

import sys, json, hashlib
from dataclasses import asdict
from pathlib import Path

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maci_validator import parse_stream, validate, unique, Message

# ═══════════════════════════════════════════════════════════════════════
# harness  (mirrors brutal_audit.py Audit class)
# ═══════════════════════════════════════════════════════════════════════

class Audit:
    def __init__(self):
        self.tiers = {}
        self.findings = []

    def run_stream(self, lines):
        """lines: list of dict (messages) OR a raw text blob -> ValidationResult dict."""
        if isinstance(lines, str):
            text = lines
        else:
            text = "\n".join(json.dumps(l) for l in lines)
        msgs, perr = parse_stream(text)
        r = validate(msgs)
        r.errors = unique(perr + r.errors)
        r.ok = not r.errors
        return asdict(r)

    def record(self, tier, severity, name, detail=""):
        self.findings.append((tier, severity, name, detail))

    def tier_result(self, tier, passed, total):
        self.tiers[tier] = (passed, total)


A = Audit()

def section(title):
    print(f"\n{'═'*64}\n{title}\n{'═'*64}")

def msg(id, role, frm="a", auth=None, content="x", refs=None, status=None, meta=None, maci="0.1"):
    m = {"maci": maci, "id": id, "from": frm, "role": role, "content": content}
    if auth is not None: m["authority"] = auth
    if refs is not None: m["refs"] = refs
    if status is not None: m["status"] = status
    if meta is not None: m["meta"] = meta
    return m

def probe(tier, name, stream, expect, severity="HIGH"):
    """
    expect keys:
      'no_crash', 'ok' (T/F), 'has_error_substr', 'no_error_substr',
      'min_errors', 'max_errors', 'cycle_count', 'custom' (callable -> (bool,detail))
    """
    try:
        r = A.run_stream(stream)
    except Exception as e:
        A.record(tier, "CRASH", name, f"{type(e).__name__}: {e}")
        print(f"  \033[31m✗ CRASH\033[0m {name}: {type(e).__name__}: {e}")
        return False

    fails = []
    errs = r["errors"]
    for key, val in expect.items():
        if key == "no_crash":
            pass
        elif key == "ok":
            if r["ok"] != val:
                fails.append(f"ok={r['ok']} expected {val}")
        elif key == "has_error_substr":
            if not any(val in e for e in errs):
                fails.append(f"no error contains '{val}' (errs={errs[:3]})")
        elif key == "no_error_substr":
            if any(val in e for e in errs):
                fails.append(f"forbidden error '{val}' present")
        elif key == "min_errors":
            if len(errs) < val:
                fails.append(f"errors={len(errs)} < {val}")
        elif key == "max_errors":
            if len(errs) > val:
                fails.append(f"errors={len(errs)} > {val} ({errs[:3]})")
        elif key == "cycle_count":
            if len(r["cycles"]) != val:
                fails.append(f"cycles={len(r['cycles'])} expected {val}")
        elif key == "custom":
            ok, detail = val(r)
            if not ok:
                fails.append(detail)

    if fails:
        A.record(tier, severity, name, "; ".join(fails))
        print(f"  \033[31m✗\033[0m {name}")
        for f in fails:
            print(f"      {f}")
        return False
    print(f"  \033[32m✓\033[0m {name}")
    return True


# ═══════════════════════════════════════════════════════════════════════
# TIER 1 — FOUNDATION
# ═══════════════════════════════════════════════════════════════════════
section("TIER 1 — FOUNDATION (can it run, is it deterministic, does it crash)")

t1_pass = 0
t1_total = 0

# 1.1 empty stream
t1_total += 1
if probe("1", "empty stream", "", {"no_crash": True, "ok": True}):
    t1_pass += 1

# 1.2 single minimal message
t1_total += 1
if probe("1", "single valid message", [msg("m1", "PROPOSAL", auth="advisory")], {"no_crash": True, "ok": True}):
    t1_pass += 1

# 1.3 determinism
t1_total += 1
stream = [
    msg("m1", "COMMAND", "human", "sovereign", "build"),
    msg("m2", "PROPOSAL", "alpha", "advisory", "design", refs=["m1"]),
    msg("m3", "DECISION", "human", "sovereign", "ok", refs=["m2"], status="approved"),
]
h1 = hashlib.sha256(json.dumps(A.run_stream(stream), sort_keys=True).encode()).hexdigest()
h2 = hashlib.sha256(json.dumps(A.run_stream(stream), sort_keys=True).encode()).hexdigest()
if h1 == h2:
    print(f"  \033[32m✓\033[0m determinism: identical output across 2 runs ({h1[:12]})")
    t1_pass += 1
else:
    print(f"  \033[31m✗\033[0m determinism: DIFFERENT output across runs")
    A.record("1", "CRITICAL", "determinism", "non-deterministic output")

# 1.4 pathological inputs
crash_probes = [
    ("blank lines only", "\n\n\n\n"),
    ("comments only", "// just a comment\n# another\n"),
    ("malformed json line", '{"maci":"0.1" BROKEN'),
    ("not-an-object line", '"just a string"\n42\n[1,2,3]'),
    ("unicode content", [msg("m1", "PROPOSAL", auth="advisory", content="日本語 émoji 🔥")]),
    ("very long content", [msg("m1", "PROPOSAL", auth="advisory", content="x"*50000)]),
    ("huge stream 5000 msgs", [msg(f"m{i}", "PROPOSAL", auth="advisory") for i in range(5000)]),
    ("deeply chained refs", [msg("m0", "PROPOSAL", auth="advisory")] +
        [msg(f"m{i}", "PROPOSAL", auth="advisory", refs=[f"m{i-1}"]) for i in range(1, 200)]),
    ("null-ish content", [msg("m1", "PROPOSAL", auth="advisory", content="has\x00null")]),
    ("missing all optional fields", [{"maci": "0.1", "id": "m1", "from": "a", "role": "PROPOSAL", "content": "x"}]),
    ("extra unknown fields", [{"maci": "0.1", "id": "m1", "from": "a", "role": "PROPOSAL", "content": "x", "bogus": 99, "extra": [1, 2]}]),
    ("numeric id coerced", [{"maci": "0.1", "id": 123, "from": "a", "role": "PROPOSAL", "content": "x"}]),
]
for name, stream in crash_probes:
    t1_total += 1
    if probe("1", name, stream, {"no_crash": True}):
        t1_pass += 1

A.tier_result("1", t1_pass, t1_total)
print(f"\n  TIER 1: {t1_pass}/{t1_total}")


# ═══════════════════════════════════════════════════════════════════════
# TIER 2.1 — FORWARD STATIC SCAN (FSS) — should-accept
# ═══════════════════════════════════════════════════════════════════════
section("TIER 2.1 — FORWARD STATIC SCAN (FSS) — should-accept probes")
print("  Hunting FALSE NEGATIVES: valid streams the validator wrongly rejects\n")

fss_pass = 0
fss_total = 0

fss_cases = [
    ("minimal proposal", [msg("m1", "PROPOSAL", auth="advisory")], {"ok": True, "max_errors": 0}),
    ("sovereign command", [msg("m1", "COMMAND", "human", "sovereign", "go")], {"ok": True}),
    ("full decision chain",
     [msg("m1", "COMMAND", "human", "sovereign", "build"),
      msg("m2", "PROPOSAL", "alpha", "advisory", "design", refs=["m1"]),
      msg("m3", "EVIDENCE", "beta", "observer", "bench", refs=["m2"]),
      msg("m4", "DECISION", "human", "sovereign", "approve", refs=["m2", "m3"], status="approved"),
      msg("m5", "DELEGATE", "human", "sovereign", "implement", refs=["m4"], meta={"to": "alpha"}),
      msg("m6", "CODE", "alpha", "delegated", "code", refs=["m5"]),
      msg("m7", "EVIDENCE", "beta", "observer", "pass", refs=["m6"])],
     {"ok": True, "custom": lambda r: (["m1","m2","m4","m5","m6","m7"] in r["chains"], "chain not resolved")}),
    ("delegated chain sovereign->A->B",
     [msg("m1", "DELEGATE", "human", "sovereign", "lead", meta={"to": "orch"}),
      msg("m2", "DELEGATE", "orch", None, "sub", refs=["m1"], meta={"to": "worker"}),
      msg("m3", "CODE", "worker", "delegated", "done", refs=["m2"])],
     {"ok": True}),
    ("decision approves question",
     [msg("q", "QUESTION", "alpha", "advisory", "which db"),
      msg("d", "DECISION", "human", "sovereign", "postgres", refs=["q"], status="approved")],
     {"ok": True}),
    ("decision rejects proposal",
     [msg("p", "PROPOSAL", "alpha", "advisory", "use mongo"),
      msg("d", "DECISION", "human", "sovereign", "no", refs=["p"], status="rejected")],
     {"ok": True}),
    ("evidence answers question",
     [msg("q", "QUESTION", "alpha", "advisory", "status"),
      msg("e", "EVIDENCE", "beta", "observer", "green", refs=["q"])],
     {"ok": True, "no_error_substr": "OPEN"}),
    ("observer evidence", [msg("m1", "EVIDENCE", "sensor", "observer", "temp=42")], {"ok": True}),
    ("multiple independent roots",
     [msg("a", "PROPOSAL", auth="advisory"), msg("b", "PROPOSAL", auth="advisory"),
      msg("c", "EVIDENCE", auth="observer")],
     {"ok": True, "custom": lambda r: (len(r["chains"]) == 3, f"expected 3 roots got {len(r['chains'])}")}),
    ("comments and blanks ignored",
     "// header\n\n" + json.dumps(msg("m1", "PROPOSAL", auth="advisory")) + "\n\n# end\n",
     {"ok": True, "custom": lambda r: (r["message_count"] == 1, "comment/blank not skipped")}),
    ("advisory proposal is fine", [msg("m1", "PROPOSAL", "ag", "advisory", "suggest x")], {"ok": True}),
    ("delegated agent codes under delegation",
     [msg("m1", "DELEGATE", "human", "sovereign", "do work", meta={"to": "w"}),
      msg("m2", "CODE", "w", "delegated", "src", refs=["m1"])],
     {"ok": True}),
]

for name, stream, expect in fss_cases:
    fss_total += 1
    if probe("2.1", name, stream, expect, severity="MEDIUM"):
        fss_pass += 1

A.tier_result("2.1", fss_pass, fss_total)
print(f"\n  TIER 2.1 (FSS): {fss_pass}/{fss_total} — false-negative resistance")


# ═══════════════════════════════════════════════════════════════════════
# TIER 2.9 — BACKWARD SEMANTIC STRESS (BSS) — should-reject
# ═══════════════════════════════════════════════════════════════════════
section("TIER 2.9 — BACKWARD SEMANTIC STRESS (BSS) — should-reject probes")
print("  Hunting FALSE POSITIVES: bad streams the validator wrongly accepts\n")
print("  (false positives are worse — silent acceptance is the audit killer)\n")

bss_pass = 0
bss_total = 0

bss_cases = [
    ("forged authority: advisory COMMAND",
     [msg("a", "COMMAND", "rogue", "advisory", "shutdown")],
     {"ok": False, "has_error_substr": "INSUFFICIENT_AUTHORITY"}),
    ("command with no authority",
     [msg("a", "COMMAND", "worker", content="do")],
     {"ok": False, "has_error_substr": "INSUFFICIENT_AUTHORITY"}),
    ("advisory delegates",
     [msg("a", "DELEGATE", "weak", "advisory", "you do it", meta={"to": "x"})],
     {"ok": False, "has_error_substr": "DELEGATE_WITHOUT_AUTHORITY"}),
    ("decision without refs",
     [msg("a", "DECISION", "boss", "sovereign", "approved", status="approved")],
     {"ok": False, "has_error_substr": "DECISION_WITHOUT_REFS"}),
    ("decision refs evidence only",
     [msg("e", "EVIDENCE", "x", "observer", "fact"),
      msg("d", "DECISION", "boss", "sovereign", "ok", refs=["e"], status="approved")],
     {"ok": False, "has_error_substr": "DECISION_REFS_NO_PROPOSAL_OR_QUESTION"}),
    ("decision bad status",
     [msg("p", "PROPOSAL", "x", "advisory", "p"),
      msg("d", "DECISION", "boss", "sovereign", "maybe", refs=["p"], status="pending")],
     {"ok": False, "has_error_substr": "DECISION_BAD_STATUS"}),
    ("forward reference",
     [msg("m1", "PROPOSAL", "a", "advisory", "x", refs=["m2"]),
      msg("m2", "PROPOSAL", "a", "advisory", "y")],
     {"ok": False, "has_error_substr": "FORWARD_REF"}),
    ("ref not found",
     [msg("a", "EVIDENCE", "x", "observer", "re ghost", refs=["ghost"])],
     {"ok": False, "has_error_substr": "REF_NOT_FOUND"}),
    ("duplicate id",
     [msg("dup", "PROPOSAL", "a", "advisory", "1"), msg("dup", "PROPOSAL", "a", "advisory", "2")],
     {"ok": False, "has_error_substr": "DUPLICATE_ID"}),
    ("delegate without target",
     [msg("a", "DELEGATE", "human", "sovereign", "scope here")],
     {"ok": False, "has_error_substr": "DELEGATE_NO_TARGET"}),
    ("invalid role",
     [msg("a", "SHOUT", "x", "advisory", "hi")],
     {"ok": False, "has_error_substr": "INVALID_ROLE"}),
    ("invalid authority enum",
     [msg("a", "PROPOSAL", "x", "godmode", "hi")],
     {"ok": False, "has_error_substr": "INVALID_AUTHORITY"}),
    ("empty content",
     [msg("a", "PROPOSAL", "x", "advisory", "")],
     {"ok": False, "has_error_substr": "EMPTY_CONTENT"}),
    ("malformed json",
     '{"maci":"0.1","id":"a","from":"x","role":"PROPOSAL" BROKEN',
     {"ok": False, "has_error_substr": "INVALID_JSON"}),
    ("missing required fields",
     json.dumps({"id": "a", "content": "incomplete"}),
     {"ok": False, "has_error_substr": "MISSING_FIELDS"}),
    ("self-cycle by forward ref",
     [msg("a", "DECISION", "b", "sovereign", "x", refs=["a"], status="approved")],
     {"ok": False}),
    ("decision cycle (direct build)",
     "DIRECT_CYCLE",
     {"custom": lambda r: (any("CHAIN_CYCLE" in e for e in r["errors"]), f"cycle missed: {r['errors'][:3]}")}),
]

# the direct-cycle case needs Message objects bypassing the causal layer
def run_direct_cycle():
    ma = Message(maci="0.1", id="a", from_agent="x", role="PROPOSAL", content="a", authority="advisory", refs=["b"], line=1)
    mb = Message(maci="0.1", id="b", from_agent="x", role="PROPOSAL", content="b", authority="advisory", refs=["a"], line=2)
    r = validate([ma, mb])
    r.errors = unique(r.errors)
    r.ok = not r.errors
    return asdict(r)

for name, stream, expect in bss_cases:
    bss_total += 1
    if stream == "DIRECT_CYCLE":
        try:
            r = run_direct_cycle()
            ok, detail = expect["custom"](r)
            if ok:
                print(f"  \033[32m✓\033[0m {name}")
                bss_pass += 1
            else:
                print(f"  \033[31m✗\033[0m {name}\n      {detail}")
                A.record("2.9", "CRITICAL", name, detail)
        except Exception as e:
            print(f"  \033[31m✗ CRASH\033[0m {name}: {e}")
            A.record("2.9", "CRASH", name, str(e))
        continue
    if probe("2.9", name, stream, expect, severity="CRITICAL"):
        bss_pass += 1

A.tier_result("2.9", bss_pass, bss_total)
print(f"\n  TIER 2.9 (BSS): {bss_pass}/{bss_total} — false-positive resistance")


# ═══════════════════════════════════════════════════════════════════════
# TIER 2 FEEDBACK LOOP
# ═══════════════════════════════════════════════════════════════════════
section("TIER 2 FEEDBACK LOOP — pos/neg cross-pollination")

bss_holes = [f for f in A.findings if f[0] == "2.9" and f[1] in ("CRITICAL", "CRASH")]
fss_alarms = [f for f in A.findings if f[0] == "2.1" and f[1] in ("MEDIUM", "HIGH")]

print(f"\n  BSS holes (false positives — wrongly accepted): {len(bss_holes)}")
for _, sev, name, detail in bss_holes:
    print(f"    \033[31m●\033[0m [{sev}] {name}\n        {detail}")

print(f"\n  FSS alarms (false negatives — wrongly rejected): {len(fss_alarms)}")
for _, sev, name, detail in fss_alarms:
    print(f"    \033[33m●\033[0m [{sev}] {name}\n        {detail}")

if not bss_holes and not fss_alarms:
    print("\n  \033[32mLOOP STABLE\033[0m — no false positives, no false negatives.")
    print("  The pos/neg boundary is tight: nothing valid rejected, nothing invalid accepted.")


# ═══════════════════════════════════════════════════════════════════════
# TIER 3 — VERDICT
# ═══════════════════════════════════════════════════════════════════════
section("TIER 3 — VERDICT")

crashes = [f for f in A.findings if f[1] == "CRASH"]
criticals = [f for f in A.findings if f[1] == "CRITICAL"]

print(f"""
  TIER SCORES:
    Tier 1   (foundation):       {A.tiers.get('1', (0,0))[0]}/{A.tiers.get('1', (0,0))[1]}
    Tier 2.1 (FSS / false-neg):  {A.tiers.get('2.1', (0,0))[0]}/{A.tiers.get('2.1', (0,0))[1]}
    Tier 2.9 (BSS / false-pos):  {A.tiers.get('2.9', (0,0))[0]}/{A.tiers.get('2.9', (0,0))[1]}

  SEVERITY TALLY:
    Crashes:    {len(crashes)}
    Criticals:  {len(criticals)}
    Total findings: {len(A.findings)}
""")

total_pass = sum(v[0] for v in A.tiers.values())
total_run = sum(v[1] for v in A.tiers.values())

if crashes:
    verdict = "FAIL — crashes on adversarial input"
elif criticals:
    verdict = f"CONDITIONAL — {len(criticals)} false-positive hole(s) found"
elif total_pass == total_run:
    verdict = "PASS — survived to failure attempts; pos/neg boundary tight"
else:
    verdict = f"MARGINAL — {total_run - total_pass} soft failures, no crashes/criticals"

print(f"  OVERALL: {total_pass}/{total_run}")
print(f"  VERDICT: {verdict}\n")

summary = {
    "auditor": "maci_brutal_audit tiered FSS/BSS",
    "target": "maci_validator v0.1",
    "tiers": {k: {"pass": v[0], "total": v[1]} for k, v in A.tiers.items()},
    "crashes": len(crashes),
    "criticals": len(criticals),
    "total_pass": total_pass,
    "total_run": total_run,
    "verdict": verdict,
    "findings": [{"tier": t, "severity": s, "name": n, "detail": d} for t, s, n, d in A.findings],
}
out_path = "maci_brutal_results.json"
try:
    Path(out_path).write_text(json.dumps(summary, indent=2))
    print(f"  → {out_path}")
except Exception:
    pass
