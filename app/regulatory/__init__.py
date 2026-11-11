"""Agent 3 (regulatory advice / retrieval) implementation.

The retrieval backend is vendored in this repository: `mercatoria/` + `data/regulatory/`.
`InProcessRetriever` is the default; `SMART_EDIT_RAG=<url>` switches to the HTTP adapter.

- `retriever` talks to the local index, an external service, or a fake;
- `query` turns run state into queries + pre-retrieval filters (deterministic, no model);
- `answer` turns retrieved chunks into citations/claims (extractive by default);
- `cite_check` downgrades claims whose citation does not survive checking;
- `index` builds/inspects the local SQLite index;
- `node` assembles `legal`, `retrieved`, `R-` findings and the stage report.

It never writes `business_type`, `fields`, `extra_fields`, `verification` or `gate`.
"""
