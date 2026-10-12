# SHARNOUBy AI v2: calculation and scope audit

This release fixes cross-page scope, event-date accounting, stale evidence and unsupported forecast conversion. Operational sources remain explicitly modeled training records; no report claims actual company financial results.

## Money and dates

- Invoiced net sales: sum Net_Sales_EGP for Order_Date within the selected period and scope. This is already after discounts, before refunds.
- Recorded refunds: sum Refund_Value_EGP for Returned=Yes and Return_Date in the period. Include refunds of purchases from earlier periods. Never subtract an eventual refund from an earlier period before that return happened.
- Net after refunds: invoiced net sales less event-date refunds. This is the dataset's recorded sales adjustment, not verified cash receipts or audited accounting revenue.
- Orders: distinct Invoice_ID in the sale-date period. Every supplied invoice is unique, but counting remains distinct by definition.
- AOV: invoiced net sales / distinct orders. Unavailable for zero orders; denominator is never silently forced to one.
- Units: recorded Quantity before returns. Returned quantities are not available and are never inferred from partial monetary refunds.
- Profit and margin: supplied estimated gross profit before returns, divided by invoiced net sales for margin. No unsupported COGS reversal or return-adjusted profit.
- Exact full calendar month selection compares with the previous full calendar month. Other arbitrary daily ranges compare with the previous equal-length range. Calendar-month questions in Copilot use calendar-month/month-to-date windows explicitly. Percentage change is unavailable for nonpositive baseline or incomplete previous history.
- Group-by category/product contributions use the same event-date accounting as the total; sums are independently tested.

## Historical versus current planning

Historical metrics follow category, location and selected dates. Current inventory and trained forecasts cannot move to an earlier date simply because the history filter moves. Current planning pages disable historical date controls and show forecast origin and inventory closing month. Model Center and Data Quality disable business filters and explicitly show whole-company scope.

Product-wide forecasts allocate to branches using last-90-day shares computed across all branches, never renormalized after selecting one branch. The sum of branch allocations equals the original company product forecast. Branch intervals are scaled proxies, not validated branch prediction intervals.

Inventory keeps the reported Closing_Stock. Current positions with a stock-equation mismatch or a sales-ledger disagreement are flagged and excluded from production optimization and transfer donors/recipients. They are not silently repaired. Suggested transfers conserve units and donor buffers; they are alternatives and are netted only with an explicit planning checkbox. Reorder/coverage quantities are planning proxies based on monthly units and supplier lead time, not exact stockout dates or guaranteed service levels.

## Insights and models

- Insights cite observed comparison values and arithmetic contributions. They do not state that discounts, stockouts, seasonality or another factor caused a sales change without a supported causal method.
- Historical product momentum follows the selected windows. Next-month-vs-last-month forecast change is separately labeled; a seasonal rebound is not automatically called an emerging product.
- Product segments and catalog similarity remain global precomputed descriptive models. Their scope is explicitly labeled. Similarity does not mean frequently bought together.
- Customer audience follows selected history and optional consent. Scoped RFM uses only data up to the selected historical end, with transparent thresholds. Company-wide repeat probability is separately labeled at its actual latest model origin. Unscored buyers remain visible with an unavailable probability.
- Anomaly detection has a distinct offline model per branch/category scope. The UI selects the matching precomputed model and filters flagged dates. Company models are not improperly applied to small branch volumes. Anomaly score percentile is training-reference unusualness, not error probability or fraud confidence.
- Pricing/scenario model now uses complete Monday–Sunday weeks, calibration and temporal final test. Partial edge weeks are removed. It predicts weekly units directly; the unvalidated weekly-to-monthly multiplier was removed. Discount/price values outside observed support are blocked. Constant list prices do not establish elasticity. Zero-sale weeks lack an observed discount treatment and are not fabricated into price training records. Price/discount response is exploratory observational association, not causal impact. Supply/production assumptions and stock date limitations are displayed.
- Copilot queries the same calculation layer as the UI and clears its stored response when scope or date changes. Calendar comparisons have explicit windows.

## Operations event bases

Completed production uses Completion_Date; printing uses Print_Date; QC uses Inspection_Date; received POs use Actual_Receipt_Date; marketing uses campaigns ending in the range with full campaign totals; web metrics use Date; support uses Open_Date with final recorded response/CSAT; group KPIs use whole overlapping Month rows. Category applies only to product-linked records. Factory/support/web tables have no retail branch key, so branch controls are disabled. Unrelated KPI units are not summed. Session/order chart scales are separate. Attributed marketing ROAS is not incremental causal ROAS.

## Optimization

Production minimizes assumed product cost plus low/central/high demand stress-scenario shortage/excess costs under capacity and recommended-need bounds. Scenario weights 20%/60%/20% are planning assumptions, not forecast probabilities. Costs, scenarios and material quantities recompute on every input change. Quantities may legitimately stay optimal while cost inputs change; this is explained rather than forcing fake changes. Rounded quantities have recomputed costs. Missing MOQ, line/material availability and route timing are not invented.
