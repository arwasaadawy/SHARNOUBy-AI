"""Annual close and physical-count workspaces, independent of ML training."""
import io,json,calendar,re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from src.annual import ADJUSTMENT_KINDS,adjustments,annual_report,annual_bundle,add_adjustment,void_adjustment,count_sheet,reconcile_count,save_count,saved_counts
from src.seasonality import high_season,season_products

def year_picker(sales,key):
    years=list(range(sales.Order_Date.min().year,sales.Order_Date.max().year+1))
    complete=[y for y in years if sales.Order_Date.min()<=pd.Timestamp(y,1,1) and sales.Order_Date.max()>=pd.Timestamp(y,12,31)]
    preferred=max(complete) if complete else max(years)
    return st.selectbox('Calendar year',years,index=years.index(preferred),key=key)

def render_annual(t,scope,branch,category,db,table,plot,amount):
    allsales=t['sales_transactions'];year=year_picker(allsales,'closing_year');entries=adjustments(db)
    report=annual_report(scope,year,entries,branch,category,allsales.Order_Date.min(),allsales.Order_Date.max())
    st.caption(f'ANNUAL REPORT SCOPE · {branch} / {category} · calendar year {year}. The year selector governs this page; the historical date filter is disabled.')
    if not report['complete_year']:st.warning(f'Incomplete source year: {report["coverage_start"]:%d %b %Y}–{report["coverage_end"]:%d %b %Y}. This is a partial-year report, not a completed annual close.')
    st.info('Sales are invoices after discounts, less refunds on their return dates. These are not collected cash or receivables. Cost of goods is ESTIMATED in the supplied records. Net profit cannot be certified from this dataset.')
    a,b,c,d=st.columns(4);a.metric('Distinct invoices',amount(report['kpis']['Orders'],0));b.metric('Net recorded sales after refunds','EGP '+amount(report['kpis']['Net_After_Refunds']));c.metric('Estimated gross profit before refunds','EGP '+amount(report['estimated_gross_profit']));d.metric('Estimated result after entered adjustments','EGP '+amount(report['estimated_result']))
    if report['excluded_adjustments']:st.warning(f'{report["excluded_adjustments"]} ledger entries do not match this slice and were excluded. Company-wide/unallocated costs are never silently assigned to a branch/category; slice results may omit those costs.')
    st.download_button('Download annual closing pack (.zip)',annual_bundle(report),f'annual_closing_{year}.zip','application/zip',key='annual_bundle')
    tabs=st.tabs(['Yearly result','Invoice & refund register','Expenses & adjustments'])
    with tabs[0]:
        st.warning('The final result remains an estimate. Missing operating/finance/tax costs and unsupported returned-goods cost recovery can materially change it. Zero entered expenses does not mean zero real expenses.')
        table(report['profit'],'annual_profit_'+str(year));plot(px.bar(report['monthly'],x='Month',y=['Invoiced_Net_Sales','Refunds','Net_After_Refunds'],barmode='group'));table(report['monthly'],'annual_months_'+str(year))
        st.caption('Formula: net recorded sales after event-date refunds − estimated sold COGS + documented manual return COGS recovery − entered expenses. No automatic tax calculation, VAT separation, cash reconciliation or COGS reversal. Inventory remains an asset proxy, not sales revenue. Purchase-order costs are not deducted again on top of sold COGS.')
    with tabs[1]:
        invoice_search=st.text_input('Search invoice ID',key='annual_invoice_search')
        invoices=report['invoices'];visible=invoices[invoices.Invoice_ID.str.contains(invoice_search,case=False,regex=False)] if invoice_search else invoices
        st.caption(f'Visible register: {len(visible):,} invoices; invoiced net sales EGP {visible.Invoiced_Net_Sales.sum():,.2f}. Search changes this register only, not annual cards.')
        table(visible,'annual_invoices_'+str(year));st.subheader('Refund events within the year · including earlier-year purchases');table(report['refunds'],'annual_refunds_'+str(year))
        if len(invoices) and invoices.Identity_Conflict.any():st.error('Conflicting invoice date/location/customer identities exist. Reconcile them before closing.')
        st.caption('Invoice register reconciles to invoiced net sales. Refund events reconcile separately by Return_Date; refunds of prior-year invoices may not be rows in the current sales register. No payment settlement status is inferred.')
    with tabs[2]:
        st.caption('Enter expense DOCUMENT totals that are not already included in Estimated_COGS. Record rent, wages, utilities, marketing and other operating costs using a reference. Tax/finance costs must come from reviewed records. Return COGS recovery needs evidence of recoverable goods cost; do not enter the refund value as recovered cost.')
        with st.form('annual_expense_form'):
            day=st.date_input('Expense/adjustment event date',value=min(pd.Timestamp(year,12,31),allsales.Order_Date.max()).date(),min_value=pd.Timestamp(year,1,1).date(),max_value=min(pd.Timestamp(year,12,31),allsales.Order_Date.max()).date(),key='expense_day_'+str(year))
            kind=st.selectbox('Entry type',ADJUSTMENT_KINDS);value=st.number_input('Documented amount (EGP)',0.,1e12,0.,step=100.)
            reference=st.text_input('Document/reference (required)');note=st.text_input('Description / source')
            st.caption(f'Saved at scope {branch} / {category}. All/All means unallocated company-wide cost.')
            if st.form_submit_button('Save annual entry'):
                try:add_adjustment(db,day,kind,value,branch,category,reference,note);st.session_state['annual_saved']='Annual entry saved.';st.rerun()
                except ValueError as e:st.error(str(e))
        if st.session_state.pop('annual_saved',None):st.success('Annual entry saved; result recalculated.')
        table(report['adjustments'],'annual_adjustments_'+str(year))
        if len(report['adjustments']):
            choices=report['adjustments'].entry_id.tolist();lookup=report['adjustments'].set_index('entry_id')
            selected=st.selectbox('Entry to reverse',choices,format_func=lambda x:lookup.loc[x,'reference']+' · '+str(lookup.loc[x,'amount']))
            if st.button('Reverse selected entry (retain audit history)'):void_adjustment(db,selected);st.rerun()
        with st.expander('Full adjustment audit · including reversed records'):table(entries,'annual_ledger_audit')

