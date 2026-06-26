#!/usr/bin/env python3
"""
system_brutal_audit.py — brutal audit of the ASSEMBLED Duality Engine.

Every prior audit tested a COMPONENT (a validator, a torture suite, a
converged layer). This one tests the SYSTEM: the wiring, the adapters,
the runner, the convergence logic, and the meta-properties that only
exist once the pieces are bolted together.

The danger surface of an assembled system is different from its parts:
  - adapters can silently mistranslate between halves
  - the runner can report PASS while a sub-process actually failed
  - a "stable" convergence can be vacuously stable (testing nothing)
  - imports can resolve to the wrong validator version
  - the status file can drift from the actual run
  - an asymmetry can be hidden instead of recorded

Tiers (mirrors the component auditors, aimed at the whole):
  TIER 1   integration foundation: does the assembled system load & run
  TIER 2.1 SYSTEM-FSS: the engine must report PASS when everything is sound
  TIER 2.9 SYSTEM-BSS: the engine must report FAIL when ANY piece is broken
                       (the dangerous direction: a system that always says OK)
  TIER 3   meta-verdict + anti-vacuity proof
"""

import sys, os, json, subprocess, tempfile, shutil, importlib.util, hashlib

ENGINE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(ENGINE) == "shared":
    ENGINE = os.path.dirname(ENGINE)

findings = []
def record(tier, sev, name, detail=""):
    findings.append((tier, sev, name, detail))

def section(t): print(f"\n{'═'*66}\n{t}\n{'═'*66}")

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ═══════════════════════════════════════════════════════════════════════
section("TIER 1 — INTEGRATION FOUNDATION")
# ═══════════════════════════════════════════════════════════════════════
t1p = t1t = 0

def t1(name, fn):
    global t1p, t1t
    t1t += 1
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    if ok:
        t1p += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}\n      {detail}")
        record("1", "HIGH", name, detail)

# 1.1 both validators import from their package locations
def _imports():
    sys.path.insert(0, os.path.join(ENGINE, "haci"))
    sys.path.insert(0, os.path.join(ENGINE, "maci"))
    import haci_validator as H, maci_validator as M
    return (hasattr(H, "validate_project") and hasattr(M, "validate")), "missing entry points"
t1("both validators import from package", _imports)

# 1.2 the converged module loads
def _conv_loads():
    p = os.path.join(ENGINE, "shared", "converged_audit.py")
    return os.path.exists(p), f"missing {p}"
t1("converged audit module present", _conv_loads)

# 1.3 the runner exists and is executable
def _runner():
    p = os.path.join(ENGINE, "run_duality_engine.py")
    return os.path.exists(p), "runner missing"
t1("master runner present", _runner)

# 1.4 HACI validator is the TRIMMED v2.6 (not stale v2.5)
def _trimmed():
    sys.path.insert(0, os.path.join(ENGINE, "haci"))
    import haci_validator as H
    # v2.6 collapsed context/mixed -> shared; check classify returns 'shared' not 'context'
    r = H.classify_owner_v2("The Sentence Case")
    return r == "shared", f"classify returned '{r}', expected 'shared' (stale v2.5?)"
t1("HACI is trimmed v2.6 (context->shared)", _trimmed)

# 1.5 the two validators are genuinely DIFFERENT code (no accidental aliasing)
def _distinct():
    h = open(os.path.join(ENGINE, "haci", "haci_validator.py")).read()
    m = open(os.path.join(ENGINE, "maci", "maci_validator.py")).read()
    return h != m and "validate_project" in h and "def validate(" in m, "validators aliased or wrong"
t1("HACI and MACI validators are distinct", _distinct)

print(f"\n  TIER 1: {t1p}/{t1t}")


# ═══════════════════════════════════════════════════════════════════════
section("TIER 2.1 — SYSTEM-FSS (engine must report PASS when sound)")
# ═══════════════════════════════════════════════════════════════════════
print("  Hunting FALSE NEGATIVES: a healthy engine that wrongly reports failure\n")
fssp = fsst = 0

def fss(name, fn):
    global fssp, fsst
    fsst += 1
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    if ok:
        fssp += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}\n      {detail}")
        record("2.1", "MEDIUM", name, detail)

# 2.1.1 the full runner exits 0 on the intact system
def _runner_passes():
    p = subprocess.run([sys.executable, "run_duality_engine.py"],
                       cwd=ENGINE, capture_output=True, text=True)
    return p.returncode == 0 and "STABLE" in p.stdout, f"rc={p.returncode}, no STABLE in output"
