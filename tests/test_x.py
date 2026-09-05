"""Specs for facechain.search.platforms.x — parsing the public syndication payloads (no network)."""
# ruff: noqa: E501

from __future__ import annotations

from facechain.search.platforms.x import (
    Tweet,
    parse_timeline_html,
    parse_tweet_result,
    tweet_id_from_url,
    tweets_to_candidates,
)

TIMELINE_HTML = (
    '<html><body><script id="__NEXT_DATA__" type="application/json">'
    + """{"props":{"pageProps":{"timeline":{"entries":[
      {"type":"tweet","entry_id":"tweet-1","content":{"tweet":{"id_str":"1001","full_text":"Siuuu 🏆 https://t.co/x",
        "created_at":"Fri Sep 05 10:00:00 +0000 2026","user":{"screen_name":"Cristiano","name":"Cristiano Ronaldo"},
        "entities":{"media":[{"type":"photo","media_url_https":"https://pbs.twimg.com/media/AAA.jpg"}]},
        "permalink":"/Cristiano/status/1001"}}},
      {"type":"tweet","entry_id":"tweet-2","content":{"tweet":{"id_str":"1002","full_text":"text only",
        "created_at":"Fri Sep 05 09:00:00 +0000 2026","user":{"screen_name":"Cristiano"},"entities":{}}}},
      {"type":"tweet","entry_id":"tweet-3","content":{"tweet":{"id_str":"1003","full_text":"video",
        "created_at":"Fri Sep 05 08:00:00 +0000 2026","user":{"screen_name":"Cristiano"},
        "entities":{"media":[{"type":"video","media_url_https":"https://pbs.twimg.com/ext_tw_video_thumb/BBB.jpg"}]}}}}
    ]}}}}"""
    + "</script></body></html>"
)

TWEET_RESULT = {
    "id_str": "1001",
    "text": "Siuuu 🏆",
    "created_at": "2026-09-05T10:00:00.000Z",
    "user": {"screen_name": "Cristiano", "name": "Cristiano Ronaldo"},
    "mediaDetails": [
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/AAA.jpg"},
        {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/AAB.jpg"},
    ],
}


def test_parse_timeline_keeps_only_tweets_with_media_in_order() -> None:
    tweets = parse_timeline_html(TIMELINE_HTML)
    assert [t.id for t in tweets] == ["1001", "1003"]
    first = tweets[0]
    assert first == Tweet(
        id="1001",
        url="https://x.com/Cristiano/status/1001",
        author="@Cristiano",
        text="Siuuu 🏆 https://t.co/x",
        media_urls=("https://pbs.twimg.com/media/AAA.jpg",),
        created_at="Fri Sep 05 10:00:00 +0000 2026",
    )


def test_parse_timeline_without_next_data_returns_empty() -> None:
    assert parse_timeline_html("Rate limit exceeded") == []
    assert parse_timeline_html('<html><script id="__NEXT_DATA__">not json</script>') == []


def test_parse_tweet_result_collects_all_photos() -> None:
    tweet = parse_tweet_result(TWEET_RESULT, handle_hint="Cristiano")
    assert tweet is not None
    assert tweet.url == "https://x.com/Cristiano/status/1001"
    assert tweet.media_urls == (
        "https://pbs.twimg.com/media/AAA.jpg",
        "https://pbs.twimg.com/media/AAB.jpg",
    )
    assert tweet.text == "Siuuu 🏆"
    assert parse_tweet_result({"error": "not found"}, handle_hint="x") is None


def test_tweet_id_from_url() -> None:
    assert tweet_id_from_url("https://x.com/Cristiano/status/1001") == "1001"
    assert tweet_id_from_url("https://twitter.com/a/status/55/photo/1") == "55"
    assert tweet_id_from_url("https://x.com/Cristiano") is None


def test_tweets_to_candidates_sets_engine_author_text_and_first_photo() -> None:
    tweets = parse_timeline_html(TIMELINE_HTML)
    cands = tweets_to_candidates(tweets, engine="identity:x")
    assert [c.url for c in cands] == [
        "https://x.com/Cristiano/status/1001",
        "https://x.com/Cristiano/status/1003",
    ]
    assert cands[0].engine == "identity:x" and cands[0].engine_rank == 1
    assert cands[0].author == "@Cristiano" and cands[0].platform == "x" and cands[0].is_post
    assert cands[0].text == "Siuuu 🏆 https://t.co/x"
    assert cands[0].media_url == "https://pbs.twimg.com/media/AAA.jpg"
