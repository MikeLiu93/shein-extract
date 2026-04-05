@echo off
REM 定时任务专用：无 pause，适合 Task Scheduler 调用
cd /d "C:\Users\ak\Desktop\Claude\shein extract"
C:\Users\ak\anaconda3\python.exe take_orders_worker.py --once
exit /b %ERRORLEVEL%
