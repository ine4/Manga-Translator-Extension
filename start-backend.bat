@echo off
setlocal
:: MangaTranslator Extension Backend Launcher
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist "%~dp0..\MangaTranslator\runtime\python.exe" set "PYTHON_EXE=%~dp0..\MangaTranslator\runtime\python.exe"
if exist "%~dp0backend\runtime\python.exe" set "PYTHON_EXE=%~dp0backend\runtime\python.exe"
if exist "%~dp0backend\.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0backend\.venv\Scripts\python.exe"

echo Starting MangaTranslator stack on ports 7677 and 7678...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local-ai\start-stack.ps1" -PythonExe "%PYTHON_EXE%"

pause
