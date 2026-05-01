@echo off
REM ============================================================
REM  Owner-only build script. NOT for employees.
REM  Produces: dist\SheinExtract-Setup-{version}.exe
REM ============================================================
REM
REM Prerequisites (one-time setup on your build machine):
REM   1. Python 3.10+ on PATH (Anaconda is fine)
REM   2. pip install pyinstaller
REM   3. pip install -r requirements.txt
REM   4. Inno Setup 6.x installed (so iscc.exe is on PATH or under
REM      C:\Program Files (x86)\Inno Setup 6\)
REM   5. Create .build_key.txt next to this script with the raw
REM      Anthropic API key on a single line. (gitignored.)
REM
REM Usage:
REM   build.bat            full build + installer
REM   build.bat exe        only PyInstaller, skip Inno Setup
REM ============================================================

setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  Step 1/3: Generate key_store.py from .build_key.txt
echo ============================================================
if not exist .build_key.txt (
    echo [ERROR] .build_key.txt not found. Create it with the raw API key.
    exit /b 1
)
python make_key_store.py
if errorlevel 1 (
    echo [ERROR] make_key_store.py failed.
    exit /b 1
)

echo.
echo ============================================================
echo  Step 2/3: PyInstaller — build SheinExtract.exe
echo ============================================================
if exist build rmdir /s /q build
if exist dist\SheinExtract.exe del /q dist\SheinExtract.exe
pyinstaller pyinstaller.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller failed.
    exit /b 1
)

if /i "%1"=="exe" (
    echo.
    echo Skipping Inno Setup ^(--exe-only mode^). dist\SheinExtract.exe is ready.
    exit /b 0
)

echo.
echo ============================================================
echo  Step 3/3: Inno Setup — wrap into installer
echo ============================================================
where iscc >nul 2>nul
if errorlevel 1 (
    if exist "C:\Program Files (x86)\Inno Setup 6\iscc.exe" (
        set ISCC="C:\Program Files (x86)\Inno Setup 6\iscc.exe"
    ) else (
        echo [ERROR] iscc.exe not found. Install Inno Setup 6 from
        echo https://jrsoftware.org/isdl.php
        exit /b 1
    )
) else (
    set ISCC=iscc
)
%ISCC% installer.iss
if errorlevel 1 (
    echo [ERROR] Inno Setup compilation failed.
    exit /b 1
)

echo.
echo ============================================================
echo  Build complete!
echo ============================================================
echo Installer: dist\SheinExtract-Setup-*.exe
echo.
echo Next steps:
echo   1. Test the installer on a clean Windows VM
echo   2. git tag v3.5.0 ^&^& git push --tags
echo   3. Create GitHub release v3.5.0 with dist\SheinExtract-Setup-3.5.0.exe attached
echo   4. Send the installer link to employees
echo ============================================================
