"""LLM-as-judge for the b2c-concierge conversational battery (S08).

Adapted from agent-usa `evals/judge.py`, with two deliberate departures:

1. **LiteLLM, not a raw SDK** (project invariant — see CLAUDE.md). agent-usa's
   judge instantiated an OpenAI client but called it with the Anthropic Messages
   shape (`client.messages.create`, `response.content[0].text`) — a latent
   runtime bug. Routing through `litellm.acompletion` makes the provider a
   config knob (`RELEASE_GATE_JUDGE_MODEL`) and removes that mismatch.
2. **Per-scenario behavioural rubric, not the 5 search-only dimensions.** The
   battery spans 8 families (faq / compare / booking / empty_dead …), not just
   hotel search, so a fixed geographic/price/timeslot rubric does not fit. Each
   scenario in `evalset/evalset-v0.json` already ships an `expected`
   natural-language description of the family's correct behaviour; the judge
   scores the assistant's answer against THAT, plus the universal Dayuse red
   flags (invented hotel/price/link, dead-end, wrong output language, repeating
   an already-asked question).

Determinism: temperature 0, structured JSON output, bounded LiteLLM retries.
The judge is an EVAL-TIME call — it never counts against the concierge's per-turn
LLM budget (that budget is measured from the concierge's own metric log).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import litellm
from b2c_common import DEFAULT_MODEL, max_tokens_kwargs_for, reasoning_kwargs_for, temperature_kwargs_for

# The judge model is a config knob (portability), overridable to a stronger
# judge without code changes. It does NOT follow DAYUSE_MODEL: that variable
# picks the stack under test, and a judge following it grades the stack with
# itself. Default = the shared code default (gpt-4o-mini shuts down 2027-01-14).
JUDGE_MODEL = os.environ.get("RELEASE_GATE_JUDGE_MODEL", "").strip() or DEFAULT_MODEL
JUDGE_TIMEOUT = float(os.environ.get("RELEASE_GATE_JUDGE_TIMEOUT_SECONDS", "30"))
JUDGE_NUM_RETRIES = int(os.environ.get("RELEASE_GATE_JUDGE_NUM_RETRIES", "2"))


@dataclass
class Judgment:
    """The verdict on one scenario."""

    scenario_id: str
    family: str
    verdict: str  # "pass" | "fail" | "error"
    score: float  # 1..5 (0.0 on error)
    reasoning: str
    red_flags: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "family": self.family,
            "verdict": self.verdict,
            "score": round(self.score, 2),
            "reasoning": self.reasoning,
            "red_flags": self.red_flags,
        }


_JUDGE_SYSTEM = """You are a strict but fair evaluator for the Dayuse b2c-concierge,
the conversational assistant of dayuse.com (day-use hotel booking). You grade one
completed conversation against the EXPECTED behaviour for its scenario family.

You are given: the family, the user's turns in order, the assistant's final reply
(and earlier replies for context), and an EXPECTED description of what a correct
assistant does for this family.

Judge whether the assistant's behaviour MATCHES the EXPECTED description. Be
lenient about wording and tone — grade the substance, not the phrasing. An honest
"I couldn't reach the search right now / no availability" degradation is
ACCEPTABLE only when the family expects an empty or dead-end outcome; for a family
that expects results or a useful answer, a generic failure/degradation message is
a FAIL.

UNIVERSAL RED FLAGS (each one, if present, should lower the score and usually make
the verdict "fail"):
- Invents a hotel, price, availability, date, policy, or booking link not grounded
  in what was retrieved.
- Produces a dead-end (gives up / loops on the same clarifying question) when the
  family expects recovery or a concrete next step.
