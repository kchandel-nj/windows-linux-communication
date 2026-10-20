@echo off
:: setup.bat - one-time setup for the SIRIUS hub (Windows)
:: Double-click it, or run it from a terminal in the hub folder.
:: Safe to run again: anything already done is skipped.
::   1. Python            (installs with winget if missing)
::   2. Python packages   (requirements.txt)
::   3. .env              (starter config if missing)
::   4. Ollama + model    (installs with winget if missing, pulls OLLAMA_MODEL)
::   5. Firewall rule     (inbound TCP on SERVER_PORT; asks for admin once)

setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title SIRIUS hub setup
set /a WARN=0

:: ---------------------------------------------------------------- 1. Python
echo == 1/5 Python
python --version >nul 2>&1
if not errorlevel 1 goto :python_ok
echo   [..]   Python not found. Installing with winget...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo   [warn] Python was just installed. Close this window and run setup.bat again
echo          so Windows picks up the new "python" command.
pause
exit /b 1
:python_ok
for /f "tokens=2" %%V in ('python --version 2^>^&1') do echo   [ok]   Python %%V

:: ---------------------------------------------------------------- 2. Packages
echo == 2/5 Python packages
if not exist requirements.txt (echo python-dotenv> requirements.txt)
python -m pip install --quiet --upgrade pip >nul 2>&1
python -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo   [warn] pip install failed
    set /a WARN+=1
) else (
    echo   [ok]   requirements.txt
)

:: ---------------------------------------------------------------- 3. .env
echo == 3/5 Config (.env)
if exist .env (
    echo   [skip] .env already exists
) else (
    > .env (
        echo SERVER_PORT=5001
        echo OLLAMA_MODEL=llama3.2
        echo OLLAMA_URL=http://localhost:11434/api/generate
        echo OLLAMA_TIMEOUT=50
        echo OLLAMA_KEEP_ALIVE=-1
    )
    echo   [ok]   created .env
)
set "MODEL=llama3.2"
set "PORT=5001"
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    for /f "tokens=1" %%C in ("%%B") do (
        if /i "%%A"=="OLLAMA_MODEL" set "MODEL=%%C"
        if /i "%%A"=="SERVER_PORT"  set "PORT=%%C"
    )
)
echo          model: !MODEL!   port: !PORT!

:: ---------------------------------------------------------------- 4. Ollama
echo == 4/5 Ollama
set "OLLAMA=ollama"
where ollama >nul 2>&1
if not errorlevel 1 goto :ollama_found
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if exist "!OLLAMA!" goto :ollama_found
echo   [..]   Ollama not found. Installing with winget...
winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
if exist "!OLLAMA!" goto :ollama_found
echo   [warn] Ollama install failed. Install it from https://ollama.com/download and rerun.
set /a WARN+=1
goto :firewall
:ollama_found
echo   [ok]   Ollama installed

:: Make sure the Ollama server is answering (the tray app normally handles this)
curl -s -o nul http://localhost:11434
if not errorlevel 1 goto :ollama_up
echo   [..]   Starting Ollama...
start "Ollama" /min "!OLLAMA!" serve
for /l %%i in (1,1,20) do (
    timeout /t 1 /nobreak >nul
    curl -s -o nul http://localhost:11434 && goto :ollama_up
)
echo   [warn] Ollama didn't start. Open Ollama from the Start menu and rerun.
set /a WARN+=1
goto :firewall
:ollama_up
echo   [ok]   Ollama is running

echo   [..]   Pulling model !MODEL! (first time can take a few minutes)...
"!OLLAMA!" pull !MODEL!
if errorlevel 1 (
    echo   [warn] Couldn't pull !MODEL!. If it was a "digest mismatch", just rerun setup.bat.
    set /a WARN+=1
) else (
    echo   [ok]   Model !MODEL! ready
)

:: ---------------------------------------------------------------- 5. Firewall
:firewall
echo == 5/5 Firewall (inbound TCP !PORT!)
netsh advfirewall firewall show rule name="SIRIUS Hub" >nul 2>&1
if not errorlevel 1 (
    echo   [skip] rule "SIRIUS Hub" already exists
    goto :done
)
net session >nul 2>&1
if errorlevel 1 (
    echo   [..]   Asking for administrator permission to add the rule...
    powershell -NoProfile -Command "Start-Process netsh -Verb RunAs -Wait -ArgumentList 'advfirewall firewall add rule name=\"SIRIUS Hub\" dir=in action=allow protocol=TCP localport=!PORT!'"
) else (
    netsh advfirewall firewall add rule name="SIRIUS Hub" dir=in action=allow protocol=TCP localport=!PORT! >nul
)
netsh advfirewall firewall show rule name="SIRIUS Hub" >nul 2>&1
if errorlevel 1 (
    echo   [warn] Firewall rule not added. Allow TCP !PORT! manually, or accept the prompt when the hub first runs.
    set /a WARN+=1
) else (
    echo   [ok]   rule "SIRIUS Hub" allows inbound TCP !PORT!
)

:: ---------------------------------------------------------------- Done
:done
echo.
if !WARN! EQU 0 (
    echo Setup complete.
) else (
    echo Setup finished with !WARN! warning^(s^); see [warn] lines above.
)
echo.
echo Put one of these addresses in the wrist computer's .env as SERVER_IP:
ipconfig | findstr /c:"IPv4"
echo.
echo Start the hub with run.bat ^(or: python pc_server.py^)
pause