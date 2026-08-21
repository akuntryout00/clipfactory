from app.config.loaders import load_persona, load_template
from app.llm import prompts
from app.schemas.pipeline import NormalizedScene


def test_script_prompt_carries_persona_template_topic_and_budget():
    p = load_persona("young_professional")
    t = load_template("list_v1")
    txt = prompts.script_user_prompt(p, t, "3 habits that waste your time", 18, 40, 52)
    assert "3 habits that waste your time" in txt and "40-52 words" in txt
    assert "item_1" in txt and "US professionals" in txt and "fake personal stories" in txt


def test_rank_prompt_lists_candidates_per_scene():
    sc = [NormalizedScene(order=1, section="hook", start=0, end=2, first_word=0, last_word=3, intent="typing", query_tags=["typing"])]
    txt = prompts.rank_user_prompt(
        "t",
        sc,
        {
            1: [
                {
                    "asset_id": "asset_001",
                    "description": "typing",
                    "action": "typing",
                    "location": "cafe",
                    "shot": "close",
                    "duration": 9,
                    "score": 0.8,
                }
            ]
        },
    )
    assert "SCENE 1" in txt and "asset_001" in txt