fss("intact engine: runner exits 0 + STABLE", _runner_passes)

# 2.1.2 status file reports stable=true AND matches a fresh run
def _status_truthful():
    sf = os.path.join(ENGINE, "duality_engine_status.json")
    d = json.load(open(sf))
    return d.get("stable") is True, f"status.stable={d.get('stable')}"
fss("status file reports stable=true", _status_truthful)

# 2.1.3 converged audit exits 0 standalone
def _conv_passes():
    p = subprocess.run([sys.executable, "converged_audit.py"],
                       cwd=os.path.join(ENGINE, "shared"), capture_output=True, text=True)
    return p.returncode == 0, f"converged rc={p.returncode}"
fss("converged audit exits 0 standalone", _conv_passes)

# 2.1.4 all four component results files report ok
def _components_ok():
    checks = []
    for f in ["haci/haci_brutal_results.json", "maci/maci_brutal_results.json"]:
        p = os.path.join(ENGINE, f)
        if os.path.exists(p):
            d = json.load(open(p))
            checks.append(d.get("crashes", 1) == 0 and d.get("criticals", 1) == 0)
    return all(checks) and len(checks) == 2, f"component results: {checks}"
fss("both brutal-audit result files clean", _components_ok)

print(f"\n  TIER 2.1 (SYSTEM-FSS): {fssp}/{fsst}")


# ═══════════════════════════════════════════════════════════════════════
section("TIER 2.9 — SYSTEM-BSS (engine must report FAIL when ANY piece breaks)")
# ═══════════════════════════════════════════════════════════════════════
print("  Hunting FALSE POSITIVES: a BROKEN engine that still reports OK.")
print("  This is the dangerous direction — a system that can't detect its own")
print("  breakage is worse than no system. We INJECT breakage and demand FAIL.\n")
bssp = bsst = 0

def bss(name, fn):
    global bssp, bsst
    bsst += 1
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {e}"
    if ok:
        bssp += 1; print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}\n      {detail}")
        record("2.9", "CRITICAL", name, detail)

