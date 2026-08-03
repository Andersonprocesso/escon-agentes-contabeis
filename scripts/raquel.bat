@echo off
REM Raquel — triagem automática da caixa contato@escondigital.com.br
REM Agende este arquivo; ele grava log e nunca fica esperando digitação.
cd /d "%~dp0.."
set PYTHONPATH=%CD%\src
set PYTHONIOENCODING=utf-8
if not exist "data\logs" mkdir "data\logs"
echo. >> "data\logs\raquel.log"
echo ===== %DATE% %TIME% ===== >> "data\logs\raquel.log"
python -m escon_agentes raquel-emails --dias 2 >> "data\logs\raquel.log" 2>&1
echo (saida %ERRORLEVEL%) >> "data\logs\raquel.log"
