"""Legal review module (`/legal/*`, task from `AI-Law_agent_reqirement.md`).

L1 first slice: legal advice (`modes=["legal"]`) — reuse `StatuteRetriever.chat_detailed()`
(`/v1/chat`) and map the outcome onto a traceable `Finding`. Synchronous, no persistence.
The deterministic/semantic engines are not part of this module.

Contract truth source: `tradeAI_requirementDesign_v2/AI-Law_agent_reqirement.md` §8.2.
This is NOT the POC `app/regulatory/` contract (`EditState.legal` / LangGraph state keys).
"""
