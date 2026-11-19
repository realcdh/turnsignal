"""교통 위반 영상 검토 서비스 - FastAPI 백엔드

실행:  uvicorn main:app --reload --port 8000     (backend 폴더에서)
문서:  http://127.0.0.1:8000/docs
"""
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import db
import engine
import seed as seed_mod

STATUSES = ('pending', 'approved', 'rejected', 'held')
TYPES = ('signal_violation', 'lane_change_no_signal')
REASON_REQUIRED = ('rejected', 'held')

# 분석(YOLO)은 무거우므로 한 번에 하나씩만 돌린다
executor = ThreadPoolExecutor(max_workers=1)


@asynccontextmanager
async def lifespan(_app):
    db.init()
    if os.environ.get('SEED_DEMO', '1') == '1':      # 비어 있으면 시연용 데이터 채움 (끄려면 SEED_DEMO=0)
        seed_mod.seed()
    yield


app = FastAPI(title='교통 위반 검토 API', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                   allow_methods=['*'], allow_headers=['*'])


# ───────────────────────── 케이스 ─────────────────────────
def _case_view(c):
    c = dict(c)
    c['has_clip'] = bool(c.get('clip_path')) and os.path.exists(c['clip_path'])
    c.pop('clip_path', None)
    return c


@app.get('/api/cases')
def list_cases(type: list[str] = Query(default=[]), status: list[str] = Query(default=[]),
               region: list[str] = Query(default=[]), q: Optional[str] = None,
               days: Optional[int] = Query(default=None, ge=1), date_from: Optional[str] = None,
               date_to: Optional[str] = None,
               sort: Literal['priority', 'confidence', 'newest', 'oldest'] = 'priority',
               page: int = Query(default=1, ge=1), size: int = Query(default=20, ge=1, le=100)):
    where, args = [], []
    for col, vals in (('type', type), ('status', status), ('region', region)):
        if vals:
            where.append(f'{col} IN ({",".join("?" * len(vals))})')
            args += vals
    if q:
        where.append('(description LIKE ? OR verdict LIKE ? OR CAST(id AS TEXT)=?)')
        args += [f'%{q}%', f'%{q}%', q]
    if days:
        where.append("occurred_at >= datetime('now','localtime',?)")
        args.append(f'-{days} days')
    if date_from:
        where.append('occurred_at >= ?')
        args.append(date_from)
    if date_to:
        where.append('occurred_at <= ?')
        args.append(date_to + 'T23:59:59')
    w = ('WHERE ' + ' AND '.join(where)) if where else ''
    order = {
        # 대기 건 먼저 → 신뢰도 높은 것 먼저(빠른 승인 가능) → 접수가 오래된 것 먼저
        'priority': "(status='pending') DESC, confidence DESC, occurred_at ASC",
        'confidence': 'confidence DESC',
        'newest': 'occurred_at DESC',
        'oldest': 'occurred_at ASC',
    }[sort]
    total = db.one(f'SELECT COUNT(*) n FROM cases {w}', args)['n']
    items = db.rows(f'SELECT * FROM cases {w} ORDER BY {order}, id LIMIT ? OFFSET ?', args + [size, (page - 1) * size])
    return dict(items=[_case_view(c) for c in items], total=total, page=page, size=size)


@app.get('/api/cases/{case_id}')
def get_case(case_id: int):
    c = db.one('SELECT * FROM cases WHERE id=?', (case_id,))
    if not c:
        raise HTTPException(404, '존재하지 않는 케이스입니다')
    out = _case_view(c)
    out['history'] = db.rows('SELECT * FROM history WHERE case_id=? ORDER BY id DESC', (case_id,))
    out['memos'] = db.rows('SELECT * FROM memos WHERE case_id=? ORDER BY id DESC', (case_id,))
    # 같은 원본 영상에서 나온 다른 클립(1영상 → N클립)
    out['siblings'] = [_case_view(s) for s in db.rows(
        'SELECT * FROM cases WHERE video_id=? AND id<>? ORDER BY t_sec', (c['video_id'], case_id))] if c['video_id'] else []
    return out


class StatusIn(BaseModel):
    status: Literal['pending', 'approved', 'rejected', 'held']
    reason: Optional[str] = None
    actor: str = '담당자'


@app.patch('/api/cases/{case_id}/status')
def change_status(case_id: int, body: StatusIn):
    c = db.one('SELECT id,status FROM cases WHERE id=?', (case_id,))
    if not c:
        raise HTTPException(404, '존재하지 않는 케이스입니다')
    reason = (body.reason or '').strip()
    if body.status in REASON_REQUIRED and not reason:
        raise HTTPException(422, '반려·보류는 사유를 입력해야 합니다')
    if body.status == c['status']:
        raise HTTPException(409, '이미 같은 상태입니다')
    db.execute('UPDATE cases SET status=? WHERE id=?', (body.status, case_id))
    db.execute('INSERT INTO history(case_id,from_status,to_status,reason,actor,at) VALUES(?,?,?,?,?,?)',
               (case_id, c['status'], body.status, reason or None, body.actor, db.now()))
    if reason:
        db.execute('INSERT INTO memos(case_id,kind,body,actor,at) VALUES(?,?,?,?,?)',
                   (case_id, 'reason', reason, body.actor, db.now()))
    return get_case(case_id)


class MemoIn(BaseModel):
    body: str
    actor: str = '담당자'


