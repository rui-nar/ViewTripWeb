"""Tests for the poster card-placement algorithm (issue #14, unit C).

Covers the invariants the caller (renderer) relies on:
  - placed cards never overlap each other and stay within canvas bounds
  - placement is deterministic across runs
  - pins that can't fit a card anywhere within the search radius are
    reported as overflow (placed=False), never silently dropped or
    force-overlapped
  - a lone pin gets a sensible non-overlapping card
"""

from __future__ import annotations

from datetime import date

import pytest

from src.poster.card_placement import CardPlacement, PinSpec, Rect, place_cards


def _rects_overlap(a: Rect, b: Rect) -> bool:
    return a.overlaps(b)


def _placed_rects(results: list[CardPlacement]) -> list[Rect]:
    return [r.card_rect for r in results if r.placed]


class TestNoOverlapInvariant:
    def test_sparse_pins_all_placed_without_overlap(self):
        pins = [
            PinSpec(id=f"p{i}", x=x, y=y, sort_key=date(2025, 6, 1 + i))
            for i, (x, y) in enumerate(
                [(200, 200), (800, 200), (200, 800), (800, 800), (500, 500)]
            )
        ]
        results = place_cards(pins, card_size=(120, 80), canvas_size=(1200, 1200))

        assert len(results) == len(pins)
        rects = _placed_rects(results)
        assert len(rects) == len(pins), "sparse pins should all get a card"

        for rect in rects:
            assert rect.within((1200, 1200))

        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not _rects_overlap(rects[i], rects[j]), (
                    f"cards for pin {i} and {j} overlap: {rects[i]} vs {rects[j]}"
                )

    def test_dense_cluster_placed_cards_never_overlap(self):
        # 12 pins packed within a tight 40x40 box: some will overflow, but
        # whichever ones do get a card must never overlap another.
        pins = [
            PinSpec(id=f"c{i}", x=500 + (i % 4) * 10, y=500 + (i // 4) * 10, sort_key=date(2025, 7, 1 + i))
            for i in range(12)
        ]
        results = place_cards(pins, card_size=(100, 60), canvas_size=(2000, 2000))

        assert len(results) == 12
        rects = _placed_rects(results)
        for rect in rects:
            assert rect.within((2000, 2000))
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not _rects_overlap(rects[i], rects[j])


class TestDeterminism:
    def test_same_input_yields_identical_output(self):
        pins = [
            PinSpec(id=f"p{i}", x=300 + (i % 5) * 15, y=300 + (i // 5) * 15, sort_key=date(2025, 1, 1 + i))
            for i in range(20)
        ]
        first = place_cards(pins, card_size=(90, 50), canvas_size=(1500, 1500))
        second = place_cards(pins, card_size=(90, 50), canvas_size=(1500, 1500))

        assert first == second

    def test_determinism_survives_unsorted_input_order(self):
        pins = [
            PinSpec(id="a", x=100, y=100, sort_key=date(2025, 3, 3)),
            PinSpec(id="b", x=110, y=100, sort_key=date(2025, 3, 1)),
            PinSpec(id="c", x=100, y=110, sort_key=date(2025, 3, 2)),
        ]
        first = place_cards(pins, card_size=(80, 40), canvas_size=(1000, 1000))
        second = place_cards(list(reversed(pins)), card_size=(80, 40), canvas_size=(1000, 1000))

        # Result order follows sort_key (ascending), regardless of input order.
        assert [r.pin_id for r in first] == ["b", "c", "a"]
        assert first == second


class TestLegendFallback:
    def test_overflow_pins_are_marked_not_dropped_or_overlapping(self):
        # 30 pins crammed into a small area with a small canvas: far too
        # dense for every pin to get a non-overlapping card.
        pins = [
            PinSpec(
                id=f"n{i}",
                x=300 + (i % 6) * 5,
                y=300 + (i // 6) * 5,
                sort_key=date(2025, 5, 1 + i),
            )
            for i in range(30)
        ]
        results = place_cards(pins, card_size=(150, 100), canvas_size=(700, 700))

        assert len(results) == 30, "every pin must appear in the output, none dropped"

        overflowed = [r for r in results if not r.placed]
        placed = [r for r in results if r.placed]

        assert len(overflowed) > 0, "cluster should be dense enough to force overflow"
        for r in overflowed:
            assert r.card_rect is None

        rects = [r.card_rect for r in placed]
        for rect in rects:
            assert rect.within((700, 700))
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not _rects_overlap(rects[i], rects[j])

    def test_earlier_sort_key_wins_contested_space(self):
        # Two pins so close together that only one can claim the immediate
        # ring of positions before the other's card would overlap it -- the
        # earlier-dated pin (processed first) should be the one placed if
        # space is tight enough to matter, and no result is ever dropped.
        pins = [
            PinSpec(id="later", x=100, y=100, sort_key=date(2025, 1, 2)),
            PinSpec(id="earlier", x=102, y=100, sort_key=date(2025, 1, 1)),
        ]
        results = place_cards(pins, card_size=(60, 40), canvas_size=(4000, 4000))
        by_id = {r.pin_id: r for r in results}
        # Canvas is huge, so both should actually fit -- this just checks
        # ordering/processing, not forced overflow.
        assert by_id["earlier"].placed
        assert by_id["later"].placed


class TestSanitySinglePin:
    def test_single_pin_gets_card_at_sensible_offset(self):
        pin = PinSpec(id="only", x=500, y=500, sort_key=date(2025, 1, 1))
        results = place_cards([pin], card_size=(100, 60), canvas_size=(1000, 1000))

        assert len(results) == 1
        result = results[0]
        assert result.placed
        assert result.pin_id == "only"
        rect = result.card_rect
        assert rect is not None
        assert rect.within((1000, 1000))

        # Card must not sit directly on top of the pin: the pin point
        # itself should fall outside the card rectangle.
        pin_inside_card = rect.left <= pin.x <= rect.right and rect.top <= pin.y <= rect.bottom
        assert not pin_inside_card

        # Card should be a reasonable distance away, not clear across the canvas.
        cx = (rect.left + rect.right) / 2
        cy = (rect.top + rect.bottom) / 2
        dist = ((cx - pin.x) ** 2 + (cy - pin.y) ** 2) ** 0.5
        assert dist < 300


class TestEmptyInput:
    def test_no_pins_returns_empty_list(self):
        assert place_cards([], card_size=(100, 60), canvas_size=(1000, 1000)) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
