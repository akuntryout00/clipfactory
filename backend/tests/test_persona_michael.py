from app.config.loaders import load_persona, load_template
from app.llm import prompts


def test_michael_persona_loads_with_identity_tools_products():
    p = load_persona("michael")
    assert p.identity.name == "Michael" and p.identity.age == 35 and "US" in p.identity.location
    assert "Claude Code" in " ".join(p.tools)
    assert p.products == [] and p.product_mention_policy == "never"
    assert p.closing_style == "punchline_no_cta"
    assert "life hacks" in " ".join(p.topics).lower()


def test_persona_block_carries_identity_tools_policy_and_closing():
    p = load_persona("michael")
    txt = prompts.persona_block(p)
    assert "Michael" in txt and "35" in txt and "CTO" in txt and "first person" in txt.lower()
    assert "Claude Code" in txt and "Notion" in txt
    assert "Never mention the creator's own products" in txt
    assert "punchline" in txt.lower() and "no call to action" in txt.lower()
    assert "energetic" in txt.lower()


def test_script_prompt_uses_persona_block_for_michael():
    p = load_persona("michael")
    t = load_template("story_v1")
    txt = prompts.script_user_prompt(p, t, "Why I stopped taking notes by hand", 18, 40, 50)
    assert "solopreneur" in txt.lower()


def test_generic_persona_still_works_without_identity():
    p = load_persona("young_professional")
    txt = prompts.persona_block(p)
    assert "PERSONA" in txt


def test_template_closing_overrides_persona_closing_in_script_prompt():
    p = load_persona("michael")
    for tid, needle in (("story_v1", "punchline"), ("list_v1", "question"), ("pov_v1", "sarcastic"), ("problem_solution_v1", "invite")):
        t = load_template(tid)
        assert t.closing, tid
        txt = prompts.script_user_prompt(p, t, "topic", 18, 40, 50)
        assert "CLOSING" in txt and needle in txt.lower(), (tid, txt[-400:])
