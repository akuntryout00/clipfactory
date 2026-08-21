"""Prompt builders — kept separate so they can be tuned without touching provider code."""
from __future__ import annotations

import json

from app.schemas.configs import PersonaConfig, TemplateConfig
from app.schemas.pipeline import NormalizedScene, ScriptOutput, WordTiming


_CLOSING = {
    "punchline_no_cta": "End on a single punchline. No call to action, no 'follow/like/comment'.",
    "question": "End with one short question to the viewer. No 'follow/like'.",
    "soft_follow": "End on a punchline; at most a very light 'more of this tomorrow' style invite, never 'like and subscribe'.",
}
_PRODUCT_POLICY = {
    "never": "Never mention the creator's own products.",
    "occasional_soft": "You MAY mention one of the creator's products only when the topic is directly about that problem, at most once, "
                       "phrased casually ('I built a small tool for this called X'), never as a pitch. Use only the name and the "
                       "one-liner given — never invent features, prices or results. Most videos should mention no product at all.",
    "problem_solution_only": "Mention a product only in problem/solution templates as the solution, casually, name + one-liner only; "
                             "never invent features.",
}


def persona_block(p: PersonaConfig) -> str:
    lines = [f"PERSONA: {p.name}"]
    if p.identity:
        i = p.identity
        who = f"You ARE {i.name}"
        if i.age:
            who += f", {i.age}"
        if i.location:
            who += f", {i.location}"
        if i.background:
            who += f" — {i.background}"
        lines.append(who + ".")
        lines.append(f"Speak as this person in {i.speaks_as}. Only claim experiences consistent with this background; no invented anecdotes with specifics you weren't given.")
    lines += [
        f"Audience: {p.audience}",
        f"Language: {p.language}",
        f"Tone: {', '.join(p.tone)}",
        f"Content pillars: {'; '.join(p.topics)}",
        f"Never: {', '.join(p.avoid)}",
    ]
    if p.tools:
        lines.append("Tools this person really uses (reference only these when naming tools): " + "; ".join(p.tools))
    if p.products and p.product_mention_policy != "never":
        prods = "; ".join(f"{x.name} — {x.one_liner}" if x.one_liner else x.name for x in p.products)
        lines.append(f"Own products: {prods}. {_PRODUCT_POLICY[p.product_mention_policy]}")
    else:
        lines.append(_PRODUCT_POLICY["never"])
    lines.append("Default closing (used only if the template does not define its own): " + _CLOSING.get(p.closing_style, _CLOSING["punchline_no_cta"]))
    return "\n".join(lines) + "\n"


def template_block(t: TemplateConfig) -> str:
    secs = "\n".join(f"  - {s.type} (~{int(s.weight * 100)}% of runtime): {s.guidance}" for s in t.sections)
    return f"TEMPLATE: {t.name} ({t.id}) — {t.description}\nSections, in order:\n{secs}\n"


SCRIPT_SYSTEM = (
    "You write spoken-word scripts for short vertical TikTok videos that are narrated over real B-roll footage. "
    "You never produce video; you produce a script. Rules:\n"
    "- The first section is the HOOK: a pattern interrupt delivered in the first 1-2 seconds. No 'hey guys', no intro.\n"
    "- Conversational, spoken English. Short sentences. Contractions are fine.\n"
    "- Every section text must be plain spoken prose (no emojis, no hashtags, no stage directions, no markdown).\n"
    "- Do NOT invent personal anecdotes or statistics you cannot verify. No hard selling, no corporate speak, max one soft CTA.\n"
    "- Respect the word budget precisely: that is what controls the video length.\n"
    "- Return exactly one text entry per template section, in template order, using the section type names given."
)


def script_user_prompt(persona: PersonaConfig, template: TemplateConfig, topic: str, target_duration: float, lo: int, hi: int) -> str:
    return (
        f"{persona_block(persona)}\n{template_block(template)}\n"
        f"TOPIC: {topic}\n"
        f"TARGET DURATION: {target_duration:.0f} seconds → write {lo}-{hi} words in total across all sections.\n"
        f"CLOSING (this template): {template.closing or _CLOSING.get(persona.closing_style, _CLOSING['punchline_no_cta'])}\n"
        "Write the script now."
    )


def shorten_user_prompt(persona: PersonaConfig, template: TemplateConfig, script: ScriptOutput, target_words: int, reason: str) -> str:
    return (
        f"{persona_block(persona)}\n{template_block(template)}\n"
        f"The following script is too long ({reason}). Rewrite it to at most {target_words} words total while keeping the same "
        "hook idea, the same section structure and the same meaning. Cut filler first, then merge sentences.\n\n"
        f"CURRENT SCRIPT (json):\n{json.dumps(script.model_dump(), ensure_ascii=False)}"
    )


