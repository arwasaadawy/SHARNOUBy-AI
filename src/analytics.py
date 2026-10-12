"""One definition of scope, dates, money and evidence shared by every workspace."""
import numpy as np
import pandas as pd

DATE_FIELDS=['Order_Date','Return_Date','Snapshot_Month','Month','Date','Open_Date','Start_Date','End_Date','Completion_Date','Due_Date','Print_Date','Inspection_Date','Promised_Date','Actual_Receipt_Date']
def normalize(df):
    d=df.copy()
    for c in DATE_FIELDS:
        if c in d:d[c]=pd.to_datetime(d[c],errors='coerce')
    return d

def ratio(a,b):
    return float(a/b) if pd.notna(b) and b!=0 else np.nan

def select_scope(sales,master,branch='All',category='All'):
    ids=master.loc[master.Product_Family.eq(category) if category!='All' else pd.Series(True,index=master.index),'Product_ID']
    s=sales[sales.Product_ID.isin(ids)]
    if branch!='All':s=s[s.Location_Name.eq(branch)]
    return s.copy(),list(ids)

def comparison_dates(start,end,calendar=False):
    start,end=pd.Timestamp(start).normalize(),pd.Timestamp(end).normalize()
    full_month=start.day==1 and end==(start+pd.offsets.MonthEnd(0))
    if calendar or full_month:
        cur_start=end.to_period('M').to_timestamp();cur_end=end
        prev_start=cur_start-pd.offsets.MonthBegin(1)
        prev_end=prev_start+pd.offsets.MonthEnd(0) if end==cur_start+pd.offsets.MonthEnd(0) else min(prev_start+pd.Timedelta(days=end.day-1),prev_start+pd.offsets.MonthEnd(0))
        return cur_start,cur_end,prev_start,prev_end,'Previous calendar month' if full_month else 'Previous month-to-date'
    days=(end-start).days+1
    return start,end,start-pd.Timedelta(days=days),start-pd.Timedelta(days=1),'Previous equal-length period'

def period_sales(s,start,end):return s[s.Order_Date.between(pd.Timestamp(start),pd.Timestamp(end))].copy()
def refunds_in_period(s,start,end):
    return s[s.Returned.eq('Yes')&s.Return_Date.between(pd.Timestamp(start),pd.Timestamp(end))].copy()

def financial_kpis(s,start,end):
    orders=period_sales(s,start,end);refunds=refunds_in_period(s,start,end)
    invoiced=float(orders.Net_Sales_EGP.sum());returns=float(refunds.Refund_Value_EGP.sum());n=int(orders.Invoice_ID.nunique())
    return dict(Invoiced_Net_Sales=invoiced,Refunds_By_Return_Date=returns,Net_After_Refunds=invoiced-returns,Units=int(orders.Quantity.sum()),Orders=n,Active_Products=int(orders.Product_ID.nunique()),AOV=ratio(invoiced,n),Estimated_Profit_Before_Returns=float(orders.Gross_Profit_EGP.sum()),Estimated_Margin_Before_Returns=ratio(orders.Gross_Profit_EGP.sum(),invoiced),Return_Events=int(refunds.Invoice_ID.nunique()))

def money_by(s,start,end,key):
    sales=period_sales(s,start,end).groupby(key).Net_Sales_EGP.sum().rename('Invoiced')
    refunds=refunds_in_period(s,start,end).groupby(key).Refund_Value_EGP.sum().rename('Refunds')
    d=pd.concat([sales,refunds],axis=1).fillna(0);d['Net_After_Refunds']=d.Invoiced-d.Refunds
    return d

def daily_money(s,start,end):
    a=period_sales(s,start,end).groupby('Order_Date').Net_Sales_EGP.sum().rename('Invoiced')
    b=refunds_in_period(s,start,end).groupby('Return_Date').Refund_Value_EGP.sum().rename('Refunds')
    d=pd.concat([a,b],axis=1).reindex(pd.date_range(start,end,freq='D')).fillna(0);d.index.name='Date';d['Net_After_Refunds']=d.Invoiced-d.Refunds
    return d.reset_index()

