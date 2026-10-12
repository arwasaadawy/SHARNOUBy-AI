from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/processed'
MODELS=ROOT/'models'
DATE_COLS=['Order_Date','Return_Date','Join_Date','Snapshot_Month','Month','Date','Open_Date','Print_Date','Start_Date','Due_Date','Completion_Date','Expected_Receipt','Actual_Receipt','Order_Date','Inspection_Date','Campaign_Start','Campaign_End']

