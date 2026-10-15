@echo off
setlocal
cd /d "%~dp0"

title AI 테마주 인사이트 리포트 - 자동 검사

if not exist "venv\Scripts\python.exe" goto ERR_VENV

echo ===================================================
echo   AI 테마주 인사이트 리포트 - 로컬 자동 검사
echo ===================================================
echo [안내] 외부 API 호출 없이 가짜 응답으로 80개 테스트를 검증합니다...
echo.

".\venv\Scripts\python.exe" -m unittest discover -s tests -v
goto END

:ERR_VENV
echo.
echo [오류] Python 가상환경 venv 폴더를 찾을 수 없습니다.
echo venv\Scripts\python.exe 경로를 확인해주세요.
echo.
pause
exit /b 1

:END
echo.
echo ===================================================
echo   검사 완료
echo ===================================================
echo.
pause
