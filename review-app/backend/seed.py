"""시연용 더미 데이터

실제 분석 결과가 아직 없을 때 화면을 확인하기 위한 데이터.
영상은 ffmpeg 의 테스트 패턴으로 짧은 mp4 3개를 만들어 여러 케이스가 돌려 쓴다.
"""
import os
import random
import shutil
import subprocess
from datetime import datetime, timedelta

import db
from engine import CONFIDENCE, _lane_desc, _red_desc

REGIONS = ['강남구', '서초구', '송파구', '마포구', '영등포구', '성동구', '강서구', '노원구']


def _ffmpeg():
    return shutil.which('ffmpeg')


def _make_demo_clips():
    d = os.path.join(db.DATA_DIR, 'demo_clips')
    os.makedirs(d, exist_ok=True)
    ff = _ffmpeg()
    paths = []
    for i, pattern in enumerate(['testsrc2', 'smptebars', 'rgbtestsrc'], 1):
        p = os.path.join(d, f'demo_{i}.mp4')
        if not os.path.exists(p) and ff:
            subprocess.run([ff, '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', f'{pattern}=size=640x360:rate=30',
                            '-t', '6', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', p], check=False)
        paths.append(p if os.path.exists(p) else None)
    return paths


def seed(n=40, force=False):
    if db.rows('SELECT 1 FROM cases LIMIT 1') and not force:
        return 0
    if force:
        for t in ('cases', 'history', 'memos', 'videos'):
            db.execute(f'DELETE FROM {t}')
    rnd = random.Random(7)
    clips = _make_demo_clips()
    now = datetime.now()
    for i in range(n):
        kind = rnd.choice(['signal_violation', 'lane_change_no_signal', 'lane_change_no_signal'])
        sec = round(rnd.uniform(5, 55), 1)
        occurred = now - timedelta(days=rnd.randint(0, 29), hours=rnd.randint(0, 23), minutes=rnd.randint(0, 59))
        if kind == 'signal_violation':
            verdict, direction, conf = '적색 신호 위반', None, CONFIDENCE['RED_LIGHT']
            desc = _red_desc(sec)
        else:
            sig = rnd.choice(['OFF', 'OFF', 'WRONG_SIDE'])
            direction = rnd.choice(['L', 'R'])
            verdict = '깜빡이 미점등' if sig == 'OFF' else '반대쪽 깜빡이'
            conf = CONFIDENCE[sig]
            desc = _lane_desc(direction, sig, sec)
        conf = round(min(0.99, max(0.3, conf + rnd.uniform(-0.25, 0.18))), 2)   # 시연용으로 분산
        status = rnd.choices(['pending', 'approved', 'rejected', 'held'], [6, 2, 1, 1])[0]
        cid = db.execute(
            'INSERT INTO cases(video_id,type,t_sec,vehicle_id,verdict,direction,confidence,description,clip_path,'
            'clip_start,region,occurred_at,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (f'demo{i // 3}', kind, sec, rnd.randint(1, 40), verdict, direction, conf, desc, rnd.choice(clips),
             3.0, rnd.choice(REGIONS), occurred.isoformat(timespec='seconds'), status,
             occurred.isoformat(timespec='seconds')))
        if status != 'pending':
            reason = {'rejected': '위반 근거가 불충분합니다.', 'held': '추가 영상 확인이 필요합니다.'}.get(status)
            db.execute('INSERT INTO history(case_id,from_status,to_status,reason,actor,at) VALUES(?,?,?,?,?,?)',
                       (cid, 'pending', status, reason, '담당자A', db.now()))
            if reason:
                db.execute('INSERT INTO memos(case_id,kind,body,actor,at) VALUES(?,?,?,?,?)',
                           (cid, 'reason', reason, '담당자A', db.now()))
    return n
