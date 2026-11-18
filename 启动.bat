@echo off
title Process Performance Monitor
cd /d "%~dp0"
chcp 65001 >nul

rem Pick a 64-bit Python 3.9+ interpreter. Keep this file pure ASCII:
rem non-ASCII text in a .bat is parsed with the OEM codepage and breaks.

if exist "C:\Program Files\Python39\python.exe" goto run64
where py >nul 2>nul
if not errorlevel 1 goto runpy
where python >nul 2>nul
if not errorlevel 1 goto runpath
if exist "C:\Program Files (x86)\Python39-32\python.exe" goto run32
goto nopython

:run64
"C:\Program Files\Python39\python.exe" app.py %*
goto done

:runpy
py -3 app.py %*
goto done

:runpath
python app.py %*
goto done

:run32
rem 32-bit fallback: only sees 32-bit processes reliably, use with care.
"C:\Program Files (x86)\Python39-32\python.exe" app.py %*
goto done

:done
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo [FAILED] The tool exited with an error - see the messages above.
echo Copy them when reporting the problem, then press any key to close.
pause >nul
exit /b 1

:nopython
echo.
echo [FAILED] Python 3.9+ not found.
echo Install 64-bit Python 3.9 or newer, then run this file again.
pause >nul
exit /b 1
