@echo off
setlocal
cd /d "%~dp0"
title EditalOS - Agenda de Estudos
color 1F
echo ==============================================
echo    EditalOS - Agenda + NotebookLM
echo ==============================================
where py >nul 2>nul
if %errorlevel%==0 (set "PYCMD=py") else (set "PYCMD=python")
echo.
echo Verificando dependencias...
%PYCMD% -m pip install -r requirements.txt
if errorlevel 1 (echo Falha ao instalar dependencias. & pause & exit /b 1)
echo.
echo O EditalOS nao possui IA incorporada.
echo Gere o planejamento no NotebookLM e importe o JSON pela aplicacao.
echo.
echo Abrindo http://127.0.0.1:8000 ...
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000"
%PYCMD% app.py
pause
