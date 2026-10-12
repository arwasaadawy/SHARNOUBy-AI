from ui_nav import navigate,sidebar_select,ALL_VIEWS
import sqlite3
import pandas as pd
from streamlit.testing.v1 import AppTest
from src.settings import ROOT

def test_customer_audience_filters():
    with sqlite3.connect(ROOT/'data/processed/business.db') as con:
        s=pd.read_sql_query('select * from sales_transactions',con)
        scores=pd.read_sql_query('select Customer_ID from customer_scores',con)
        consent=pd.read_sql_query("select Customer_ID from customers where Consent_Status='Opted-in'",con)
    s.Order_Date=pd.to_datetime(s.Order_Date);end=s.Order_Date.max();start=end.replace(day=1);s=s[s.Order_Date.between(start,end)]
    allowed=set(consent.Customer_ID)
    app=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run();navigate(app,'Customers')
    audiences=[]
    for category in ['All']+sorted(s.Product_Family.unique()):
        sidebar_select(app,'Category').set_value(category).run(timeout=60);assert not app.exception
        subset=s if category=='All' else s[s.Product_Family.eq(category)]
        expected=len(set(subset.Customer_ID)&allowed);assert int(app.metric[0].value.replace(',',''))==expected;audiences.append(expected)
    assert len(set(audiences))>1
    sidebar_select(app,'Location').set_value('LEO MODA - Sidi Bishr Store').run(timeout=60)
    subset=subset[subset.Location_Name.eq('LEO MODA - Sidi Bishr Store')];assert not app.exception;assert int(app.metric[0].value.replace(',',''))==len(set(subset.Customer_ID)&allowed)
    app.sidebar.date_input[0].set_value((end.date(),end.date())).run(timeout=60)
    assert not app.exception;assert int(app.metric[0].value.replace(',',''))==len(set(subset.loc[subset.Order_Date.eq(end),'Customer_ID'])&allowed)
