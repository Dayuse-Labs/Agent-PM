"""StatelessLeafLeg — one-turn A2A messages to the (stateless) leaves.

Latency audit 2026-07-28. Stock `RemoteA2aAgent` builds its outgoing A2A
message by walking `ctx.session.events` in reverse and stopping at the last
event IT authored — but `_run_leaf` (agent.py) CONSUMES the leg's events
without re-yielding them (deliberately: raw leaf output must never reach the
user unsynthesized), so the ADK runner never persists any leg-authored event
and the stop condition never fires. Every leaf call therefore re-sent the
WHOLE conversation: every prior user message, every model answer, and — since
`_attach_outgoing_datapart` mutates the stored user event in place — every
prior turn's full profile snapshot. Turn N shipped N profile snapshots, and
the leaf's prompt grew linearly within a conversation (measured: leaf
prompt_tokens climbing turn over turn).

The leaves are STATELESS by architecture (CLAUDE.md invariant): all cross-turn
state travels in the CURRENT profile DataPart (`{query_params, profile_in}`),
so the current user event — its text plus that DataPart — is the entire
contract. This subclass sends exactly that, and returns `context_id=None`
(fresh remote session per call, which was already the de-facto behaviour: with
nothing persisted, the parent never had a context_id to reuse either).

Coupling note: `_construct_message_parts_from_session` is a private ADK
method (google-adk==2.4.0). The repo already couples to this exact seam by
documented design (a2a_datapart.py: session events are the ONLY injection
point into the outgoing message). test_stateless_leg.py pin-guards the base
method's signature so an ADK bump fails loudly here instead of silently
regrowing the payload.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from google.adk.agents.remote_a2a_agent import RemoteA2aAgent

if TYPE_CHECKING:  # imported only for signatures — keep import cost off boot
    from a2a.types import Part as A2APart
    from google.adk.agents.invocation_context import InvocationContext


class StatelessLeafLeg(RemoteA2aAgent):
    """RemoteA2aAgent that sends ONLY the current turn's user event."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Pure passthrough. Without it, the pydantic mypy plugin synthesizes a
        # fields-only signature for this subclass and rejects the parent's
        # real kwargs (agent_card, httpx_client, …).
        super().__init__(*args, **kwargs)

    def _construct_message_parts_from_session(
        self, ctx: "InvocationContext"
    ) -> "tuple[list[A2APart], Optional[str]]":
        for event in reversed(ctx.session.events):
            if event.author != "user" or not event.content or not event.content.parts:
                continue
            message_parts: list["A2APart"] = []
            for part in event.content.parts:
                converted = self._genai_part_converter(part)
                if not isinstance(converted, list):
                    converted = [converted] if converted else []
                for converted_part in converted:
                    # Same stamping as the parent: the leaf's request converter
                    # distinguishes user input from agent context by this flag.
                    converted_part.root.metadata = converted_part.root.metadata or {}
                    converted_part.root.metadata["is_user_input"] = True
                message_parts.extend(converted)
            return message_parts, None
        return [], None
