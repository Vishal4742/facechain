"""Specs for facechain.search.filters — written before the implementation."""

from __future__ import annotations

import pytest

from facechain.search.filters import canonical_url, is_post_url, platform_of


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.instagram.com/p/Cabc123/", "instagram"),
        ("https://x.com/imVkohli/status/1234567890", "x"),
        ("https://twitter.com/imVkohli/status/1234567890", "x"),
        ("https://mobile.twitter.com/imVkohli/status/1234567890", "x"),
        ("https://m.facebook.com/virat.kohli/posts/1", "facebook"),
        ("https://www.tiktok.com/@user/video/72000", "tiktok"),
        ("https://www.threads.net/@user/post/Cxyz", "threads"),
        ("https://www.threads.com/@user/post/Cxyz", "threads"),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
        ("https://in.linkedin.com/posts/someone_activity-1", "linkedin"),
        ("https://in.pinterest.com/pin/123456/", "pinterest"),
        ("https://www.espncricinfo.com/story/1", None),
        ("not a url", None),
    ],
)
def test_platform_of(url: str, platform: str | None) -> None:
    assert platform_of(url) == platform


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.instagram.com/p/Cabc123/", True),
        ("https://www.instagram.com/reel/Cabc123/", True),
        ("https://www.instagram.com/virat.kohli/", False),
        ("https://x.com/imVkohli/status/1234567890", True),
        ("https://x.com/imVkohli", False),
        ("https://www.tiktok.com/@user/video/72000", True),
        ("https://www.tiktok.com/@user", False),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", True),
        ("https://youtu.be/dQw4w9WgXcQ", True),
        ("https://www.youtube.com/@channel", False),
        ("https://www.facebook.com/virat.kohli/posts/123", True),
        ("https://www.facebook.com/photo/?fbid=123", True),
        ("https://www.facebook.com/virat.kohli/", False),
        ("https://www.threads.net/@user/post/Cxyz", True),
        ("https://in.pinterest.com/pin/123456/", True),
        ("https://in.linkedin.com/posts/someone_activity-1", True),
        ("https://www.espncricinfo.com/story/1", False),
    ],
)
def test_is_post_url(url: str, expected: bool) -> None:
    assert is_post_url(url) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://twitter.com/imVkohli/status/123/photo/1?s=20&t=abc",
            "https://x.com/imVkohli/status/123",
        ),
        ("https://mobile.twitter.com/imVkohli/status/123/", "https://x.com/imVkohli/status/123"),
        (
            "HTTPS://WWW.Instagram.com/p/Cabc123/?igsh=xyz#frag",
            "https://www.instagram.com/p/Cabc123",
        ),
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        (
            "https://www.facebook.com/photo/?fbid=123&set=a.1",
            "https://www.facebook.com/photo?fbid=123",
        ),
        ("https://example.com/a/b/", "https://example.com/a/b"),
    ],
)
def test_canonical_url(url: str, expected: str) -> None:
    assert canonical_url(url) == expected
