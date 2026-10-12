# SHARNOUBy AI

A runnable Python/Streamlit fashion decision product, built from the 20 supplied CSVs. Includes precomputed trained models, SQLite, forecast comparison, inventory decisions, a constrained production planner, scenarios, read-only copilot, and auditable data provenance.

**Important:** operational files identify themselves as **modeled training data**. This is a functional local product evaluated on those records, not an assertion that these are actual company transactions or audited finances. Public catalog and business/location facts are kept separate. The dictionary references `Sources.csv`, which was not provided.

## Upgrade on your existing Windows installation

Extract this full release to a NEW directory and reuse the working Python environment; leave the old project intact. Stop the previous app using Ctrl+C, then run:

```powershell
Expand-Archive -LiteralPath "C:\Users\Number One\Downloads\SHARNOUBy_AI_V5.zip" -DestinationPath "D:\SHARNOUBy_AI_V5" -Force
cd "D:\SHARNOUBy_AI_V5"
.\run_app.bat "D:\SHARNOUBy_AI\.venv\Scripts\python.exe"
```

No retraining is needed. The optional interpreter path avoids another environment installation. If the old directory differs, supply its actual interpreter path.

## Windows: fresh installation

1. Install Python **3.12** if needed. Keep the Python launcher (`py`) enabled.
2. Extract the ZIP completely to a folder such as `D:\sharnouby_ai`.
3. Double-click **run_app.bat**. First run creates `.venv` and installs dependencies; subsequent runs reuse it. Open **http://localhost:8501** if the browser does not open automatically.

Internet is required for the first dependency installation. Forecasts and model artifacts are already included, so **you do not need to retrain to use the app**. If PowerShell execution policy blocks activation, use the commands below directly; activation is unnecessary.

```powershell
cd D:\sharnouby_ai
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app\Home.py
```

To stop, press Ctrl+C in the terminal. Runtime memory depends on the selected page; the app caches the SQLite tables in the process. This is a local single-user release, not a hosted multi-tenant service.

## Six connected workspaces

| Workspace | Related views |
|---|---|
| Business Overview | Overview and prioritized actions |
| Sales & Products | Product profile → forecasting → seasonal signals; discoveries and customers |
| Inventory & Operations | Inventory, production planner, weekly scenarios and operations reports |
| Finance & Reports | Live Business Report, year-end forecast, annual invoice/profit close and physical count |
| AI Copilot | English-only conversation and provider connection settings |
| Settings & Trust | Data quality and model monitoring |

The View selector keeps related tools within one workspace. Product selections persist between profile, forecast and weekly scenario; Continue buttons carry context into the next view. Branch/category/date filters retain shared business scope. Financial inputs are shared between Live Business Report and Year-End Profit; changes rebuild calculations and exports immediately. Production assumptions carry into a report only for matching scope. YTD accounting, fixed-origin forecasts and selected historical facts remain explicitly separate. Forecast origin is 30 September 2026; horizons October–December. Dates do not retrain or backdate forecasts.

The live report includes observed KPIs, YTD reconciliation, forecasts and scenario calculations, margins, break-even/target figures, audited inventory, production plan, product details, invoice/refund/expense registers, and anomaly evidence. Download HTML for reading and a ZIP for complete CSV tables + assumptions. Readable HTML previews up to 200 rows per table; CSVs contain every row. No API credentials enter exports.

Anomaly results distinguish no trained scope, no evaluated days (e.g. warm-up), and evaluated days with zero flags. September 2026 All/All contains 30 evaluated days and zero flags. Show all evaluated days for inspection; flags are not forced to create artificial alerts.

## Actual model results

Models were trained and compared here, using observed data, never hardcoded prediction numbers.

