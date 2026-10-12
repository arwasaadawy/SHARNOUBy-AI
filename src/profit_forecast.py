"""Validated demand forecasts converted to explicitly conditional profit estimates.
Stress bounds are not calibrated portfolio profit intervals. No costs/tax inferred.
"""
import numpy as np
import pandas as pd
from .analytics import normalize,refunds_in_period
from .annual import annual_report


def financial_rates(s,cutoff,product_ids):
    s=normalize(s);cutoff=pd.Timestamp(cutoff);past=s[s.Order_Date<=cutoff]
    recent=past[past.Order_Date.between(cutoff-pd.Timedelta(days=89),cutoff)]
    annual=past[past.Order_Date.between(cutoff-pd.Timedelta(days=364),cutoff)]
    def aggregate(d):return d.groupby('Product_ID').agg(Units=('Quantity','sum'),Net=('Net_Sales_EGP','sum'),Cost=('Estimated_COGS_EGP','sum'))
    a=aggregate(recent);b=aggregate(annual);allpast=aggregate(past);rows=[]
    refund=refunds_in_period(past,cutoff-pd.Timedelta(days=364),cutoff).groupby('Product_ID').Refund_Value_EGP.sum()
    company_rate=float(refund.sum()/annual.Net_Sales_EGP.sum()) if annual.Net_Sales_EGP.sum()>0 else np.nan
    for pid in product_ids:
        source=None;basis=None
        for frame,label in [(a,'Past 90 days'),(b,'Past 365 days fallback'),(allpast,'All prior sales fallback')]:
            if pid in frame.index and frame.loc[pid,'Units']>0:source=frame.loc[pid];basis=label;break
        price=float(source.Net/source.Units) if source is not None else np.nan
        cost=float(source.Cost/source.Units) if source is not None else np.nan
        rate=float(refund.get(pid,0)/b.loc[pid,'Net']) if pid in b.index and b.loc[pid,'Net']>0 else company_rate
        rows.append(dict(Product_ID=pid,Net_Price_Per_Unit=price,Estimated_Cost_Per_Unit=cost,Refund_Event_Rate=rate,Price_Cost_Basis=basis,Refund_Basis='Past 365-day return-date refunds / invoiced net sales',Rate_Valid=bool(np.isfinite(price) and np.isfinite(cost) and price>=0 and cost>=0 and np.isfinite(rate) and 0<=rate<=1)))
    return pd.DataFrame(rows)


def value_units(f,rates,units_column='Units',price_change=0.,cost_change=0.,fulfillment=1.,refund_multiplier=1.,supply_limits=None):
    for value in [price_change,cost_change,fulfillment,refund_multiplier]:
        if not np.isfinite(value):raise ValueError('Scenario assumptions must be finite')
    if price_change<=-1 or cost_change<=-1 or not 0<=fulfillment<=1 or refund_multiplier<0:raise ValueError('Invalid price/cost/fulfillment/refund assumptions')
    d=normalize(f).merge(rates,on='Product_ID',how='left',validate='many_to_one')
    if d.Rate_Valid.isna().any() or not d.Rate_Valid.all():raise ValueError('Missing or invalid historical price/cost/refund evidence; no profit estimate generated')
    if (d[units_column]<0).any() or not np.isfinite(d[units_column]).all():raise ValueError('Demand units must be finite and nonnegative')
    d['Fulfilled_Units']=d[units_column]*fulfillment
    if supply_limits is not None:
        limits=[supply_limits.get((r.Product_ID,pd.Timestamp(r.Month)),np.inf) for r in d.itertuples()]
        if any(v<0 or np.isnan(v) for v in limits):raise ValueError('Supply limits must be nonnegative')
        d['Supply_Limit_Units']=limits
        d['Fulfilled_Units']=np.minimum(d.Fulfilled_Units,limits)
    d['Invoiced_Sales_Estimate']=d.Fulfilled_Units*d.Net_Price_Per_Unit*(1+price_change)
    d['Refund_Rate_Assumption']=(d.Refund_Event_Rate*refund_multiplier).clip(upper=1)
    d['Refund_Estimate']=d.Invoiced_Sales_Estimate*d.Refund_Rate_Assumption
    d['Net_Sales_Estimate']=d.Invoiced_Sales_Estimate-d.Refund_Estimate
    d['Sold_COGS_Estimate']=d.Fulfilled_Units*d.Estimated_Cost_Per_Unit*(1+cost_change)
    d['Contribution_Before_Future_Expenses']=d.Net_Sales_Estimate-d.Sold_COGS_Estimate
    return d


