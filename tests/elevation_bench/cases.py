"""The elevation-gain benchmark: one table of cases, with targets (issue #386).

Why this exists. Elevation gain has been rewritten four times (#260, #371,
#382, #389). Each round measured its change against the fixtures that happened
to be to hand, shipped, and was then found to have wrecked a class of track
nobody had thought to generate: a sample-counted window erased planned routes,
a distance-counted one erased rollers, a noise estimate that finally measured
correlated drift correctly erased rolling terrain outright. Every one of those
regressions was cheap to detect and expensive to discover.

So the input classes are enumerated once, here, with what each should report,
and a change to the estimator is measured against all of them at once.

Two kinds of case:

``GATE``
    Asserted by ``tests/test_elevation_bench.py``. Breaking one fails the
    build. Bounds are set from what the current implementation actually
    measures, with enough slack to absorb the generators' seed — they pin
    behaviour against regression, they are not claims of accuracy.

``INFO``
    Printed, never asserted. These are the cases the current approach CANNOT
    get right — phone-class GPS altitude, where the sensor's drift and gentle
    terrain are the same signal. Recording them keeps the size of that gap
    visible (and honest) instead of leaving it in a closed issue. When terrain
    substitution lands they become gates.

Run ``python -m tests.elevation_bench`` from the repo root for the table.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from . import generators as gen


@dataclass(frozen=True)
class Case:
    key: str
    label: str
    build: Callable[[], gen.Track]
    #: Inclusive bounds on the reported gain, in metres. ``None`` on either
    #: side means unbounded. ``None`` for both makes the case informational.
    low: Optional[float] = None
    high: Optional[float] = None
    note: str = ""

    @property
    def is_gate(self) -> bool:
        return self.low is not None or self.high is not None


# ── Gates ─────────────────────────────────────────────────────────────────────
#
# Bounds come from measurement, not intent: see the module docstring. Where a
# bound looks loose, it is holding a known, documented loss rather than
# pretending the number is good — the note says which.

GATES = [
    # Flat ground. True gain is zero, so every metre reported is invented.
    Case("flat-baro", "flat 30 km, barometric watch",
         lambda: gen.flat(30.0, 1.5, "barometric"),
         high=60.0,
         note="the good sensor: this is what a correct figure looks like"),
    Case("flat-white", "flat 30 km, white noise 3 m",
         lambda: gen.flat(30.0, 1.5, "white"),
         high=30.0,
         note="uncorrelated error averages away; the band handles it"),
    Case("flat-smart", "flat 30 km, smart recording @40 m",
         lambda: gen.flat(30.0, 40.0, "white", speed_ms=5.0),
         high=60.0),
    Case("flat-held-5", "flat 10 km, altimeter held 5 samples",
         lambda: gen.held_readings(10.0, 1.5, hold=5, kind="barometric"),
         high=60.0,
         note="repeated readings once collapsed the noise estimate to zero"),
    Case("flat-held-10", "flat 10 km, altimeter held 10 samples",
         lambda: gen.held_readings(10.0, 1.5, hold=10, kind="barometric"),
         high=60.0),

    # Real climbs. Under-reporting here is what over-correcting looks like.
    Case("climb-baro", "600 m climb, barometric",
         lambda: gen.climb(600.0, 20.0, 1.5, "barometric"),
         low=555.0, high=645.0),
    Case("climb-white", "600 m climb, white noise 3 m",
         lambda: gen.climb(600.0, 20.0, 5.5, "white", speed_ms=5.0),
         low=540.0, high=660.0),

    # Planned routes: terrain-model elevation, sparse, no sensor at all.
    # A sample-counted window reported 3 m of the 600 here (#376).
    Case("route-600-100", "planned route, 20 m hills/600 m @100 m",
         lambda: gen.rollers(20.0, 600.0, 18.0, 100.0, "clean"),
         low=540.0, high=660.0),
    Case("route-1200-100", "planned route, 20 m hills/1200 m @100 m",
         lambda: gen.rollers(20.0, 1200.0, 24.0, 100.0, "clean"),
         low=360.0, high=440.0),
    Case("route-fine-10", "planned route, 10 m hills/600 m @100 m",
         lambda: gen.rollers(10.0, 600.0, 18.0, 100.0, "clean"),
         low=250.0, high=330.0),
    Case("route-25", "planned route, 20 m hills/600 m @25 m",
         lambda: gen.rollers(20.0, 600.0, 12.0, 25.0, "clean"),
         low=350.0,
         note="denser sampling of the same route; the 60 m window floor costs some"),

    # Rolling terrain under a real sensor. The class #389 erased.
    Case("rollers-clean", "rollers 10 m/200 m, no sensor",
         lambda: gen.rollers(10.0, 200.0, 20.0, 2.0, "clean"),
         low=700.0,
         note="200 m hills are near the 60 m smoothing floor; ~25% is lost here"),
    Case("rollers-baro", "rollers 10 m/200 m, barometric",
         lambda: gen.rollers(10.0, 200.0, 20.0, 2.0, "barometric"),
         low=650.0),
    Case("rollers-smart", "rollers 30 m/300 m, smart recording @40 m, quiet",
         lambda: gen.rollers(30.0, 300.0, 20.0, 40.0, "white", sigma=1.0),
         low=1500.0,
         note="a barometric device sub-sampling; the noisy twin is informational"),
    Case("rollers-tri", "rollers 10 m/200 m triangular, barometric",
         lambda: gen.rollers(10.0, 200.0, 20.0, 2.0, "barometric", shape="tri"),
         low=580.0,
         note="straight flanks: the shape that hid two broken estimators"),

    # Rolling terrain under PHONE noise, swept across correlation time. The
    # phantom climb this sensor produces on flat ground cannot be removed (see
    # the informational cases), but the real climb under it must survive — and
    # this is where PR #389 was caught: it reported 0 m of a true 1000 at the
    # short correlation times, while what shipped reports 818-974 throughout.
    # Sweeping tau is the point. #389 was a no-op at 60 s and a catastrophe at
    # 10 s, and a benchmark fixed at either value would have missed it.
    Case("phone-rollers-tau10", "rollers 10 m/200 m, phone GPS drifting over 10 s",
         lambda: gen.rollers(10.0, 200.0, 20.0, 2.0, "phone", speed_ms=2.0, tau_s=10.0),
         low=700.0),
    Case("phone-rollers-tau20", "rollers 10 m/200 m, phone GPS drifting over 20 s",
         lambda: gen.rollers(10.0, 200.0, 20.0, 2.0, "phone", speed_ms=2.0, tau_s=20.0),
         low=700.0),
    Case("phone-rollers-tau30", "rollers 10 m/200 m, phone GPS drifting over 30 s",
         lambda: gen.rollers(10.0, 200.0, 20.0, 2.0, "phone", speed_ms=2.0, tau_s=30.0),
         low=700.0),
    Case("phone-rollers-tau60", "rollers 10 m/200 m, phone GPS drifting over 60 s",
         lambda: gen.rollers(10.0, 200.0, 20.0, 2.0, "phone", speed_ms=2.0, tau_s=60.0),
         low=700.0),

    # Fragments, as a split or a trimmed edit leaves behind.
    Case("fragment-climb", "middle 2 km of the 600 m climb, barometric",
         lambda: gen.fragment(gen.climb(600.0, 20.0, 1.5, "barometric"),
                              gen.climb(600.0, 20.0, 1.5, "clean"),
                              0.30, 0.40),
         low=100.0, high=140.0),
    Case("fragment-flat", "a flat 2 km piece, barometric",
         lambda: gen.fragment(gen.flat(20.0, 1.5, "barometric"),
                              gen.flat(20.0, 1.5, "clean"),
                              0.30, 0.40),
         high=25.0),
]


# ── Informational ─────────────────────────────────────────────────────────────
#
# Phone-class GPS altitude: error that is both large and correlated over
# minutes. On the distance axis this is the same signal as gentle terrain, so
# no threshold-and-smoothing estimator can separate them — established by
# sweeping every span x threshold pair (issue #386). These are printed so the
# gap stays measured; substituting terrain-model elevation is what will close
# them, at which point they become gates.

INFO = [
    # Flat ground, swept across correlation time: every metre here is invented,
    # and how much depends entirely on how long the sensor's error stays
    # correlated — which is the number nobody has measured from real handsets.
    Case("phone-flat-tau10", "flat 30 km walk, phone GPS drifting over 10 s",
         lambda: gen.flat(30.0, 1.5, "phone", tau_s=10.0)),
    Case("phone-flat-tau30", "flat 30 km walk, phone GPS drifting over 30 s",
         lambda: gen.flat(30.0, 1.5, "phone", tau_s=30.0)),
    Case("phone-flat-tau60", "flat 30 km walk, phone GPS drifting over 60 s",
         lambda: gen.flat(30.0, 1.5, "phone", tau_s=60.0)),
    Case("phone-flat-tau120", "flat 30 km walk, phone GPS drifting over 120 s",
         lambda: gen.flat(30.0, 1.5, "phone", tau_s=120.0)),
    Case("phone-flat-ride", "flat 30 km ride, phone GPS",
         lambda: gen.flat(30.0, 7.0, "phone", speed_ms=7.0)),
    Case("phone-climb", "600 m climb, phone GPS",
         lambda: gen.climb(600.0, 20.0, 1.5, "phone")),
    Case("phone-held", "flat 10 km, phone GPS, altimeter held 5",
         lambda: gen.held_readings(10.0, 1.5, hold=5, kind="phone")),
    # Not phone-class, but the same shape of loss: at 40 m spacing a 300 m hill
    # is seven points, and the window needed to quiet 3 m of noise is wider than
    # the hill. Sub-sampling and noise together are their own hard case.
    Case("smart-noisy-rollers", "rollers 30 m/300 m @40 m, noisy sub-sampling",
         lambda: gen.rollers(30.0, 300.0, 20.0, 40.0, "white", sigma=3.0)),
]

ALL = GATES + INFO
