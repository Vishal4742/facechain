"""Specs for facechain.search.identity — pure parsing of Wikidata responses (no network)."""

from __future__ import annotations

from facechain.search.identity import Handles, Identity, parse_handles, pick_human_entity

SEARCH_RESPONSE = {
    "search": [
        {
            "id": "Q30936517",
            "label": "Cristiano Ronaldo: World at His Feet",
            "description": "2014 film",
        },
        {
            "id": "Q11571",
            "label": "Cristiano Ronaldo",
            "description": "Portuguese association football player (born 1985)",
        },
        {
            "id": "Q118125023",
            "label": "Cristiano Ronaldo Jr.",
            "description": "footballer (born 2010)",
        },
    ]
}

SPARQL_RESPONSE = {
    "results": {
        "bindings": [
            {
                "item": {"value": "http://www.wikidata.org/entity/Q11571"},
                "itemLabel": {"value": "Cristiano Ronaldo"},
                "human": {"value": "true"},
                "x": {"value": "Cristiano"},
                "ig": {"value": "cristiano"},
                "fb": {"value": "Cristiano"},
                "yt": {"value": "UCtxD0x6AuNNqdXO9Wp5GHew"},
            },
            {
                "item": {"value": "http://www.wikidata.org/entity/Q30936517"},
                "itemLabel": {"value": "Cristiano Ronaldo: World at His Feet"},
                "human": {"value": "false"},
            },
        ]
    }
}


def test_pick_human_entity_prefers_the_first_human_among_search_results() -> None:
    candidates = [e["id"] for e in SEARCH_RESPONSE["search"]]
    humans = {"Q11571": True, "Q30936517": False, "Q118125023": True}
    assert pick_human_entity(candidates, humans) == "Q11571"
    assert pick_human_entity(["Q30936517"], {"Q30936517": False}) is None


def test_parse_handles_maps_properties_and_tolerates_missing_ones() -> None:
    parsed = parse_handles(SPARQL_RESPONSE)
    assert parsed["Q11571"] == Identity(
        qid="Q11571",
        label="Cristiano Ronaldo",
        human=True,
        handles=Handles(
            x="Cristiano",
            instagram="cristiano",
            facebook="Cristiano",
            youtube="UCtxD0x6AuNNqdXO9Wp5GHew",
        ),
    )
    assert parsed["Q30936517"].human is False
    assert parsed["Q30936517"].handles == Handles()


def test_handles_exposes_author_tags_for_corroboration() -> None:
    ident = Identity(
        qid="Q1",
        label="Someone",
        human=True,
        handles=Handles(x="imVkohli", instagram="virat.kohli"),
    )
    assert ident.author_tags() == {"x": "@imVkohli", "instagram": "@virat.kohli"}


def test_name_matches_rejects_generic_hints_and_accepts_name_variants() -> None:
    from facechain.search.identity import name_matches

    assert name_matches("Cristiano Ronaldo", "Cristiano Ronaldo")
    assert name_matches("Virat Kohli", "virat Kohli")
    assert name_matches("Kohli", "Virat Kohli")
    assert not name_matches("cricketer", "Vaibhav Davne")
    assert not name_matches("", "Anyone")