def render_count(t,branch,category,db,table,amount):
    year=year_picker(t['sales_transactions'],'count_year');sheet,cutoff=count_sheet(t['inventory_history'],t['sales_transactions'],t['product_master'],year,branch,category)
    if sheet.empty:st.info('No book inventory positions match this year/scope.');return
    st.caption(f'BOOK CUTOFF · {cutoff:%d %b %Y} · {branch} / {category}. Product × branch grain; no size/color inventory ledger was supplied.')
    if cutoff.month!=12:st.warning('No December closing inventory is available for this year. This is an interim count at the displayed cutoff; it is not a 31 December annual count.')
    st.info('Enter physically counted units at this book cutoff, or import a completed count CSV. Blank means NOT COUNTED; zero means counted and absent. Counts recorded today cannot be compared as if they were historical counts. Same-date source inventory is needed for a current count.')
    st.caption('Book stock is not changed by saving a count. Value columns use past-365-day estimated sales COGS/unit as a proxy, not audited stock valuation. Flagged book positions remain visible for reconciliation.')
    st.download_button('Download blank physical count sheet',sheet.to_csv(index=False).encode('utf-8-sig'),f'count_{cutoff:%Y%m%d}.csv',key='count_template')
    upload=st.file_uploader('Import completed count CSV',type=['csv'],key='count_upload_'+str(year)+'_'+branch+'_'+category)
    editor_key='count_editor_'+str(year)+'_'+branch+'_'+category
    if upload is not None:
        try:edited=pd.read_csv(upload,dtype={'Product_ID':str,'Location_ID':str});reconciled=reconcile_count(sheet,edited)
        except (ValueError,pd.errors.ParserError,UnicodeError) as e:st.error(str(e));return
    else:
        edited=st.data_editor(sheet,hide_index=True,width='stretch',num_rows='fixed',disabled=[c for c in sheet if c!='Actual_Units'],column_config={'Actual_Units':st.column_config.NumberColumn('Physical count',min_value=0,step=1)},key=editor_key)
        try:reconciled=reconcile_count(sheet,edited)
        except ValueError as e:st.error(str(e));return
    counted=reconciled[reconciled.Counted];a,b,c=st.columns(3);a.metric('Positions physically counted',f'{len(counted)} / {len(sheet)}');b.metric('Net difference · counted only',amount(counted.Difference_Units.sum(),0));c.metric('Positions requiring reconciliation',amount((counted.Difference_Units.ne(0)|counted.Book_Data_Issue).sum(),0))
    if len(counted):
        st.caption(f'Shortages: {abs(counted.loc[counted.Difference_Units.lt(0),"Difference_Units"].sum()):,.0f} units; surpluses: {counted.loc[counted.Difference_Units.gt(0),"Difference_Units"].sum():,.0f} units. Netting does not hide gross differences. Unpriced counted positions: {counted.Unit_Cost_Proxy.isna().sum()}.')
    table(reconciled,'physical_count_reconciliation')
    note=st.text_input('Count reference / counted-at-cutoff confirmation (required)',key='count_note')
    if st.button('Save physical count snapshot',disabled=counted.empty):
        try:
            session=save_count(db,sheet,edited,cutoff,branch,category,note);st.success('Saved count '+session[:8]+'. Ledger stock remains unchanged.')
        except ValueError as e:st.error(str(e))
    sessions,lines=saved_counts(db)
    scoped=sessions[sessions.branch.eq(branch)&sessions.category.eq(category)]
    with st.expander('Saved count history',expanded=False):
        table(scoped,'count_sessions')
        if len(scoped):
            selected=st.selectbox('Saved count',scoped.session_id.tolist(),format_func=lambda k:scoped.set_index('session_id').loc[k,'cutoff']+' · '+k[:8]);table(lines[lines.session_id.eq(selected)],'saved_count_lines')
    st.caption('Count differences require review of receipts, sales, returns, damage and counting errors. They are not automatically recognized as expense, fraud or lost revenue. An approved write-down can be entered separately in Annual Closing after review, avoiding duplicate cost recognition.')

