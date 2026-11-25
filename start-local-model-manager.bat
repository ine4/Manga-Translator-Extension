@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=python"
if exist "%~dp0backend\runtime\python.exe" set "PYTHON_EXE=%~dp0backend\runtime\python.exe"
if exist "%~dp0backend\.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0backend\.venv\Scripts\python.exe"
powershell -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0local-ai\manager.ps1" -PythonExe "%PYTHON_EXE%"