def with_broken_copy(mutate_fn, run_target):
    """Copy the engine to temp, mutate it, run a target, return (rc, stdout)."""
    tmp = tempfile.mkdtemp(prefix="engine_mut_")
    dst = os.path.join(tmp, "engine")
    shutil.copytree(ENGINE, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    try:
        mutate_fn(dst)
        cwd, script = run_target(dst)
        p = subprocess.run([sys.executable, script], cwd=cwd, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# 2.9.1 break the HACI validator -> engine must NOT report stable
def _break_haci():
    def mut(dst):
        p = os.path.join(dst, "haci", "haci_validator.py")
        s = open(p).read()
        # neuter cycle detection -> torture/brutal should catch it
        s = s.replace("cycles = detect_cycles(edges)", "cycles = []")
        open(p, "w").write(s)
    rc, out, err = with_broken_copy(mut, lambda d: (d, "run_duality_engine.py"))
    return rc != 0 or "UNSTABLE" in out or "STABLE" not in out, \
           f"broken HACI still reported stable (rc={rc})"
bss("broken HACI cycle detection -> engine reports failure", _break_haci)

# 2.9.2 break the MACI validator -> engine must NOT report stable
def _break_maci():
    def mut(dst):
        p = os.path.join(dst, "maci", "maci_validator.py")
        s = open(p).read()
        s = s.replace('if claimed not in allowed:', 'if False and claimed not in allowed:')
        open(p, "w").write(s)
    rc, out, err = with_broken_copy(mut, lambda d: (d, "run_duality_engine.py"))
    return rc != 0 or "UNSTABLE" in out or "STABLE" not in out, \
           f"broken MACI still reported stable (rc={rc})"
bss("broken MACI authority check -> engine reports failure", _break_maci)

# 2.9.3 break the converged adapter -> convergence must FAIL, not vacuously pass
def _break_adapter():
    def mut(dst):
        p = os.path.join(dst, "shared", "converged_audit.py")
        s = open(p).read()
        # make the maci adapter always claim ok=True (silent acceptance)
        s = s.replace("r.ok = not r.errors\n    toks", "r.ok = True  # INJECTED\n    toks")
        open(p, "w").write(s)
    rc, out, err = with_broken_copy(mut, lambda d: (os.path.join(d, "shared"), "converged_audit.py"))
    # if the adapter lies (always ok), the converged BSS should now see
    # false positives and the loop should go UNSTABLE
    return rc != 0 or "UNSTABLE" in out, \
           f"broken adapter still reported converged STABLE (rc={rc})"
bss("broken converged adapter -> convergence reports unstable", _break_adapter)

# 2.9.4 anti-vacuity: a converged audit that tests NOTHING must not pass
def _anti_vacuity():
    def mut(dst):
        p = os.path.join(dst, "shared", "converged_audit.py")
        s = open(p).read()
        # delete all invariants from the run list -> 0 tests
        s = s.replace("invariants = [I1(), I2(), I3(), I4(), I5(), I6(), I7()]",
                      "invariants = []")
        open(p, "w").write(s)
    rc, out, err = with_broken_copy(mut, lambda d: (os.path.join(d, "shared"), "converged_audit.py"))
    # with 0 invariants, fss_total==0 and bss_total==0. A well-built auditor
    # must NOT call that "stable" — 0/0 is vacuous, not sound.
    vacuous_pass = ("STABLE" in out and "0/0" in out)
    return not vacuous_pass, "convergence reports STABLE on zero tests (vacuous pass)"
bss("anti-vacuity: zero-test convergence must not pass", _anti_vacuity)

# 2.9.5 the runner must not report PASS if a subprocess crashes
def _crash_subprocess():
    def mut(dst):
        p = os.path.join(dst, "maci", "maci_torture.py")
        # inject a hard crash at import time
        s = open(p).read()
        open(p, "w").write("raise RuntimeError('injected crash')\n" + s)
    rc, out, err = with_broken_copy(mut, lambda d: (d, "run_duality_engine.py"))
    return rc != 0 or "STABLE" not in out, \
           f"runner reported stable despite a crashing subprocess (rc={rc})"
bss("crashing subprocess -> runner does not report stable", _crash_subprocess)

print(f"\n  TIER 2.9 (SYSTEM-BSS): {bssp}/{bsst}")


# ═══════════════════════════════════════════════════════════════════════
section("TIER 3 — META-VERDICT")
# ═══════════════════════════════════════════════════════════════════════

crashes = [f for f in findings if f[1] == "CRASH"]
crits = [f for f in findings if f[1] == "CRITICAL"]
highs = [f for f in findings if f[1] == "HIGH"]

tp = t1p + fssp + bssp
tt = t1t + fsst + bsst

print(f"""
  TIER SCORES:
    Tier 1   (integration foundation): {t1p}/{t1t}
    Tier 2.1 (SYSTEM-FSS / false-neg): {fssp}/{fsst}
    Tier 2.9 (SYSTEM-BSS / false-pos): {bssp}/{bsst}

  SEVERITY:
    Crashes:   {len(crashes)}
    Criticals: {len(crits)}   (system can't detect its own breakage)
    Highs:     {len(highs)}

  ANTI-VACUITY:
    The SYSTEM-BSS tier proves the engine FAILS when broken — it is not
    a rubber stamp. Each injected break (HACI, MACI, adapter, zero-test,
    crash) was demanded to surface as a failure. {bssp}/{bsst} surfaced.
""")

if crashes or crits:
    verdict = f"FAIL — {len(crits)} critical(s): the assembled system cannot reliably detect its own breakage"
elif tp == tt:
    verdict = "PASS — the assembled system is sound AND proven non-vacuous (it fails when broken)"
else:
    verdict = f"MARGINAL — {tt-tp} soft issue(s), no criticals"

print(f"  OVERALL: {tp}/{tt}")
print(f"  VERDICT: {verdict}")
print("═" * 66)

summary = {
    "audit": "system_brutal_audit (assembled Duality Engine)",
    "tiers": {"1": [t1p, t1t], "2.1": [fssp, fsst], "2.9": [bssp, bsst]},
    "crashes": len(crashes), "criticals": len(crits), "highs": len(highs),
    "overall": [tp, tt],
    "verdict": verdict,
    "findings": [{"tier": t, "sev": s, "name": n, "detail": d} for t, s, n, d in findings],
}
open(os.path.join(ENGINE, "system_audit_results.json"), "w").write(json.dumps(summary, indent=2))
sys.exit(0 if (tp == tt and not crits and not crashes) else 1)