def render_season(t,scope,viewf,viewinv,plot,table):
    begin=t['sales_transactions'].Order_Date.min();origin=t['sales_transactions'].Order_Date.max()
    threshold=st.slider('High-season threshold · multiple of same-year average month',1.0,2.0,1.2,.05)
    summary,history,years=high_season(scope,begin,origin,threshold)
    if summary.empty:st.info('A complete calendar year is required to analyze seasonality.');return
    st.caption('Calendar-month demand index = recorded month units / mean month units in that complete year; average across complete years '+', '.join(map(str,years))+'. This is a historical seasonal signal, not a causal explanation or a new forecast.')
    plot(px.bar(summary,x='Month',y='Seasonal_Index',color='High_Season_Signal'));table(summary,'high_season_calendar');plot(px.line(history,x='Month',y='Units',color='Year',markers=True))
    if len(years)<2:st.warning('Only one full year: recurrence cannot be established. High-season recommendations are unavailable.')
    month=st.selectbox('Prepare for calendar month',list(range(1,13)),index=origin.month%12,format_func=lambda x:calendar.month_name[x],key='season_month')
    target=pd.Timestamp(origin.year,month,1)
    if target<=origin:target=pd.Timestamp(origin.year+1,month,1)
    buffer=st.number_input('Preparation buffer (days) · assumption',0,120,14,step=1)
    d=season_products(scope,years,month,viewf,viewinv,target,buffer)
    st.caption(f'Next occurrence: {target:%b %Y}. Prepare-by uses supplier lead time plus your buffer; it does not model factory queues, transport or intervening sales. Forecast gap is shown only for supported trained horizons and fully reconciled product positions.')
    if not pd.to_datetime(viewf.Month).eq(target).any():st.warning('This target is outside the trained forecast horizon. Historical target-month averages are descriptive only; no future forecast or production quantity is invented.')
    table(d,'season_product_plan');st.caption('Rank products by measured seasonal index and demand. Complete-year historical patterns can change; holiday/event dates are not inferred from calendar-month patterns. Use Forecasting Center and Production Planner for supported future quantities.')

