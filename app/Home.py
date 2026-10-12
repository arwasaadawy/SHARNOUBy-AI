from pathlib import Path
import sys,sqlite3,json,pickle
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from style import STYLE
from src.settings import ROOT
from src.inventory import optimize
from src.analytics import normalize,ratio,select_scope,comparison_dates,period_sales,financial_kpis,daily_money,category_comparison,product_facts,forecast_view,inventory_plan,customer_audience,insight_cards
from workspaces import render_annual,render_count,render_season,render_chat,render_profit_forecast,production_controls
from src.annual import ensure_workspace
from src.navigation import NAVIGATION,section_for

st.set_page_config(page_title='SHARNOUBy AI',page_icon='✦',layout='wide')
st.markdown(STYLE,unsafe_allow_html=True)
DB=ROOT/'data/processed/business.db'
PAGES=list(NAVIGATION)
if not DB.exists():st.error('Database unavailable. Run train_models.bat once.');st.stop()
ensure_workspace(DB)
@st.cache_resource(max_entries=1)
def load_data(db_stamp,registry_stamp):
    names=['sales_transactions','product_master','locations','forecasts','inventory_history','inventory','product_intelligence','recommendations','customer_scores','customers','anomalies','scoped_anomalies','forecast_metrics','forecast_residuals','forecast_test','quality','date_audit','issues','production_orders','purchase_orders','qc_inspections','customer_service','marketing','web_traffic_daily','machine_downtime','printing_batches','product_bom','group_operations','weekly_price_forecasts']
    c=sqlite3.connect(DB)
    try:
        tables={n:normalize(pd.read_sql_query('SELECT * FROM '+n,c)) for n in names}
    finally:c.close()
    validation_file=ROOT/'data/processed/profit_forecast_validation.csv'
    if validation_file.exists():tables['profit_forecast_validation']=normalize(pd.read_csv(validation_file))
    registry=json.loads((ROOT/'models/registry.json').read_text())
    return tables,registry
try:t,registry=load_data(DB.stat().st_mtime_ns,(ROOT/'models/registry.json').stat().st_mtime_ns)
except sqlite3.OperationalError:st.error('This database needs the v2 auxiliary artifacts. Use the complete v2 release, or run train_models.bat.');st.stop()
sales=t['sales_transactions'];master=t['product_master'];origin=sales.Order_Date.max()
if pd.isna(origin):st.error('No usable sales history.');st.stop()
admin=['Model Center','Data Quality'];planning=['Action Center','Inventory Command','Production Planner','What-if Lab','High Season','Annual Count','Annual Closing','Year-End Profit']
ops_options=['Production','Printing & quality','Procurement','Marketing','Web funnel','Customer service','Group operations']
with st.sidebar:
    st.markdown('## ✦ SHARNOUBy AI');st.caption('CONNECTED WORKSPACE')
    workspace=st.radio('Workspace',PAGES,label_visibility='collapsed',key='main_workspace')
    views=NAVIGATION[workspace]
    page=st.selectbox('View',views,key='view_'+workspace) if len(views)>1 else views[0]
    operation=st.selectbox('Operations report',ops_options,key='ops_report') if page=='Operations' else None
    st.divider();st.markdown('**Scope controls**')
    branch_enabled=page not in admin+['Operations']
    category_enabled=page not in admin and not(page=='Operations' and operation in ['Procurement','Web funnel','Customer service','Group operations'])
    chosen_branch=st.selectbox('Location',['All']+sorted(sales.Location_Name.unique()),disabled=not branch_enabled,key='scope_branch')
    chosen_category=st.selectbox('Category',['All']+sorted(master.Product_Family.unique()),disabled=not category_enabled,key='scope_category')
    date_enabled=page not in admin+planning
    dates=st.date_input('Historical period',(origin.date()-pd.Timedelta(days=29),origin.date()),min_value=sales.Order_Date.min().date(),max_value=origin.date(),disabled=not date_enabled,key='scope_dates')
    st.caption('Grey controls do not apply to this workspace. Historical windows never move the trained forecast origin.')
    st.caption('Operational records are modeled training data; public catalog facts are separate.')
