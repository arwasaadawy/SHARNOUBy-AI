# Data and leakage audit

## Provenance
Operational tables explicitly say modeled training data. Public catalog/location/business facts are separate. This is a working decision product evaluated on modeled data, not a claim of actual company results. Sources.csv is referenced in the dictionary but was not supplied.

## Grain
180,000 sales rows; every Invoice_ID is unique. No basket/co-purchase model is supported. Content recommendations use catalog attributes. 59 products; 36 months. Forecasting uses product/month; branch allocations use recent sales shares, not branch forecast models.

## Dates
No missing or invalid order dates in supplied data. Return dates absent for nonreturns are not applicable, not dates to impute. Unique-invoice agreement is the only automated recovery rule. IDs do not encode legitimate event dates. Date audit and row-level provenance are retained.

## Inventory
147 inventory arithmetic inconsistencies. Reported closing stock retained and flagged. Inventory monthly Sold_Qty is a separate modeled ledger and may differ from sales records. Recommendations combine these sources as an explicit scenario, not reconciled accounting.

## Temporal safeguards
Forecast inputs are shifted past units only; calendar known in advance. Three expanding recursive folds, final three months excluded from selection. No random split. Target horizon errors inform marginal intervals from development only. Holdout interval coverage: 82.5%. Stockout labels are NEXT month's stockout; current Closing_Stock and current completed-month sales are available at end of month. Historical Stockout_Days is lagged relative to target. Sigmoid calibration and F2 threshold use intermediate chronological period; untouched final test. Customer features use past 365 days at each cutoff; target next 90 days; same customers can recur in later snapshots. Cluster scaler fit only for descriptive current segmentation; not predictive evaluation. Price evaluation chronological; no contemporaneous target-derived features. Anomalies trained on first 70% of chronology; later flags are prospective and earlier flags retrospective.

## Limitations
Observed sales are not unconstrained demand. Monthly inventory cannot establish exact stockout day. Branch intervals are scaled product uncertainty, not calibrated branch intervals. No causal pricing claim. No color or images provided. No actual capacity/cost/transport constraints established: planner inputs are user assumptions. No unsupported DL layer. No fake confidence percentage: High/Medium/Low comes from per-product development WAPE (<20%, <40%, otherwise Low); classification outputs have separate test calibration diagnostics. Drift shown as observed demand distribution shift, not proof of model degradation.