def render_chat(t,scope,viewinv,viewf,products,branch,category,start,end,origin,db,context_key,table,plot):
    from src.chat import chat_answer,export_conversation
    from src.analytics import customer_audience
    st.caption('English-only offline data assistant. All answers use local evidence; no API key or connection is required.')
    year=year_picker(t['sales_transactions'],'chat_year')
    chat_key=tuple(context_key)+(year,)
    if st.session_state.get('chat_scope_key')!=chat_key:
        st.session_state['chat_messages']=[];st.session_state['chat_context']={};st.session_state['chat_scope_key']=chat_key
    if st.button('Clear conversation'):
        st.session_state['chat_messages']=[];st.session_state['chat_context']={};st.rerun()
    samples=['What are the top 5 actions I should take?',f'Calculate annual profit {year}',f'Show invoices {year}','Predict year-end profit','Which months show high seasonal demand?',f'Help with annual physical count {year}','Explain Product P017']
    sample=st.selectbox('Suggested question',samples,key='chat_sample')
    quick=st.button('Get evidence',type='primary')
    prompt=st.chat_input('Ask a business question in English…',key='business_chat_input')
    question=prompt or (sample if quick else None)
    messages=st.session_state['chat_messages']
    if question and re.search(r'[\u0600-\u06ff]',question):st.warning('Please ask in English.');question=None
    if question:
        data={'sales':scope,'all_sales':t['sales_transactions'],'inventory':viewinv,'inventory_history':t['inventory_history'],'master':t['product_master'],'forecasts':viewf,'products':products,'monthly':scope.assign(Month=scope.Order_Date.dt.to_period('M').dt.to_timestamp()).groupby(['Month','Product_ID']).Quantity.sum().rename('Units').reset_index(),'customers':customer_audience(scope,t['customers'],t['customer_scores'],start,end,True),'anomalies':t['scoped_anomalies'][t['scoped_anomalies'].Scope_Branch.eq(branch)&t['scoped_anomalies'].Scope_Category.eq(category)],'annual_adjustments':adjustments(db),'period_start':start,'period_end':end,'available_start':t['sales_transactions'].Order_Date.min(),'forecast_origin':origin,'scope_label':branch+' / '+category,'branch':branch,'category':category}
        try:
            history=[{'role':m['role'],'content':m['content']} for m in messages]
            with st.spinner('Retrieving verified evidence…'):result,resolved=chat_answer(question,data,st.session_state['chat_context'],history,default_year=year)
            if result['intent']=='invoices' and isinstance(result['EVIDENCE'],pd.DataFrame) and len(result['EVIDENCE'])>100:
                result['ANSWER']+=f' Showing the first 100 of {len(result["EVIDENCE"]):,} invoices; full register is in Finance & Closing.';result['EVIDENCE']=result['EVIDENCE'].head(100)
            def english_value(value):
                if isinstance(value,str):return re.sub(r'[\u0600-\u06ff]+','[source text]',value)
                if isinstance(value,pd.DataFrame):
                    value=value.copy()
                    for col in value.select_dtypes(include=['object','string']):value[col]=value[col].map(lambda x:english_value(x) if isinstance(x,str) else x)
                return value
            for field in ['ANSWER','EVIDENCE','PREDICTION','WHY','RECOMMENDATION','CONFIDENCE']:result[field]=english_value(result.get(field))
            messages.extend([{'role':'user','content':question},{'role':'assistant','content':result['ANSWER'],'result':result,'scope':branch+' / '+category,'year':resolved['year']}]);del messages[:-20]
            st.session_state['chat_context']=resolved
        except Exception as e:st.error(f'Could not retrieve evidence ({type(e).__name__}). Check the local source data; no result was fabricated.')
    if not messages:st.info('Try: Calculate annual profit 2025 → What about the previous year? Or: Explain P017 → Why?')
    for j,m in enumerate(messages):
        with st.chat_message(m['role']):
            if m['role']=='user':st.write(m['content']);continue
            result=m['result'];st.caption(result['mode']+' · '+m['scope'])
            if result.get('llm_error'):st.warning(result['llm_error'])
            if result.get('narrative'):st.write(result['narrative']);st.caption('AI qualitative interpretation. Verify decisions against the evidence below.')
            st.markdown('**Answer**');st.write(result['ANSWER'])
            for name in ['EVIDENCE','PREDICTION']:
                value=result.get(name)
                if value is not None:
                    with st.expander(name,expanded=name=='EVIDENCE'):
                        if isinstance(value,pd.DataFrame):table(value,'chat_'+str(j)+'_'+name)
                        else:st.write(value)
            with st.expander('Why, recommendation & confidence'):
                for name in ['WHY','RECOMMENDATION','CONFIDENCE']:st.markdown('**'+name+'**');st.write(result[name])
            if result['intent']=='comparison' and isinstance(result['EVIDENCE'],pd.DataFrame):plot(px.bar(result['EVIDENCE'],x='Product_Family',y=['Current','Previous'],barmode='group'))
    if messages:st.download_button('Export conversation & evidence',export_conversation(messages),'sharnouby_conversation.json','application/json',key='chat_export')

