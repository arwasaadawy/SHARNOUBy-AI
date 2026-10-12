from src.navigation import NAVIGATION,section_for
ALL_VIEWS=[v for views in NAVIGATION.values() for v in views]
def sidebar_select(app,label):return next(x for x in app.sidebar.selectbox if x.label==label)
def navigate(app,view):
    section=section_for(view)
    app.sidebar.radio[0].set_value(section).run(timeout=60)
    if len(NAVIGATION[section])>1:sidebar_select(app,'View').set_value(view).run(timeout=60)
    return app