PLAN_SYSTEM = (
    "You are a short-form video editor planning B-roll shots for a narrated TikTok. You receive the spoken words with their "
    "indices and timestamps (seconds). Cut the video into scenes by choosing inclusive word-index ranges. Rules:\n"
    "- Scene boundaries must fall on sentence or clause changes, or when the visual concept changes — never arbitrary.\n"
    "- Scenes must cover every word exactly once, in order, with no gaps (first_word of scene n+1 = last_word of scene n + 1).\n"
    "- Aim for shots of 1.5-4 seconds (use the timestamps), total 4-8 scenes. The hook is its own short scene.\n"
    "- For each scene give `intent`: what the viewer should SEE (concrete, filmable with everyday B-roll: laptop, phone, walking, "
    "coffee, desk, reactions). Not the words. And `query_tags`: 3-6 lowercase search tags from this vocabulary where possible: "
    "typing, laptop, desk, phone, scrolling, walking, street, cafe, coffee, stressed, frustrated, airpods, call, screen, ai, "
    "notebook, product, reaction, close, wide.\n"
    "- `overlay_text`: a big on-screen creative text (max 4 words, punchy, may be ALL CAPS) for only 1-3 scenes per video — "
    "the hook and the key payoff/items. null for the rest. For list templates, each item scene gets an overlay like '1. NAME'.\n"
    "Output JSON only."
)


def plan_user_prompt(persona: PersonaConfig, template: TemplateConfig, topic: str, script: ScriptOutput,
                     words: list[WordTiming], voice_duration: float, section_ranges: dict[str, tuple[int, int]],
                     library: str | None = None) -> str:
    listing = "\n".join(f"{i}: {w.word} [{w.start:.2f}-{w.end:.2f}]" for i, w in enumerate(words))
    secs = "\n".join(f"  - {k}: words {a}-{b}" for k, (a, b) in section_ranges.items())
    lib = f"\nAVAILABLE B-ROLL (plan only what this library can show; reference asset_ids in `intent` when one fits):\n{library}\n" if library else ""
    return (
        f"{template_block(template)}\nTOPIC: {topic}\nVOICE DURATION: {voice_duration:.2f} s\n{lib}"
        f"SHOT LENGTH: {template.shot_duration.min}-{template.shot_duration.max} s; overlays allowed: {int(template.overlays.min)}-{int(template.overlays.max)}\n"
        f"SECTION → WORD RANGES:\n{secs}\n\nWORDS:\n{listing}\n\nPlan the scenes."
    )


RANK_SYSTEM = (
    "You pick the best real B-roll clip for each scene of a narrated TikTok from a shortlist (for small libraries the shortlist is "
    "the whole library). Judge by the clip DESCRIPTION against the scene intent — the numeric score is only a weak prior. Rules:\n"
    "- Choose exactly one asset_id per scene, only from that scene's candidates.\n"
    "- Never use the same asset_id for two scenes.\n"
    "- Prefer visual match to the scene intent, then variety between consecutive scenes (alternate locations/shot sizes), "
    "then the provided score. Avoid two consecutive scenes with the same action.\n"
    "- Candidates marked recently_used=True were already used in another video today; avoid them unless they are clearly the "
    "only good match, so videos do not all look alike.\n"
    "Output JSON only."
)


def rank_user_prompt(topic: str, scenes: list[NormalizedScene], candidates: dict[int, list[dict]]) -> str:
    blocks = []
    for sc in scenes:
        cands = candidates.get(sc.order, [])
        c_lines = "\n".join(
            f"    - {c['asset_id']}: {c.get('description') or ''} | action={c.get('action')} location={c.get('location')} "
            f"shot={c.get('shot')} dur={c.get('duration')} score={c.get('score')} recently_used={c.get('recently_used')}" for c in cands)
        blocks.append(f"SCENE {sc.order} [{sc.start:.1f}-{sc.end:.1f}s] ({sc.section}) intent: {sc.intent}\n  candidates:\n{c_lines}")
    return f"TOPIC: {topic}\n\n" + "\n\n".join(blocks) + "\n\nChoose one asset per scene."


ENRICH_SYSTEM = (
    "You are tagging a B-roll library for a short-form video factory. For each clip you get a human-written description and any "
    "existing tags. Produce rich, literal, lowercase single-word search tags (6-12) covering: objects visible, the action, the "
    "place, the framing, the feeling, and what concepts the clip could illustrate in a productivity/career/AI video (e.g. "
    "'distraction', 'focus', 'overwhelm', 'commute', 'planning'). Also give action (snake_case), location, mood and shot. "
    "Never invent things not implied by the description. Output JSON only."
)


def enrich_user_prompt(assets: list[dict]) -> str:
    lines = [f"- {a['asset_id']} ({a['file']}): {a.get('description') or ''} | existing tags: {', '.join(a.get('tags') or [])} | "
             f"action={a.get('action')} location={a.get('location')} shot={a.get('shot')}" for a in assets]
    return "CLIPS:\n" + "\n".join(lines) + "\n\nReturn one entry per asset_id."


ANALYZE_SYSTEM = (
    "You are cataloguing B-roll for a short-form video factory. You see several frames sampled evenly from one vertical clip. "
    "Describe literally what is visible and happening (people, hands, devices, objects, place, framing, camera motion), then "
    "produce search metadata. Tags must be lowercase single words: objects, the action, the place, framing (close/medium/wide), "
    "the feeling, and 2-4 concepts the clip could illustrate in productivity/career/AI/lifestyle videos (e.g. focus, distraction, "
    "commute, planning, overwhelm). Do not invent things you cannot see. Output JSON only."
)


def analyze_user_prompt(filename: str, duration: float, categories: list[str], n_frames: int) -> str:
    cats = ", ".join(categories) if categories else "(none yet)"
    return (f"Clip file: {filename} · duration {duration:.1f}s · {n_frames} frames sampled in order.\n"
            f"Existing library categories (folders): {cats}. Pick the best one as suggested_category, or propose a short new one.\n"
            "Fill every field.")
