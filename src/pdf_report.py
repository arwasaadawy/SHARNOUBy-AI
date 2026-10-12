"""Portable readable PDF export from the current live report, without browser dependencies."""
import io,math,re
from html import escape
from numbers import Number
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape,letter
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,TableStyle,KeepTogether

PREVIEW_ROWS=20

def display(value):
    if value is None:return 'Not entered'
    if isinstance(value,(bool,)):return 'Yes' if value else 'No'
    if isinstance(value,Number):
        if not math.isfinite(float(value)):return 'Unavailable'
        return f'{value:,.2f}'
    if isinstance(value,pd.Timestamp):return value.strftime('%d %b %Y') if pd.notna(value) else 'Unavailable'
    text=str(value)
    text=re.sub(r'[\u0600-\u06ff]+','[source text]',text)
    return text.replace('\u2212','-').replace('\u2013','-').replace('\u2014','-')[:180]

def report_pdf(report):
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Cell',fontName='Helvetica',fontSize=7.5,leading=10,spaceAfter=0))
    styles.add(ParagraphStyle(name='HeadCell',parent=styles['Cell'],fontName='Helvetica-Bold',textColor=colors.white))
    styles['Title'].fontSize=20;styles['Title'].leading=24
    styles['Heading2'].fontSize=12;styles['Heading2'].leading=16
    styles['BodyText'].fontSize=9;styles['BodyText'].leading=12
    output=io.BytesIO();doc=SimpleDocTemplate(output,pagesize=landscape(letter),leftMargin=32,rightMargin=32,topMargin=30,bottomMargin=35,title='SHARNOUBy AI Live Business Report',author='SHARNOUBy AI')
    story=[]
    def paragraph(text,style='BodyText'):return Paragraph(escape(str(text)),styles[style])
    def grid(headers,rows):
        width=doc.width/len(headers)
        cells=[[paragraph(str(h).replace('_',' '),'HeadCell') for h in headers]]
        cells.extend([[paragraph(display(v),'Cell') for v in row] for row in rows])
        t=LongTable(cells,colWidths=[width]*len(headers),repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#233f50')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f1f4f6')]),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#d9d9d9')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
        return t
    meta=report['metadata']
    story.append(paragraph('SHARNOUBy AI Live Business Report','Title'))
    story.append(paragraph(f"Scope: {meta.get('branch','All')} / {meta.get('category','All')} | Historical period: {meta.get('historical_start')} to {meta.get('historical_end')} | Forecast origin: {meta.get('forecast_origin')}"))
    story.append(Spacer(1,8))
    story.append(paragraph('Recorded facts, uncertain predictions and assumption-based recommendations are presented separately. Financial results use estimated costs and entered expenses. Missing costs remain unknown; stress cases are not calibrated annual confidence intervals.'))
    story.append(paragraph(f'Readable tables preview up to {PREVIEW_ROWS} rows each. Wide tables are split into labeled column groups. Download the complete report pack for every row and column. Non-Latin source labels are abbreviated as [source text]; original values remain in CSV files.'))
    if not meta.get('expense_budget_known'):story.append(paragraph('Expense budget missing: year-end estimates are BEFORE unknown future expenses and are not certified net profit.'))
    for name in ['financial_assumptions','production_assumptions']:
        story.extend([Spacer(1,10),paragraph(name.replace('_',' ').title(),'Heading2'),grid(['Input','Current value'],list(meta.get(name,{}).items()))])
    for name,frame in report['frames'].items():
        story.extend([Spacer(1,14),paragraph(name.replace('_',' ').title(),'Heading2')])
        if frame.empty:
            story.append(paragraph('No matching records. For anomalies, zero flagged records is a result, not proof that every outcome is healthy.'));continue
        preview=frame.head(PREVIEW_ROWS)
        story.append(paragraph(f'Showing {len(preview):,} of {len(frame):,} rows.'))
        columns=list(frame.columns);anchor=next((c for c in ['Product_ID','Invoice_ID','Metric'] if c in columns),None)
        rest=[c for c in columns if c!=anchor] if anchor else columns
        size=5 if anchor else 6
        groups=[(([anchor] if anchor else [])+rest[i:i+size]) for i in range(0,len(rest),size)] or [[anchor]]
        for j,cols in enumerate(groups):
            if len(groups)>1:story.append(paragraph(f'Column group {j+1} of {len(groups)}'))
            story.append(grid(cols,preview[cols].itertuples(index=False,name=None)));story.append(Spacer(1,7))
    story.append(paragraph(f"Anomaly evidence: {meta.get('evaluated_days',0)} evaluated days and {meta.get('flagged_days',0)} flagged days. Production plan costs are separate from financial sold cost of goods and are not deducted twice."))
    def footer(canvas,document):
        canvas.saveState();canvas.setFont('Helvetica',8);canvas.drawString(32,19,'SHARNOUBy AI | Current scope and assumptions');canvas.drawRightString(760,19,f'Page {document.page}');canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
