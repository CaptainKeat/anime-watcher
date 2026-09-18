@echo off
set "PYTHONPATH=%~dp0vendor;%PYTHONPATH%"
pythonw "%~dp0app.py"
