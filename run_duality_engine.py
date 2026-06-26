#!/usr/bin/env python3
"""
run_duality_engine.py — prove the whole engine in one pass.

The Duality Engine: two symmetric protocol halves, each with a validator,
a torture suite, and a brutal tiered auditor (Tier 1 | [2.1 FSS, 2.9 BSS] | 3).

  HACI  — human side  (document dialect, .haci)
  MACI  — machine side (message protocol, .maci)

Both validated identically. This runner executes all four test artifacts
and reports the unified verdict. If both halves pass, the engine is stable.
"""

import subprocess, json, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))

def run(label, cwd, script):
    p = subprocess.run([sys.executable, script], cwd=cwd, capture_output=True, text=True)
    return p.stdout, p.stderr, p.returncode

def torture_summary(stdout):
    try:
        d = json.loads(stdout)
        return d["pass"], d["result_count"], d["results_hash"][:12], d["fail"] == 0
    except Exception:
        return None, None, None, False

def brutal_verdict(stdout):
    overall = None
    passed = False
    for line in stdout.splitlines():
        if "OVERALL:" in line:
            overall = line.split("OVERALL:")[1].strip()
        if "VERDICT:" in line and "PASS" in line:
            passed = True
    return overall, passed

print("=" * 64)
print("  THE DUALITY ENGINE — full verification pass")
print("=" * 64)

results = {}

# ── HACI side ──────────────────────────────────────────────────────────
print("\n┌─ HACI (human side) ─────────────────────────────────────────┐")

out, err, rc = run("haci-torture", os.path.join(HERE, "haci"), "haci_torture.py")
hp, hc, hh, hok = torture_summary(out)
print(f"│  torture suite : {hp}/{hc} pass   hash {hh}   {'✓' if hok else '✗'}")
results["haci_torture"] = {"pass": hp, "count": hc, "hash": hh, "ok": hok}

out, err, rc = run("haci-brutal", os.path.join(HERE, "haci"), "haci_brutal_audit.py")
hv, hbok = brutal_verdict(out)
print(f"│  brutal audit  : {hv}   {'✓' if hbok else '✗'}")
results["haci_brutal"] = {"verdict": hv, "ok": hbok}
print("└─────────────────────────────────────────────────────────────┘")

# ── MACI side ──────────────────────────────────────────────────────────
print("\n┌─ MACI (machine side) ───────────────────────────────────────┐")

out, err, rc = run("maci-torture", os.path.join(HERE, "maci"), "maci_torture.py")
mp, mc, mh, mok = torture_summary(out)
print(f"│  torture suite : {mp}/{mc} pass   hash {mh}   {'✓' if mok else '✗'}")
results["maci_torture"] = {"pass": mp, "count": mc, "hash": mh, "ok": mok}

out, err, rc = run("maci-brutal", os.path.join(HERE, "maci"), "maci_brutal_audit.py")
mv, mbok = brutal_verdict(out)
print(f"│  brutal audit  : {mv}   {'✓' if mbok else '✗'}")
results["maci_brutal"] = {"verdict": mv, "ok": mbok}
print("└─────────────────────────────────────────────────────────────┘")

# ── unified verdict ────────────────────────────────────────────────────
print("\n" + "=" * 64)
all_ok = all(r.get("ok") for r in results.values())
sym = (results["haci_torture"]["ok"] and results["maci_torture"]["ok"]
       and results["haci_brutal"]["ok"] and results["maci_brutal"]["ok"])

print("  SYMMETRY CHECK:")
print(f"    HACI: validator + torture + brutal(3|[2.1,2.9]|3)  {'✓' if results['haci_torture']['ok'] and results['haci_brutal']['ok'] else '✗'}")
print(f"    MACI: validator + torture + brutal(3|[2.1,2.9]|3)  {'✓' if results['maci_torture']['ok'] and results['maci_brutal']['ok'] else '✗'}")
print()
print(f"  ENGINE STATUS: {'✓ STABLE — both halves symmetric and passing' if all_ok else '✗ UNSTABLE'}")
print("=" * 64)

with open(os.path.join(HERE, "duality_engine_status.json"), "w") as f:
    json.dump({"stable": all_ok, "symmetric": sym, "results": results}, f, indent=2)

sys.exit(0 if all_ok else 1)
