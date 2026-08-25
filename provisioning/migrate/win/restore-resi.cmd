@echo off
REM Self-elevating DESTRUCTIVE restore of the RESI image onto the SD card (PHYSICALDRIVE1).
REM Double-click, approve the UAC prompt, then type RESTORE when asked. THIS ERASES THE CARD.
setlocal
set "PS1=%~dp0Restore-Card.ps1"
set "IMG=%USERPROFILE%\sdcard\sd-card.img"
set "LOG=%USERPROFILE%\sdcard\resi-restore.log"

net session >nul 2>&1
if %errorlevel%==0 goto :elevated

echo Requesting administrator rights (approve the UAC prompt)...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:elevated
echo Restoring RESI image -^> PHYSICALDRIVE1
echo   image: %IMG%
echo   (writes the whole card; ~6-9 min. Progress is written to the log.)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -DiskNumber 1 -ImageFile "%IMG%" -LogFile "%LOG%"
echo.
echo Done. Log: %LOG%
pause
