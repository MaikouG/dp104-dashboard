@echo off
setlocal
title DP104 Dashboard v2.4 EXE Builder
cd /d "%~dp0\.."

echo ========================================
echo DP104 Dashboard v2.4 - Build Windows EXE
echo ========================================
echo.

where python.exe >nul 2>nul
if errorlevel 1 (
    echo ERROR: python.exe was not found in PATH.
    echo Install Python 3.12 or newer and enable "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo [1/4] Removing obsolete standard-library backports if present...
for %%P in (pathlib typing enum34) do (
    python.exe -m pip show %%P >nul 2>nul
    if not errorlevel 1 (
        echo Removing obsolete package: %%P
        python.exe -m pip uninstall -y %%P
        if errorlevel 1 (
            echo ERROR: Could not remove obsolete package %%P.
            pause
            exit /b 1
        )
    )
)

echo.
echo [2/4] Installing build dependencies...
python.exe -m pip install --upgrade -r requirements-build.txt
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

echo.
echo [3/4] Building DP104Dashboard.exe...
python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller-work build\DP104Dashboard.spec
if errorlevel 1 (
    echo ERROR: EXE build failed.
    pause
    exit /b 1
)

echo.
echo [4/4] Done.
echo Output:
echo   dist\DP104Dashboard.exe
echo.
pause
endlocal
