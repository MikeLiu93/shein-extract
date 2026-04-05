@echo off
cd /d "C:\Users\ak\Desktop\Claude\shein extract"
C:\Users\ak\anaconda3\python.exe take_orders_worker.py --once
echo.
echo Done. Press any key to close...
pause >nul