- Claims to have booked, cancelled, refunded, or modified anything.
- Replies in the wrong language (must match the user's language).
- Emits a booking link WITHOUT an explicit user confirmation (R9 safety).

Respond with ONLY raw JSON (no markdown, no code fence), exactly:
{"verdict": "pass" | "fail", "score": <integer 1-5>, "reasoning": "<one or two sentences>", "red_flags": ["<short>", ...]}

Scoring anchors: 5 = fully meets EXPECTED, no red flags; 4 = meets it with a minor
gap; 3 = partially meets it; 2 = largely misses it; 1 = wrong or a red flag fired.
Use verdict "pass" for score >= 4, "fail" otherwise."""


def _build_user_prompt(
    *, family: str, lang: str, user_turns: list[str], answers: list[str], expected: str
) -> str:
    turns_block = "\n".join(f"  [user t{i}] {t}" for i, t in enumerate(user_turns))
    prior = answers[:-1]
    final = answers[-1] if answers else ""
    prior_block = (
        "\n".join(f"  [assistant t{i}] {a}" for i, a in enumerate(prior))
        if prior
        else "  (none)"
    )
    return (
        f"FAMILY: {family}\n"
        f"USER LANGUAGE: {lang}\n\n"
        f"USER TURNS:\n{turns_block}\n\n"
        f"ASSISTANT EARLIER REPLIES (context):\n{prior_block}\n\n"
        f"ASSISTANT FINAL REPLY (the one to grade):\n<<<\n{final}\n>>>\n\n"
        f"EXPECTED behaviour for this family:\n<<<\n{expected}\n>>>"
    )


def _extract_json(text: str) -> dict:
    """Tolerant JSON extraction: strip an optional ```json fence, else grab the
    first {...} block. Raises json.JSONDecodeError if nothing parses."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        return json.loads(brace.group(0))
    return json.loads(text)  # let it raise with the raw text


class LLMJudge:
    """Grades scenarios via one bounded LiteLLM call each (temperature 0)."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or JUDGE_MODEL

    async def evaluate(
        self,
        *,
        scenario_id: str,
        family: str,
        lang: str,
        user_turns: list[str],
        answers: list[str],
        expected: str,
    ) -> Judgment:
        """One judged scenario. Never raises: a judge failure returns an
        `error` verdict (score 0) so the battery keeps going and the gate sees
        the miss instead of crashing."""
        if not answers or not any(a.strip() for a in answers):
            return Judgment(
                scenario_id, family, "fail", 1.0,
                "Assistant produced no answer.", ["empty answer"],
            )
        user = _build_user_prompt(
            family=family, lang=lang, user_turns=user_turns, answers=answers, expected=expected
        )
        # Same provider-aware params as the stack's own calls (llm_params): on
        # gpt-6* a bare temperature + the provider's default effort is a 400,
        # which this method would swallow into an `error` verdict.
        extra_params: dict = dict(reasoning_kwargs_for(self.model, "JUDGE"))
        extra_params.update(temperature_kwargs_for(self.model, 0.0, "JUDGE"))
        extra_params.update(max_tokens_kwargs_for(self.model, "JUDGE"))
        try:
            resp = await litellm.acompletion(
                model=self.model,
                messages=[
                    {"role": "system", "content": _JUDGE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                timeout=JUDGE_TIMEOUT,
                num_retries=JUDGE_NUM_RETRIES,
                **extra_params,
            )
        except Exception as exc:  # noqa: BLE001 — a judge outage must not crash the gate
            return Judgment(
                scenario_id, family, "error", 0.0,
                f"Judge call failed: {type(exc).__name__}", ["judge unavailable"],
            )
        raw = (resp.choices[0].message.content or "").strip()
        return self._parse(scenario_id, family, raw)

    def _parse(self, scenario_id: str, family: str, raw: str) -> Judgment:
        try:
            data = _extract_json(raw)
        except (json.JSONDecodeError, ValueError):
            return Judgment(
                scenario_id, family, "error", 0.0,
                f"Unparseable judge output: {raw[:160]!r}", ["judge parse error"],
            )
        verdict = str(data.get("verdict", "")).lower().strip()
        if verdict not in ("pass", "fail"):
            verdict = "fail"
        try:
            score = float(data.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(1.0, min(5.0, score)) if score else (4.0 if verdict == "pass" else 1.0)
        red = data.get("red_flags") or []
        if not isinstance(red, list):
            red = [str(red)]
        return Judgment(
            scenario_id, family, verdict, score,
            str(data.get("reasoning", "")).strip(), [str(r) for r in red],
        )
