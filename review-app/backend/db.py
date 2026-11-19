"""SQLite 저장소 (표준 라이브러리만 사용)

테이블
- videos   : 업로드된 원본 영상과 분석 진행 상태
- cases    : 위반 클립 1건 = 케이스 1건 (영상 1개 → 케이스 0~N개)
- history  : 처리 상태 변경 이력
- memos    : 담당자 메모 / 반려·보류 사유
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(HERE, 'data'))
DB_PATH = os.path.join(DATA_DIR, 'app.db')
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    path        TEXT NOT NULL,
    region      TEXT,
    status      TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | error
    progress    REAL NOT NULL DEFAULT 0,
    message     TEXT,
    n_cases     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id     TEXT,
    type         TEXT NOT NULL,        -- signal_violation | lane_change_no_signal
    t_sec        REAL,                 -- 원본 영상에서의 위반 시각(초)
    vehicle_id   INTEGER,
    verdict      TEXT,
    direction    TEXT,
    confidence   REAL,                 -- 0~1 (엔진이 값을 주지 않아 규칙 기반 추정치)
    description  TEXT,
    clip_path    TEXT,
    clip_start   REAL,                 -- 클립 안에서 위반 순간(초) → 뷰어 마커
    region       TEXT,
    occurred_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected | held
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_video ON cases(video_id);
CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     INTEGER NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    reason      TEXT,
    actor       TEXT,
    at          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memos (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id  INTEGER NOT NULL,
    kind     TEXT NOT NULL DEFAULT 'note',      -- note | reason
    body     TEXT NOT NULL,
    actor    TEXT,
    at       TEXT NOT NULL
);
"""


def now():
    return datetime.now().isoformat(timespec='seconds')


def init():
    os.makedirs(DATA_DIR, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def connect():
    # 분석 스레드와 요청 스레드가 같이 쓰므로 연결은 호출마다 새로 만들고 쓰기는 락으로 직렬화
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def rows(sql, args=()):
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    r = rows(sql, args)
    return r[0] if r else None


def execute(sql, args=()):
    with connect() as c:
        return c.execute(sql, args).lastrowid