branch=chosen_branch if branch_enabled else 'All';category=chosen_category if category_enabled else 'All'
if len(dates)!=2:st.info('Select both start and end dates.');st.stop()
start,end=map(pd.Timestamp,dates)
if not date_enabled:start=origin-pd.Timedelta(days=29);end=origin
scope,ids=select_scope(sales,master,branch,category);catalog=master[master.Product_ID.isin(ids)].copy()
cs,ce,ps,pe,basis=comparison_dates(start,end);period=period_sales(scope,start,end)
complete=ps>=sales.Order_Date.min()
kpis=financial_kpis(scope,start,end);old=financial_kpis(scope,ps,pe)
viewf=forecast_view(t['forecasts'],sales,t['locations'],ids,branch,origin)
viewinv,transfers,snapshot=inventory_plan(t['inventory_history'],t['inventory'],sales,t['forecasts'],t['locations'],ids,branch,origin)
products=product_facts(scope,catalog,start,end,ps,pe)
if not complete:products[['Previous_Units','Unit_Change','Historical_Unit_Growth']]=np.nan
products=products.merge(t['product_intelligence'][['Product_ID','Segment','Cluster']],on='Product_ID',how='left')
first=viewf[viewf.horizon.eq(1)][['Product_ID','Units','Lower','Upper','Confidence','Validation_WAPE']].rename(columns={'Units':'Next_Month_Units'})
products=products.merge(first,on='Product_ID',how='left')
latest_start=origin.to_period('M').to_timestamp();latest_units=period_sales(scope,latest_start,origin).groupby('Product_ID').Quantity.sum()
products['Last_Recorded_Month_Units']=products.Product_ID.map(latest_units).fillna(0)
products['Next_vs_Last_Month']=np.where(products.Last_Recorded_Month_Units>0,products.Next_Month_Units/products.Last_Recorded_Month_Units-1,np.nan)
key=(page,branch,category,str(start.date()),str(end.date()),DB.stat().st_mtime_ns)
st.caption('SHARNOUBy / '+page.upper());st.title(workspace);st.caption(page)
st.markdown('<span class="pill">FACT · recorded values</span><span class="pill">PREDICTION · uncertain model output</span><span class="pill">RECOMMENDATION · explicit planning assumptions</span>',unsafe_allow_html=True)
if page in admin:st.caption('Whole-company model/data audit. Business filters are disabled here; model evaluation figures do not change with a business slice.')
elif page in ['Annual Closing','Annual Count']:st.caption(f'ANNUAL WORKSPACE · {branch} / {category}. Select the year below; report cutoffs are displayed separately.')
elif page in planning:st.caption(f'CURRENT PLANNING SCOPE · {branch} / {category} · inventory closing month {snapshot:%b %Y} · forecast origin {origin:%d %b %Y}. Historical dates are disabled.')
else:st.caption(f'HISTORICAL SCOPE · {branch} / {category} · {start:%d %b %Y}–{end:%d %b %Y}. Comparison: {basis}, {ps:%d %b}–{pe:%d %b %Y}.')
if branch!='All':st.caption('Branch forecasts allocate the validated company product forecast by last-90-day unit shares. They are estimates, not separately trained branch models; branch bands are scaled proxies.')

def amount(v,decimals=2):return f'{v:,.{decimals}f}' if pd.notna(v) else 'Unavailable'
def pct(v):return f'{v:.1%}' if pd.notna(v) else 'Unavailable'
def table(d,key,height=400):
    if d.empty:
        st.info('No matching records for this scope and period. Try a wider period or another view.');return
    st.dataframe(d,width='stretch',hide_index=True,height=height)
    st.download_button('Export full CSV',d.to_csv(index=False).encode('utf-8-sig'),file_name=key+'.csv',mime='text/csv',key='download_'+key)
