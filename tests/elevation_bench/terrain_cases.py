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
    What the gain pipeline reports from the model along a PERFECT path — the
    ceiling this approach can actually reach. Quoting ``true_gain`` alone would
    make the approach look broken; quoting the ceiling alone would let the
    pipeline's own smoothing hide inside the baseline, which is exactly how PR
    #389's numbers looked good.

    Two things it is not. It is not what pure substitution would report in
    production, which samples along the noisy smoothed path and so pays a
    coupling term the true path never shows (28.5 m on a cross-slope against a
    ceiling of 0.0). And most of its gap from ``true_gain`` is
    :func:`elevation_gain`'s 60 m smoothing floor rather than the 30 m grid: on
    a 10 m/100 m roller field the grid costs 17% and the pipeline 57%.

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
    TerrainCase(
        "terrain-sparse-mixed", "40 m spacing, white noise, half flat",
        ter.half_flat_half_hill,
        {"spacing_m": 40.0, "speed_ms": 5.0, "vertical_kind": "white"},
        low=250.0, high=340.0,
        note="the review's finding: the SPLICED series is part noise-free "
             "model, so measuring noise on it read the model's calm as the "
             "sensor's and left the recording's own windows unsmoothed and "
             "unbanded — 454-544 m against a true 300, worse than either "
             "source. Sparse and white is the only fixture where the span and "
             "band are not already pinned at their floors"),
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
        note="594 of a true 1999 through the pipeline here, of which the 30 m "
             "grid costs 17% and elevation_gain's own 60 m smoothing the rest. "
             "Substituting would be a 31% loss against the recording — but the "
             "recording's 907 is 850 of pipeline-limited terrain plus phantom, "
             "not extra information it has and the model lacks"),
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
    TerrainCase(
        "terrain-noop-odd-length", "gentle drag, length not a whole window",
        ter.steady_grade,
        {"length_km": 20.30},
        no_op=True,
        note="the tail, and this length is chosen not arbitrary: 20.30 km "
             "leaves a 295 m stub whose relief reads 4.26 m, under the 5 m "
             "threshold purely because it is a partial window of real relief. "
             "A threshold in metres only means anything against a fixed length "
             "of ground, so the tail is judged over the last FULL window "
             "instead. Rejecting only stubs under half a window (250 m) leaves "
             "exactly this band broken"),
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

    # The model's OWN error, which every gate above assumes away. Measured, not
    # gated: which of these two models real tiles follow decides whether the
    # relief verdict fires at all, and a synthetic surface cannot answer it.
    # Unit 2 must, against real tiles over known terrain, before this is wired.
    TerrainCase(
        "terrain-watch-model-err-corr", "flat, model error 1 m over 500 m",
        ter.flat_plain, {"post_sigma_m": 1.0, "error_length_m": 500.0},
        note="give the model its own error and the verdict stops being "
             "reliable: across the five seeds the flat group reaches 6.39 m of "
             "apparent relief and the relief group falls to 4.38, so they "
             "overlap and no threshold orders them"),
    TerrainCase(
        "terrain-watch-model-err-window-scale", "drag, model error at 300 m",
        ter.steady_grade, {"post_sigma_m": 1.0, "error_length_m": 300.0},
        note="where the RELIEF verdict fails: a drag's no-op survives 40/40 "
             "seeds with a perfect model, 32/40 at 100 m, 26/40 at 300 m, "
             "34/40 at 500 m, 40/40 by 1500 m. Error near the window's own "
             "scale is a slope that cancels the terrain's. (The earlier note "
             "said 200 m and quoted 5 seeds; at 40 it is 300 m)"),
    TerrainCase(
        "terrain-watch-model-err-indep", "flat, INDEPENDENT 1.5 m per post",
        ter.flat_plain, {"post_sigma_m": 1.5},
        note="where the FLAT verdict fails. A range cannot average error "
             "away — more excursions inside a window push its max and min "
             "further apart — so short-correlation error inflates flat "
             "ground's reading to 5.62 m. 13-18 of 40 windows then read "
             "relief on level ground and the oracle leaves 135-170 m of the "
             "285 m it should have removed"),
    TerrainCase(
        "terrain-watch-subthreshold-rollers", "4 m/300 m rollers, sparse white",
        lambda: ter.rollers(300.0, 2.0),
        {"spacing_m": 40.0, "speed_ms": 5.0, "vertical_kind": "white"},
        note="the mirror of the noise fix. Relief here is real -- 259 m true, "
             "and the model's own series reports 194-199 of it -- but under "
             "the 5 m threshold per window, so the model is substituted and "
             "then SMOOTHED AND BANDED with the recording's, which steps "
             "carrying no sensor error deserve neither. The span is the larger "
             "term: 2.95 m of sigma at 40 m spacing caps it at 240 m, and a "
             "240 m mean over a 300 m wave removes ~88% before the band sees "
             "anything. Reports 0. And on gentler terrain it is WORSE than "
             "what ships -- 6 m/4000 m rollers: ships 17, oracle 0 -- so this "
             "is a regression, not only a missed opportunity. #412"),
]

ALL = FIXED + NO_OP + WATCH
GATES = FIXED + NO_OP
