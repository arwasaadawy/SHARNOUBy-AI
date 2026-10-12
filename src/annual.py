"""Invoice reconciliation, explicit annual profit estimates and auditable physical counts.
No cash/receivables, VAT, tax policy or actual COGS is inferred from sales records.
"""
import json, sqlite3, uuid
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from .analytics import normalize, financial_kpis, period_sales, refunds_in_period

ADJUSTMENT_KINDS=['Operating expense','Finance cost','Tax expense','Inventory write-down','Return COGS recovery']

def ensure_workspace(db):
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE IF NOT EXISTS annual_adjustments (entry_id TEXT PRIMARY KEY, event_date TEXT NOT NULL, kind TEXT NOT NULL, amount REAL NOT NULL CHECK(amount>=0), branch TEXT NOT NULL, category TEXT NOT NULL, reference TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL, voided INTEGER NOT NULL DEFAULT 0)')
        c.execute('CREATE TABLE IF NOT EXISTS count_sessions (session_id TEXT PRIMARY KEY, cutoff TEXT NOT NULL, branch TEXT NOT NULL, category TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS count_lines (session_id TEXT NOT NULL, Product_ID TEXT NOT NULL, Location_ID TEXT NOT NULL, book_units REAL NOT NULL, actual_units REAL NOT NULL, difference REAL NOT NULL, unit_cost_proxy REAL, data_issue INTEGER NOT NULL, PRIMARY KEY(session_id,Product_ID,Location_ID), FOREIGN KEY(session_id) REFERENCES count_sessions(session_id))')

def adjustments(db):
    ensure_workspace(db)
    with sqlite3.connect(db) as c:return pd.read_sql_query('SELECT * FROM annual_adjustments ORDER BY event_date,created_at',c)

def add_adjustment(db,event_date,kind,amount,branch,category,reference,note=''):
    if kind not in ADJUSTMENT_KINDS:raise ValueError('Unsupported adjustment type')
    amount=float(amount)
    if not np.isfinite(amount) or amount<0:raise ValueError('Amount must be finite and nonnegative')
    if abs(amount-round(amount,2))>1e-9:raise ValueError('Money entries must use at most two decimal places')
    if not str(reference).strip():raise ValueError('A document/reference is required')
    date=pd.Timestamp(event_date)
    if pd.isna(date):raise ValueError('A valid event date is required')
    ensure_workspace(db);key=uuid.uuid4().hex
    with sqlite3.connect(db) as c:
        existing=c.execute('SELECT 1 FROM annual_adjustments WHERE event_date=? AND kind=? AND branch=? AND category=? AND reference=? AND voided=0',(str(date.date()),kind,branch,category,reference.strip())).fetchone()
        if existing:raise ValueError('This date/type/scope/reference already exists; review the ledger before duplicating it')
        c.execute('INSERT INTO annual_adjustments VALUES (?,?,?,?,?,?,?,?,?,0)',(key,str(date.date()),kind,amount,branch,category,reference.strip(),note.strip(),datetime.now(timezone.utc).isoformat()))
    return key

def void_adjustment(db,key):
    ensure_workspace(db)
    with sqlite3.connect(db) as c:c.execute('UPDATE annual_adjustments SET voided=1 WHERE entry_id=?',(key,))

def selected_adjustments(entries,year,branch='All',category='All'):
    if entries.empty:return entries.copy(),0
    d=entries.copy();d['event_date']=pd.to_datetime(d.event_date)
    d=d[d.event_date.dt.year.eq(int(year))&d.voided.eq(0)]
    # Company costs never silently allocated to a filtered business slice.
    mask=pd.Series(True,index=d.index)
    if branch!='All':mask &= d.branch.eq(branch)
    if category!='All':mask &= d.category.eq(category)
    excluded=int((~mask).sum())
    return d[mask],excluded

def invoice_register(s,year):
    s=normalize(s);start=pd.Timestamp(int(year),1,1);end=pd.Timestamp(int(year),12,31)
    d=period_sales(s,start,end)
    if d.empty:return pd.DataFrame(columns=['Invoice_ID','Order_Date','Location_Name','Lines','Units','Gross_Before_Discount','Discount_Value','Invoiced_Net_Sales','Estimated_COGS','Estimated_Gross_Profit_Before_Returns','Refunds_In_Year','Identity_Conflict'])
    out=d.groupby('Invoice_ID').agg(Order_Date=('Order_Date','min'),Location_Name=('Location_Name','first'),Lines=('Invoice_ID','size'),Units=('Quantity','sum'),Gross_Before_Discount=('Gross_Sales_EGP','sum'),Invoiced_Net_Sales=('Net_Sales_EGP','sum'),Estimated_COGS=('Estimated_COGS_EGP','sum'),Estimated_Gross_Profit_Before_Returns=('Gross_Profit_EGP','sum'))
    out['Discount_Value']=out.Gross_Before_Discount-out.Invoiced_Net_Sales
    r=refunds_in_period(s,start,end).groupby('Invoice_ID').Refund_Value_EGP.sum()
    out['Refunds_In_Year']=out.index.map(r).fillna(0)
    conflicts=d.groupby('Invoice_ID')[['Order_Date','Location_ID','Customer_ID']].nunique().gt(1).any(axis=1)
    out['Identity_Conflict']=out.index.map(conflicts)
    return out.reset_index()

