@echo off
REM Scheduled task entry point: no pause, for Task Scheduler use
cd /d "C:\Users\ak\Desktop\Claude\shein extract"
if not exist debug_logs mkdir debug_logs
REM Log stdout/stderr to timestamped cmd_*.log for troubleshooting
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set TS=%DT:~0,8%_%DT:~8,6%
set CMDLOG=debug_logs\cmd_%TS%.log
echo ===== %DATE% %TIME% scheduled run start ===== > "%CMDLOG%"
echo --- python --once --- >> "%CMDLOG%"
C:\Users\ak\anaconda3\python.exe take_orders_worker.py --once >> "%CMDLOG%" 2>&1
set ONCE_RC=%ERRORLEVEL%
echo --- once exit code: %ONCE_RC% --- >> "%CMDLOG%"
echo --- python --retry --- >> "%CMDLOG%"
C:\Users\ak\anaconda3\python.exe take_orders_worker.py --retry >> "%CMDLOG%" 2>&1
set RETRY_RC=%ERRORLEVEL%
echo --- retry exit code: %RETRY_RC% --- >> "%CMDLOG%"
exit /b %RETRY_RC%
