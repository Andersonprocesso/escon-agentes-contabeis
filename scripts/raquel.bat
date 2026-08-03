@echo off
REM Raquel - triagem automatica. Caminhos absolutos: no agendador o cd
REM relativo falhava silenciosamente e o log ia parar em System32.
setlocal
set "PROJ=C:\Users\ander\OneDrive\Desktop\Projetos\Agentes Contabeis Escon"
set "PYEXE=C:\Users\ander\AppData\Local\Programs\Python\Python314\python.exe"
set "PYTHONPATH=%PROJ%\src"
set "PYTHONIOENCODING=utf-8"
set "LOG=%PROJ%\data\logs\raquel.log"
if not exist "%PROJ%\data\logs" mkdir "%PROJ%\data\logs"
echo ===== %DATE% %TIME% ===== >> "%LOG%"
cd /d "%PROJ%" || echo FALHA no cd para %PROJ% >> "%LOG%"
"%PYEXE%" -m escon_agentes raquel-emails --dias 2 >> "%LOG%" 2>&1
echo (saida %ERRORLEVEL%) >> "%LOG%"
endlocal