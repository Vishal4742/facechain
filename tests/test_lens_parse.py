"""Specs for parsing a SerpApi Google Lens response into candidates and identity hints."""

from __future__ import annotations

from facechain.search.base import Hint
from facechain.search.lens import parse_lens_response

FIXTURE = {
    "search_metadata": {
        "id": "68ba7c1f2e9d4a6b8c0f1a2b",
        "status": "Success",
        "created_at": "2026-09-05 09:12:33 UTC",
    },
    "visual_matches": [
        {
            "position": 1,
            "title": 'Virat Kohli on Instagram: "Test day"',
            "link": "https://www.instagram.com/p/Cabc123/",
            "source": "Instagram",
            "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:thumb1",
            "image": "https://scontent.cdninstagram.com/v/t51/full1.jpg",
        },
        {
            "position": 2,
            "title": "Kohli scores again | ESPNcricinfo",
            "link": "https://www.espncricinfo.com/story/1",
            "source": "ESPNcricinfo",
            "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:thumb2",
        },
        {
            "position": 3,
            "title": "Virat Kohli (@imVkohli) on X",
            "link": "https://twitter.com/imVkohli/status/1234567890/photo/1",
            "source": "X",
            "thumbnail": "https://encrypted-tbn0.gstatic.com/images?q=tbn:thumb3",
        },
        {"position": 4, "title": "broken entry without link"},
    ],
    "related_content": [
        {
            "query": "Virat Kohli",
            "kgmid": "/m/0f1jm3",
            "link": "https://www.google.com/search?q=...",
        },
        {"query": "cricketer", "link": "https://www.google.com/search?q=cricketer"},
    ],
}


def test_parses_candidates_with_platform_engine_rank_and_media_preference() -> None:
    cands, hints = parse_lens_response(FIXTURE, engine="lens:visual")
    assert [c.engine_rank for c in cands] == [1, 2, 3]  # entry without link is dropped
    assert all(c.engine == "lens:visual" for c in cands)
    assert cands[0].platform == "instagram"
    assert (
        cands[0].media_url == "https://scontent.cdninstagram.com/v/t51/full1.jpg"
    )  # image > thumbnail
    assert cands[0].thumbnail_url == "https://encrypted-tbn0.gstatic.com/images?q=tbn:thumb1"
    assert cands[1].platform is None
    assert cands[2].platform == "x"
    assert cands[2].url == "https://x.com/imVkohli/status/1234567890"  # canonicalised
    assert cands[2].media_url == "https://encrypted-tbn0.gstatic.com/images?q=tbn:thumb3"
    assert (cands[0].title or "").startswith("Virat Kohli on Instagram")


def test_identity_hints_take_kgmid_from_field_or_link_and_keep_name_only_hints() -> None:
    _, hints = parse_lens_response(FIXTURE, engine="lens:visual")
    assert hints == [
        Hint(query="Virat Kohli", kgmid="/m/0f1jm3"),
        Hint(query="cricketer", kgmid=None),
    ]
    data = {
        "related_content": [
            {
                "query": "Lewis Hamilton",
                "link": "https://www.google.com/search?hl=en&q=Lewis+Hamilton&kgmid=/m/031_jy&sa=X",
            }
        ]
    }
    assert parse_lens_response(data, engine="lens:visual")[1] == [
        Hint(query="Lewis Hamilton", kgmid="/m/031_jy")
    ]


def test_exact_matches_are_parsed_with_their_own_engine_tag() -> None:
    data = {
        "exact_matches": [
            {
                "position": 1,
                "title": "same image on X",
                "link": "https://x.com/u/status/1",
                "source": "X",
                "thumbnail": "https://t/1.jpg",
                "date": "2 days ago",
            }
        ]
    }
    cands, hints = parse_lens_response(data, engine="lens:exact")
    assert len(cands) == 1 and cands[0].engine == "lens:exact" and hints == []


def test_empty_or_error_response_yields_nothing() -> None:
    assert parse_lens_response({}, engine="lens:visual") == ([], [])
    assert parse_lens_response(
        {"error": "Google hasn't returned any results"}, engine="lens:visual"
    ) == ([], [])