def plot(fig):
    fig.update_layout(template='plotly_white',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',font=dict(color='#254d48'),colorway=['#1d7768','#d7ac64','#6aa7b4','#b97269'],margin=dict(l=15,r=15,t=35,b=25))
    st.plotly_chart(fig,width='stretch')
def trend(pid,horizon=3):
    h=scope[scope.Product_ID.eq(pid)].assign(Month=lambda d:d.Order_Date.dt.to_period('M').dt.to_timestamp()).groupby('Month').Quantity.sum().reset_index()
    months=pd.date_range(start.to_period('M').to_timestamp(),end.to_period('M').to_timestamp(),freq='MS');h=h.set_index('Month').reindex(months,fill_value=0).rename_axis('Month').reset_index()
    f=viewf[viewf.Product_ID.eq(pid)&(viewf.horizon<=horizon)]
    fig=go.Figure();fig.add_trace(go.Scatter(x=h.Month,y=h.Quantity,name='Recorded monthly units',line=dict(color='#256e61',width=3)))
    if len(f):
        fig.add_trace(go.Scatter(x=f.Month,y=f.Upper,line=dict(width=0),showlegend=False));fig.add_trace(go.Scatter(x=f.Month,y=f.Lower,fill='tonexty',fillcolor='rgba(69,143,119,.18)',line=dict(width=0),name='Empirical marginal band'));fig.add_trace(go.Scatter(x=f.Month,y=f.Units,name='Fixed-origin forecast',line=dict(color='#d4a257',width=3,dash='dash')))
    fig.update_layout(yaxis_title='Units before returns',xaxis_title='Month');plot(fig)
    st.caption('Historical chart shows whole recorded months overlapping the selected dates. Edge months may extend outside the exact daily window. Forecast origin stays fixed; no predictions are moved back in time.')
def open_linked_view(view,pid):
    st.session_state['_selected_product']=pid
    from src.navigation import canonical_view
    view=canonical_view(view);section=section_for(view);st.session_state['main_workspace']=section;st.session_state['view_'+section]=view

def product_selector(key):
    if catalog.empty:st.info('No product matches this catalog scope.');st.stop()
    options=catalog.Product_ID.tolist();selected=st.session_state.get('_selected_product',options[0])
    if selected not in options:selected=options[0]
    if st.session_state.get('shared_product') not in options:st.session_state.pop('shared_product',None)
    def remember():st.session_state['_selected_product']=st.session_state['shared_product']
    pid=st.selectbox('Product',options,index=options.index(selected),format_func=lambda p:p+' · '+str(catalog.set_index('Product_ID').loc[p,'Product_Name']),key='shared_product',on_change=remember)
    st.session_state['_selected_product']=pid
    next_view={'Product Intelligence':'What-if Lab','What-if Lab':'Inventory Command'}.get(page)
    if next_view:st.button('Continue to '+next_view,on_click=open_linked_view,args=(next_view,pid),key='continue_'+page)
    return pid
def action_state():
    from src.action_store import read_actions
    return read_actions(DB)
def set_action(a,status):
    from src.action_store import save_action
    save_action(DB,a,status)
def month_forecast_note():
    st.caption(f'Forecast {viewf.Month.min():%b %Y}–{viewf.Month.max():%b %Y}, trained through {origin:%d %b %Y}. Sales are observed units, not unconstrained demand. Nominal 90% marginal bands achieved {registry["demand"]["test_interval_coverage"]:.1%} holdout coverage; not guarantees or additive portfolio intervals.')
def cards(d):
    for r in d.itertuples():
        st.markdown('**'+r.Title+'** · '+r.Type);st.write(r.Evidence);st.caption(r.Action)

if page=='Inventory Command':
    risks=st.multiselect('Risk level',sorted(viewinv.Risk.unique()),default=sorted(viewinv.Risk.unique()));d=viewinv[viewinv.Risk.isin(risks)]
    cols=['Product_ID','Location_Name','Closing_Stock','Forecast','Lower','Upper','Coverage_Days','Reorder_Point','Stockout_Probability','Risk','Data_Issue','Suggested_Units','Proposed_Transfer_In']
    event=st.dataframe(d[cols],hide_index=True,width='stretch',on_select='rerun',selection_mode='single-row',key='inventory_select')
    if event.selection.rows and event.selection.rows[0]<len(d):
        selected=d.iloc[event.selection.rows[0]].Product_ID;st.session_state['_selected_product']=selected;trend(selected)
        st.button('Inspect selected product',on_click=open_linked_view,args=('Product Intelligence',selected))
    st.download_button('Export inventory positions',d[cols].to_csv(index=False).encode('utf-8-sig'),'inventory_positions.csv')
    st.caption('Closing stock is the latest reported completed-month balance. Coverage assumes evenly spread forecast sales. Reorder point is a supplier-lead-time planning proxy, not a calibrated service-level guarantee.')
    st.subheader('Proposed transfer alternatives · not executed');table(transfers,'transfers')
    st.caption('All transfers conserve units, preserve donor forecast upper-band/buffer and exclude unreconciled stock. Selected-branch transfers can involve other branches. They do not silently reduce production need.')

    st.subheader('Production & material plan')
    inputs=production_controls(branch,category)
    capacity,unit_cost,penalty,holding=(inputs[k] for k in ['capacity','unit_cost','penalty','holding'])
    transfers_approved=inputs['transfers_approved']
    plan=viewinv.copy()
    if transfers_approved:
        plan.Transfer_In=plan.Proposed_Transfer_In;plan.Transfer_Out=plan.Proposed_Transfer_Out;plan.Net_Production_Need=(plan.Suggested_Units-plan.Transfer_In).clip(lower=0)
    blocked=plan[~plan.Recommendation_Eligible];plan=plan[plan.Recommendation_Eligible].copy()
    if len(blocked):st.warning(f'{len(blocked)} stock positions excluded until current ledgers are reconciled; no quantity is allocated to them.')
    costs=sales.groupby('Product_ID').agg(COGS=('Estimated_COGS_EGP','sum'),Units=('Quantity','sum'));reference=(costs.COGS/costs.Units.clip(lower=1)).to_dict()
    result=optimize(plan,capacity,unit_cost,penalty,holding,cost_reference=reference)
    inputs=(branch,category,capacity,unit_cost,penalty,holding,transfers_approved);previous=st.session_state.get('live_plan_comparison');current=dict(zip(result.Product_ID,result.Produce))
    if previous and previous['inputs']!=inputs and previous['scope']==(branch,category):
        changed=sum(current.get(p,0)!=previous['quantities'].get(p,0) for p in set(current)|set(previous['quantities']))
        if changed:st.success(f'Recalculated: quantities changed for {changed} products.')
        else:st.info('Recalculated: best quantities are unchanged under these assumptions. The displayed cost breakdown still reflects all updated inputs.')
    st.session_state['live_plan_comparison']={'inputs':inputs,'scope':(branch,category),'quantities':current}
    c=st.columns(4);c[0].metric('Allocated production',amount(result.Produce.sum(),0)+' units');c[1].metric('Production cost estimate','EGP '+amount(result.Production_Cost.sum()));c[2].metric('Weighted shortage cost','EGP '+amount(result.Shortage_Cost.sum()));c[3].metric('Weighted excess cost','EGP '+amount(result.Holding_Cost.sum()));st.metric('Total planning scenario cost','EGP '+amount(result.Total_Planning_Cost.sum()))
    table(result,'production_plan');bom=t['product_bom'].merge(result[['Product_ID','Produce']],on='Product_ID');bom['Required']=bom.Required_Per_Unit*bom.Produce;table(bom.groupby(['Material_ID','Material_Name','Unit']).Required.sum().reset_index(),'material_requirements')
    st.caption('Every input recalculates. Costs are assumptions: production cost scales estimated historical COGS/unit; shortage/excess use forecast lower/central/upper stress scenarios weighted 20%/60%/20%, not calibrated probabilities. Excess includes existing stock. Capacity and recommended-need bounds constrain production; rounded units have recomputed costs. Material requirements are consumption estimates, not confirmation of material availability. Lead-time/route/MOQ/line constraints are not known.')

elif page=='Product Intelligence':
    q=st.text_input('Search catalog')
    if q:catalog=catalog[catalog.Product_Name.str.contains(q,case=False,regex=False)|catalog.Product_ID.str.contains(q,case=False,regex=False)]
    pid=product_selector('deep_pid');r=products[products.Product_ID.eq(pid)].iloc[0];st.subheader(r.Product_Name)
    c=st.columns(4);c[0].metric('Period net after refunds','EGP '+amount(r.Period_Net_After_Refunds));c[1].metric('Period units',amount(r.Period_Units,0));c[2].metric('Historical units change',pct(r.Historical_Unit_Growth) if complete else 'Unavailable');c[3].metric('Estimated period margin',pct(r.Period_Margin_Before_Returns))
    st.caption('These four cards follow the selected dates, branch and category. Growth uses the preceding comparison window. Zero or incomplete prior history produces an unavailable percentage.')
    horizon=st.slider('Future months',1,3,3);trend(pid,horizon);st.markdown('**Current forecast and inventory, separate date basis**')
    c=st.columns(3);c[0].metric('Next month allocated forecast',amount(r.Next_Month_Units,1));c[1].metric('Forecast vs last recorded month',pct(r.Next_vs_Last_Month));c[2].metric('Forecast error band',r.Confidence)
    st.caption(f'Global product segment: {r.Segment}. The segment is precomputed across company history; it is not silently reclustered per filter. A forecast rise versus last month can be seasonal and is not evidence of emerging annual growth.')
    table(viewinv[viewinv.Product_ID.eq(pid)][['Location_Name','Closing_Stock','Forecast','Risk','Data_Issue','Stockout_Probability','Suggested_Units']],'product_inventory')
    a,b=st.columns(2)
    with a:
        d=period[period.Product_ID.eq(pid)].groupby('Size').Quantity.sum().reset_index();st.subheader('Selected-period size preference');plot(px.bar(d,x='Size',y='Quantity'))
    with b:
        d=t['recommendations'][t['recommendations'].Product_ID.eq(pid)].merge(master[['Product_ID','Product_Name']],left_on='Similar_Product_ID',right_on='Product_ID',suffixes=('','_similar'));st.subheader('Catalog similarity · global');table(d[['Similar_Product_ID','Product_Name','Similarity']],'similar_products')
    st.caption('Cosine similarity describes catalog attributes, not co-purchase or conversion probability. The invoices have no multi-product basket evidence.')

    st.subheader('Validated forecast for this product')
    f=viewf[viewf.Product_ID.eq(pid)&(viewf.horizon<=horizon)];table(f[['Product_ID','Month','Units','Lower','Upper','Model','Validation_WAPE','Confidence']],'product_forecast');month_forecast_note()
    st.subheader('Company-level candidate model validation')
    d=t['forecast_metrics'].groupby('model')[['MAE','RMSE','WAPE','MAPE','Bias']].mean().reset_index();d['Selected']=d.model.eq(registry['demand']['model']);table(d.sort_values('WAPE'),'model_comparison')
    st.caption('Model-selection metrics evaluate all-company product tasks and are not recomputed as branch accuracy. Validation_WAPE in the forecast table evaluates the selected product at company level. High/Medium/Low bands are <20%/<40%/otherwise, not correctness probabilities.')

elif page=='Customers':
    mode=st.radio('Audience definition',['Period purchasers','All known buyers up to period end'],horizontal=True)
    consent=st.checkbox('Only opted-in customers',True)
    d=customer_audience(scope,t['customers'],t['customer_scores'],start,end,consent,mode)
    choices=['Inactive >180 days','Low frequency','Recent frequent','Regular'];segments=st.multiselect('Scoped historical RFM segments',choices,default=choices,key='customer_segments');d=d[d.RFM_Segment.isin(segments)]
    c=st.columns(3);c[0].metric('Customers in audience',amount(len(d),0));c[1].metric('Audience orders in period',amount(d.Scope_Orders.sum(),0));c[2].metric('Audience period net after refunds','EGP '+amount(d.Scope_Net_After_Refunds.sum()))
    st.caption('RFM follows the selected branch/category and uses only information up to selected end: past-365-day frequency/value, recency since last scoped purchase. Recent frequent means recency ≤60 days and ≥3 orders; inactive means >180 days. Period-purchaser mode naturally excludes many inactive customers.')
    if d.empty:st.info('No audience matches these selections.')
    else:plot(px.histogram(d.dropna(subset=['Repeat_90D_Probability']),x='Repeat_90D_Probability',nbins=25))
    table(d.sort_values('Scope_Net_After_Refunds',ascending=False),'customer_audience')
    st.caption(f'Repeat probability is a separate COMPANY-WIDE model forecast as of {origin:%d %b %Y}, not a category-specific forecast or a prediction made at the historical end date. Customers without a current model score remain in the audience with an unavailable probability. Temporal model ROC-AUC {registry["customers"]["ROC_AUC"]:.3f}: exploratory, modest discrimination.')

elif page=='What-if Lab':
    pid=product_selector('scenario_pid');r=products[products.Product_ID.eq(pid)].iloc[0]
    with open(ROOT/'models/price.pkl','rb') as h:pm=pickle.load(h)
    baseline=pm['last'][pm['last'].Product_ID.eq(pid)].iloc[0];limits=pm['ranges'].loc[pid]
    recent=sales[sales.Product_ID.eq(pid)&sales.Order_Date.between(origin-pd.Timedelta(days=89),origin)]
    allocation=float(ratio(recent.loc[recent.Location_Name.eq(branch),'Quantity'].sum(),recent.Quantity.sum())) if branch!='All' else 1.
    if not np.isfinite(allocation):st.info('No recent branch allocation evidence for this product.');st.stop()
    stock=int(viewinv[viewinv.Product_ID.eq(pid)].Closing_Stock.sum());week=pd.Timestamp(pm['forecast_week'])
    st.caption(f'WEEKLY SCENARIO · {week:%d %b %Y}–{week+pd.Timedelta(days=6):%d %b %Y}. Complete-week model; no weekly-to-monthly conversion. Stock is reported latest month-end, not a confirmed stock balance for the future week.')
    a,b,c=st.columns(3);production=a.number_input('Additional available units by modeled week',0,100000,0,step=50)
    if limits.Min_Price==limits.Max_Price:price=b.number_input('Observed list price (no variation evidence)',value=float(baseline.Price),disabled=True)
    else:price=b.number_input('List price (EGP)',float(limits.Min_Price),float(limits.Max_Price),float(baseline.Price))
    discount=c.slider('Discount fraction',0.,.5,float(np.clip(baseline.Discount,limits.Min_Discount,limits.Max_Discount)),.01)
    scenario_stock=st.number_input('Scenario opening stock assumption (units)',0,1000000,stock,step=10)
    st.caption(f'Observed complete-week discount support: {limits.Min_Discount:.2%}–{limits.Max_Discount:.2%}. Constant list prices do not establish price elasticity.')
    if not limits.Min_Discount<=discount<=limits.Max_Discount:st.warning('Discount is outside the observed support. No demand estimate is returned.');st.stop()
    base=baseline[pm['features']].to_frame().T;scenario=base.copy();scenario.Price=price;scenario.Discount=discount
    bd=max(0,float(pm['model'].predict(base)[0]))*allocation;sd=max(0,float(pm['model'].predict(scenario)[0]))*allocation
    current_supply=stock;scenario_supply=scenario_stock+production;unit_cost=st.number_input('Assumed cost per newly produced unit (EGP)',0.,10000.,100.)
    result=pd.DataFrame({'Metric':['Modeled weekly units','Available units assumption','Central shortage units','Central excess units','Revenue ceiling before returns','Additional production cost assumption'],'Current':[bd,current_supply,max(0,bd-current_supply),max(0,current_supply-bd),min(bd,current_supply)*float(baseline.Price)*(1-float(baseline.Discount)),0.],'Scenario':[sd,scenario_supply,max(0,sd-scenario_supply),max(0,scenario_supply-sd),min(sd,scenario_supply)*price*(1-discount),production*unit_cost]})
    table(result,'weekly_scenario');st.caption(f'Company weekly scenario band: max(0, {sd:.1f} − residual scale {pm["interval_radius"]*allocation:.1f}) to {sd+pm["interval_radius"]*allocation:.1f} units; branch scaling is a proxy. No calibrated counterfactual stockout probability is computed.')
    st.warning('Observational model estimate, not causal discount uplift or guaranteed revenue. Tree predictions can remain constant for small price/discount changes. Supply and revenue arithmetic still recalculates. Transit/production delays, returns and future intervening sales are not simulated.')
    st.caption(f'Weekly temporal WAPE {registry["price"]["WAPE"]:.1%}; baseline {registry["price"]["baseline_WAPE"]:.1%}; measured interval coverage {registry["price"]["interval_coverage"]:.1%}.')

elif page=='Operations':
    st.caption('Factory/support/digital ledgers have no customer branch key. Location filter is disabled. Each report names its event-date basis; category is disabled for reports without product relationships.')
    def event_rows(name,date_col,product_scope=False):
        d=t[name];d=d[d[date_col].between(start,end)].copy()
        if product_scope:d=d[d.Product_ID.isin(ids)]
        return d
    if operation=='Production':
        d=event_rows('production_orders','Completion_Date',True);st.caption('Completed orders whose Completion_Date is in the selected period; full completed-order totals.')
        c=st.columns(3);c[0].metric('Completed good units',amount(d.Good_Qty.sum(),0));c[1].metric('Completed orders delayed',pct(d.Delay_Days.gt(0).mean()) if len(d) else 'Unavailable');c[2].metric('Production yield',pct(ratio(d.Good_Qty.sum(),d.Produced_Qty.sum())))
        table(d.groupby('Line_ID').agg(Orders=('Production_Order_ID','size'),Good=('Good_Qty','sum'),Rejected=('Rejected_Qty','sum'),Mean_Delay_Days=('Delay_Days','mean')).reset_index(),'production_lines')
    elif operation=='Printing & quality':
        d=event_rows('printing_batches','Print_Date',True);q=event_rows('qc_inspections','Inspection_Date',True);st.metric('Printing rejection fraction',pct(ratio(d.Rejected_Qty.sum(),d.Printed_Qty.sum())));table(d,'printing_batches');table(q,'quality_inspections')
    elif operation=='Procurement':
        d=event_rows('purchase_orders','Actual_Receipt_Date');d['Late_Days']=(d.Actual_Receipt_Date-d.Promised_Date).dt.days.clip(lower=0);c=st.columns(3);c[0].metric('Received purchase orders',len(d));c[1].metric('On-time receipts',pct(d.Actual_Receipt_Date.le(d.Promised_Date).mean()) if len(d) else 'Unavailable');c[2].metric('Accepted / ordered units',pct(ratio(d.Accepted_Qty.sum(),d.Ordered_Qty.sum())));table(d,'received_purchase_orders')
    elif operation=='Marketing':
        d=event_rows('marketing','End_Date',True);st.caption('Campaigns ending within the selected dates. Spend and attributed revenue are whole-campaign totals; no invented daily proration or causal attribution.')
        c=st.columns(3);c[0].metric('Campaign spend','EGP '+amount(d.Spend_EGP.sum()));c[1].metric('Attributed revenue','EGP '+amount(d.Attributed_Revenue_EGP.sum()));c[2].metric('Attributed revenue / spend',amount(ratio(d.Attributed_Revenue_EGP.sum(),d.Spend_EGP.sum()),2)+'×');table(d,'campaigns')
    elif operation=='Web funnel':
        d=event_rows('web_traffic_daily','Date');c=st.columns(3);c[0].metric('Sessions',amount(d.Sessions.sum(),0));c[1].metric('Recorded web orders',amount(d.Orders.sum(),0));c[2].metric('Orders / sessions',pct(ratio(d.Orders.sum(),d.Sessions.sum())));plot(px.line(d,x='Date',y='Sessions'));plot(px.line(d,x='Date',y='Orders'));st.caption('Sessions and orders use separate axes/charts. Web orders are a distinct modeled analytics ledger, not silently reconciled with Sales_Transactions.');table(d,'web_funnel')
    elif operation=='Customer service':
        d=event_rows('customer_service','Open_Date');c=st.columns(3);c[0].metric('Tickets opened',len(d));c[1].metric('Mean first response minutes',amount(d.First_Response_Minutes.mean(),1));c[2].metric('Recorded mean CSAT',amount(d.CSAT_1_to_5.mean(),2));st.caption('Final recorded resolution/CSAT for tickets opened in the period; resolution timestamp is not available for an as-of historical status reconstruction.');table(d,'support_tickets')
    else:
        d=t['group_operations'];d=d[d.Month.between(start.to_period('M').to_timestamp(),end.to_period('M').to_timestamp())];st.caption('Whole-month unit KPIs for months overlapping the historical dates. Different business units have different KPI units; volumes are not summed into a meaningless total.');table(d,'group_operations')
    if d.empty:st.info('No events match this report and period.')

elif page=='AI Copilot':
    chat_key=(branch,category,str(start.date()),str(end.date()),DB.stat().st_mtime_ns)
    render_chat(t,scope,viewinv,viewf,products,branch,category,start,end,origin,DB,chat_key,table,plot)

elif page=='High Season':
    render_season(t,scope,viewf,viewinv,plot,table)

elif page=='Annual Count':
    render_count(t,branch,category,DB,table,amount)

elif page=='Annual Closing':
    render_annual(t,scope,branch,category,DB,table,plot,amount)

elif page=='Live Business Report':
    from reporting import render_report
    render_report(t,scope,viewf,viewinv,products,branch,category,start,end,origin,DB,registry,table,plot,amount)

    with st.expander('Business discoveries & unusual days'):
        cards(insight_cards(scope,start,end,ps,pe,viewinv,complete))
        st.subheader('Observed product momentum · selected historical windows')
        d=products[products.Period_Units.gt(0)|products.Previous_Units.gt(0)].sort_values('Unit_Change',ascending=False)
        table(d[['Product_ID','Product_Name','Period_Units','Previous_Units','Unit_Change','Historical_Unit_Growth','Period_Net_After_Refunds','Period_Margin_Before_Returns']],'historical_product_momentum')
        st.subheader('Seasonal memory · scope history up to selected end')
        h=scope[scope.Order_Date<=end].assign(Month=lambda d:d.Order_Date.dt.month,Year=lambda d:d.Order_Date.dt.year).groupby(['Year','Month']).Quantity.sum().reset_index();plot(px.line(h,x='Month',y='Quantity',color='Year',markers=True))
        st.caption('Available months only; incomplete current years are not treated as full annual totals.')
        st.subheader('Scoped unusual days')
        available=t['scoped_anomalies'];matched=available[available.Scope_Branch.eq(branch)&available.Scope_Category.eq(category)].copy()
        if matched.empty:st.warning('No trained anomaly model is available for this scope.')
        else:
            observed=matched[matched.Order_Date.between(start,end)];flagged=observed[observed.Flag.eq(1)]
            st.caption(f'{len(observed):,} days evaluated; {len(flagged):,} flagged in this exact scope and period.')
            if observed.empty:st.info('No evaluated days overlap this period. Early history may precede the 28-day feature warm-up.')
            elif flagged.empty:st.success('No unusual days were flagged for this scope and period. This does not mean every business outcome is healthy.')
            show_all=st.checkbox('Show all evaluated days',False,key='all_anomaly_days');shown=observed if show_all else flagged
            if len(shown):table(shown[['Order_Date','Units','Revenue','Rolling_Units','Deviation','Reference_Score_Percentile','Flag','Evaluation_Type','Explanation']],'scoped_anomalies')
        st.caption('A separate anomaly model was trained offline for this exact branch/category scope. Reference percentile is unusualness against training scores, not a probability of error/fraud. Anomalies and correlations do not establish causes or cannibalization.')
    with st.expander('Action review & follow-up',expanded=True):
        st.subheader('Review evidence before acting');state=action_state();show=st.checkbox('Include dismissed and acknowledged',False)
        risks=st.multiselect('Action types',sorted(viewinv.Risk.unique()),default=sorted(viewinv.Risk.unique()))
        d=viewinv[viewinv.Risk.isin(risks)].sort_values(['Data_Issue','Central_Shortage_Units'],ascending=False)
        limit=st.number_input('Maximum actions to display',1,max(1,len(d)),min(20,max(1,len(d))))
        for r in d.head(limit).itertuples():
            aid=f'{r.Product_ID}:{r.Location_ID}:{t["forecasts"].Month.min():%Y-%m}';status=state.get(aid,'Open')
            if status!='Open' and not show:continue
            with st.container(border=True):
                st.markdown(f'**{r.Product_ID} · {r.Location_Name} · {r.Risk} · {status}**')
                c=st.columns(4);c[0].metric('Reported stock',amount(r.Closing_Stock,0));c[1].metric('Allocated monthly units',amount(r.Forecast,1));c[2].metric('Approximate coverage days',amount(r.Coverage_Days,1));c[3].metric('Next-month stockout model',pct(r.Stockout_Probability))
                if r.Data_Issue:st.warning('No production or transfer recommendation: reconcile this current stock position first.')
                elif r.Risk=='Replenish':st.write(f'Planning quantity before unapproved transfers: {r.Net_Production_Need:,.0f} units. Proposed transfer alternative: {r.Proposed_Transfer_In:,.0f} units. Approve transfer assumptions explicitly in Inventory Command before netting them.')
                elif r.Risk=='Excess':st.write(f'Upper-band excess estimate: {r.Excess:,.0f} units. Review transfer or a supported price scenario; no causal promotion uplift is promised.')
                else:st.write('No forecast coverage trigger. Maintain observation; inspect the separate stockout classifier if it raises an alert.')
                st.caption(f'Central forecast gap {r.Central_Shortage_Units:,.1f} units. Revenue exposure ceiling EGP {r.Revenue_Exposure_Estimate:,.2f}, based on historical unit invoiced revenue; not proven lost or recoverable sales. Confidence band: {r.Forecast_Confidence}.')
                c=st.columns(3)
                for col,label,status in zip(c,['Acknowledge','Dismiss','Reopen'],['Acknowledged','Dismissed','Open']):
                    col.button(label,key=aid+label,on_click=set_action,args=(aid,status))
        if d.empty:st.info('No positions match this scope.')

elif page=='Model Center':
    for name in ['demand','stockout','customers','segments','anomaly','price']:
        with st.expander(name.upper(),expanded=name=='demand'):st.json(registry[name])
    h=sales.assign(Month=sales.Order_Date.dt.to_period('M').dt.to_timestamp()).groupby(['Month','Product_ID']).Quantity.sum().rename('Units').reset_index();months=sorted(h.Month.unique());a=h[h.Month.isin(months[-3:])].groupby('Product_ID').Units.mean();b=h[h.Month.isin(months[-15:-12])].groupby('Product_ID').Units.mean();change=(a-b)/b.replace(0,np.nan);table(change.rename('Same_season_mean_change').reset_index(),'same_season_shift')
    st.caption('Same-season observed change is a drift indicator, not proof of deployed model degradation. There are no post-origin actuals to score deployment forecasts.')
    for name in ['stockout','customers']:
        importance=registry[name].get('feature_importance',{})
        if importance:plot(px.bar(pd.DataFrame({'Feature':list(importance),'Importance':list(importance.values())}),x='Importance',y='Feature',orientation='h',title=name))
    st.caption('Impurity feature importance is model-wide, not per-record SHAP or causal evidence.');table(t['forecast_test'],'company_holdout')

elif page=='Data Quality':
    st.subheader('Dates · missing versus not applicable');a=t['date_audit'];c=st.columns(3);c[0].metric('Missing date cells',int(a.total_missing.sum()));c[1].metric('Not applicable',int(a.not_applicable.sum()));c[2].metric('Applicable unresolved dates',int(a.unrecoverable.sum()));table(a,'date_audit')
    table(t['issues'],'source_integrity');table(t['quality'],'column_quality')
    recon=pd.read_csv(ROOT/'data/validation/inventory_sales_reconciliation.csv');table(recon[recon.Difference.ne(0)],'inventory_sales_reconciliation')
    st.subheader('Current planning exclusions');table(viewinv[viewinv.Data_Issue][['Product_ID','Location_ID','Snapshot_Month','Closing_Stock','Data_Issue']],'current_planning_exclusions')
    st.subheader('Accounting definitions and audit');st.markdown((ROOT/'reports/V2_CALCULATION_AUDIT.md').read_text())
    st.download_button('Download full calculation audit',(ROOT/'reports/V2_CALCULATION_AUDIT.md').read_bytes(),'V2_CALCULATION_AUDIT.md')
