#!/usr/bin/env python3
"""
brutal_audit.py — tiered adversarial audit of HACI validator v2.5.

Scaffolding:
  TIER 1            foundation: can it run, is it deterministic, does it crash
  TIER 2.1 (FSS)    Forward Static Scan — positive probes: well-formed inputs
                    that SHOULD validate cleanly. Catches false negatives.
  TIER 2.9 (BSS)    Backward Semantic Stress — negative probes: malformed/
                    adversarial inputs that SHOULD be rejected. Catches false
                    positives (the dangerous direction: silent acceptance).
  TIER 3            verdict: synthesize the pos/neg feedback loop.

The 2.1/2.9 loop:
  FSS finds inputs the validator wrongly REJECTS (over-strict).
  BSS finds inputs the validator wrongly ACCEPTS (under-strict).
  A failure in either tier feeds the other: every BSS bypass becomes a
  new FSS regression guard, every FSS false-alarm narrows the BSS net.
"""

import sys, json, tempfile, shutil, hashlib, traceback
from pathlib import Path

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from haci_validator import validate_project

# ═══════════════════════════════════════════════════════════════════════
# harness
# ═══════════════════════════════════════════════════════════════════════

class Audit:
    def __init__(self):
        self.tiers = {}
        self.findings = []   # (tier, severity, name, detail)

    def run_project(self, files: dict, strict=False):
        """Write a virtual project to disk, validate, return ProjectResult."""
        d = Path(tempfile.mkdtemp(prefix='haci_audit_'))
        try:
            for rel, content in files.items():
                p = d / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding='utf-8')
            return validate_project(d, strict=strict)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def record(self, tier, severity, name, detail=""):
        self.findings.append((tier, severity, name, detail))

    def tier_result(self, tier, passed, total):
        self.tiers[tier] = (passed, total)


A = Audit()

def section(title):
    print(f"\n{'═'*64}\n{title}\n{'═'*64}")

def probe(tier, name, files, expect, severity="HIGH", strict=False):
    """
    expect: dict of assertions, any of:
      'no_crash': True
      'has_error_substr': 'TOKEN'   → some error contains TOKEN
      'no_error_substr': 'TOKEN'    → no error contains TOKEN
      'ok': True/False              → result.ok
      'cycle_count': N
      'min_errors': N
      'max_errors': N
      'custom': callable(result) -> (bool, detail)
    Returns True if all expectations met.
    """
    try:
        r = A.run_project(files, strict=strict)
    except Exception as e:
        A.record(tier, "CRASH", name, f"{type(e).__name__}: {e}")
        print(f"  \033[31m✗ CRASH\033[0m {name}: {type(e).__name__}: {e}")
        return False

    fails = []
    errs = r.errors
    warns = r.warnings

    for key, val in expect.items():
        if key == 'no_crash':
            pass
        elif key == 'ok':
            if r.ok != val:
                fails.append(f"ok={r.ok} expected {val}")
        elif key == 'has_error_substr':
            if not any(val in e for e in errs):
                fails.append(f"no error contains '{val}' (errors={errs[:3]})")
        elif key == 'no_error_substr':
            if any(val in e for e in errs):
                fails.append(f"error contains forbidden '{val}'")
        elif key == 'has_warn_substr':
            if not any(val in w for w in warns):
                fails.append(f"no warning contains '{val}'")
        elif key == 'cycle_count':
            if len(r.cycles) != val:
                fails.append(f"cycles={len(r.cycles)} expected {val}")
        elif key == 'min_errors':
            if len(errs) < val:
                fails.append(f"errors={len(errs)} < {val}")
        elif key == 'max_errors':
            if len(errs) > val:
                fails.append(f"errors={len(errs)} > {val} ({errs[:3]})")
        elif key == 'custom':
            ok, detail = val(r)
            if not ok:
                fails.append(detail)

    if fails:
        A.record(tier, severity, name, "; ".join(fails))
        print(f"  \033[31m✗\033[0m {name}")
        for f in fails:
            print(f"      {f}")
        return False
    else:
        print(f"  \033[32m✓\033[0m {name}")
        return True


