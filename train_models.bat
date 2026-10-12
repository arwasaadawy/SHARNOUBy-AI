@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%CD%\_temp"
set "TMP=%CD%\_temp"
if not exist "%TEMP%" mkdir "%TEMP%"
if not "%~1"=="" goto custom_python
if exist ".venv\Scripts\python.exe" goto local_python
py -3.12 -m venv .venv
if errorlevel 1 exit /b 1
:local_python
set "APP_PYTHON=%CD%\.venv\Scripts\python.exe"
goto train
:custom_python
set "APP_PYTHON=%~1"
:train
"%APP_PYTHON%" -m pip install --no-cache-dir -r requirements.txt
if errorlevel 1 exit /b 1
"%APP_PYTHON%" -m src.engine
pause
endlocal
