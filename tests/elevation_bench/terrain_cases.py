"""Terrain-oracle cases: what the second measurement is allowed to change.

:mod:`cases` enumerates what the estimator sees — one elevation series over
distance — and its informational block records the class it provably cannot get
right: phone-class altitude error, which has the same spectrum as gentle terrain
on the distance axis. This table is the other half. Each case here carries a
terrain *model* as well as a recording, and asks what
:func:`src.models.track_edit.terrain_corrected_gain` does with both.

Two columns matter, and they are different questions:

``true_gain``
    The ascent of the actual surface. The honest target, and out of reach: a
    30 m terrain model cannot see a 10 m hill 100 m long, and no tile zoom fixes
    that because it interpolates the same posts.

``model_ceiling``
    What the gain pipeline reports from the model along a PERFECT path. The
    ceiling this approach can actually reach — and the number pure substitution
    would produce. Quoting ``true_gain`` alone would make the approach look
    broken; quoting the ceiling alone would let the model's own smoothing hide
    inside the baseline, which is exactly how PR #389's numbers looked good.

The cases split into three kinds, and the middle one is the point:

``FIXED``
    The oracle is supposed to change these, because the recording is inventing
    climb that is not there. Bounds are on the oracle's figure.

``NO_OP``
    The model sees relief throughout, so the recording must come through
    **bit-identical**. These are the cases that already work, and the gate is
    equality rather than a bound — the strongest statement available, and the
    reason this is safe to ship at all.

``WATCH``
    Printed, not asserted: the gap this approach does NOT close, and the
    artefacts it adds. Recording them keeps the size of each visible instead of
    leaving it in a closed issue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from . import terrain as ter


@dataclass(frozen=True)
class TerrainCase:
    key: str
    label: str
    #: The surface, as a factory so the table stays one flat list of rows.
    surface: Callable[[], ter.Surface]
    #: Anything else :func:`terrain.track_over` needs for this row.
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    #: Inclusive bounds on the gain the oracle reports, in metres.
    low: Optional[float] = None
    high: Optional[float] = None
    #: True when the model must see relief everywhere, so the oracle has to
    #: return exactly what the recording alone would.
    no_op: bool = False
    note: str = ""

    @property
    def is_gate(self) -> bool:
        return self.no_op or self.low is not None or self.high is not None

    def build(self, seed: int = 17) -> ter.TerrainTrack:
        """Draw this case's track, optionally at another noise seed.

        The seed is a parameter rather than baked into the row so the gates can
        re-draw the correlated noise: a bound measured from a single draw is a
        bound that fails on somebody else's machine for no reason.
        """
        return ter.track_over(self.surface(), seed=seed, **self.kwargs)


# ── The oracle is supposed to change these ───────────────────────────────────
#
# Bounds are measured across the five seeds with slack, per the convention in
# ``cases.py``: they pin behaviour against regression and are not claims of
# accuracy. The "ships" figure in each note is what the recording alone reports
# — the size of the defect being fixed.

FIXED = [
    TerrainCase(
        "terrain-flat", "flat plain, phone recording",
        ter.flat_plain,
        high=30.0,
        note="the whole point: 285 m of invented climb becomes 0"),
    TerrainCase(
        "terrain-cross-slope", "20% cross-slope, nothing climbed",
        ter.cross_slope,
        high=60.0,
        note="285 m ships; what is left is the horizontal-into-vertical "
             "coupling this approach ADDS, 27-36 m across seeds"),
    TerrainCase(
        "terrain-valley", "shallow valley, 40 m over 20 km",
        ter.shallow_valley,
        low=25.0, high=60.0,
        note="290 m ships against a true 40; the model is accurate on relief "
             "this gentle, so the oracle lands at 38-40"),
    TerrainCase(
        "terrain-half-and-half", "10 km level, then a 300 m hill",
        ter.half_flat_half_hill,
        low=270.0, high=340.0,
        note="452 m ships; the case that forces a windowed verdict, since one "
             "verdict for the whole track must lose either the flat or the hill"),
]


# ── The oracle must not touch these ──────────────────────────────────────────
#
# Equality, not a bound. Where the model sees relief in every window the spliced
# series IS the recording, so any difference at all means a boundary sample was
# dropped or a verdict misfired — and the first version of this code did drop
# one delta per window, which cost 92 m on 200 m rollers.

NO_OP = [
    TerrainCase(
        "terrain-noop-rollers-200", "rollers 10 m/200 m under a phone",
        lambda: ter.rollers(200.0),
        no_op=True,
        note="858 m against a true 999; the model would say 704, so the "
             "recording is the better of the two here and is left alone"),
    TerrainCase(
        "terrain-noop-rollers-100", "rollers 10 m/100 m under a phone",
        lambda: ter.rollers(100.0),
        no_op=True,
        note="the model sees 594 of a true 1999 at this wavelength — near its "
             "own Nyquist. Substituting here would be a 31% loss"),
    TerrainCase(
        "terrain-noop-big-rollers", "rollers 20 m/600 m under a phone",
        lambda: ter.rollers(600.0, 10.0),
        no_op=True,
        note="wavelength the model resolves well (619 of 670), and still a "
             "no-op: relief in every window means the recording stands"),
    TerrainCase(
        "terrain-noop-steady-grade", "steady 1.5% drag, 20 km",
        ter.steady_grade,
        no_op=True,
        note="see WATCH: a no-op the oracle arguably should not be, but "
             "changing it needs a second threshold on the same pass"),
]


# ── Measured, not asserted ───────────────────────────────────────────────────

WATCH = [
    TerrainCase(
        "terrain-watch-steady-grade", "steady 1.5% drag: the gap left open",
        ter.steady_grade,
        note="477 m ships against a true 300, and the oracle is a no-op on it "
             "because the model sees real relief. The model itself would say "
             "299 — nearly exact. Telling 'the model resolves this terrain' "
             "from 'it under-resolves it' is a spectral question and a "
             "follow-up, not a second threshold bolted onto this pass"),
    TerrainCase(
        "terrain-watch-viaduct", "60 m gorge crossed on the level",
        ter.valley_with_viaduct, {"on_the_level": True},
        note="a bare-earth model puts the rider on the gorge floor, so pure "
             "substitution invents 58 m of descent-and-climb. The oracle "
             "mostly escapes it — a gorge IS relief, so that window keeps the "
             "recording, which knows the rider stayed level — and reports ~19"),
    TerrainCase(
        "terrain-watch-cross-slope-10", "cross-slope with 10 m horizontal error",
        ter.cross_slope, {"sigma_h": 10.0},
        note="the coupling term at twice the horizontal noise; how far the "
             "artefact grows with a worse fix"),
]

ALL = FIXED + NO_OP + WATCH
GATES = FIXED + NO_OP
