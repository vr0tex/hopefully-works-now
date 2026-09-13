@echo off
title Paradox Discord Bot
echo Starting Paradox Discord Bot...

:: If run from the root directory, change to the discord bot directory
cd /d "%~dp0"
if exist "discord bot" (
    cd /d "%~dp0\discord bot"
)

:: Try to find Python in common paths to bypass Microsoft Store redirection issues
set PYTHON_PATH=

:: Check Local App Data (default single-user install)
for /d %%I in ("%LocalAppData%\Programs\Python\Python*") do (
    if exist "%%I\python.exe" set PYTHON_PATH=%%I\python.exe
)

:: Check Program Files (system-wide install)
if "%PYTHON_PATH%"=="" (
    for /d %%I in ("C:\Program Files\Python*") do (
        if exist "%%I\python.exe" set PYTHON_PATH=%%I\python.exe
    )
)

:: Check Program Files x86 (system-wide install 32-bit)
if "%PYTHON_PATH%"=="" (
    for /d %%I in ("C:\Program Files (x86)\Python*") do (
        if exist "%%I\python.exe" set PYTHON_PATH=%%I\python.exe
    )
)

:: Set final command
if not "%PYTHON_PATH%"=="" (
    set PYTHON_CMD="%PYTHON_PATH%"
) else (
    set PYTHON_CMD=python
)

echo Running bot using: %PYTHON_CMD%
%PYTHON_CMD% app.py.py
if %errorlevel% neq 0 (
    echo.
    echo Default Python command failed. Trying 'py' command...
    py app.py.py
)

pause