- Demand: **Seasonal naive won** three expanding-window development folds, compared with naive, moving average, simple exponential smoothing, Random Forest, XGBoost and histogram boosting. It uses the same month last year. Final untouched three-month holdout WAPE **26.78%**, MAE **238.81 units/product/month**. The system deliberately selects the better baseline rather than calling a worse complex model the winner.
- Demand interval: nominal 90% empirical horizon-specific marginal residual bands. Measured final holdout coverage **82.49%**, so these bands are imperfect and should not be interpreted as guarantees. Do not sum per-product bands to get a calibrated portfolio interval.
- Stockout: Random Forest with sigmoid calibration; next month's reported stockout. Untouched chronological test: recall **88.89%**, precision **35.82%**, PR-AUC **0.526**, ROC-AUC **0.965**, 27 positive cases/531 rows. A development F2 threshold favors recall. False alerts matter; approve actions after review.
- Customers: Random Forest 90-day repeat-purchase model, temporal ROC-AUC **0.569**, PR-AUC **0.563**; exploratory with modest discrimination. No lifetime-value claim.
- Price response: weekly histogram boosting, temporal WAPE **35.46%** versus product-average baseline **56.57%**. Associational scenario only, no causal uplift. Constant list-price support prevents unsupported list-price changes.
- Product segmentation: standardized KMeans; cluster count selected by silhouette. Descriptive trait labels are derived from measured percentile characteristics.
- Anomalies: 20 separately trained branch/category Isolation Forest models, trained on the first 70% of each chronological daily series; observed deviations use shifted rolling means. No invented labeled anomaly accuracy.
- Recommendations: TF-IDF/cosine similarity on catalog family, audience, gender, season and sizes. Every invoice has a single row, so no “frequently bought together” claim.

No useful product images or color attributes were supplied. Only 36 monthly observations per product are available. Deep learning is not justified by this history and was not added.

## Data and decisions

Original CSVs remain unmodified in `data/raw/`. SQLite persists all provided tables plus derived predictions and action state. The generated CSV outputs and model registry permit inspection outside the app.

The supplied sales dates are complete and agree with `Month_Key`. There are 171,457 missing return dates for non-returned rows, correctly treated as not applicable. **147 inventory balance inconsistencies** and **19 monthly sales/stock ledger differences** are flagged; closing stock is retained, never silently repaired. Detailed row date provenance is in `data/validation/sales_dates.csv`.

Branch demand is allocated from product forecast by recent 90-day unit shares; it is not a separately validated branch forecasting model. The inventory ledger's sold quantities are separately modeled and are not assumed reconciled with the sales ledger. Reported stock is combined with forecast as a planning scenario; reconcile real ledgers before action.

Planning logic:

```
coverage days = reported closing stock / allocated forecast daily units
reorder point = daily forecast × lead time + uncertainty planning buffer
production need = max(0, monthly forecast + buffer - closing stock)
optional transfer planning: subtract proposed incoming units only after explicit opt-in
```

The buffer scales product upper-band deviation by sqrt(lead-time/month-days), a documented proxy rather than a validated branch service-level guarantee. Transfers consume donor excess after preserving its forecast upper band and buffer. Optimization constrains total capacity and recommended need. Product production costs scale the reference cost input by historical estimated COGS/unit relative to the catalog median. Shortage/excess costs use low/central/high demand stress scenarios with explicit planning weights 20%/60%/20%; these are not calibrated forecast probabilities. All controls recalculate the plan immediately, with a production/shortage/excess cost breakdown. Optimal quantities can remain unchanged when assumptions change; the UI explains this rather than forcing artificial changes. MOQ, actual line availability, material stock, transport routes and costs are not established by these data. Proposals do not execute business orders.

Health shows measured components rather than an arbitrary composite score. Confidence High/Medium/Low means per-product development WAPE below 20%/40%/otherwise; it is not a probability that the forecast is correct. Growth outlook is next-month units vs last observed month, not a separate classifier. Opportunities concern existing catalog combinations and are not guarantees for unseen designs.

## Offline business assistant
English guided questions retrieve local evidence and preserve session context. No external service is required.

## Retraining and tests

Use **train_models.bat**, or:

```powershell
.\.venv\Scripts\python.exe -m src.engine
.\.venv\Scripts\python.exe -m pytest -q
```

