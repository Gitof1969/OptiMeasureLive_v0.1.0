@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Installation de OptiMeasure Live ===
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py"
) else (
    set "PYTHON_CMD=python"
)

%PYTHON_CMD% --version >nul 2>nul
if errorlevel 1 (
    echo Python est introuvable.
    echo Installez Python 3.10 ou plus recent depuis https://www.python.org/
    echo puis relancez ce fichier.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement Python...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
echo Installation des dependances...
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Installation terminee.
echo Utilisez maintenant demarrer_windows.bat
echo.
pause
exit /b 0

:error
echo.
echo Echec de l'installation. Consultez les messages ci-dessus.
pause
exit /b 1