def annual_report(s,year,entries=None,branch='All',category='All',available_start=None,available_end=None):
    """Sales must already be scoped; branch/category govern expense attribution only."""
    s=normalize(s);year=int(year);start=pd.Timestamp(year,1,1);end=pd.Timestamp(year,12,31)
    amin=pd.Timestamp(available_start if available_start is not None else s.Order_Date.min());amax=pd.Timestamp(available_end if available_end is not None else s.Order_Date.max())
    full=bool(pd.notna(amin) and pd.notna(amax) and amin<=start and amax>=end)
    k=financial_kpis(s,start,end);sold=period_sales(s,start,end);refunds=refunds_in_period(s,start,end)
    selected,excluded=selected_adjustments(entries if entries is not None else pd.DataFrame(),year,branch,category)
    if len(selected):selected=selected[pd.to_datetime(selected.event_date)<=min(end,amax)]
    totals=selected.groupby('kind').amount.sum().to_dict() if len(selected) else {}
    cogs=float(sold.Estimated_COGS_EGP.sum());pre=float(sold.Net_Sales_EGP.sum())-cogs
    recovery=float(totals.get('Return COGS recovery',0));expenses=sum(float(totals.get(kind,0)) for kind in ADJUSTMENT_KINDS if kind!='Return COGS recovery')
    after=k['Net_After_Refunds']-cogs+recovery-expenses
    profit=pd.DataFrame({'Component':['Gross sales before discounts','Discounts','Invoiced net sales','Refunds by return date','Net sales after refunds','Estimated sold COGS','Estimated gross profit before refunds','Manual return COGS recovery','Entered operating/finance/tax/write-down expenses','Estimated result after entered adjustments'], 'EGP':[float(sold.Gross_Sales_EGP.sum()),float((sold.Gross_Sales_EGP-sold.Net_Sales_EGP).sum()),k['Invoiced_Net_Sales'],k['Refunds_By_Return_Date'],k['Net_After_Refunds'],cogs,pre,recovery,expenses,after]})
    monthly=[]
    for month in range(1,13):
        ms=pd.Timestamp(year,month,1);me=ms+pd.offsets.MonthEnd(0)
        present=pd.notna(amin) and pd.notna(amax) and ms<=amax and me>=amin
        mk=financial_kpis(s,ms,me) if present else {}
        monthly.append(dict(Month=ms,Coverage='Full month' if present and amin<=ms and amax>=me else ('Partial source coverage' if present else 'Outside source history'),Invoiced_Net_Sales=mk.get('Invoiced_Net_Sales',np.nan),Refunds=mk.get('Refunds_By_Return_Date',np.nan),Net_After_Refunds=mk.get('Net_After_Refunds',np.nan),Orders=mk.get('Orders',np.nan),Estimated_Profit_Before_Returns=mk.get('Estimated_Profit_Before_Returns',np.nan)))
    return dict(year=year,complete_year=full,coverage_start=max(start,amin) if pd.notna(amin) else None,coverage_end=min(end,amax) if pd.notna(amax) else None,kpis=k,estimated_gross_profit=pre,estimated_result=after,expenses=expenses,recovery=recovery,excluded_adjustments=excluded,profit=profit,monthly=pd.DataFrame(monthly),invoices=invoice_register(s,year),refunds=refunds[['Invoice_ID','Order_Date','Return_Date','Product_ID','Location_Name','Refund_Value_EGP']],adjustments=selected)

