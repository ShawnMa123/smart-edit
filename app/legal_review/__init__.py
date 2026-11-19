"""Legal review module (`/legal/*`, task from `AI-Law_agent_reqirement.md`).

L1 first slice: the pure deterministic core — a typed, restricted DSL evaluator plus one
synthetic rule. This is the vertical minimal loop (spec §14.2): an authorised snapshot in,
one synthetic rule runs, a Finding comes out. Deterministic-only, synchronous, no persistence.

Contract truth source: `tradeAI_requirementDesign_v2/AI-Law_agent_reqirement.md` §8.2.
This is NOT the POC `app/regulatory/` contract (`EditState.legal` / LangGraph state keys).
"""