# ═══════════════════════════════════════════════════════════════════════
# TIER 1 — FOUNDATION
# ═══════════════════════════════════════════════════════════════════════
section("TIER 1 — FOUNDATION (can it run, is it deterministic, does it crash)")

t1_pass = 0
t1_total = 0

# 1.1 empty project
t1_total += 1
if probe("1", "empty project (no files)", {}, {'no_crash': True, 'ok': True}):
    t1_pass += 1

# 1.2 single trivial file
t1_total += 1
if probe("1", "single file, one line", {'runtime.haci': '! main start the system'},
         {'no_crash': True}):
    t1_pass += 1

# 1.3 determinism: same input twice → identical output
t1_total += 1
files = {
    '00_core/registry.haci': '! registry define the table',
    '10_memory/m.haci': '? m previous result >\nstore parsed nodes',
    '20_code/c.haci': '! c use m for cache',
}
r1 = A.run_project(files)
r2 = A.run_project(files)
def _norm(r):
    # strip the per-run temp root from error/warning strings before comparing
    def clean(items): return sorted(s.replace(r.root, 'ROOT') for s in items)
    return json.dumps({'symbols': sorted(r.symbols.keys()), 'errors': clean(r.errors),
                       'warnings': clean(r.warnings), 'cycles': r.cycles}, sort_keys=True)
h1 = hashlib.sha256(_norm(r1).encode()).hexdigest()
h2 = hashlib.sha256(_norm(r2).encode()).hexdigest()
if h1 == h2:
    print(f"  \033[32m✓\033[0m determinism: identical output across 2 runs ({h1[:12]})")
    t1_pass += 1
else:
    print(f"  \033[31m✗\033[0m determinism: DIFFERENT output across runs")
    A.record("1", "CRITICAL", "determinism", "non-deterministic output")

# 1.4 pathological inputs that often crash parsers
crash_probes = [
    ("empty file", {'a.haci': ''}),
    ("only whitespace", {'a.haci': '   \n  \n\t\n'}),
    ("only operators", {'a.haci': '! ? >\n> ! ?\n? > !'}),
    ("unicode payload", {'a.haci': '! m 日本語 émoji 🔥 payload'}),
    ("very long line", {'a.haci': '! m ' + 'x'*50000}),
    ("null-ish bytes", {'a.haci': '! m payload\x00with\x00nulls'}),
    ("nested code fences", {'a.haci': '```\n```\n```\n! m after fences'}),
    ("unclosed code fence", {'a.haci': '```python\n! m this is inside\nnever closed'}),
    ("crlf line endings", {'a.haci': '! m line one\r\n! m line two\r\n'}),
    ("tab-indented operators", {'a.haci': '\t\t! m indented command'}),
    ("1000 blank lines", {'a.haci': '\n'*1000 + '! m finally'}),
    ("deeply nested folders", {'/'.join(f'{i:02d}_d' for i in range(20)) + '/deep.haci': '! deep nested'}),
]
for name, files in crash_probes:
    t1_total += 1
    if probe("1", name, files, {'no_crash': True}):
        t1_pass += 1

A.tier_result("1", t1_pass, t1_total)
print(f"\n  TIER 1: {t1_pass}/{t1_total}")


# ═══════════════════════════════════════════════════════════════════════
# TIER 2.1 — FORWARD STATIC SCAN (FSS) — positive probes
# Well-formed inputs that SHOULD validate cleanly. Catches FALSE NEGATIVES
# (validator being wrongly strict / rejecting valid HACI).
# ═══════════════════════════════════════════════════════════════════════
section("TIER 2.1 — FORWARD STATIC SCAN (FSS) — should-accept probes")
print("  Hunting FALSE NEGATIVES: valid HACI the validator wrongly rejects\n")

