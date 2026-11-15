@echo off
rem Stops sworkr on Windows. Your data is kept; start.bat brings it back.
cd /d "%~dp0"
docker compose -f docker-compose.prod.yml down
echo.
echo sworkr is stopped. Your data is safe. Double-click start.bat to start it again.
echo.
pause