Training rebuilds SQLite source/derived tables but preserves `action_state`. It performs expanding recursive demand validation, chooses the best mean development WAPE, scores untouched final months, then refits forecast artifacts on all historical monthly sales. Classification calibration/thresholds have their own chronological intermediate split, and final test metrics remain separate. Pages never retrain models.

Tests cover temporal feature causality, fold order, selection independent of holdout, uncertainty bounds, transfer conservation, production capacity, missing-date policy, artifact probabilities, grounded copilot, optional adapter protocol and all 17 Streamlit pages including core interactions. `reports/TEST_REPORT.md` records the executed result.

## Structure

- `app/Home.py`: Streamlit navigation and product pages.
- `src/engine.py`: explicit pipeline orchestration.
- `src/validation.py`, `forecasting.py`, `risk.py`, `intelligence.py`, `inventory.py`: data validation, demand models, calibrated classification, recommendations/anomalies/price models, decisions/optimization.
- `src/copilot.py`: read-only evidence tools and local routing.
- `models/`: trained artifacts and `registry.json`.
- `data/raw/`: all 20 original input files.
- `data/processed/`: SQLite, inspectable model outputs.
- `data/validation/`: row-level date audit.
- `reports/`: leakage/data audit, acceptance scope, testing.
- `tests/`: business and UI tests.

Database access is isolated behind load/save helpers and UI read functions. SQLite is currently the only configured backend; PostgreSQL and FastAPI remain future adaptations, not existing deployed services.

## Release scope

This is a functional local v5 with trained models and tested workflows. It does **not** include user authentication, multi-tenant permissions, commercial deployment, real-time ingestion, operational order execution, causal price effects, exact stockout-day predictions, . A real commercial release requires actual company transaction feeds and operational validation. These are stated limits, not hidden placeholder buttons.


## v2 correctness changes

See `reports/V2_CALCULATION_AUDIT.md`, `reports/VERIFIED_INSIGHTS.md` and `reports/TEST_REPORT.md`. These cover independent SQL reconciliation, customer filters, dated refunds, forecast allocation, separately trained scoped anomalies, complete-week scenario forecasts, live cost-aware production planning and stale-copilot clearing. Changes to costs may legitimately leave an optimal quantity unchanged; costs still update and the UI explains the result. No fabricated impact or forced numeric variation is added.

Current audited planning exports are `data/processed/inventory_plan_v2.csv` and `proposed_transfers_v2.csv`. Legacy `inventory` and `transfers` pipeline tables/CSVs are intermediate company model/decision outputs, not approved operational plans; the application recomputes audited scoped decisions and excludes current reconciliation issues.


## v3 annual accounting and count boundaries

Annual Closing uses calendar years and explicitly marks partial 2023/2026 source years. Invoice totals reconcile to invoiced net sales; refund events include prior-year purchases and reconcile by Return_Date. COGS is estimated. The report subtracts entered operating, finance, tax and inventory-write-down expenses and adds only documented manual returned-goods cost recovery. No unknown tax, VAT, cash settlement, returned quantity or cost recovery is fabricated. Unallocated company costs are excluded from branch/category slices with a visible warning. Zero entered costs is not evidence of zero real costs; results remain estimated rather than certified net profit. Partial-year adjustment events are cut off at the source end date. Purchases/marketing costs are not automatically deducted again on top of estimated sold COGS.

Annual Count compares user-supplied physical counts with the exact available book closing month for the selected year. Blank is uncounted; zero is a real count. Missing December stock cannot be relabeled as a December count. Historical book quantities cannot support a today count without intervening movements/current inventory. Product/branch IDs, duplicates and integer counts are validated. Count sessions preserve book stock, count values, difference, cost proxy, book data issue and timestamp. Saving does not modify the book ledger or automatically recognize an expense. Valuation uses past-365-day estimated sales COGS/unit; unpriced rows remain unavailable. Count and annual-adjustment tables are retained by explicit retraining.

High Season uses only complete calendar years and averages month/within-year mean demand ratios. Recurrence requires at least two complete years; the threshold is explicit. Target-month historical averages are not future predictions. Future demand/gaps are exposed only for matching precomputed horizons; preparation dates are lead-time/buffer assumptions, not validated delivery commitments. No holiday dates are invented.