fss_pass = 0
fss_total = 0

fss_cases = [
    # (name, files, expectations)
    ("clean declaration commits with >",
     {'10_m/m.haci': '! m define memory >'},
     {'no_error_substr': 'PENDING', 'max_errors': 0}),

    ("clean declaration commits with !",
     {'10_m/m.haci': '! m define memory !'},
     {'max_errors': 0}),

    ("forward reference: higher refs lower (legal)",
     {'00_core/base.haci': '! base foundation >',
      '20_app/app.haci': '! app use base for config >'},
     {'max_errors': 0}),

    ("self-reference inside own file",
     {'10_m/m.haci': '! m define interface >\nm provides read access'},
     {'max_errors': 0}),

    ("canonical dot-path reference",
     {'10_data/store.haci': '! store define >',
      '20_app/app.haci': '! app use store for data >'},
     {'max_errors': 0}),

    ("question declaration stays pending (correct, not error)",
     {'10_m/m.haci': '? m what is the state'},
     {'max_errors': 0, 'custom': lambda r: (
         any('PENDING' in str(c.get('diagnostics', [])) or not c.get('complete')
             for c in r.conversations) if r.conversations else True,
         "pending question should produce an unresolved conversation")}),

    ("ask/observe round trip same object",
     {'10_m/m.haci': '? m fetch the result\n> m here is the result'},
     {'max_errors': 0}),

    ("multiple files no cross-refs",
     {'10_a/a.haci': '! a first >', '20_b/b.haci': '! b second >', '30_c/c.haci': '! c third >'},
     {'max_errors': 0, 'cycle_count': 0}),

    ("code fence content ignored",
     {'10_m/m.haci': '! m define >\n```python\n! this is not a real command\nx = [1,2,3]\n```\nm continues'},
     {'max_errors': 0}),

    ("headings and blanks as boundaries",
     {'10_m/m.haci': '# Section One\n\n! m define >\n\n# Section Two\n\n> m result'},
     {'max_errors': 0}),

    ("sentence-case shared context lines",
     {'10_m/m.haci': '! m define >\nThe memory subsystem caches AST nodes.\nIt persists across runs.'},
     {'max_errors': 0}),

    ("deep dot path that exists",
     {'10_sys/net/net.haci': '! net define >',  # canonical: sys.net.net? depends on folder
      '20_app/app.haci': '! app reference >'},
     {'no_crash': True}),
]

for name, files, expect in fss_cases:
    fss_total += 1
    if probe("2.1", name, files, expect, severity="MEDIUM"):
        fss_pass += 1

A.tier_result("2.1", fss_pass, fss_total)
print(f"\n  TIER 2.1 (FSS): {fss_pass}/{fss_total} — false-negative resistance")


# ═══════════════════════════════════════════════════════════════════════
# TIER 2.9 — BACKWARD SEMANTIC STRESS (BSS) — negative probes
# Malformed/adversarial inputs that SHOULD be rejected. Catches FALSE
# POSITIVES (silent acceptance) — the DANGEROUS direction for an audit tool.
# ═══════════════════════════════════════════════════════════════════════
section("TIER 2.9 — BACKWARD SEMANTIC STRESS (BSS) — should-reject probes")
print("  Hunting FALSE POSITIVES: bad input the validator wrongly accepts\n")
print("  (false positives are worse — silent acceptance is the audit killer)\n")

bss_pass = 0
bss_total = 0