def profit_outlook(scope,forecasts,origin,entries=None,branch='All',category='All',available_start=None,remaining_expenses=None,price_change=0.,cost_change=0.,fulfillment=1.,target_result=None,supply_limits=None):
    origin=pd.Timestamp(origin).normalize()
    if origin!=origin+pd.offsets.MonthEnd(0):raise ValueError('A completed month-end origin is required; no unmodeled partial-month demand is inserted')
    if remaining_expenses is not None and (not np.isfinite(remaining_expenses) or remaining_expenses<0):raise ValueError('Remaining expense budget must be nonnegative and finite')
    if target_result is not None and not np.isfinite(target_result):raise ValueError('Target must be finite')
    year=origin.year;f=normalize(forecasts);f=f[(f.Month>origin)&f.Month.dt.year.eq(year)].copy()
    required=pd.date_range(origin+pd.offsets.MonthBegin(1),pd.Timestamp(year,12,1),freq='MS') if origin.month<12 else pd.DatetimeIndex([])
    if f.duplicated(['Product_ID','Month']).any():raise ValueError('Duplicate product/month forecasts would double-count revenue')
    if not {'Lower','Units','Upper'}.issubset(f.columns):raise ValueError('Forecast bounds are required')
    if not ((f.Lower<=f.Units)&(f.Units<=f.Upper)).all():raise ValueError('Invalid demand bounds')
    missing=sorted(set(required)-set(f.Month.unique()));coverage_complete=len(missing)==0
    if any(set(required)-set(g.Month.unique()) for _,g in f.groupby('Product_ID')):coverage_complete=False
    facts=annual_report(scope,year,entries,branch,category,available_start or scope.Order_Date.min(),origin)
    rates=financial_rates(scope,origin,f.Product_ID.unique())
    if f.empty:raise ValueError('No future forecast months exist within this source year; use Annual Closing for recorded results')
    scenarios=[];monthly=[];details=[];expenses=float(remaining_expenses or 0)
    # Demand lower/upper are marginal bands; combining them is a transparent stress assumption.
    for name,units,pc,cc,rm in [('Lower-demand / cost stress','Lower',price_change,cost_change+.05,1.25),('Central assumptions','Units',price_change,cost_change,1.),('Upper-demand stress','Upper',price_change,cost_change,1.)]:
        d=value_units(f,rates,units,pc,cc,fulfillment,rm,supply_limits);d['Scenario']=name;details.append(d)
        cols=['Fulfilled_Units','Invoiced_Sales_Estimate','Refund_Estimate','Net_Sales_Estimate','Sold_COGS_Estimate','Contribution_Before_Future_Expenses']
        row=d[cols].sum().to_dict();row.update(Scenario=name,Future_Expense_Budget=expenses if remaining_expenses is not None else np.nan,Forecast_Period_Result=row['Contribution_Before_Future_Expenses']-expenses,Full_Year_Result_Estimate=facts['estimated_result']+row['Contribution_Before_Future_Expenses']-expenses if coverage_complete else np.nan,Missing_Expense_Budget=remaining_expenses is None)
        scenarios.append(row);g=d.groupby('Month')[cols].sum().reset_index();g['Scenario']=name;monthly.append(g)
    scenarios=pd.DataFrame(scenarios);detail=pd.concat(details,ignore_index=True);months=pd.concat(monthly,ignore_index=True)
    central=scenarios[scenarios.Scenario.eq('Central assumptions')].iloc[0]
    net=float(central.Net_Sales_Estimate);contribution=float(central.Contribution_Before_Future_Expenses);units=float(central.Fulfilled_Units)
    margin=contribution/net if net>0 else np.nan;unit_margin=contribution/units if units>0 else np.nan
    gap=max(0,float(target_result)-float(central.Full_Year_Result_Estimate)) if target_result is not None and coverage_complete else np.nan
    targets=dict(Contribution_Ratio=margin,Contribution_Per_Unit=unit_margin,Remaining_Period_BreakEven_Net_Sales=expenses/margin if remaining_expenses is not None and margin>0 else np.nan,Remaining_Period_BreakEven_Units=expenses/unit_margin if remaining_expenses is not None and unit_margin>0 else np.nan,Target_Gap=gap,Additional_Net_Sales_For_Target=gap/margin if margin>0 and pd.notna(gap) else np.nan)
    central_detail=detail[detail.Scenario.eq('Central assumptions')]
    watch=central_detail.groupby('Product_ID').agg(Projected_Units=('Fulfilled_Units','sum'),Projected_Net_Sales=('Net_Sales_Estimate','sum'),Estimated_COGS=('Sold_COGS_Estimate','sum'),Contribution=('Contribution_Before_Future_Expenses','sum')).reset_index()
    watch['Contribution_Ratio']=np.where(watch.Projected_Net_Sales>0,watch.Contribution/watch.Projected_Net_Sales,np.nan)
    watch['Contribution_Per_Unit']=np.where(watch.Projected_Units>0,watch.Contribution/watch.Projected_Units,np.nan)
    watch['Negative_Contribution']=watch.Contribution.lt(0)
    watch=watch.sort_values('Contribution_Ratio',na_position='last')
    return dict(margin_watch=watch,origin=origin,year=year,facts=facts,rates=rates,scenarios=scenarios,monthly=months,details=detail,coverage_complete=coverage_complete,missing_months=missing,expense_budget_known=remaining_expenses is not None,targets=targets)


