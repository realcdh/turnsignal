#!/bin/bash
# 더블클릭 실행 (macOS). 처음 한 번은 설치 때문에 5~10분 걸림
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "[처음 실행] 파이썬 가상환경 만들고 패키지 설치 중..."
  python3 -m venv .venv || { echo "python3 가 없습니다. https://www.python.org 에서 Python 3.10 이상 설치 후 다시 실행하세요."; read -r; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt || { echo "패키지 설치 실패. 인터넷 연결 확인 후 다시 실행하세요."; read -r; exit 1; }
fi
echo "프로그램 시작 - 브라우저가 열립니다 (안 열리면 http://127.0.0.1:7860). 끝내려면 이 창을 닫으세요."
.venv/bin/python gui_app.py