bss_cases = [
    # references must sit in the OBJECT SLOT (first token after operator) to form edges.

    ("phantom dot-path in object slot must be rejected",
     {'10_m/m.haci': '! m define memory >',
      '20_c/c.haci': '> m.ghost fetch something from a missing subpath'},
     {'has_error_substr': 'DOT_PATH_NOT_FOUND'}),

    ("ambiguous alias must be flagged",
     {'10_x/shared.haci': '! shared define a >',
      '20_y/shared.haci': '! shared define b >',
      '30_z/user.haci': '> shared fetch the thing'},
     {'custom': lambda r: (any('AMBIGUOUS' in e for e in r.errors),
                           f"ambiguous alias not flagged (errors={r.errors[:3]})")}),

    ("circular dependency must be detected (object-slot refs)",
     {'10_m/m.haci': '! m define memory >\n> c need compiled output',
      '20_c/c.haci': '! c define code >\n> m need cached state'},
     {'custom': lambda r: (len(r.cycles) >= 1 or any('CYCLE' in e for e in r.errors),
                           f"cycle missed (cycles={r.cycles}, cyc_errs={[e for e in r.errors if 'CYCLE' in e]})")}),

    ("deep cycle a->b->c->a must be detected (object-slot refs)",
     {'10_a/a.haci': '! a define alpha >\n> b need beta',
      '20_b/b.haci': '! b define beta >\n> c need gamma',
      '30_c/c.haci': '! c define gamma >\n> a need alpha'},
     {'custom': lambda r: (len(r.cycles) >= 1, f"deep cycle missed (cycles={r.cycles})")}),

    ("protocol line without symbol object must error",
     {'10_m/m.haci': '! Just A Payload With No Lowercase Symbol Token First >'},
     {'custom': lambda r: (any('OBJECT_REQUIRED' in e for e in r.errors),
                           f"missing-object not caught (errors={r.errors[:3]})")}),

    ("empty payload on operator line must error",
     {'10_m/m.haci': '! m >'},
     {'custom': lambda r: (any('EMPTY_PAYLOAD' in e for e in r.errors),
                           f"empty payload not caught (errors={r.errors[:3]})")}),

    ("orphan return to undeclared object must error/warn",
     {'10_m/m.haci': '! m define memory >',
      '20_c/c.haci': '> ghost orphan answer for a thing that was never declared'},
     {'custom': lambda r: (any('UNDECLARED' in e or 'DOT_PATH' in e for e in r.errors) or
                           any('RETURN_WITHOUT_OPEN' in w for w in r.warnings),
                           f"orphan/undeclared not flagged (errs={r.errors[:2]}, warns={r.warnings[:2]})")}),

    ("ambiguous return pair must not silently complete both",
     {'10_m/m.haci': '? m fetch the data result value now\n> m the data result value here\n> m the data result value also here'},
     {'custom': lambda r: (
         len([c for c in r.conversations if c.get('complete') and c.get('kind') in ('conversation','declaration')]) <= 1,
         f"multiple completions from ambiguous returns: {[(c.get('kind'),c.get('complete')) for c in r.conversations]}")}),

    ("self-reference must not infinite-loop",
     {'10_m/m.haci': '! m define memory >\n> m self reference loop attempt'},
     {'no_crash': True}),

    ("AUTHORITY_MUTATION: committed human meaning is immutable",
     {'00_core/x.haci': '! x first human meaning here >\n! x second conflicting meaning here >'},
     {'custom': lambda r: (any('AUTHORITY_MUTATION' in e or 'CONFLICTING' in e for e in r.errors),
                           f"meaning mutation not caught (errors={r.errors[:3]})")}),

    ("uppercase-only owner = AI-owned (convention check)",
     {'10_m/m.haci': '! M DEFINE THE THING IN CAPS >'},
     {'no_crash': True,
      'custom': lambda r: (
          any(n.get('owner') == 'ai' for n in r.nodes if n.get('outbound')),
          f"uppercase should be ai-owned (owners={[n.get('owner') for n in r.nodes if n.get('outbound')]})")}),

    ("pending question declaration must NOT commit",
     {'10_m/m.haci': '? m tentative meaning that should stay open'},
     {'custom': lambda r: (
         not any(s.get('commit_state') == 'committed' for s in r.symbols.values()),
         f"pending question wrongly committed: {[(k,s.get('commit_state')) for k,s in r.symbols.items()]}")}),
]

