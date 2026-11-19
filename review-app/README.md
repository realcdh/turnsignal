# 교통 위반 영상 검토 서비스

시민이 신고한 블랙박스 영상을 AI(YOLO 기반 엔진)가 분석해 **위반 클립 단위 케이스**로 만들고,
공무원이 대시보드에서 영상을 확인하고 **승인 / 반려 / 보류** 처리하는 웹 서비스.

```
backend/   FastAPI + SQLite   케이스 API, 상태 변경·이력·메모, 통계, 업로드→분석 작업
frontend/  Vite + React       목록(필터·정렬) / 상세(영상 뷰어·처리) / 통계 / 업로드
(레포 루트)  팀 AI 엔진 turnsignal_app.py — 이 앱의 상위 폴더에 있음
tests/     브라우저 E2E
```

## 실행

```bash
# 1) 백엔드
cd backend && pip install -r requirements.txt
uvicorn main:app --reload --port 8000        # 첫 실행 시 시연용 더미 40건 자동 생성 (SEED_DEMO=0 으로 끔)

# 2) 프론트
cd frontend && npm install && npm run dev    # http://localhost:5173  (/api 는 8000 으로 프록시)
```

시연 데이터 영상은 ffmpeg 로 만든 테스트 패턴입니다(ffmpeg 필요). 실제 위반 영상이 아닙니다.

## 실제 AI 엔진 연결

엔진(`turnsignal_app.py`)이 이 폴더의 상위(레포 루트)에 있어서 기본값으로 바로 찾습니다. 다른 위치면 `TURNSIGNAL_DIR=/경로` 로 지정.
```bash
pip install -r ../../requirements.txt                       # 엔진 의존성: torch, ultralytics 등 (2~3GB)
# yolo11n.pt, yolo11s.pt 모델 파일은 레포에 없으므로 레포 루트에 따로 받아 넣을 것
SEED_DEMO=0 uvicorn main:app --port 8000                    # backend/ 에서 실행
```
엔진이 잡히면 사이드바가 "AI 엔진 연결됨"으로 바뀌고 `/upload` 가 동작합니다.
분석은 느리므로(영상 1분당 1~10분) 백그라운드 작업 1개씩 순서대로 돌고, 화면은 2초마다 진행률을 확인합니다.
**실제 엔진 연결은 이 환경에서 검증하지 못했습니다** (모델·샘플 영상·torch 없음). `backend/engine.py` 가 엔진의 `run()` 반환값(`res`, `meta['red_light']`)을 읽는 부분을 처음 연결할 때 확인하세요.

## API (자세한 건 http://127.0.0.1:8000/docs)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/cases` | 목록. `type` `status` `region`(복수 가능) `days` `q` `sort` `page` `size` |
| GET | `/api/cases/{id}` | 상세 + 처리 이력 + 메모 + 같은 영상의 다른 클립 |
| PATCH | `/api/cases/{id}/status` | 상태 변경. 반려·보류는 `reason` 필수(422) |
| POST | `/api/cases/{id}/memos` | 메모 추가 |
| GET | `/api/cases/{id}/clip` | 클립 영상 (Range 지원). `?download=true` 면 다운로드 |
| GET | `/api/stats` | 유형·상태·지역·일자별 집계, 처리율 |
| POST/GET | `/api/videos`, `/api/videos/{id}` | 업로드→분석 시작, 진행 상태 |

## 주차별 계획과 코드 위치

| 주차 | 내용 | 위치 | 상태 |
|---|---|---|---|
| 1~2 | IA, 레이아웃, 디자인 시스템 | `styles.css`(토큰), `components/Layout.jsx`, `lib/constants.js` | 구현됨 |
| 3 | 라우팅, 케이스 리스트 | `App.jsx`, `pages/CaseList.jsx` | 구현됨 |
| 4 | 상세, 영상 뷰어 | `pages/CaseDetail.jsx`, `components/VideoViewer.jsx` | 구현됨 |
| 5 | 승인/반려/보류, 메모, 이력 | `ActionPanel` `MemoPanel` `HistoryTimeline` | 구현됨 |
| 6 | 정렬·필터 | `FilterPanel`, URL 쿼리 동기화 | 구현됨 (필터는 서버 쿼리) |
| 7 | API 연동, 로딩·에러 | `api/client.js`, `hooks/useFetch.js`, `States.jsx` | 구현됨 |
| 8~9 | 통합·반응형·엣지케이스 | 반응형 CSS, 페이지네이션, 빈 화면 | 기본만 (실데이터 통합 테스트 필요) |
| 고규민 | 통계 | `pages/Statistics.jsx`, `/api/stats` | **뼈대** (차트 4종, 필터 연동·히트맵 없음) |

## 알려진 한계 (솔직하게)

- **위반 유형은 2종**: 신호위반, 깜빡이 미점등 차선변경. 정지선 위반 이륜차·안전거리 미확보는 엔진에 없음.
- **신뢰도는 추정값**: 엔진이 점수를 주지 않아 판정 종류별 고정값(`engine.py` 의 `CONFIDENCE`)을 쓰고 화면에도 "추정"으로 표시.
- **발생 일시·지역은 엔진 결과가 아님**: 업로드 시각과 업로드 때 고른 지역을 사용. 시연 데이터는 임의 값.
- 프레임 이동은 30fps 로 가정. 인증/권한 없음(담당자 이름 고정). 엔진 검출률은 낮음(신호위반 ~12%, 차선변경 37~46%, 엔진 README 기준).
- 테스트는 브라우저 E2E 1개뿐 (`tests/e2e.py`, 17개 항목 통과).

## 나중에 Electron 으로 감싸기
화면은 `npm run build` 결과(`frontend/dist`)를 FastAPI 가 정적으로 서빙하게 하거나, Electron 이 백엔드를 자식 프로세스로 띄우고 창에서 `http://127.0.0.1:8000` 을 열면 됩니다. Python/torch 를 exe 안에 묶는 건 용량·설정 부담이 커서 비추.
