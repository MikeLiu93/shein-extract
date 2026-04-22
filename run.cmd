@echo off
cd /d "C:\Users\ak\Desktop\Claude\shein extract"
echo ===== Processing new submitted files =====
C:\Users\ak\anaconda3\python.exe take_orders_worker.py --once
echo.
echo ===== Retrying previously failed URLs =====
C:\Users\ak\anaconda3\python.exe take_orders_worker.py --retry
echo.
echo Done. Press any key to close...
pause >nul