for name, files, expect in bss_cases:
    bss_total += 1
    if probe("2.9", name, files, expect, severity="CRITICAL"):
        bss_pass += 1

# explicit structural check: pending does not poison committed
print()
r = A.run_project({'10_m/m.haci': '? m tentative\n! m committed meaning >'})
committed_convs = [c for c in r.conversations if c.get('complete')]
pending_convs = [c for c in r.conversations if c.get('unresolved')]
mono_ok = len(committed_convs) >= 1 and len(pending_convs) >= 1
bss_total += 1
if mono_ok:
    print(f"  \033[32m✓\033[0m monotonicity: pending + committed coexist without poisoning")
    bss_pass += 1
else:
    print(f"  \033[31m✗\033[0m monotonicity: committed={len(committed_convs)} pending={len(pending_convs)}")
    A.record("2.9", "CRITICAL", "monotonicity", "pending poisoned committed or vice versa")

A.tier_result("2.9", bss_pass, bss_total)
print(f"\n  TIER 2.9 (BSS): {bss_pass}/{bss_total} — false-positive resistance")


# ═══════════════════════════════════════════════════════════════════════
# TIER 2 FEEDBACK LOOP — cross-pollinate FSS and BSS findings
# ═══════════════════════════════════════════════════════════════════════
section("TIER 2 FEEDBACK LOOP — pos/neg cross-pollination")

# every BSS case that PASSED (correctly rejected) becomes a regression guard.
# every BSS case that FAILED (silently accepted) is a HOLE — promote to a
# targeted FSS-style minimal reproducer.

bss_holes = [f for f in A.findings if f[0] == '2.9' and f[1] in ('CRITICAL', 'CRASH')]
fss_alarms = [f for f in A.findings if f[0] == '2.1' and f[1] in ('MEDIUM', 'HIGH')]

print(f"\n  BSS holes (false positives — wrongly accepted): {len(bss_holes)}")
for _, sev, name, detail in bss_holes:
    print(f"    \033[31m●\033[0m [{sev}] {name}")
    print(f"        {detail}")

print(f"\n  FSS alarms (false negatives — wrongly rejected): {len(fss_alarms)}")
for _, sev, name, detail in fss_alarms:
    print(f"    \033[33m●\033[0m [{sev}] {name}")
    print(f"        {detail}")

if not bss_holes and not fss_alarms:
    print("\n  \033[32mLOOP STABLE\033[0m — no false positives, no false negatives.")
    print("  The pos/neg boundary is tight: nothing valid rejected, nothing invalid accepted.")


# ═══════════════════════════════════════════════════════════════════════
# TIER 3 — VERDICT
# ═══════════════════════════════════════════════════════════════════════
section("TIER 3 — VERDICT")

crashes = [f for f in A.findings if f[1] == 'CRASH']
criticals = [f for f in A.findings if f[1] == 'CRITICAL']

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
    verdict = f"CONDITIONAL — {len(criticals)} false-positive hole(s) found (silent acceptance)"
elif total_pass == total_run:
    verdict = "PASS — survived to failure attempts; pos/neg boundary tight"
else:
    verdict = f"MARGINAL — {total_run - total_pass} soft failures, no crashes/criticals"

print(f"  OVERALL: {total_pass}/{total_run}")
print(f"  VERDICT: {verdict}\n")

# emit machine-readable summary
summary = {
    "auditor": "brutal_audit tiered FSS/BSS",
    "target": "haci_project_validator_v2_5",
    "tiers": {k: {"pass": v[0], "total": v[1]} for k, v in A.tiers.items()},
    "crashes": len(crashes),
    "criticals": len(criticals),
    "total_pass": total_pass,
    "total_run": total_run,
    "verdict": verdict,
    "findings": [{"tier": t, "severity": s, "name": n, "detail": d} for t, s, n, d in A.findings],
}
Path('haci_brutal_results.json').write_text(json.dumps(summary, indent=2))
print(f"  → haci_brutal_results.json")
