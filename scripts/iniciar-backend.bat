@echo off
REM PRICE WATCH - inicia a API + monitoramento em segundo plano (sem janela).
REM Logs: backend\instance\pricewatch.log
cd /d "%~dp0..\backend"
start "" ".venv\Scripts\pythonw.exe" run.py
