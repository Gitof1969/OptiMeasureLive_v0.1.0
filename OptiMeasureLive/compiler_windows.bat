@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Creation de OptiMeasureLive.exe ===
echo.

if not exist ".venv\Scripts\python.exe" (
    echo L'environnement Python est introuvable.
    echo Lancez d'abord installer_windows.bat
    goto :error
)

if not exist "app.py" (
    echo Le fichier app.py est introuvable.
    goto :error
)

if not exist "assets\optimeasure_icon.png" (
    echo Le fichier assets\optimeasure_icon.png est introuvable.
    goto :error
)

if not exist "assets\optimeasure_icon.ico" (
    echo Le fichier assets\optimeasure_icon.ico est introuvable.
    goto :error
)

echo Verification de PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo Installation de PyInstaller...
    ".venv\Scripts\python.exe" -m pip install "pyinstaller>=6,<7"
    if errorlevel 1 goto :error
)

echo Compilation en cours...
".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name OptiMeasureLive ^
    --icon "assets\optimeasure_icon.ico" ^
    --add-data "assets:assets" ^
    app.py

if errorlevel 1 goto :error

if not exist "dist\OptiMeasureLive.exe" (
    echo La compilation est terminee, mais l'executable est introuvable.
    goto :error
)

echo.
echo Compilation terminee avec succes.
echo Executable : %CD%\dist\OptiMeasureLive.exe
echo.
pause
exit /b 0

:error
echo.
echo Echec de la compilation. Consultez les messages ci-dessus.
echo.
pause
exit /b 1