def category_comparison(s,start,end,prev_start,prev_end):
    a=money_by(s,start,end,'Product_Family').Net_After_Refunds.rename('Current')
    b=money_by(s,prev_start,prev_end,'Product_Family').Net_After_Refunds.rename('Previous')
    d=pd.concat([a,b],axis=1).fillna(0);d['Change']=d.Current-d.Previous;d['Growth']=np.where(d.Previous>0,d.Change/d.Previous,np.nan)
    return d.reset_index()

def product_facts(s,master,start,end,prev_start,prev_end):
    current=period_sales(s,start,end);previous=period_sales(s,prev_start,prev_end)
    a=current.groupby('Product_ID').agg(Period_Units=('Quantity','sum'),Period_Invoiced=('Net_Sales_EGP','sum'),Period_Profit=('Gross_Profit_EGP','sum'),Period_Orders=('Invoice_ID','nunique'))
    b=previous.groupby('Product_ID').Quantity.sum().rename('Previous_Units')
    refunds=refunds_in_period(s,start,end).groupby('Product_ID').Refund_Value_EGP.sum().rename('Period_Refunds')
    d=master.merge(pd.concat([a,b,refunds],axis=1).reset_index(),on='Product_ID',how='left')
    cols=['Period_Units','Period_Invoiced','Period_Profit','Period_Orders','Previous_Units','Period_Refunds'];d[cols]=d[cols].fillna(0)
    d['Period_Net_After_Refunds']=d.Period_Invoiced-d.Period_Refunds;d['Unit_Change']=d.Period_Units-d.Previous_Units
    d['Historical_Unit_Growth']=np.where(d.Previous_Units>0,d.Unit_Change/d.Previous_Units,np.nan)
    d['Period_Margin_Before_Returns']=np.where(d.Period_Invoiced>0,d.Period_Profit/d.Period_Invoiced,np.nan)
    return d

def allocate_forecasts(f,sales,locations,origin):
    """Shares always computed across the company; branch filters never renormalize to 100%."""
    recent=sales[sales.Order_Date.between(origin-pd.Timedelta(days=89),origin)]
    qty=recent.groupby(['Product_ID','Location_ID']).Quantity.sum().rename('Location_Units').reset_index()
    qty['Share']=qty.Location_Units/qty.groupby('Product_ID').Location_Units.transform('sum')
    d=f.merge(qty[['Product_ID','Location_ID','Share']],on='Product_ID',how='left')
    for c in ['Units','Lower','Upper']:d[c]=d[c]*d.Share
    return d.merge(locations[['Location_ID','Location_Name']],on='Location_ID',how='left')

def forecast_view(f,sales,locations,ids,branch,origin):
    d=f[f.Product_ID.isin(ids)].copy()
    if branch!='All':
        d=allocate_forecasts(d,sales,locations,origin);d=d[d.Location_Name.eq(branch)]
    return d

