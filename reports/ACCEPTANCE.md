# Acceptance: implemented and supported scope

| Requirement | Result |
|---|---|
| Real data connection | All 20 uploaded tables connected; operational provenance says modeled |
| Quality / dates | Actual fields audited, inapplicable return dates separated, row-level provenance, 147 arithmetic mismatches and 19 ledger differences surfaced; current affected positions excluded from allocation |
| Trained ML deployed | Calibrated stockout RF, customer RF, KMeans, Isolation Forest, price regressor stored and exposed |
| Forecast comparison | Seven candidates, chronological CV, separate holdout, winning baseline deployed |
| Predictions and uncertainty | Three monthly product horizons, measured marginal intervals, WAPE-based qualitative confidence |
| Inventory / decisions | Allocated product demand, reorder proxy, production need, conservative transfers |
| Optimization | LP capacity allocation and BOM material requirements with editable assumptions |
| Product performance | Forecast growth trajectory, measured clusters and similarity |
| Recommendations | Content similarity; baskets unsupported by unique single-line invoices |
| Opportunity signals | Existing products, season memory, inventory exposure; unseen designs not predicted |
| Scenarios | Bounded observed price/discount support; production and inventory exposure; no causal promise |
| Copilot | Working offline evidence assistant; optional read-only LLM routing adapter. Live key required and not exercised |
| UX | Sixteen pages, scope filters, selection/drilldown, charts, exports, durable alert state, scenario controls, readable errors |
| Leakage | Shifted temporal features, chronological partitions, per-task audit |
| Explainability | Transparent baseline formula and measured classifier feature importances, uncertainty/assumptions exposed |
| Model monitoring | Source hashes and same-season demand shift; degradation unavailable without new observed actuals |
| Health | Measured component indicators; no invented composite score |
| Tests | Business invariants and all-page Streamlit integration tests executed |
| Clean start | Python dependency install and included artifacts verified; Windows launcher supplied (Windows OS not available here) |
| Commercial readiness | Local single-user v3, not authenticated/hosted multi-tenant production SaaS |

No deep learning added: per-product monthly history is 36 points and baselines performed well. No image model without image assets. No fake stockout-day interval. No cross-sell basket claim without baskets. No financial impact labeled guaranteed.

V3 adds session-based conversational UI with optional LLM qualitative responses; complete-year seasonal evidence; explicit annual invoice/refund reconciliation and expense ledger; physical count imports and audit snapshots. Annual profit remains estimated due to source estimated COGS and expense completeness.

V5 consolidates user navigation into six related workspaces, shares product context and financial scenario inputs, adds a reproducible HTML/CSV report pack, enforces English-only chat UI, and exposes explicit provider connection/anomaly empty states. Live account connectivity remains dependent on user-supplied credentials; tests simulate provider responses.
