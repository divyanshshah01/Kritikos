import csv
import json

from app.services.oasis_profile_generator import (
    OasisAgentProfile,
    OasisProfileGenerator,
    _coerce_to_str,
    _coerce_to_str_list,
)


def test_text_coercion_handles_none_nested_objects_and_lists():
    assert _coerce_to_str(None) == ""
    assert _coerce_to_str({"text": {"value": "in 文"}}) == "in 文"
    assert _coerce_to_str([None, {"description": "alpha"}, ["beta"]]) == "alpha, beta"
    assert _coerce_to_str({"unexpected": None}) == '{"unexpected": null}'


def test_list_coercion_flattens_nested_values_and_drops_missing_items():
    assert _coerce_to_str_list(
        ["AI", ["policy", None], {"name": "society"}, 4]
    ) == ["AI", "policy", "society", "4"]
    assert _coerce_to_str_list(None) == []


def test_profile_construction_is_the_single_normalization_boundary():
    profile = OasisAgentProfile(
        user_id=1,
        user_name="agent",
        name="Agent Name",
        bio=None,
        persona={"text": {"value": "详细Character profile"}},
        gender=["female"],
        mbti={"value": "INTJ"},
        country={"name": "in 国"},
        profession={"description": "研究员"},
        interested_topics=["AI", ["Politics策", None], {"name": "社会"}],
    )

    assert profile.bio == "Agent Name"
    assert profile.persona == "详细Character profile"
    assert profile.gender == "female"
    assert profile.mbti == "INTJ"
    assert profile.country == "in 国"
    assert profile.profession == "研究员"
    assert profile.interested_topics == ["AI", "Politics策", "社会"]
    assert "None" not in json.dumps(profile.to_dict(), ensure_ascii=False)


def test_normalized_profile_serializes_to_twitter_and_reddit(tmp_path):
    profile = OasisAgentProfile(
        user_id=1,
        user_name="agent",
        name="Agent Name",
        bio={"summary": "公开简Introduce"},
        persona=["详细", "Character profile"],
        mbti={"text": "ENFP"},
        interested_topics=["AI", ["Politics策"]],
    )
    generator = object.__new__(OasisProfileGenerator)
    twitter_path = tmp_path / "twitter_profiles.csv"
    reddit_path = tmp_path / "reddit_profiles.json"

    generator._save_twitter_csv([profile], str(twitter_path))
    generator._save_reddit_json([profile], str(reddit_path))

    with twitter_path.open(encoding="utf-8") as handle:
        twitter = next(csv.DictReader(handle))
    reddit = json.loads(reddit_path.read_text(encoding="utf-8"))[0]

    assert twitter["description"] == "公开简Introduce"
    assert twitter["user_char"] == "公开简Introduce 详细, Character profile"
    assert reddit["bio"] == "公开简Introduce"
    assert reddit["persona"] == "详细, Character profile"
    assert reddit["mbti"] == "ENFP"
    assert reddit["interested_topics"] == ["AI", "Politics策"]
