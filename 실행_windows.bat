@echo off
chcp 65001 > nul
rem 더블클릭 실행 (Windows). 처음 한 번은 설치 때문에 5~10분 걸림
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo [처음 실행] 파이썬 가상환경 만들고 패키지 설치 중...
  py -3 -m venv .venv || python -m venv .venv || (echo Python 이 없습니다. https://www.python.org 에서 Python 3.10 이상 설치 ^(Add to PATH 체크^) 후 다시 실행하세요. & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || (echo 패키지 설치 실패. 인터넷 연결 확인 후 다시 실행하세요. & pause & exit /b 1)
)
echo 프로그램 시작 - 브라우저가 열립니다 (안 열리면 http://127.0.0.1:7860). 끝내려면 이 창을 닫으세요.
.venv\Scripts\python gui_app.py
pause