For exhaustive yearly arithmetic reconciliation, see `reports/V3_NUMERIC_AUDIT.md` and `V3_ANNUAL_RECONCILIATION.csv`: all 80 branch/category/year combinations passed 880 SQL/conservation checks, to monetary rounding precision. This is source-record arithmetic validation, not a promise of perfect predictions or certified actual profit.


## v4 conditional year-end result forecast

`Year-End Profit` uses the latest completed sales month as origin, not today's date or historical filters. YTD facts come from the same event-date annual ledger. Remaining product/month units use the precomputed selected demand model. Selling price after discounts and estimated unit COGS are quantity-weighted from the past 90 days, with explicit prior-history fallbacks; the refund-event ratio uses 365 days and never uses returns after the financial cutoff. The future expense budget is explicitly entered; unknown expenses remain unknown and the result is labeled BEFORE missing future expenses. No double deduction of procurement or forecast production costs: only estimated sold COGS plus non-COGS expenses is used. Supply fulfillment is a user assumption including replenishment, not verified stock/capacity feasibility. Price adjustments hold demand constant and do not imply causal elasticity.

Year-end output is unavailable when supported horizons do not cover every remaining month/product. Marginal demand lower/upper bands are used as stress cases, not summed into a calibrated annual interval. Lower demand stress adds five percentage points to the unit-cost multiplier and multiplies refund rate by 1.25, capped at 100%; controls and limits are shown. Scenario ordering may reverse for negative-margin products.

Break-even and target-gap arithmetic assumes unchanged product mix and marginal unit economics, and treats entered remaining expenses as fixed for this planning calculation. Required additional sales are a target, not forecast additional demand or capacity assurance. Nonpositive contribution prevents a finite break-even calculation. Margin Watch ranks the lowest modeled product contribution ratios; it does not automatically stop production.

Financial conversion is backtested using frozen rates at 30 June 2026 and the untouched July–September demand holdout. The measured contribution-proxy WAPE is about 3.43% across ONLY THREE aggregate months. This is not validated actual net profit, annual accuracy or an annual confidence interval; portfolio cancellation and absence of actual expenses/COGS limit generalization. Results and limits are in the model registry and `profit_forecast_validation.csv`. Validation is regenerated during explicit training.

To preserve entered V3 expense/count/alert records on upgrade, the launcher accepts a second argument for the previous database:

```powershell
.\run_app.bat "D:\SHARNOUBy_AI\.venv\Scripts\python.exe" "D:\SHARNOUBy_AI_V3\data\processed\business.db"
```

Migration is idempotent, read-only against the old database, and rolls back on conflicting IDs. Source and model tables are not replaced. Stop the old app first. A missing previous database is skipped. Exported scenario assumptions are JSON; they remain session inputs unless you keep that export.


## V5 English copilot and connection setup


Chat responses and suggestions are English-only. Non-English catalog text is omitted from chat displays with IDs retained. Arabic user input is rejected at the UI with an English prompt. The narrative must pass an English/qualitative-only guard; rejected explanations show an explicit reason while verified tables remain available. Conversation still retrieves numbers from local business tools.

For upgrade, the second launcher argument can point to `D:\SHARNOUBy_AI_V4\data\processed\business.db`. Workspace records are migrated without replacing source/model tables; an existing `.env` is copied only when the new release has none. Stop the old app before upgrading.

PDF downloads use ReportLab directly; no browser or HTML conversion is required. The readable PDF previews 20 rows per table, with complete calculation rows preserved in the CSV report pack.


## Offline release
No external API or credentials are used. The English guided assistant uses local data and models. Live Business Report caps next-month fulfilled sales by eligible stock plus allocated production; later months retain the user fulfillment assumption. Capacity is an upper bound and can stop affecting outputs when the optimum is reached. Historical sales never change with planning inputs. Exports use the same calculations. Run run_app.bat or use Python 3.12 in a virtual environment.