def profit_controls(branch,category,origin):
    current_scope=(branch,category,str(origin.date()))
    if st.session_state.get('profit_assumption_scope')!=current_scope:
        for widget in ['profit_price','profit_cost','profit_fulfillment','profit_budget_known','profit_expenses','profit_target']:st.session_state.pop(widget,None)
        st.session_state['profit_assumption_scope']=current_scope
    st.caption(f'SOURCE YEAR {origin.year} · observed through {origin:%d %b %Y}. Recorded year-to-date result is kept separate from the modeled remaining months.')
    st.info('This is a conditional financial forecast from validated demand × historical net selling price/cost, with a historical return-event ratio. It is not a separately trained net-profit model. Future sold COGS remains estimated; cash, taxes and unrecorded costs are not invented.')
    a,b,c=st.columns(3)
    price=a.slider('Future net selling price change (%) · constant demand assumption',-50,50,0,1,key='profit_price')/100
    cost=b.slider('Future unit COGS change (%)',-50,100,0,1,key='profit_cost')/100
    fulfillment=c.slider('Assumed demand fulfillment (%)',0,100,100,1,key='profit_fulfillment')/100
    st.caption('Fulfillment is an editable supply assumption, not a guarantee derived from current inventory. It includes your assumed replenishment/capacity. Price changes alter valuation only; no causal price-demand response is claimed.')
    budget_known=st.checkbox('I have entered a reviewed remaining-period expense budget',False,key='profit_budget_known')
    budget=st.number_input('Remaining operating/finance/tax expense budget (EGP)',0.,1e12,0.,step=1000.,disabled=not budget_known,key='profit_expenses') if budget_known else None
    if budget_known:st.caption('Treat this budget as fixed for the remaining-period break-even calculation. Enter only costs not already in sold COGS; do not duplicate source-year ledger expenses. Tax estimates need reviewed inputs, not an automatic percentage.')
    target=st.number_input('Full-year result target (EGP) · planning assumption',-1e12,1e12,0.,step=100000.,key='profit_target')
    return budget,price,cost,fulfillment,target