def inventory_plan(inventory_history,stock_scores,sales,forecasts,locations,ids,branch,origin,use_transfers=False):
    from .inventory import decisions
    raw=normalize(inventory_history);snapshot=raw.Snapshot_Month.max();latest=raw[raw.Snapshot_Month.eq(snapshot)].copy()
    ps=stock_scores[['Product_ID','Location_ID','Stockout_Probability','Flag']].drop_duplicates(['Product_ID','Location_ID'])
    latest=latest.merge(ps,on=['Product_ID','Location_ID'],how='left',validate='one_to_one')
    plan,transfers=decisions(latest,forecasts,sales)
    balance=latest.Opening_Stock+latest.Received_Qty-latest.Sold_Qty+latest.Returned_Qty-latest.Damaged_Qty-latest.Closing_Stock
    ledger_sales=sales[sales.Order_Date.dt.to_period('M').eq(snapshot.to_period('M'))].groupby(['Product_ID','Location_ID']).Quantity.sum()
    flags={ (r.Product_ID,r.Location_ID):bool(balance.loc[j]!=0 or abs(r.Sold_Qty-ledger_sales.get((r.Product_ID,r.Location_ID),0))>0) for j,r in latest.iterrows()}
    plan['Data_Issue']=[flags[(r.Product_ID,r.Location_ID)] for r in plan.itertuples()]
    # Recompute transfers after excluding unreconciled stock positions.
    plan['Transfer_In']=0;plan['Transfer_Out']=0;valid=plan[~plan.Data_Issue].copy();rows=[]
    for pid,g in valid.groupby('Product_ID'):
        donors={j:int(r.Excess) for j,r in g.iterrows() if r.Excess>0}
        for j,r in g.sort_values('Suggested_Units',ascending=False).iterrows():
            need=int(r.Suggested_Units)
            for k in donors:
                qty=min(need,donors[k])
                if qty>0 and k!=j:
                    rows.append(dict(Product_ID=pid,From=plan.loc[k,'Location_ID'],To=r.Location_ID,Units=qty,Assumption='Proposed only; exclude unreconciled stock, approve route/time/cost'))
                    donors[k]-=qty;need-=qty;plan.loc[j,'Transfer_In']+=qty;plan.loc[k,'Transfer_Out']+=qty
    transfers=pd.DataFrame(rows,columns=['Product_ID','From','To','Units','Assumption'])
    plan['Proposed_Transfer_In']=plan.Transfer_In;plan['Proposed_Transfer_Out']=plan.Transfer_Out
    if not use_transfers:plan['Transfer_In']=0;plan['Transfer_Out']=0
    plan['Net_Production_Need']=(plan.Suggested_Units-plan.Transfer_In).clip(lower=0).astype(int)
    plan['Risk_Before_Audit']=plan.Risk;plan.loc[plan.Data_Issue,'Risk']='Review data'
    plan['Coverage_Days']=np.where(plan.Daily_Demand>0,plan.Closing_Stock/plan.Daily_Demand,np.nan)
    plan['Central_Shortage_Units']=(plan.Forecast-plan.Closing_Stock).clip(lower=0)
    plan['Recommendation_Eligible']=~plan.Data_Issue
    plan=plan[plan.Product_ID.isin(ids)]
    if branch!='All':
        selected_locations=locations.loc[locations.Location_Name.eq(branch),'Location_ID']
        plan=plan[plan.Location_ID.isin(selected_locations)]
        transfers=transfers[transfers.From.isin(selected_locations)|transfers.To.isin(selected_locations)]
    transfers=transfers[transfers.Product_ID.isin(ids)]
    return plan,transfers,snapshot

