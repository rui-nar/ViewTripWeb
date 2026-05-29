"""Tests for memory comment tree builder and related helpers."""

import pytest

from api.memories import _build_comment_tree, _utc_now
from models.project_db import DBMemoryComment


def _make_row(id, memory_id, parent_id, name, text):
    row = DBMemoryComment(
        id=id,
        memory_id=memory_id,
        parent_comment_id=parent_id,
        user_info_id=1,
        commenter_name=name,
        text=text,
        created_at="2026-05-29T10:00:00Z",
    )
    return row


class TestBuildCommentTree:
    def test_empty_returns_empty_list(self):
        assert _build_comment_tree([]) == []

    def test_single_root_comment(self):
        rows = [_make_row(1, 10, None, "Alice", "Hello")]
        tree = _build_comment_tree(rows)
        assert len(tree) == 1
        assert tree[0]["id"] == 1
        assert tree[0]["commenter_name"] == "Alice"
        assert tree[0]["text"] == "Hello"
        assert tree[0]["replies"] == []

    def test_one_level_reply(self):
        rows = [
            _make_row(1, 10, None, "Alice", "Root"),
            _make_row(2, 10, 1,    "Bob",   "Reply"),
        ]
        tree = _build_comment_tree(rows)
        assert len(tree) == 1
        assert len(tree[0]["replies"]) == 1
        assert tree[0]["replies"][0]["commenter_name"] == "Bob"

    def test_deeply_nested_replies(self):
        rows = [
            _make_row(1, 10, None, "Alice", "L0"),
            _make_row(2, 10, 1,    "Bob",   "L1"),
            _make_row(3, 10, 2,    "Carol", "L2"),
            _make_row(4, 10, 3,    "Dan",   "L3"),
        ]
        tree = _build_comment_tree(rows)
        assert len(tree) == 1
        l1 = tree[0]["replies"]
        assert len(l1) == 1
        l2 = l1[0]["replies"]
        assert len(l2) == 1
        l3 = l2[0]["replies"]
        assert len(l3) == 1
        assert l3[0]["commenter_name"] == "Dan"

    def test_multiple_root_comments(self):
        rows = [
            _make_row(1, 10, None, "Alice", "First"),
            _make_row(2, 10, None, "Bob",   "Second"),
        ]
        tree = _build_comment_tree(rows)
        assert len(tree) == 2

    def test_multiple_replies_on_one_root(self):
        rows = [
            _make_row(1, 10, None, "Alice", "Root"),
            _make_row(2, 10, 1,    "Bob",   "Reply A"),
            _make_row(3, 10, 1,    "Carol", "Reply B"),
        ]
        tree = _build_comment_tree(rows)
        assert len(tree) == 1
        assert len(tree[0]["replies"]) == 2

    def test_orphan_parent_falls_back_to_root(self):
        """A reply whose parent doesn't exist in the batch is treated as root."""
        rows = [_make_row(5, 10, 99, "Eve", "Orphan")]
        tree = _build_comment_tree(rows)
        assert len(tree) == 1

    def test_comment_includes_user_info_id(self):
        rows = [_make_row(1, 10, None, "Alice", "Hello")]
        tree = _build_comment_tree(rows)
        assert tree[0]["user_info_id"] == 1

    def test_comment_includes_created_at(self):
        rows = [_make_row(1, 10, None, "Alice", "Hello")]
        tree = _build_comment_tree(rows)
        assert tree[0]["created_at"] == "2026-05-29T10:00:00Z"


class TestUtcNow:
    def test_format_is_iso_utc(self):
        ts = _utc_now()
        assert ts.endswith("Z"), f"Expected UTC 'Z' suffix, got: {ts}"
        assert len(ts) == 20  # "YYYY-MM-DDTHH:MM:SSZ"

    def test_is_parseable(self):
        from datetime import datetime
        ts = _utc_now()
        dt = datetime.fromisoformat(ts.rstrip("Z"))
        assert dt.year >= 2026
