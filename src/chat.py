"""Conversational interface over allowlisted evidence; persistent session context.
Numeric reports always come from local tools.
"""
import json,re
import pandas as pd
from .copilot import answer,route
from .annual import annual_report,count_sheet
from .seasonality import high_season

MONTHS={'يناير':1,'فبراير':2,'مارس':3,'ابريل':4,'أبريل':4,'مايو':5,'يونيو':6,'يوليو':7,'اغسطس':8,'أغسطس':8,'سبتمبر':9,'اكتوبر':10,'أكتوبر':10,'نوفمبر':11,'ديسمبر':12,'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,'august':8,'september':9,'october':10,'november':11,'december':12}

def interpret(question,context,default_year):
    q=question.lower().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩','0123456789'));explicit=re.search(r'\b(20\d{2})\b',q);year=int(explicit.group()) if explicit else int(context.get('year',default_year))
    if not explicit and any(w in q for w in ['السنة اللي قبل','السنه اللي قبل','السنة السابقة','السنه السابقه','previous year','year before','السنة الي قبل']):year-=1
    if any(w in q for w in ['ربح','أرباح','ارباح','بروفيت','profit']) and any(w in q for w in ['توقع','متوقع','predict','forecast','نهاية السنة','نهاية السنه','year end','year-end']):intent='profit_outlook'
    elif any(w in q for w in ['هاي سيزون','هاى سيزون','high season','high-season','موسم','مواسم','seasonal','seasonality','peak']):intent='season'
    elif any(w in q for w in ['جرد','physical count','annual count']):intent='count'
    elif any(w in q for w in ['فاتور','فواتير','invoice']):intent='invoices'
    elif any(w in q for w in ['ربح','أرباح','ارباح','بروفيت','profit','سنوي','سنوى','annual','السنة','السنه','year']):intent='annual'
    else:
        intent,pid=route(q)
        follow=any(w in q for w in ['طب','طيب','نفس','ليه','لماذا','why','what about','and ','للسنة','السنة اللي قبل','previous year','year before'])
        if follow and intent=='overview' and context.get('intent'):intent=context['intent']
    pid_match=re.search(r'\bp\d{3}\b',q,re.I);pid=pid_match.group().upper() if pid_match else (context.get('product_id') if intent=='product' else None)
    if pid_match and intent not in ['annual','invoices','season','count','profit_outlook']:intent='product'
    month=next((value for word,value in MONTHS.items() if word in q),context.get('month'))
    return {'intent':intent,'product_id':pid,'year':year,'month':month}

def chat_answer(question,tables,context=None,history=None,use_llm=False,default_year=None,llm_config=None):
    context=context or {};history=history or [];all_sales=tables.get('all_sales',tables['sales']);latest=pd.Timestamp(all_sales.Order_Date.max())
    default_year=default_year or latest.year;resolved=interpret(question,context,default_year)
    if resolved['intent']=='profit_outlook' and not re.search(r'20\d{2}',question.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩','0123456789'))):resolved['year']=latest.year
    intent=resolved['intent'];pid=resolved['product_id'];year=resolved['year'];label=tables.get('scope_label','All company')
    if intent=='profit_outlook':
        from .profit_forecast import profit_outlook
        if year!=latest.year:
            report={'intent':intent,'ANSWER':'Financial forecasting is available only for the source year.','EVIDENCE':None,'PREDICTION':None,'WHY':'No backdated or out-of-horizon annual profit forecast is invented.','RECOMMENDATION':'Open Year-End Profit for supported forecast months.','CONFIDENCE':'Unavailable for the requested year'}
        else:
            r=profit_outlook(tables['sales'],tables['forecasts'],latest,tables.get('annual_adjustments'),tables.get('branch','All'),tables.get('category','All'),all_sales.Order_Date.min())
            report={'intent':intent,'ANSWER':f'Year-end {year} estimate before missing future expenses; not certified net profit.','EVIDENCE':r['facts']['profit'],'PREDICTION':r['scenarios'],'WHY':'Demand is validated separately. Net price, estimated unit cost and return-event ratios are frozen historical assumptions. No future expense budget was supplied through chat.','RECOMMENDATION':'Open Year-End Profit and enter reviewed expenses, cost changes and fulfillment assumptions; inspect break-even and the target gap.','CONFIDENCE':'Conditional financial estimate; stress scenarios are not calibrated annual intervals.'}
    elif intent in ['annual','invoices']:
        r=annual_report(tables['sales'],year,tables.get('annual_adjustments'),tables.get('branch','All'),tables.get('category','All'),all_sales.Order_Date.min(),all_sales.Order_Date.max())
        if pd.Timestamp(year,12,31)<all_sales.Order_Date.min() or pd.Timestamp(year,1,1)>all_sales.Order_Date.max():
            report={'intent':intent,'ANSWER':f'No source coverage is available for {year}.','EVIDENCE':None,'PREDICTION':None,'WHY':'No financial totals are invented for years outside source history.','RECOMMENDATION':'Choose an available year in Annual Closing.','CONFIDENCE':'Unavailable'}
        else:
            report={'intent':intent,'ANSWER':f'{label} · {year} · '+('Complete source year.' if r['complete_year'] else 'Partial source year; not a completed annual close.')+f' Net recorded sales after refunds EGP {r["kpis"]["Net_After_Refunds"]:,.2f}. Estimated result after entered adjustments EGP {r["estimated_result"]:,.2f}.','EVIDENCE':r['invoices'] if intent=='invoices' else r['profit'],'PREDICTION':None,'WHY':'Invoices use sale dates; refunds use return dates. COGS is estimated. Expenses and return cost recovery are explicitly entered; missing expenses are not assumed absent. No cash, tax or certified net profit inference.','RECOMMENDATION':'Review Annual Closing, add documented expenses, reconcile invoices/refunds and complete physical counts before approving the annual statement.','CONFIDENCE':'Recorded arithmetic; profit estimate depends on COGS and expense completeness.'}
            if r['excluded_adjustments']:report['WHY']+=f' {r["excluded_adjustments"]} adjustment entries were excluded from this scope; unallocated costs may remain.'
    elif intent=='season':
        d,h,years=high_season(tables['sales'],all_sales.Order_Date.min(),latest)
        if resolved['month']:d=d[d.Month.eq(resolved['month'])] if len(d) else d
        report={'intent':intent,'ANSWER':f'Seasonal patterns for {label}, based on complete years '+', '.join(map(str,years))+'.' if years else 'No complete years are available for seasonality analysis.','EVIDENCE':d.sort_values('Seasonal_Index',ascending=False) if len(d) else d,'PREDICTION':None,'WHY':'Index compares a recorded month with that same year average; partial years are excluded. High-season signal requires at least two complete years and index ≥1.2. It is not a future forecast or a holiday calendar.','RECOMMENDATION':'Open High Season, select the target month and review validated forecasts only within their trained horizon.','CONFIDENCE':'Historical pattern; limited number of complete years.'}
    elif intent=='count':
        d,cutoff=count_sheet(tables['inventory_history'],all_sales,tables['master'],year,tables.get('branch','All'),tables.get('category','All'))
        report={'intent':intent,'ANSWER':f'Available book inventory for {year}: '+(f'{cutoff:%d %b %Y}; {len(d)} product/location positions.' if cutoff is not None else 'No book inventory is available.'),'EVIDENCE':d,'PREDICTION':None,'WHY':'Book stock is not a physical count. Blank actual counts remain unknown. Value is a past COGS proxy; historical cutoff must match count evidence.','RECOMMENDATION':'Open Annual Count, enter/import actual counts at the stated cutoff, reconcile differences and save a separate audit snapshot. No book stock is modified by chat.','CONFIDENCE':'Physical verification required; no invented actual counts.'}
    else:
        routed_question='Explain '+pid if intent=='product' and pid else {'overview':'overview','actions':'actions','forecast':'forecast','product':'product','opportunities':'opportunities','customers':'customers','anomalies':'anomalies','comparison':'Compare selected period','inventory':'stock'}.get(intent,question)
        report=answer(routed_question,tables,False)
        if not pid and intent=='overview' and not any(w in question.lower() for w in ['overview','sales','status','مبيعات','ملخص','الحالة','بيزنس']):report['ANSWER']='I can help with sales, forecasts, inventory, seasonal demand, invoices and annual results. Ask a specific business question or select a suggestion.'
    report['mode']='Offline guided business chat · verified local data'
    report['narrative']=None
    return report,resolved

def export_conversation(messages):
    def convert(value):
        if isinstance(value,pd.DataFrame):return json.loads(value.to_json(orient='records',date_format='iso'))
        if isinstance(value,dict):return {k:convert(v) for k,v in value.items()}
        if isinstance(value,list):return [convert(v) for v in value]
        return value
    return json.dumps(convert(messages),ensure_ascii=False,default=str,indent=2).encode('utf-8')
