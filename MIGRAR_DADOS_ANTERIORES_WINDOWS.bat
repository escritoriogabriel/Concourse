@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set "PYCMD=py") else (set "PYCMD=python")
%PYCMD% migrar_dados.py
pause
