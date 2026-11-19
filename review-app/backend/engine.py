"""분석 엔진 어댑터

팀 AI 파트의 엔진(realcdh/turnsignal 의 turnsignal_app.py)을 그대로 호출해서
결과(events.csv / red_light.csv + 클립 mp4)를 '케이스' dict 목록으로 바꿔 준다.

엔진 위치: 환경변수 TURNSIGNAL_DIR (기본: 레포 루트 = review-app/backend 기준 ../..)
엔진이 없으면 available() 이 False → 업로드 분석은 막고, 시연용 더미 데이터(seed.py)만 사용.
"""
import importlib
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_DIR = os.environ.get('TURNSIGNAL_DIR', os.path.normpath(os.path.join(HERE, '..', '..')))

LANE_VERDICT = {'OFF': '깜빡이 미점등', 'WRONG_SIDE': '반대쪽 깜빡이'}

# 엔진은 신뢰도를 주지 않는다. 임시로 판정 종류별 고정값을 쓰고 화면에는 '추정'으로 표시한다.
# (AI 파트가 점수를 내주면 이 표만 교체하면 됨)
CONFIDENCE = {'OFF': 0.80, 'WRONG_SIDE': 0.75, 'RED_LIGHT': 0.60}

_tp = None


def _load():
    global _tp
    if _tp is not None:
        return _tp
    if not os.path.exists(os.path.join(ENGINE_DIR, 'turnsignal_app.py')):
        return None
    if ENGINE_DIR not in sys.path:
        sys.path.insert(0, ENGINE_DIR)
    try:
        _tp = importlib.import_module('turnsignal_app')   # torch/ultralytics 가 없으면 여기서 실패
    except Exception as e:                                 # noqa: BLE001
        print(f'[engine] 로드 실패: {e}')
        _tp = None
    return _tp


def status():
    """(사용 가능 여부, 안 되면 사유). import 만 되고 torch/모델 파일이 없는 경우도 '불가'로 본다."""
    tp = _load()
    if tp is None:
        return False, f'turnsignal_app.py 를 불러올 수 없습니다 (TURNSIGNAL_DIR={ENGINE_DIR})'
    missing = [m for m in ('torch', 'ultralytics') if importlib.util.find_spec(m) is None]
    if missing:
        return False, '패키지 미설치: ' + ', '.join(missing) + ' (엔진 requirements.txt 설치 필요)'
    absent = [os.path.basename(tp.CFG[k]) for k in ('yolo_weights', 'light_weights') if not os.path.exists(tp.CFG[k])]
    if absent:
        return False, '모델 파일 없음: ' + ', '.join(absent)
    return True, None


def available():
    return status()[0]


def _lane_desc(direction, verdict, sec):
    side = '우측' if direction == 'R' else '좌측'
    if verdict == 'WRONG_SIDE':
        return (f'영상 {sec:.1f}초 부근에서 차량이 {side} 차선으로 변경했으나 '
                f'반대쪽 방향지시등이 점등된 것으로 판정되었습니다.')
    return (f'영상 {sec:.1f}초 부근에서 차량이 {side} 차선으로 변경했으나 '
            f'변경 직전 4초 동안 방향지시등 점등이 확인되지 않았습니다.')


def _red_desc(sec):
    return (f'영상 {sec:.1f}초 부근에서 정지 신호(적색)임에도 차량이 정지선을 넘거나 '
            f'교차로 방향으로 출발한 것으로 판정되었습니다.')


def analyze(video_path, out_dir, progress=None):
    """영상 1개 분석 → 케이스 dict 목록. progress(0~1) 콜백 선택."""
    tp = _load()
    if tp is None:
        raise RuntimeError(f'분석 엔진을 찾을 수 없습니다 (TURNSIGNAL_DIR={ENGINE_DIR})')
    cfg = {**tp.CFG, 'overlay': True}
    res, _, meta = tp.run(video_path, out_dir, cfg, progress=progress)

    cases = []
    rl = meta['red_light']
    for clip, sec, vid in zip(rl['clip'], rl['sec'], rl['id']):
        cases.append(dict(type='signal_violation', t_sec=float(sec), vehicle_id=int(vid), verdict='적색 신호 위반',
                          direction=None, confidence=CONFIDENCE['RED_LIGHT'], description=_red_desc(float(sec)),
                          clip_path=clip))
    if len(res):
        lc = res[res.signal.isin(list(LANE_VERDICT))]
        for clip, sec, vid, d, sig in zip(lc['clip'], lc['sec'], lc['id'], lc['dir'], lc['signal']):
            cases.append(dict(type='lane_change_no_signal', t_sec=float(sec), vehicle_id=int(vid),
                              verdict=LANE_VERDICT[sig], direction=d, confidence=CONFIDENCE[sig],
                              description=_lane_desc(d, sig, float(sec)), clip_path=clip))
    return cases
