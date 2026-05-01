@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Shein 总表合并工具 (merge_master)
echo ============================================
echo.
set /p STORE=请输入店铺代号 (例如 C4):
if "%STORE%"=="" (
    echo.
    echo [错误] 未输入店铺代号，退出。
    pause
    exit /b 1
)
echo.
echo 正在合并店铺 %STORE% ...
echo.
C:\Users\ak\anaconda3\python.exe merge_master.py "%STORE%"
set EXIT_CODE=%ERRORLEVEL%
echo.
echo ============================================
if %EXIT_CODE%==0 (
    echo 完成。总表已生成。
) else (
    echo [失败] 合并未成功，请查看上面的错误信息。
)
echo ============================================
pause >nul