def profit_backtest(s,heldout):
    """Frozen financial rates before the untouched unit-model holdout.
Only a contribution proxy is tested; actual costs/expenses absent.
"""
    s=normalize(s);test=normalize(heldout);cutoff=test.Month.min()-pd.Timedelta(days=1)
    rates=financial_rates(s,cutoff,test.Product_ID.unique());f=test.rename(columns={'Units_pred':'Units'})
    valued=value_units(f,rates);pred=valued.groupby('Month').Contribution_Before_Future_Expenses.sum()
    netpred=valued.groupby('Month').Net_Sales_Estimate.sum();rows=[]
    for month in sorted(test.Month.unique()):
        end=month+pd.offsets.MonthEnd(0)
        sales=s[s.Order_Date.between(month,end)];refund=refunds_in_period(s,month,end).Refund_Value_EGP.sum()
        net=sales.Net_Sales_EGP.sum()-refund;actual=net-sales.Estimated_COGS_EGP.sum()
        rows.append(dict(Month=month,Rate_Cutoff=cutoff,Actual_Contribution_Proxy=float(actual),Predicted_Contribution_Proxy=float(pred.loc[month]),Actual_Net_Sales=float(net),Predicted_Net_Sales=float(netpred.loc[month])))
    d=pd.DataFrame(rows);error=d.Predicted_Contribution_Proxy-d.Actual_Contribution_Proxy;den=d.Actual_Contribution_Proxy.abs().sum()
    metrics=dict(task='Three-month contribution proxy from heldout demand and frozen historical financial rates',MAE=float(error.abs().mean()),RMSE=float(np.sqrt((error**2).mean())),WAPE=float(error.abs().sum()/den) if den else None,Bias=float(error.mean()),Months=len(d),Rate_Cutoff=str(cutoff.date()),Limitation='Only three aggregate months; expenses and real COGS unavailable. Not validated net profit or calibrated annual interval.')
    return d,metrics