def customer_audience(s,customers,scores,start,end,consent=True,mode='Period purchasers'):
    period=period_sales(s,start,end);h=s[s.Order_Date.between(end-pd.Timedelta(days=364),end)]
    allowed=set(period.Customer_ID) if mode=='Period purchasers' else set(s.loc[s.Order_Date<=end,'Customer_ID'])
    rfm=h.groupby('Customer_ID').agg(last=('Order_Date','max'),frequency=('Invoice_ID','nunique'),monetary_before_refunds=('Net_Sales_EGP','sum'),units=('Quantity','sum'))
    # Include earlier known buyers even if inactive for more than a year.
    last_all=s[s.Order_Date<=end].groupby('Customer_ID').Order_Date.max()
    base=pd.DataFrame({'Customer_ID':pd.Series(sorted(allowed),dtype=object)}).merge(rfm.reset_index(),on='Customer_ID',how='left')
    base['last']=base.Customer_ID.map(last_all);base['recency']=(end-base['last']).dt.days
    for c in ['frequency','monetary_before_refunds','units']:base[c]=base[c].fillna(0)
    base['RFM_Segment']=np.select([base.recency>180,(base.recency<=60)&(base.frequency>=3),base.frequency<=2],['Inactive >180 days','Recent frequent','Low frequency'],default='Regular')
    agg=period.groupby('Customer_ID').agg(Scope_Orders=('Invoice_ID','nunique'),Scope_Units=('Quantity','sum'),Scope_Invoiced_Net_Sales=('Net_Sales_EGP','sum'))
    refunds=refunds_in_period(s,start,end).groupby('Customer_ID').Refund_Value_EGP.sum().rename('Scope_Refunds')
    scope=pd.concat([agg,refunds],axis=1).fillna(0);scope['Scope_Net_After_Refunds']=scope.Scope_Invoiced_Net_Sales-scope.Scope_Refunds
    base=base.merge(scope.reset_index(),on='Customer_ID',how='left').merge(customers[['Customer_ID','Consent_Status','Governorate','Acquisition_Channel']],on='Customer_ID',how='left')
    for c in scope.columns:base[c]=base[c].fillna(0)
    base=base.merge(scores[['Customer_ID','Repeat_90D_Probability']],on='Customer_ID',how='left')
    if consent:base=base[base.Consent_Status.eq('Opted-in')]
    return base

def insight_cards(s,start,end,previous_start,previous_end,inv,comparison_complete=True):
    cur=financial_kpis(s,start,end);old=financial_kpis(s,previous_start,previous_end);cards=[]
    if comparison_complete:
        change=cur['Net_After_Refunds']-old['Net_After_Refunds'];growth=ratio(change,old['Net_After_Refunds']) if old['Net_After_Refunds']>0 else np.nan
        cards.append(dict(Type='FACT',Title='Recorded sales movement',Evidence=f"EGP {cur['Net_After_Refunds']:,.2f} vs EGP {old['Net_After_Refunds']:,.2f}; difference EGP {change:+,.2f}."+(f' Change {growth:+.1%}.' if pd.notna(growth) else ' Percentage unavailable because baseline is nonpositive.'),Action='Inspect the contributions below; a change alone does not establish its cause.'))
        d=category_comparison(s,start,end,previous_start,previous_end)
        if len(d):
            r=d.loc[d.Change.abs().idxmax()];cards.append(dict(Type='FACT',Title='Largest category contribution',Evidence=f"{r.Product_Family}: EGP {r.Change:+,.2f} of the total arithmetic movement. All category changes sum to EGP {d.Change.sum():+,.2f}.",Action='Review product and channel mix. This is arithmetic attribution, not a causal explanation.'))
    else:cards.append(dict(Type='FACT',Title='Comparison not available',Evidence='The previous comparison window extends before available sales history.',Action='Choose a later period before interpreting growth.'))
    good=inv[inv.Recommendation_Eligible] if 'Recommendation_Eligible' in inv else inv
    if len(good):
        r=good.sort_values('Central_Shortage_Units',ascending=False).iloc[0]
        if r.Central_Shortage_Units>0:cards.append(dict(Type='PREDICTION + RECOMMENDATION',Title='Largest forecast coverage gap',Evidence=f"{r.Product_ID} / {r.Location_Name}: allocated next-month units {r.Forecast:,.1f}, stock {r.Closing_Stock:,.0f}, central gap {r.Central_Shortage_Units:,.1f}, planning quantity {r.Net_Production_Need:,.0f}. Forecast reliability category (historical WAPE): {r.Forecast_Confidence}.",Action='Check supply lead time and transfer availability before approving production. This is a forecast gap, not proven lost sales.'))
    if 'Data_Issue' in inv and inv.Data_Issue.any():cards.append(dict(Type='FACT',Title='Planning data needs reconciliation',Evidence=f'{int(inv.Data_Issue.sum())} selected current stock positions fail arithmetic or sales-ledger reconciliation.',Action='Review these positions in Data Quality. They are excluded from production optimization and transfer donor/recipient plans.'))
    return pd.DataFrame(cards)