def count_sheet(history,sales,master,year,branch='All',category='All'):
    h=normalize(history);s=normalize(sales);year=int(year)
    available=h[h.Snapshot_Month.dt.year.eq(year)]
    if available.empty:return pd.DataFrame(),None
    month=available.Snapshot_Month.max();cutoff=month+pd.offsets.MonthEnd(0)
    d=available[available.Snapshot_Month.eq(month)].copy()
    if d.duplicated(['Product_ID','Location_ID']).any():raise ValueError('Duplicate book positions; reconcile before creating a count sheet')
    ids=master.loc[master.Product_Family.eq(category),'Product_ID'] if category!='All' else master.Product_ID
    d=d[d.Product_ID.isin(ids)]
    if branch!='All':d=d[d.Location_Name.eq(branch)]
    costs=s[s.Order_Date.between(cutoff-pd.Timedelta(days=364),cutoff)].groupby('Product_ID').agg(cost=('Estimated_COGS_EGP','sum'),units=('Quantity','sum'))
    costs['Unit_Cost_Proxy']=costs.cost/costs.units.replace(0,np.nan)
    d=d.merge(costs[['Unit_Cost_Proxy']],on='Product_ID',how='left')
    bal=d.Opening_Stock+d.Received_Qty-d.Sold_Qty+d.Returned_Qty-d.Damaged_Qty-d.Closing_Stock
    sold=s[s.Order_Date.dt.to_period('M').eq(month.to_period('M'))].groupby(['Product_ID','Location_ID']).Quantity.sum()
    d['Book_Data_Issue']=[bool(bal.loc[j]!=0 or r.Sold_Qty!=sold.get((r.Product_ID,r.Location_ID),0)) for j,r in d.iterrows()]
    d['Book_Units']=d.Closing_Stock;d['Book_Value_Proxy']=d.Book_Units*d.Unit_Cost_Proxy;d['Actual_Units']=np.nan
    return d[['Product_ID','Product_Name','Location_ID','Location_Name','Book_Units','Unit_Cost_Proxy','Book_Value_Proxy','Book_Data_Issue','Actual_Units']],cutoff

def reconcile_count(sheet,edited):
    keys=['Product_ID','Location_ID'];required=keys+['Actual_Units']
    if not set(required).issubset(edited.columns):raise ValueError('CSV must contain Product_ID, Location_ID, Actual_Units')
    e=edited[required].copy()
    if e.duplicated(keys).any():raise ValueError('Duplicate count positions')
    allowed=set(map(tuple,sheet[keys].to_numpy()));given=set(map(tuple,e[keys].to_numpy()))
    if not given.issubset(allowed):raise ValueError('Counts contain products/branches outside this sheet')
    original=e.Actual_Units;e['Actual_Units']=pd.to_numeric(original,errors='coerce')
    nonblank=original.notna()&original.astype(str).str.strip().ne('')
    if (nonblank&e.Actual_Units.isna()).any():raise ValueError('Count values must be numeric or blank')
    observed=e.Actual_Units.dropna()
    if not np.isfinite(observed).all() or (observed<0).any() or (observed%1!=0).any():raise ValueError('Physical counts must be finite nonnegative whole units')
    d=sheet.drop(columns='Actual_Units').merge(e,on=keys,how='left',validate='one_to_one')
    d['Counted']=d.Actual_Units.notna();d['Difference_Units']=d.Actual_Units-d.Book_Units;d['Difference_Value_Proxy']=d.Difference_Units*d.Unit_Cost_Proxy
    return d

def save_count(db,sheet,edited,cutoff,branch,category,note):
    if not str(note).strip():raise ValueError('A count reference/note is required')
    if pd.isna(pd.Timestamp(cutoff)):raise ValueError('A valid cutoff is required')
    d=reconcile_count(sheet,edited);d=d[d.Counted]
    if d.empty:raise ValueError('Enter at least one actual count; blank is not zero')
    ensure_workspace(db);key=uuid.uuid4().hex
    with sqlite3.connect(db) as c:
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('INSERT INTO count_sessions VALUES (?,?,?,?,?,?)',(key,str(pd.Timestamp(cutoff).date()),branch,category,note.strip(),datetime.now(timezone.utc).isoformat()))
        c.executemany('INSERT INTO count_lines VALUES (?,?,?,?,?,?,?,?)',[(key,r.Product_ID,r.Location_ID,float(r.Book_Units),float(r.Actual_Units),float(r.Difference_Units),None if pd.isna(r.Unit_Cost_Proxy) else float(r.Unit_Cost_Proxy),int(r.Book_Data_Issue)) for r in d.itertuples()])
    return key

def saved_counts(db):
    ensure_workspace(db)
    with sqlite3.connect(db) as c:
        sessions=pd.read_sql_query('SELECT * FROM count_sessions ORDER BY created_at DESC',c)
        lines=pd.read_sql_query('SELECT * FROM count_lines',c)
    return sessions,lines


def annual_bundle(report):
    from io import BytesIO
    from zipfile import ZipFile,ZIP_DEFLATED
    buffer=BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as archive:
        for name in ['profit','monthly','invoices','refunds','adjustments']:
            archive.writestr(name+'.csv',report[name].to_csv(index=False).encode('utf-8-sig'))
        archive.writestr('READ_ME.txt',f"Calendar year: {report['year']}\nComplete source year: {report['complete_year']}\nNet sales use sale dates less refund event dates. COGS and profit are estimates. Entered expenses may be incomplete. This pack is not certified financial statements or cash reconciliation.\n")
    return buffer.getvalue()
