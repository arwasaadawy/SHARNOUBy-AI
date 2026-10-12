"""Evidence-based calendar-month seasonality; no invented holiday dates or forecasts."""
import numpy as np
import pandas as pd
from .analytics import normalize

def high_season(s,available_start,available_end,threshold=1.2):
    s=normalize(s);begin=pd.Timestamp(available_start);end=pd.Timestamp(available_end)
    years=[y for y in range(begin.year,end.year+1) if begin<=pd.Timestamp(y,1,1) and end>=pd.Timestamp(y,12,31)]
    if not years:return pd.DataFrame(),pd.DataFrame(),years
    d=s[s.Order_Date.dt.year.isin(years)].assign(Year=lambda x:x.Order_Date.dt.year,Month=lambda x:x.Order_Date.dt.month)
    base=d.groupby(['Year','Month']).agg(Units=('Quantity','sum'),Invoiced_Net_Sales=('Net_Sales_EGP','sum'))
    base=base.reindex(pd.MultiIndex.from_product([years,range(1,13)],names=['Year','Month']),fill_value=0).reset_index()
    base['Index']=base.Units/base.groupby('Year').Units.transform('mean').replace(0,np.nan)
    summary=base.groupby('Month').agg(Average_Units=('Units','mean'),Average_Invoiced=('Invoiced_Net_Sales','mean'),Seasonal_Index=('Index','mean'),Min_Index=('Index','min'),Max_Index=('Index','max'),Observed_Years=('Index','count')).reset_index()
    summary['High_Season_Signal']=summary.Seasonal_Index.ge(float(threshold))&summary.Observed_Years.ge(2)
    summary['Interpretation']=np.where(summary.Observed_Years<2,'Insufficient complete years',np.where(summary.High_Season_Signal,'Above selected seasonal threshold','Below selected seasonal threshold'))
    return summary,base,years

def season_products(s,years,target_month,forecasts,inventory,target_date,preparation_days=14):
    s=normalize(s);d=s[s.Order_Date.dt.year.isin(years)].assign(Year=lambda x:x.Order_Date.dt.year,Month=lambda x:x.Order_Date.dt.month)
    rows=[]
    for pid,g in d.groupby('Product_ID'):
        panel=g.groupby(['Year','Month']).Quantity.sum().reindex(pd.MultiIndex.from_product([years,range(1,13)],names=['Year','Month']),fill_value=0)
        annual_mean=panel.groupby(level=0).mean();season=panel.xs(int(target_month),level='Month');idx=season/annual_mean.replace(0,np.nan)
        rows.append(dict(Product_ID=pid,Product_Name=g.Product_Name.iloc[0],Historical_Target_Month_Units=float(season.mean()),Seasonal_Index=float(idx.mean()),Observed_Years=int(idx.notna().sum())))
    out=pd.DataFrame(rows,columns=['Product_ID','Product_Name','Historical_Target_Month_Units','Seasonal_Index','Observed_Years'])
    f=normalize(forecasts);target=pd.Timestamp(target_date).to_period('M').to_timestamp();matched=f[f.Month.eq(target)]
    if len(matched):out=out.merge(matched[['Product_ID','Units','Lower','Upper','Confidence']].rename(columns={'Units':'Validated_Forecast_Units'}),on='Product_ID',how='left')
    else:out['Validated_Forecast_Units']=np.nan
    if len(inventory):
        good=inventory[inventory.Recommendation_Eligible] if 'Recommendation_Eligible' in inventory else inventory
        stock=good.groupby('Product_ID').agg(Audited_Stock=('Closing_Stock','sum'),Lead_Days=('Supplier_Lead_Time_Days','max'))
        coverage=inventory.groupby('Product_ID').Recommendation_Eligible.all() if 'Recommendation_Eligible' in inventory else pd.Series(True,index=stock.index)
        stock['All_Positions_Reconciled']=coverage
        out=out.merge(stock.reset_index(),on='Product_ID',how='left')
        out['Planning_Central_Gap']=(out.Validated_Forecast_Units-out.Audited_Stock).clip(lower=0).where(out.All_Positions_Reconciled.eq(True))
        out['Prepare_By']=pd.Timestamp(target)-pd.to_timedelta(out.Lead_Days+int(preparation_days),unit='D')
    return out.sort_values('Seasonal_Index',ascending=False)
