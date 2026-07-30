@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo OptiMeasure Live n'est pas encore installe.
    echo Lancez d'abord installer_windows.bat
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python app.py

if errorlevel 1 (
    echo.
    echo L'application s'est arretee avec une erreur.
    pause
)
