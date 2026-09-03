"""Round-trip and precision guarantees for the elevation profile codec.

Issue #295 (Phase 4.2). The claim this codec has to earn is "5-10x smaller,
and lossless at the precision the data actually has" — both halves are
asserted here, because the second one is what makes the first one safe.
"""
from __future__ import annotations

import json

import pytest

from src.project.elevation_codec import (
    build_elevation_payload,
    decode_profile,
    encode_profile_arrays,
    encode_profile_pairs,
)


def _profile(n: int, *, climb: float = 1.5) -> list[list[float]]:
    """A plausible track: ~10 m sample spacing, gently gaining altitude."""
    return [[i * 0.01, 500.0 + i * climb * 0.01] for i in range(n)]


def test_round_trip_is_exact_at_the_quantised_precision():
    original = _profile(500)
    decoded = decode_profile(encode_profile_pairs(original))
    assert len(decoded) == len(original)
    # Quantisation bounds the error at half a quantum: 0.5 m of distance and
    # 0.05 m of elevation. The tolerances sit just above those so a value
    # landing exactly on a rounding boundary is not a failure.
    for (d0, e0), (d1, e1) in zip(original, decoded):
        assert d0 == pytest.approx(d1, abs=0.0006)  # 0.6 m
        assert e0 == pytest.approx(e1, abs=0.051)   # 5.1 cm


def test_empty_and_none_profiles_are_empty_strings():
    assert encode_profile_pairs([]) == ""
    assert encode_profile_pairs(None) == ""
    assert decode_profile("") == []


def test_malformed_points_are_skipped_not_raised():
    # A profile is telemetry; one bad sample must not cost an activity its
    # whole chart.
    encoded = encode_profile_pairs([[0.0, 100.0], "nope", [1], [0.01, 101.0], None])
    assert len(decode_profile(encoded)) == 2


def test_descending_and_negative_values_survive():
    # Below sea level, and going downhill: the zig-zag encoding exists for
    # exactly these.
    original = [[0.0, 5.0], [0.01, -3.5], [0.02, -12.0], [0.03, 2.0]]
    decoded = decode_profile(encode_profile_pairs(original))
    for (d0, e0), (d1, e1) in zip(original, decoded):
        assert d0 == pytest.approx(d1, abs=0.0006)
        assert e0 == pytest.approx(e1, abs=0.051)


def test_truncated_input_decodes_what_it_can_rather_than_raising():
    encoded = encode_profile_pairs(_profile(50))
    assert len(decode_profile(encoded[: len(encoded) // 2])) > 0


def test_it_is_substantially_smaller_than_json():
    # The whole justification. A real profile's consecutive deltas are small,
    # which is what varint is for; JSON spends ~20 bytes per pair regardless.
    original = _profile(5000)
    encoded_len = len(encode_profile_pairs(original))
    json_len = len(json.dumps(original))
    assert encoded_len * 5 < json_len, (
        f"encoded {encoded_len} vs json {json_len} — under 5x is not worth a "
        "new wire format"
    )


def test_a_flat_profile_compresses_hardest():
    # Zero deltas are one byte each; a flat track should be near the floor.
    flat = [[i * 0.01, 100.0] for i in range(1000)]
    assert len(encode_profile_pairs(flat)) < len(json.dumps(flat)) // 8


# ── Storage shapes (issue #295) ──────────────────────────────────────────────
#
# Activity.elevation_profile is (distances_km[], elevations_m[]); ProjectIO
# hands the REST client [[distance, elevation], ...]. For a TWO-sample profile
# those shapes are structurally identical, so an earlier version that sniffed
# between them turned ([0.0, 0.012], [500.0, 501.5]) — a 12 m activity — into
# a 500 km one. The entry points are explicit now; these pin that.


def test_the_two_shapes_agree_when_each_is_told_what_it_is():
    parallel = ([0.0, 0.01, 0.02], [500.0, 501.5, 503.0])
    pairs = [[0.0, 500.0], [0.01, 501.5], [0.02, 503.0]]
    assert encode_profile_arrays(parallel) == encode_profile_pairs(pairs)


def test_a_two_sample_parallel_profile_is_not_read_as_pairs():
    # The exact case that produced a 500 km activity from a 12 m one.
    decoded = decode_profile(encode_profile_arrays(([0.0, 0.012], [500.0, 501.5])))
    assert len(decoded) == 2
    assert decoded[0][0] == pytest.approx(0.0, abs=0.0006)
    assert decoded[0][1] == pytest.approx(500.0, abs=0.051)
    assert decoded[1][0] == pytest.approx(0.012, abs=0.0006)
    assert decoded[1][1] == pytest.approx(501.5, abs=0.051)


def test_mismatched_parallel_arrays_keep_the_samples_that_pair_up():
    decoded = decode_profile(
        encode_profile_arrays(([0.0, 0.01, 0.02], [100.0, 101.0]))
    )
    assert len(decoded) == 2


def test_non_finite_samples_are_skipped_not_fatal():
    # An unvalidated GPX <ele> can carry an infinity; round(inf) raises
    # OverflowError, which would 500 the endpoint.
    encoded = encode_profile_pairs(
        [[0.0, 100.0], [0.01, float("inf")], [0.02, float("nan")], [0.03, 103.0]]
    )
    assert len(decode_profile(encoded)) == 2


def test_arrays_encoder_tolerates_empty_and_malformed_input():
    assert encode_profile_arrays(None) == ""
    assert encode_profile_arrays(([], [])) == ""
    assert encode_profile_arrays(([1.0],)) == ""


def test_encrypted_profiles_are_surfaced_not_dropped():
    # GET /{name} still serves the envelope; omitting it here would make an
    # E2EE trip look like one with no elevation data at all (issue #26).
    class _A:
        def __init__(self, aid, profile=None, enc=None):
            self.id = aid
            self.elevation_profile = profile
            self.elevation_profile_enc = enc

    payload = build_elevation_payload([
        _A(1, profile=([0.0, 0.01], [10.0, 12.0])),
        _A(2, enc="v1:opaque-envelope"),
        _A(3),
    ])
    assert set(payload["profiles"]) == {"1"}
    assert payload["encrypted"] == {"2": "v1:opaque-envelope"}


def test_build_payload_tolerates_no_activities():
    assert build_elevation_payload(None) == {"profiles": {}, "encrypted": {}}
    assert build_elevation_payload([]) == {"profiles": {}, "encrypted": {}}
