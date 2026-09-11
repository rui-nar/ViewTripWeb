"""Print the benchmark table: ``python -m tests.elevation_bench``."""
from src.models.track_edit import elevation_gain

from .cases import GATES, INFO


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


def main() -> None:
    for title, cases in (("GATES", GATES), ("INFORMATIONAL", INFO)):
        print(f"\n{title}")
        print(f"{'case':44} {'true':>7} {'got':>8} {'target':>10}  ")
        for case in cases:
            label, true, got, bound, verdict = _row(case)
            print(f"{label:44} {true:>7.0f} {got:>8.0f} {bound:>10}  {verdict}")


main()
