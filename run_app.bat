@echo off
setlocal
cd /d "%~dp0"
if not "%~1"=="" goto custom_python
if exist ".venv\Scripts\python.exe" goto local_python
py -3.12 -m venv .venv
if errorlevel 1 goto failed
:local_python
set "APP_PYTHON=%CD%\.venv\Scripts\python.exe"
goto dependencies
:custom_python
set "APP_PYTHON=%~1"
:dependencies
"%APP_PYTHON%" -c "import streamlit,pandas,numpy,sklearn,scipy,plotly,reportlab" >nul 2>&1
if not errorlevel 1 goto launch
"%APP_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:launch
if "%~2"=="" goto start_app
"%APP_PYTHON%" -m src.migrate_workspace "%~2"
if errorlevel 1 goto failed
:start_app
"%APP_PYTHON%" -m streamlit run app\Home.py
goto end
:failed
echo Setup failed. Review the error above. Python 3.12 is required.
:end
pause
endlocal
