import streamlit as st
import plotly.express as px
from src.annual import adjustments
from src.live_report import build_report,report_zip
from src.pdf_report import report_pdf
from workspaces import profit_controls,production_controls

def render_report(t,scope,viewf,viewinv,products,branch,category,start,end,origin,db,registry,table,plot,amount):
    st.caption('One live report links observed performance, forecasts, financial assumptions, inventory and production. Changing scope or the controls below rebuilds the calculations and downloads immediately.')
    with st.expander('Linked financial inputs',expanded=True):budget,price,cost,fulfillment,target=profit_controls(branch,category,origin)
    with st.expander('Linked production inputs',expanded=False):
        planning=production_controls(branch,category)
        st.caption('Shared with Inventory & Operations. All inputs recalculate this report and exports.')
    assumptions={'remaining_expenses':budget,'price_change':price,'cost_change':cost,'fulfillment':fulfillment,'target_result':target}
    try:report=build_report(t,scope,viewf,viewinv,products,branch,category,start,end,origin,adjustments(db),assumptions,planning)
    except ValueError as e:st.warning(str(e));return
    f=report['frames'];hist=f['historical_kpis'].set_index('Metric').Value;central=f['year_end_scenarios'].iloc[1]
    a,b,c=st.columns(3);a.metric('Selected-period net recorded sales','EGP '+amount(hist['Net_After_Refunds']));b.metric('Year-end result estimate','EGP '+amount(central.Full_Year_Result_Estimate));c.metric('Allocated production',amount(f['production_plan'].Produce.sum(),0)+' units')
    st.info(report['metadata']['supply_link'])
    st.caption('Capacity is a maximum, not an instruction to produce every unit. Above demand/cost limits, allocated production and the financial estimate can remain unchanged.')
    plot(px.bar(f['year_end_scenarios'],x='Scenario',y='Full_Year_Result_Estimate',title='Year-end stress scenarios'))
    plot(px.line(f['forecast_months'],x='Month',y='Net_Sales_Estimate',color='Scenario',title='Forecast net sales'))
    if budget is None:st.warning('Future expense budget is missing. Year-end total is before missing future costs; YTD expenses also require completeness review.')
    st.download_button('Download complete report pack',report_zip(report),'sharnouby_live_report.zip','application/zip',key='complete_live_report')
    st.download_button('Download PDF report',report_pdf(report),'sharnouby_live_report.pdf','application/pdf',key='readable_live_report')
    for title,names in [('Observed business & annual reconciliation',['historical_kpis','annual_ytd_calculation']),('Predictions & financial decisions',['year_end_scenarios','forecast_months','break_even_and_target','margin_watch']),('Inventory & action plan',['inventory','production_plan']),('Evidence & unusual days',['historical_financial_rates','flagged_anomalies'])]:
        with st.expander(title,expanded=title=='Predictions & financial decisions'):
            for name in names:st.markdown('**'+name.replace('_',' ').title()+'**');table(f[name],'live_'+name)
    st.caption(f"Anomaly checks: {report['metadata']['evaluated_days']} evaluated days; {report['metadata']['flagged_days']} flagged. Exports contain complete invoice/refund/adjustment and product calculation tables; readable PDF previews up to 20 rows per table; wide tables use labeled column groups.")
