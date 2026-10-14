"""Self-check for the momentum tail-risk label (config.momentum_tail_risk + the scan line).
Plain asserts, no framework, no network.

    python test_tail_risk.py
"""
from config import MOMENTUM_TAIL_RISK, momentum_tail_risk

# bands are contiguous, ordered, and both gradients go the right way
for (lo, hi), (nlo, nhi) in zip([(b[0], b[1]) for b in MOMENTUM_TAIL_RISK],
                                [(b[0], b[1]) for b in MOMENTUM_TAIL_RISK[1:]]):
    assert hi == nlo, f"gap/overlap between bands at {hi} and {nlo}"
p20 = [b[2] for b in MOMENTUM_TAIL_RISK]
p10 = [b[3] for b in MOMENTUM_TAIL_RISK]
assert p20 == sorted(p20), "P(-20%) must be non-decreasing with momentum - that IS the finding"
assert p10 == sorted(p10, reverse=True), "10th-pct outcome must worsen with momentum"

# lookup hits the right band
assert momentum_tail_risk(0.45) == (0.02, -12.0)
assert momentum_tail_risk(6.30) == (0.06, -17.1)      # CUPID at +630%
assert momentum_tail_risk(2.00) == (0.05, -15.5)      # boundary is inclusive on the low side
assert momentum_tail_risk(1.99) == (0.03, -13.5)

# out of range returns None rather than a wrong band - the scan then prints no label
assert momentum_tail_risk(0.10) is None               # below the measured range
assert momentum_tail_risk(120.0) is None              # absurd value, don't fabricate a number

print("tail-risk label: all checks passed")
