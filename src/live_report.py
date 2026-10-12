"""One reproducible report derived from current data scope and scenario inputs."""
import io,json,html
from zipfile import ZipFile,ZIP_DEFLATED
import pandas as pd
from .analytics import financial_kpis,comparison_dates,insight_cards
from .profit_forecast import profit_outlook
from .inventory import optimize


def build_report(t,scope,forecasts,inventory,products,branch,category,start,end,origin,entries,assumptions,planning=None):
    facts=financial_kpis(scope,start,end)
    planargs=planning or {'capacity':5000,'unit_cost':100.,'penalty':200.,'holding':10.}
    reference=t['sales_transactions'].groupby('Product_ID').agg(Cost=('Estimated_COGS_EGP','sum'),Units=('Quantity','sum'))
    planned_inventory=inventory.copy()
    if planargs.get('transfers_approved',False):
        planned_inventory.Transfer_In=planned_inventory.Proposed_Transfer_In
        planned_inventory.Transfer_Out=planned_inventory.Proposed_Transfer_Out
        planned_inventory.Net_Production_Need=(planned_inventory.Suggested_Units-planned_inventory.Transfer_In).clip(lower=0)
    plan=optimize(planned_inventory,planargs['capacity'],planargs['unit_cost'],planargs['penalty'],planargs['holding'],cost_reference=(reference.Cost/reference.Units).to_dict())
    next_month=pd.Timestamp(origin)+pd.offsets.MonthBegin(1)
    # Existing stock is counted once, and only eligible positions supply the plan.
    supply_limits={(r.Product_ID,next_month):max(0.,float(r.Available_Stock+r.Produce)) for r in plan.itertuples()}
    for pid in forecasts.Product_ID.unique():supply_limits.setdefault((pid,next_month),0.)
    outlook=profit_outlook(scope,forecasts,origin,entries,branch,category,t['sales_transactions'].Order_Date.min(),supply_limits=supply_limits,**assumptions)
    anomalies=t['scoped_anomalies'];evaluated=anomalies[anomalies.Scope_Branch.eq(branch)&anomalies.Scope_Category.eq(category)&anomalies.Order_Date.between(start,end)]
    meta={'annual_source_year':int(origin.year),'branch':branch,'category':category,'historical_start':str(start.date()),'historical_end':str(end.date()),'forecast_origin':str(origin.date()),'financial_assumptions':assumptions,'production_assumptions':planargs,'supply_link':'Next forecast month sales are capped by eligible stock plus allocated production. Later months retain the entered fulfillment assumption; future replenishment is not verified.','evaluated_days':len(evaluated),'flagged_days':int(evaluated.Flag.sum()),'expense_budget_known':outlook['expense_budget_known'],'warning':'Estimated COGS and incomplete costs; stress cases are not a calibrated portfolio interval. Production costs are not deducted twice as financial sold COGS.'}
    frames={'historical_kpis':pd.DataFrame({'Metric':list(facts),'Value':list(facts.values())}),'annual_ytd_calculation':outlook['facts']['profit'],'year_end_scenarios':outlook['scenarios'],'forecast_months':outlook['monthly'],'product_forecast_calculations':outlook['details'],'historical_financial_rates':outlook['rates'],'break_even_and_target':pd.DataFrame([outlook['targets']]),'margin_watch':outlook['margin_watch'],'demand_forecasts':forecasts,'inventory':inventory,'production_plan':plan,'product_intelligence':products,'flagged_anomalies':evaluated[evaluated.Flag.eq(1)],'invoice_register':outlook['facts']['invoices'],'refund_register':outlook['facts']['refunds'],'expense_adjustments':outlook['facts']['adjustments']}
    _,_,previous_start,previous_end,_=comparison_dates(start,end)
    frames['executive_brief']=insight_cards(scope,start,end,previous_start,previous_end,inventory,previous_start>=t['sales_transactions'].Order_Date.min())
    frames['action_priorities']=planned_inventory.sort_values('Central_Shortage_Units',ascending=False) if 'Central_Shortage_Units' in planned_inventory else planned_inventory
    return {'metadata':meta,'frames':frames}


def report_html(report):
    meta=report['metadata'];parts=['<!doctype html><html lang="en"><meta charset="utf-8"><title>SHARNOUBy business report</title><style>body{font:15px system-ui;color:#183d3b;margin:40px}h1,h2{color:#175f54}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #ddd;padding:7px;text-align:left}th{background:#edf5f1}.note{background:#fff6df;padding:16px}section{margin:30px 0;overflow:auto}</style><h1>SHARNOUBy AI · Live Business Report</h1>', '<pre>'+html.escape(json.dumps(meta,indent=2,default=str))+'</pre>','<p class="note">Observed sales and YTD figures are separate from fixed-origin forecasts. Net recorded sales = invoiced net sales − return-date refunds. Year-end result = YTD estimated result + forecast net sales − estimated sold COGS − entered future expense budget. Missing costs remain unknown. Break-even assumes unchanged mix and fixed entered costs. Next-month sales are limited by eligible stock plus allocated production. Later months use the entered fulfillment assumption.</p>']
    for name,frame in report['frames'].items():
        parts.append('<section><h2>'+html.escape(name.replace('_',' ').title())+'</h2>')
        if frame.empty:parts.append('<p>No matching records. For anomalies, zero flagged days is an explicit result; see evaluated-day count.</p>')
        else:
            parts.append(frame.head(200).to_html(index=False,escape=True,float_format=lambda x:f'{x:,.2f}'))
            if len(frame)>200:parts.append(f'<p>Showing 200 of {len(frame):,} rows. Complete rows are included in the CSV report pack.</p>')
        parts.append('</section>')
    parts.append('</html>');return ''.join(parts).encode('utf-8')


def report_zip(report):
    buffer=io.BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as z:
        from .pdf_report import report_pdf
        z.writestr('report.html',report_html(report));z.writestr('report.pdf',report_pdf(report));z.writestr('assumptions.json',json.dumps(report['metadata'],indent=2,default=str))
        for name,frame in report['frames'].items():z.writestr(name+'.csv',frame.to_csv(index=False).encode('utf-8-sig'))
    return buffer.getvalue()
