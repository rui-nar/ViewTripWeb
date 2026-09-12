"""Print the benchmark table: ``python -m tests.elevation_bench``."""
from src.models.track_edit import elevation_gain, terrain_corrected_gain

from .cases import GATES, INFO
from .terrain_cases import FIXED, NO_OP, WATCH


def _row(case):
    elevations, distances, true = case.build()
    got = elevation_gain(elevations, distances)
    if case.low is None and case.high is None:
        verdict = ""
    else:
        ok = ((case.low is None or got >= case.low)
              and (case.high is None or got <= case.high))
        verdict = "ok" if ok else "FAIL"
    bound = ""
    if case.low is not None and case.high is not None:
        bound = f"{case.low:.0f}-{case.high:.0f}"
    elif case.low is not None:
        bound = f">={case.low:.0f}"
    elif case.high is not None:
        bound = f"<={case.high:.0f}"
    return case.label, true, got, bound, verdict


def _terrain_row(case):
    """One terrain-oracle row.

    ``ceil`` is what the gain pipeline gets from the model along a PERFECT path
    — the best this approach can do, and what pure substitution would report.
    It is printed beside ``true`` on purpose: quoting only the true figure makes
    the approach look broken, and quoting only the ceiling lets the model's own
    smoothing hide inside the baseline, which is how #389's numbers looked good.
    """
    track = case.build()
    ships = elevation_gain(track.recorded, track.distances_km)
    got = terrain_corrected_gain(
        track.recorded, track.terrain, track.distances_km)
    if case.no_op:
        bound = "= recording"
        verdict = "ok" if abs(got - ships) < 1e-9 else "FAIL"
    elif case.low is not None or case.high is not None:
        if case.low is not None and case.high is not None:
            bound = f"{case.low:.0f}-{case.high:.0f}"
        elif case.low is not None:
            bound = f">={case.low:.0f}"
        else:
            bound = f"<={case.high:.0f}"
        ok = ((case.low is None or got >= case.low)
              and (case.high is None or got <= case.high))
        verdict = "ok" if ok else "FAIL"
    else:
        bound, verdict = "", ""
    return (case.label, track.true_gain, track.model_ceiling, ships, got,
            bound, verdict)


def main() -> None:
    for title, cases in (("GATES", GATES), ("INFORMATIONAL", INFO)):
        print(f"\n{title}")
        print(f"{'case':44} {'true':>7} {'got':>8} {'target':>10}  ")
        for case in cases:
            label, true, got, bound, verdict = _row(case)
            print(f"{label:44} {true:>7.0f} {got:>8.0f} {bound:>10}  {verdict}")

    for title, cases in (("TERRAIN ORACLE - corrected", FIXED),
                         ("TERRAIN ORACLE - must not change", NO_OP),
                         ("TERRAIN ORACLE - measured, not asserted", WATCH)):
        print(f"\n{title}")
        print(f"{'case':40} {'true':>7} {'ceil':>7} {'ships':>7} "
              f"{'got':>7} {'target':>12}  ")
        for case in cases:
            label, true, ceil, ships, got, bound, verdict = _terrain_row(case)
            print(f"{label:40} {true:>7.0f} {ceil:>7.0f} {ships:>7.0f} "
                  f"{got:>7.0f} {bound:>12}  {verdict}")


main()
