"""Read-only tool-backed copilot. Local deterministic routing; facts come from data."""
import re
import pandas as pd
TOOLS=['overview','actions','forecast','product','opportunities','customers','anomalies','comparison','inventory','annual','invoices','season','count','profit_outlook']
def route(question):
    q=question.lower();pid=re.search(r'\bp\d{3}\b',q,re.I)
    if pid:return 'product',pid.group().upper()
    if any(w in q for w in ['produce next','produce next month','أنتج','انتج']):return 'opportunities',None
    rules=[('forecast',['forecast','next month','توقع','الشهر الجاي','القادم']),('comparison',['compare','changed','declin','drop','قارن','انخفض','قلت','تغير']),('inventory',['branch','transfer','stock','فرع','مخزون','نقل']),('opportunities',['opportun','produce next','فرص','أنتج','انتج']),('customers',['customer','repeat','عميل','عملاء']),('anomalies',['anomal','unusual','شذوذ','غير طبيعي']),('actions',['action','risk','promote','stop produc','أعمل','اعمل','خطر','اوقف','روّج'])]
    for intent,words in rules:
        if any(w in q for w in words):return intent,None
    return 'overview',None

def answer(question,tables,use_llm=False):
    from .analytics import normalize,comparison_dates,financial_kpis,category_comparison,product_facts
    intent,pid=route(question)
    s=normalize(tables['sales']);inv=tables['inventory'];f=normalize(tables['forecasts']);products=tables['products']
    origin=pd.Timestamp(tables.get('forecast_origin',s.Order_Date.max()));end=pd.Timestamp(tables.get('period_end',s.Order_Date.max()));start=pd.Timestamp(tables.get('period_start',end-pd.Timedelta(days=29)))
    calendar=intent=='comparison' and any(w in question.lower() for w in ['this month','last month','الشهر','calendar'])
    cs,ce,ps,pe,basis=comparison_dates(start,end,calendar)
    label=tables.get('scope_label','All company');complete=ps>=pd.Timestamp(tables.get('available_start',s.Order_Date.min()))
    out={'intent':intent,'ANSWER':'','EVIDENCE':None,'PREDICTION':None,'WHY':'','RECOMMENDATION':'','CONFIDENCE':'','mode':'Offline deterministic scoped evidence assistant (not an LLM)'}
    if intent in ['actions','inventory']:
        eligible=inv[inv.Recommendation_Eligible] if 'Recommendation_Eligible' in inv else inv
        key='Central_Shortage_Units' if 'Central_Shortage_Units' in inv else 'Revenue_Exposure_Estimate'
        evidence=eligible.sort_values(key,ascending=False).head(5)
        out.update(ANSWER=f'Current planning priorities for {label}; forecast origin {origin:%d %b %Y}.',EVIDENCE=evidence[['Product_ID','Location_Name','Closing_Stock','Coverage_Days','Risk']],PREDICTION=evidence[['Product_ID','Forecast','Stockout_Probability','Forecast_Confidence','Net_Production_Need']],WHY='Allocated product forecasts are compared with latest reported inventory. Classifier probability and forecast gap are different measures; neither proves lost sales.',RECOMMENDATION='Review data reconciliation, supply lead time and proposed transfers before approving production. Exact depletion dates are not modeled.',CONFIDENCE='Product WAPE bands and classifier test diagnostics; recommendations are conditional on inventory validity.')
    elif intent=='forecast':
        out.update(ANSWER=f'Three monthly horizons for {label}, fixed origin {origin:%d %b %Y}.',EVIDENCE=tables['monthly'].groupby('Month').Units.sum().tail(12).reset_index(),PREDICTION=f[['Product_ID','Month','Units','Lower','Upper','Confidence']],WHY='Past units and temporal validation select the model. A branch slice uses explicit recent-unit allocation shares; it is not a separately validated branch model.',RECOMMENDATION='Use uncertainty and reconciliation checks in the planning workspaces.',CONFIDENCE='Empirical marginal bands; branch-scaled intervals are proxies, not calibrated probabilities.')
    elif intent=='product':
        d=products[products.Product_ID.eq(pid)]
        if d.empty:out.update(ANSWER='Product was not found within the selected scope.',WHY='No invented replacement product or numbers.',CONFIDENCE='Unavailable')
        else:
            cols=[c for c in ['Product_ID','Period_Net_After_Refunds','Period_Units','Historical_Unit_Growth','Revenue','Units90','Segment'] if c in d]
            out.update(ANSWER=f'{pid}: {d.iloc[0].Product_Name} · {label}',EVIDENCE=d[cols],PREDICTION=f[f.Product_ID.eq(pid)],WHY='Historical values follow the scope and period. Forecasts retain their latest training origin. Catalog similarity is not basket evidence.',RECOMMENDATION='Inspect scoped coverage and material/supply constraints before producing.',CONFIDENCE=str(d.iloc[0].get('Confidence','See model metrics')))
    elif intent=='opportunities':
        if 'Unit_Change' in products:
            d=products[products.Period_Units.gt(0)&products.Unit_Change.gt(0)&products.Period_Margin_Before_Returns.gt(0)].sort_values('Unit_Change',ascending=False).head(8)
            eligible=inv[inv.Recommendation_Eligible] if 'Recommendation_Eligible' in inv else inv
            d=d.merge(eligible.groupby('Product_ID').Net_Production_Need.sum().reset_index(),on='Product_ID',how='left')
            evidence=d[['Product_ID','Product_Name','Period_Units','Previous_Units','Historical_Unit_Growth','Period_Margin_Before_Returns']]
            pred=d[['Product_ID','Next_Month_Units','Confidence','Net_Production_Need']]
        else:
            d=products.sort_values('Expected_Growth',ascending=False).head(8);evidence=d[['Product_ID','Product_Name','Revenue','Units90']];pred=f[f.Product_ID.isin(d.Product_ID)]
        out.update(ANSWER=f'Observed positive unit momentum with positive estimated pre-return margin in {label}.' if len(d) else 'No product meets the positive-momentum and positive-margin evidence screen.',EVIDENCE=evidence,PREDICTION=pred,WHY='Historical growth and current forecast are separate evidence. A seasonal next-month increase alone does not establish an emerging product.',RECOMMENDATION='Consider a bounded production test only when inventory and uncertainty support it.',CONFIDENCE='Opportunity screen, not a success probability for new designs.')
    elif intent=='customers':
        d=tables['customers'];columns=[c for c in ['Customer_ID','Repeat_90D_Probability'] if c in d]
        out.update(ANSWER=f'Customer audience for {label}; consent and historical scope are applied by the evidence tool.',EVIDENCE=d.groupby('RFM_Segment').size().rename('Customers').reset_index(),PREDICTION=d.sort_values('Repeat_90D_Probability',ascending=False).head(10)[columns],WHY='Scoped historical RFM describes behavior. Repeat scores predict any company-wide purchase at the latest model origin, not purchases within a category.',RECOMMENDATION='Inspect consent and unavailable score values before exporting an audience.',CONFIDENCE='Repeat model has modest temporal discrimination; do not treat scores as certainty.')
    elif intent=='anomalies':
        d=normalize(tables['anomalies']);d=d[d.Order_Date.between(start,end)&d.Flag.eq(1)].sort_values('Anomaly_Score',ascending=False).head(10)
        out.update(ANSWER=f'Unusual recorded days in {label}, {start:%d %b}–{end:%d %b %Y}.',EVIDENCE=d,WHY='The available scope model flags statistical unusualness. It does not establish the cause.',RECOMMENDATION='Check transactions, channel mix, availability and calendar events.',CONFIDENCE='Unsupervised flags; no labeled anomaly precision is claimed.')
    else:
        cur=financial_kpis(s,cs,ce);old=financial_kpis(s,ps,pe);growth=(cur['Net_After_Refunds']/old['Net_After_Refunds']-1) if complete and old['Net_After_Refunds']>0 else None
        comp=category_comparison(s,cs,ce,ps,pe)
        if not complete:comp[['Previous','Change','Growth']]=float('nan')
        evidence=comp if intent=='comparison' else pd.DataFrame({'Metric':['Invoiced net sales','Refunds by return date','Net after refunds','Units before returns','Orders','Growth versus previous window'],'Value':[cur['Invoiced_Net_Sales'],cur['Refunds_By_Return_Date'],cur['Net_After_Refunds'],cur['Units'],cur['Orders'],growth]})
        growth_text=f' ({growth:+.1%} vs {basis.lower()})' if growth is not None else ' (percentage change unavailable)'
        out.update(ANSWER=f'{label}, {cs:%d %b}–{ce:%d %b %Y}: EGP {cur["Net_After_Refunds"]:,.2f} net recorded sales after event-date refunds'+growth_text+'.',EVIDENCE=evidence,PREDICTION=f[f.horizon.eq(1)][['Product_ID','Units','Lower','Upper','Confidence']],WHY='Sales use Order_Date; refunds use Return_Date, including older purchases. Category changes sum to the total arithmetic change; they do not establish causal drivers.',RECOMMENDATION='Inspect the largest product/category contributions and latest inventory evidence.',CONFIDENCE='Recorded arithmetic is exact within the supplied modeled data; future forecasts are uncertain.')
    return out
