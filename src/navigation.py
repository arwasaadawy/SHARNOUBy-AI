NAVIGATION={
 'Business Report':['Live Business Report'],
 'Sales & Customers':['Product Intelligence','High Season','Customers','What-if Lab'],
 'Inventory & Operations':['Inventory Command','Operations','Annual Count'],
 'Finance & Closing':['Annual Closing'],
 'AI Copilot':['AI Copilot'],
 'Settings & Trust':['Data Quality','Model Center'],
}
ALIASES={'Overview':'Live Business Report','Action Center':'Live Business Report','AI Discoveries':'Live Business Report','Year-End Profit':'Live Business Report','Forecasting Center':'Product Intelligence','Production Planner':'Inventory Command'}
def canonical_view(view):return ALIASES.get(view,view)
def section_for(view):return next(section for section,views in NAVIGATION.items() if canonical_view(view) in views)
