@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=python"
if exist "%~dp0backend\runtime\python.exe" set "PYTHON_EXE=%~dp0backend\runtime\python.exe"
if exist "%~dp0backend\.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0backend\.venv\Scripts\python.exe"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local-ai\setup.ps1" -PythonExe "%PYTHON_EXE%"
if errorlevel 1 echo Local AI setup failed. Review the error above.
pause
