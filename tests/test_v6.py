import re
from streamlit.testing.v1 import AppTest
from src.settings import ROOT
from src.navigation import NAVIGATION
from ui_nav import navigate

def test_combined_views_and_live_controls():
    app=AppTest.from_file(str(ROOT/'app/Home.py'),default_timeout=60).run()
    assert not app.exception
    assert list(NAVIGATION.values())[0]==['Live Business Report']
    assert not any(v in sum(NAVIGATION.values(),[]) for v in ['Overview','Forecasting Center','Production Planner','AI Discoveries','Year-End Profit'])
    before=app.metric[1].value
    next(x for x in app.slider if x.label.startswith('Future unit COGS')).set_value(10).run()
    assert not app.exception and app.metric[1].value!=before
    estimate=app.metric[1].value
    next(x for x in app.number_input if x.label=='Monthly available capacity (units)').set_value(1234).run()
    assert not app.exception and app.metric[1].value!=estimate
    navigate(app,'Inventory Command')
    assert not app.exception
    assert next(x for x in app.number_input if x.label=='Monthly available capacity (units)').value==1234
    assert any(x.label=='Include proposed transfers as a planning assumption' for x in app.checkbox)
    navigate(app,'Product Intelligence')
    assert not app.exception
    assert any(x.label=='Future months' for x in app.slider)
    navigate(app,'AI Copilot')
    assert not any('API key' in x.label or 'Model ID' in x.label for x in app.text_input)
    app.chat_input[0].set_value('Calculate annual profit 2025').run()
    assert not app.exception
    app.chat_input[0].set_value('مرحبا').run()
    assert any('Please ask in English' in x.value for x in app.warning)
    for message in app.chat_message:
        for x in message.markdown:assert not re.search(r'[\u0600-\u06ff]',x.value)
