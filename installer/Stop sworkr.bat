@echo off
rem Stops sworkr. Your records stay. (Never add -v to these commands: that would delete them.)
cd /d "%~dp0"
docker compose down
echo sworkr is stopped. Double-click "Start sworkr" to start it again.
pause
