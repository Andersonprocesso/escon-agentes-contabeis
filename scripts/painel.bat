@echo off
REM Painel Escon - abre o dashboard local no navegador.
REM Caminhos absolutos: rodar de outra pasta (ex.: System32) quebrava o import.
setlocal
set "PROJ=C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon"
set "PYTHONPATH=%PROJ%\src"
set "PYTHONIOENCODING=utf-8"
cd /d "%PROJ%"
echo Abrindo o painel em http://127.0.0.1:8787 ...
start "" http://127.0.0.1:8787
"C:\Users\ander\AppData\Local\Programs\Python\Python314\python.exe" -m escon_agentes dashboard
pause