@app.post('/api/cases/{case_id}/memos', status_code=201)
def add_memo(case_id: int, body: MemoIn):
    if not db.one('SELECT id FROM cases WHERE id=?', (case_id,)):
        raise HTTPException(404, '존재하지 않는 케이스입니다')
    if not body.body.strip():
        raise HTTPException(422, '메모 내용이 비어 있습니다')
    db.execute('INSERT INTO memos(case_id,kind,body,actor,at) VALUES(?,?,?,?,?)',
               (case_id, 'note', body.body.strip(), body.actor, db.now()))
    return get_case(case_id)


@app.get('/api/cases/{case_id}/clip')
def get_clip(case_id: int, download: bool = False):
    c = db.one('SELECT clip_path,type,id FROM cases WHERE id=?', (case_id,))
    if not c or not c['clip_path'] or not os.path.exists(c['clip_path']):
        raise HTTPException(404, '클립 파일이 없습니다')
    name = f"case_{c['id']}_{c['type']}.mp4"
    # FileResponse 는 Range 요청을 지원하므로 <video> 의 구간 이동(시킹)이 된다
    return FileResponse(c['clip_path'], media_type='video/mp4', filename=name if download else None)


# ───────────────────────── 통계 ─────────────────────────
@app.get('/api/stats')
def stats():
    by_type = db.rows('SELECT type, COUNT(*) n FROM cases GROUP BY type')
    by_status = db.rows('SELECT status, COUNT(*) n FROM cases GROUP BY status')
    by_region = db.rows('SELECT region, COUNT(*) n FROM cases WHERE region IS NOT NULL GROUP BY region ORDER BY n DESC')
    by_day = db.rows("SELECT substr(occurred_at,1,10) day, COUNT(*) n FROM cases GROUP BY day ORDER BY day")
    total = sum(r['n'] for r in by_status)
    done = sum(r['n'] for r in by_status if r['status'] != 'pending')
    pending_old = db.one("SELECT COUNT(*) n FROM cases WHERE status='pending' AND occurred_at < datetime('now','localtime','-7 days')")['n']
    return dict(total=total, processed=done, process_rate=round(done / total, 3) if total else 0,
                pending_over_7d=pending_old, by_type=by_type, by_status=by_status, by_region=by_region, by_day=by_day)


@app.get('/api/meta')
def meta():
    ok, reason = engine.status()
    return dict(engine_available=ok, engine_reason=reason, engine_dir=engine.ENGINE_DIR)


# ───────────────────────── 업로드 · 분석 ─────────────────────────
def _run_job(video_id, path):
    out_dir = os.path.join(db.DATA_DIR, 'outputs', video_id)
    db.execute("UPDATE videos SET status='running', message='분석 중' WHERE id=?", (video_id,))
    try:
        video = db.one('SELECT region FROM videos WHERE id=?', (video_id,))
        cases = engine.analyze(path, out_dir, progress=lambda p: db.execute(
            'UPDATE videos SET progress=? WHERE id=?', (round(float(p), 3), video_id)))
        ts = db.now()
        for c in cases:
            db.execute(
                'INSERT INTO cases(video_id,type,t_sec,vehicle_id,verdict,direction,confidence,description,clip_path,'
                'clip_start,region,occurred_at,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (video_id, c['type'], c['t_sec'], c['vehicle_id'], c['verdict'], c['direction'], c['confidence'],
                 c['description'], c['clip_path'], 4.0 if c['type'] == 'lane_change_no_signal' else None,
                 video['region'], ts, 'pending', ts))
        db.execute("UPDATE videos SET status='done', progress=1, n_cases=?, message=? WHERE id=?",
                   (len(cases), f'위반 {len(cases)}건 탐지', video_id))
    except Exception as e:                                  # noqa: BLE001
        db.execute("UPDATE videos SET status='error', message=? WHERE id=?", (str(e)[:300], video_id))


@app.post('/api/videos', status_code=202)
async def upload_video(file: UploadFile = File(...), region: Optional[str] = Form(None)):
    ok, reason = engine.status()
    if not ok:
        raise HTTPException(503, f'분석 엔진을 사용할 수 없습니다: {reason}')
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ('.mp4', '.mov', '.avi', '.mkv'):
        raise HTTPException(415, '지원하지 않는 영상 형식입니다 (mp4, mov, avi, mkv)')
    vid = uuid.uuid4().hex[:10]
    d = os.path.join(db.DATA_DIR, 'uploads')
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f'{vid}{ext}')
    with open(path, 'wb') as f:
        shutil.copyfileobj(file.file, f)
    db.execute('INSERT INTO videos(id,filename,path,region,created_at) VALUES(?,?,?,?,?)',
               (vid, file.filename, path, region, db.now()))
    executor.submit(_run_job, vid, path)
    return dict(id=vid, status='queued')


@app.get('/api/videos')
def list_videos():
    return db.rows('SELECT id,filename,region,status,progress,message,n_cases,created_at FROM videos ORDER BY created_at DESC')


@app.get('/api/videos/{video_id}')
def get_video(video_id: str):
    v = db.one('SELECT id,filename,region,status,progress,message,n_cases,created_at FROM videos WHERE id=?', (video_id,))
    if not v:
        raise HTTPException(404, '존재하지 않는 영상입니다')
    return v


@app.post('/api/dev/seed')
def dev_seed(force: bool = False):
    """시연용 더미 데이터 (force=true 면 기존 데이터 삭제 후 다시 생성)"""
    return dict(created=seed_mod.seed(force=force))