def render_profit_forecast(t,scope,viewf,branch,category,origin,db,table,plot,amount):
    from src.profit_forecast import profit_outlook
    budget,price,cost,fulfillment,target=profit_controls(branch,category,origin)
    try:r=profit_outlook(scope,viewf,origin,adjustments(db),branch,category,t['sales_transactions'].Order_Date.min(),budget,price,cost,fulfillment,target)
    except ValueError as e:st.warning(str(e));return
    if not r['coverage_complete']:st.warning('Forecast horizons do not cover all remaining months. Full-year result and target gap are unavailable; missing months are not extrapolated.')
    if budget is None:st.warning('Remaining expense budget is missing. Displayed totals are BEFORE missing future expenses, not a net-profit prediction. Zero real expenses is not inferred.')
    if r['facts']['excluded_adjustments']:st.warning('Some ledger entries are outside this scope. Company-wide costs are not silently allocated; this branch/category result may exclude those costs.')
    st.caption('YTD includes only documented ledger expenses. Confirm expense completeness in Annual Closing. Even with a reviewed future budget, results remain estimates because COGS and forecasts are uncertain.')
    central=r['scenarios'][r['scenarios'].Scenario.eq('Central assumptions')].iloc[0]
    a,b,c=st.columns(3);a.metric('Recorded YTD estimated result','EGP '+amount(r['facts']['estimated_result']));b.metric('Remaining-period contribution before expenses','EGP '+amount(central.Contribution_Before_Future_Expenses));c.metric('Year-end estimate'+(' before missing future expenses' if budget is None else ' after entered budget'),'EGP '+amount(central.Full_Year_Result_Estimate))
    table(r['scenarios'],'year_end_profit_scenarios');plot(px.line(r['monthly'],x='Month',y='Contribution_Before_Future_Expenses',color='Scenario',markers=True));table(r['monthly'],'profit_forecast_months')
    st.caption('Stress cases are NOT probability-weighted scenarios or a calibrated annual confidence interval. Lower case uses marginal lower demand, +5 percentage points unit-cost stress, and ×1.25 refund-rate stress (capped at 100%). Upper case uses marginal upper demand. All other inputs are yours. Negative product margins may reverse the profit ordering of demand cases.')
    with st.expander('Product economics and forecast drivers',expanded=False):table(r['details'],'profit_forecast_product_economics');table(r['rates'],'profit_financial_rate_evidence')
    st.subheader('Margin Watch · product economics requiring review')
    table(r['margin_watch'].head(10),'profit_margin_watch')
    st.caption('Lowest projected contribution ratios under central assumptions; negative contribution means modeled sales do not cover estimated sold COGS after refunds. Review source costs/discounts before changing production; this is not an automatic stop-producing order.')
    st.subheader('Break-even & target gap · same product mix and unit economics')
    z=r['targets'];a,b,c=st.columns(3);a.metric('Remaining-period break-even net sales','EGP '+amount(z['Remaining_Period_BreakEven_Net_Sales']));b.metric('Gap to full-year target','EGP '+amount(z['Target_Gap']));c.metric('Additional net sales needed for target','EGP '+amount(z['Additional_Net_Sales_For_Target']))
    if not np.isfinite(z['Contribution_Ratio']) or z['Contribution_Ratio']<=0:st.warning('Current modeled mix has no positive contribution ratio. Increasing the same mix cannot cover fixed costs; break-even is unavailable.')
    if budget is None:st.caption('Enter a reviewed budget to calculate remaining-period break-even. A displayed target gap before missing expenses is provisional.')
    st.caption('Target arithmetic assumes constant product mix, prices, unit costs and fixed remaining expenses. It is not additional demand predicted by the model or proof of sufficient capacity. Net sales here are after estimated refunds.')
    metrics=t.get('profit_forecast_validation');registry_path=None
    if metrics is not None:
        st.subheader('Company-wide frozen-rate temporal backtest · contribution proxy only');st.caption('Validation metrics are for the company-wide holdout, not separately validated branch/category profit forecasts.');table(metrics,'profit_temporal_backtest')
    st.download_button('Export year-end forecast assumptions & results',json.dumps({'origin':str(origin.date()),'branch':branch,'category':category,'price_change':price,'cost_change':cost,'fulfillment':fulfillment,'remaining_expenses':budget,'target':target,'scenarios':json.loads(r['scenarios'].to_json(orient='records')),'targets':z,'warning':'Conditional estimate; missing costs and estimated COGS; stress cases are not calibrated intervals'},default=str,ensure_ascii=False,indent=2).encode(),file_name='year_end_profit_plan.json',mime='application/json',key='profit_plan_export')


def production_controls(branch,category):
    scope=(branch,category)
    saved=st.session_state.get('production_inputs',{})
    if saved.get('scope')!=scope:saved={}
    a,b,c,d=st.columns(4)
    result={
        'capacity':a.number_input('Monthly available capacity (units)',0,1000000,int(saved.get('capacity',5000)),step=500,key='plan_capacity'),
        'unit_cost':b.number_input('Reference production cost per unit (EGP)',0.,10000.,float(saved.get('unit_cost',100.)),key='plan_unit_cost'),
        'penalty':c.number_input('Shortage penalty per unit (EGP)',0.,10000.,float(saved.get('penalty',200.)),key='plan_penalty'),
        'holding':d.number_input('Excess carrying cost per unit (EGP)',0.,1000.,float(saved.get('holding',10.)),key='plan_holding'),
    }
    result['transfers_approved']=st.checkbox('Include proposed transfers as a planning assumption',bool(saved.get('transfers_approved',False)),key='plan_transfers')
    st.session_state['production_inputs']=dict(result,scope=scope)
    return result
