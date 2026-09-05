"""Specs for the acceptance rule in facechain.search.rank — written before the implementation.

Rule: the winner is the best-scoring social POST url in the match band, and it is accepted only
when corroborated: >= 2 distinct candidates at or above the corroboration threshold, or an
explicit corroboration signal on the winner (identity hop / engine agreement).
"""

from __future__ import annotations

from dataclasses import replace

from facechain.search.base import Candidate
from facechain.search.rank import accept, corroborate

MATCH, REVIEW, CORROB = 0.45, 0.35, 0.40


def _cand(url: str, sim: float | None, *, engine: str = "lens:visual", rank: int = 1) -> Candidate:
    return Candidate.from_url(url, engine=engine, engine_rank=rank).with_similarity(
        sim, match_thr=MATCH, review_thr=REVIEW
    )


def test_band_is_derived_from_similarity_bps() -> None:
    assert _cand("https://x.com/u/status/1", 0.71).similarity_bps == 7100
    assert _cand("https://x.com/u/status/1", 0.71).band == "match"
    assert _cand("https://x.com/u/status/1", 0.40).band == "review"
    assert _cand("https://x.com/u/status/1", 0.10).band == "reject"
    assert _cand("https://x.com/u/status/1", None).band == "no face"


def test_accept_with_two_candidates_above_corroboration_threshold() -> None:
    cands = [
        _cand("https://www.instagram.com/p/A/", 0.71),
        _cand("https://www.espncricinfo.com/story/1", 0.52),  # non-social still corroborates
        _cand("https://x.com/u/status/9", 0.20),
    ]
    decision = accept(cands, match_thr=MATCH, corroborate_thr=CORROB)
    assert decision.winner is not None
    assert decision.winner.url == "https://www.instagram.com/p/A"
    assert decision.accepted is True
    assert "2 candidates >= 0.40" in decision.reason


def test_single_uncorroborated_match_is_review_not_accepted() -> None:
    cands = [_cand("https://www.instagram.com/p/A/", 0.71), _cand("https://x.com/u/status/9", 0.20)]
    decision = accept(cands, match_thr=MATCH, corroborate_thr=CORROB)
    assert decision.winner is not None
    assert decision.accepted is False
    assert "no corroboration" in decision.reason


def test_explicit_corroboration_signal_accepts_a_lone_match() -> None:
    lone = replace(
        _cand("https://x.com/imVkohli/status/1", 0.66), corroborated_by=("identity:@imVkohli",)
    )
    decision = accept([lone], match_thr=MATCH, corroborate_thr=CORROB)
    assert decision.accepted is True
    assert "identity:@imVkohli" in decision.reason


def test_profile_urls_never_win_even_when_they_score_highest() -> None:
    cands = [
        _cand("https://www.instagram.com/virat.kohli/", 0.80),  # profile, not a post
        _cand("https://www.instagram.com/p/B/", 0.50),
    ]
    decision = accept(cands, match_thr=MATCH, corroborate_thr=CORROB)
    assert decision.winner is not None and decision.winner.url == "https://www.instagram.com/p/B"
    assert decision.accepted is True  # the profile still counts as corroboration


def test_no_winner_when_nothing_reaches_match_threshold() -> None:
    cands = [_cand("https://www.instagram.com/p/A/", 0.30), _cand("https://x.com/u/status/9", 0.41)]
    decision = accept(cands, match_thr=MATCH, corroborate_thr=CORROB)
    assert decision.winner is None and decision.accepted is False
    assert "0.41 < 0.45" in decision.reason


def test_corroborate_marks_agreement_between_engines_on_same_url_or_author() -> None:
    a = _cand("https://x.com/imVkohli/status/1", 0.6, engine="lens:visual")
    b = _cand("https://x.com/imVkohli/status/2", 0.5, engine="identity:x")
    c = _cand("https://www.instagram.com/p/Z/", 0.5, engine="lens:visual")
    out = corroborate([a, b, c])
    assert (
        "engine:identity:x" in out[0].corroborated_by
    )  # same author @imVkohli from another engine
    assert "engine:lens:visual" in out[1].corroborated_by
    assert out[2].corroborated_by == ()
