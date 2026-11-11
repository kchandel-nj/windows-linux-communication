@echo off
:: run.bat - start the SIRIUS hub
cd /d "%~dp0"
:: Prefer the "py" launcher; "python" can be a Microsoft Store shortcut that isn't real Python
py -3 --version >nul 2>&1 && (py -3 pc_server.py & goto :end)
python --version >nul 2>&1 && (python pc_server.py & goto :end)
echo Python was not found. Run setup.bat, or install Python from python.org
echo ^(tick "Add python.exe to PATH"^), then open a new window and try again.
:end
pause