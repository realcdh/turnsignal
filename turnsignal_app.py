"""
차선 변경 차량 탐지 + 방향지시등(깜빡이) 점등 판정 (단일 파일)
=================================================================
입력 : 주행(블랙박스) 영상
출력 : 차선을 바꾼 모든 차량의 클립(.mp4, 디버그 오버레이 포함) + 대표 사진(.jpg) + events.csv
       각 이벤트마다 이동 방향 쪽 깜빡이 ON / OFF / 반대쪽(WRONG) / 비상등(HAZARD) / 관측 부족(UNKNOWN) 판정

파이프라인
  1) YOLO(COCO) + ByteTrack 으로 차량 탐지·추적
  2) 횡위치 d = (차 뒷면 중심 x - 소실점 x) / 차 뒷면 폭   [단위: 차폭]
     - 거리와 무관(가까운 차·먼 차 모두 같은 척도), 차선 도색이 흐려도 동작
     - 옆면이 보이는 가까운 차는 박스 중심이 안쪽으로 쏠리므로 '뒷면' 폭(≈높이×1.25)으로 보정
     - 소실점은 내 차로 좌/우 차선의 교점(없으면 화면 중앙)
  3) d 가 앞뒤 2.5초 사이에 1차폭 이상 이동 = 차선 변경 이벤트
     내 차가 차로를 바꾼 경우(차선 좌표 급변 또는 주변 차들이 같은 방향으로 동시에 이동)는 제외
  4) 깜빡이: 차량 박스 왼/오른쪽 절반의 '호박색' 픽셀 비율 신호에서
     0.35~1.6초 간격으로 반복되는 펄스가 2회 이상이면 점등
     (호박색 = R>140, G-B 와 R-G 가 모두 큼. 붉은 미등·흰 차체는 G≈B 라 제외됨)
  5) 신호위반 (traffic_violation_yolo11 노트북 방식 통합)
     - 같은 스캔에서 COCO 'traffic light' 도 탐지 → 켜진 램프 HSV 색으로 RED/YELLOW/GREEN
     - 가장 앞(램프 1칸이 가장 큰) 차량 신호등 하나만 사용, 보행자 신호등(2구)은 비율로 제외
     - 신호등 평행 라인: y = 신호등 하단 + 램프 1칸(px) × rl_offset_lamps (카메라가 움직여도 따라감)
     - 차량 접지점(박스 하단 중앙)이 라인 아래 → 위로 넘는 순간 신호가 RED 면 신호위반

실행
  pip install ultralytics lap opencv-python pandas numpy pyyaml gradio
  python turnsignal_app.py --video 주행영상.mp4 --out outputs           # 이벤트 클립 저장
  python turnsignal_app.py --video 주행영상.mp4 --out outputs --debug   # + 전체 디버그 영상
  python turnsignal_app.py --gui                                         # 웹 GUI

알려진 한계
  - 직선·완만한 곡선 도로 가정 (급커브·교차로 회전 중에는 소실점이 틀어져 d 가 흔들림)
  - 깜빡이는 뒷면이 보이는 차만 판정 (마주 오는 차·측면만 보이는 차는 신뢰 낮음)
  - 역광·과노출로 램프가 하얗게 날아가면 OFF 로 나올 수 있음
"""
import argparse
import os
import shutil
import subprocess
import time

import cv2
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))   # 모델 가중치는 프로젝트 폴더 것을 사용 (실행 위치와 무관, 다운로드 없음)

# ──────────────────────────────────────────────────────────────
# 설정값 (시간 단위는 초 → fps 로 환산하므로 영상 fps 와 무관)
# ──────────────────────────────────────────────────────────────
CFG = dict(
    # 탐지·추적
    yolo_weights=os.path.join(HERE, 'yolo11n.pt'), conf=0.25, imgsz=1280, classes=[2, 3, 5, 7],  # car, motorcycle, bus, truck
    track_buffer_sec=3.0,
    # 기록 필터
    edge_px=3,                 # 화면 테두리에 닿은 박스 제외 (잘린 박스는 위치가 틀림)
    min_w_ratio=0.035,         # 화면 폭의 3.5% 보다 좁은 (먼) 차 제외 (작으면 d 잡음이 큼)
    max_area_ratio=0.5,        # 화면 절반 이상 박스 제외 (보닛 오탐)
    # 차선 (소실점 추정·내 차 차로 변경 감지용)
    roi_top=0.62, roi_bot=0.93,
    lane_alpha=0.2,
    # 횡위치
    rear_aspect=1.25,          # 뒷면 폭 ≈ 박스 높이 × 이 값 (옆면 보이는 차 보정)
    smooth_sec=0.7,            # d 이동 중앙값 평활 창
    split_jump=0.8,            # 한 프레임에 d 가 이만큼 튀면 ID 스위칭 → 궤적 분리
    max_gap_sec=0.5,           # 이보다 오래 끊기면 궤적 분리
    # 차선 변경
    half_win_sec=2.5,          # 변경 시점 앞뒤로 이만큼 떨어진 구간끼리 비교
    min_half_win_sec=1.0,      # 궤적이 짧으면 위 간격을 이 값까지 줄여서 비교
    level_sec=1.0,             # 비교 구간 길이
    min_shift=0.8,             # 최소 횡이동 (차폭 단위, 차로 1개 ≈ 2차폭)
    cross_margin=0.2, cross_min_shift=0.5,   # 경계를 양쪽으로 이만큼 넘고 이만큼 이동했으면 이동량이 작아도 인정
    ego_pad_sec=3.0,           # 내 차 차로 변경 전후 이 시간 동안 이벤트 무시
    ego_follow_ratio=0.6,      # 다른 차들이 같은 방향으로 이 비율 이상 같이 움직이면 내 차 이동으로 판단
    # 깜빡이
    sig_pre_sec=4.0, sig_post_sec=1.0,   # 차선을 넘는 순간 기준 판정 창
    sig_min_sec=2.0,           # 판정 창 안에서 차가 이보다 짧게 보였으면 OFF 대신 UNKNOWN (근거 부족)
    amber_min=0.05,            # 호박색 점수(상위 1% 픽셀 평균) 최소치. 이하 = 꺼짐
    blink_min_period=0.35, blink_max_period=1.6,   # 법규상 분당 60~120회 ≈ 0.5~1.0초, 여유 포함
    min_pulses=2, min_pulse_sec=0.1,
    # 신호위반
    light_class=9,             # COCO traffic light
    light_weights=os.path.join(HERE, 'yolo11s.pt'), light_conf=0.05,   # 신호등은 작아서 별도 모델(s)·낮은 임계값. AI Hub 표본 탐지율 n 54% → s 88%
    light_scan_conf=0.02,      # 스캔은 이 값으로 넉넉히 기록하고 판정 때 light_conf 로 거름 (재스캔 없이 조정)
    rl_offset_lamps=14.0,      # 라인 y = 신호등 하단 + 램프 1칸(px) × 이 값 (설치 높이 약 5m ÷ 램프 약 0.38m)
    rl_margin_px=3,            # 라인 근처 떨림 방지
    rl_min_aspect=2.25,        # 차량 신호등 최소 비율(긴 변÷짧은 변). 보행자 신호등(세로 2구) 제외
    rl_lamp_aspect=1.6,        # 이보다 정사각형에 가까운 박스 = 켜진 램프 하나만 잡힌 것(야간 번짐·낮 원거리). 램프 1칸으로 사용
    rl_smooth_sec=0.2,         # 신호 판정 다수결 창
    rl_hold_sec=0.5,           # 신호등이 안 보여도 직전 신호·라인 유지
    rl_line_alpha=0.3,         # 라인 y EMA
    rl_yellow=False,           # True 면 황색불 통과도 위반
    # 신호위반 규칙 2 (블랙박스: 내 차가 정지선에 서 있고 옆·앞 차가 빨간불에 출발하는 경우가 대부분)
    #   빨간불 동안 차가 '멀어짐'(접지점이 위로 + 박스가 작아짐) = 교차로로 진입. 옆으로 지나가는 교차 차량은 크기가 그대로라 제외
    rl_away=True, rl_away_sec=10.0, rl_away_dy=0.5, rl_away_shrink=0.85,
    rl_near_lamps=8.0,         # 출발 지점이 신호등 하단 + 램프×이 값 보다 아래(가까움)일 때만. 이미 교차로를 지난 먼 차 제외
    rl_cross_move=0.3,         # 라인 통과 시 차 자체가 박스 높이×이 값 이상 앞으로 움직였어야 함 (라인만 흔들려 생기는 통과 제외)
    rl_min_h_ratio=0.02,       # 화면 높이의 이 비율보다 낮은 박스 제외 (신호등·표지판을 차로 오인한 것)
    # 출력
    clip_post_sec=2.0,
    overlay=True,              # False 면 클립·사진을 바운딩박스 등 표시 없이 원본으로 저장 (clips_plain/)
)


# ──────────────────────────────────────────────────────────────
# 차선 검출 (고전 CV)
# ──────────────────────────────────────────────────────────────
def lane_mask(frame, top, bot):
    hls = cv2.cvtColor(frame, cv2.COLOR_BGR2HLS)
    mask = cv2.bitwise_or(cv2.inRange(hls, (0, 200, 0), (180, 255, 255)),        # 흰색
                          cv2.inRange(hls, (15, 30, 100), (35, 204, 255)))       # 노란색
    h, w = mask.shape
    yb, yt = int(h * bot), int(h * top)
    roi = np.zeros_like(mask)
    cv2.fillPoly(roi, np.array([[(int(w * .05), yb), (int(w * .45), yt), (int(w * .55), yt), (int(w * .98), yb)]]), 255)
    return cv2.bitwise_and(mask, roi)


def detect_ego_lanes(frame, top, bot):
    """내 차로 (왼쪽선, 오른쪽선). 각 선은 x = a*y + b 의 (a, b). 못 찾으면 None"""
    m = lane_mask(frame, top, bot)
    segs = cv2.HoughLinesP(cv2.Canny(m, 50, 150), 1, np.pi / 180, 20, minLineLength=20, maxLineGap=100)
    if segs is None:
        return None, None
    w = m.shape[1]
    left, right = [], []
    for x1, y1, x2, y2 in np.asarray(segs).reshape(-1, 4):
        if y1 == y2:
            continue
        slope = (x2 - x1) / (y2 - y1)
        if abs(slope) > 3:
            continue
        if slope < 0 and max(x1, x2) < w * .55:
            left.append((x1, y1, x2, y2))
        elif slope > 0 and min(x1, x2) > w * .45:
            right.append((x1, y1, x2, y2))

    def fit(g):
        if not g:
            return None
        return np.polyfit([v for s in g for v in (s[1], s[3])], [v for s in g for v in (s[0], s[2])], 1)
    return fit(left), fit(right)


def _nan2(v):
    return v if v is not None else (np.nan, np.nan)


# ──────────────────────────────────────────────────────────────
# 깜빡이 신호
# ──────────────────────────────────────────────────────────────
def amber_map(crop):
    """픽셀별 호박색 점수 0~1. 켜진 깜빡이: H≈10~16, G-B≈40+, R-G≈40+ / 붉은 미등: G≈B / 흰 차체: R≈G≈B"""
    c = crop.astype(np.float32)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    return np.clip(g - b - 15, 0, 60) * np.clip(r - g - 15, 0, 60) * (r > 140) / 3600.0


def amber_sides(frame, box, top=0.01):
    """박스 왼쪽/오른쪽 절반에서 호박색 점수 상위 1% 픽셀 평균 (좌우 3% 는 배경이라 제외).
    램프는 차 뒷면의 1~3% 정도라 절반 전체 평균을 내면 희석됨 → 상위 픽셀만 봄 (켜짐 ≈0.3~1, 꺼짐 ≈0)"""
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    x1, y1 = max(0, x1), max(0, y1)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0 or crop.shape[1] < 6:
        return np.nan, np.nan
    a = amber_map(crop)
    w = a.shape[1]
    m = max(1, int(w * .03))

    def topmean(x):
        x = x.ravel()
        k = max(3, int(len(x) * top))
        return float(np.partition(x, len(x) - k)[-k:].mean()) if len(x) > k else float(x.mean())
    return topmean(a[:, m:w // 2]), topmean(a[:, w // 2:w - m])


def blink_test(sig, fps, cfg=CFG):
    """호박색 비율 시계열에서 규칙적인 펄스(깜빡임) 찾기"""
    s = pd.Series(np.asarray(sig, float)).interpolate(limit_direction='both').fillna(0).to_numpy()
    out = dict(blink=False, pulses=0, period=np.nan, peak=round(float(s.max()) if len(s) else 0.0, 4))
    if len(s) < fps:
        return out
    lo, hi = np.percentile(s, 10), s.max()
    if hi < cfg['amber_min'] or hi - lo < cfg['amber_min']:
        return out
    on = s > lo + 0.3 * (hi - lo)
    gap = max(1, int(round(cfg['min_pulse_sec'] * fps)))      # 켜짐 중간의 짧은 끊김(압축 잡음) 메우기
    on = cv2.morphologyEx(on.astype(np.uint8)[None], cv2.MORPH_CLOSE, np.ones((1, gap + 1), np.uint8))[0] > 0
    edges = np.diff(np.r_[0, on.astype(int), 0])
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    keep = (ends - starts) >= max(1, int(round(cfg['min_pulse_sec'] * fps)))
    starts = starts[keep]
    per = np.diff(starts) / fps
    good = per[(per >= cfg['blink_min_period']) & (per <= cfg['blink_max_period'])]
    out.update(pulses=int(len(starts)), period=round(float(np.median(good)), 2) if len(good) else np.nan)
    regular = len(good) >= 1 and len(good) >= 0.6 * len(per)
    if len(good) >= 2:
        regular &= good.std() / good.mean() < 0.4
    out['blink'] = bool(len(starts) >= cfg['min_pulses'] and regular)
    return out


# ──────────────────────────────────────────────────────────────
# 신호등 색 · 신호등 평행 라인 (신호위반)
# ──────────────────────────────────────────────────────────────
def classify_light_color(crop, min_ratio=0.03):
    """신호등 crop(BGR)에서 켜진 램프(채도·밝기 높음) 색. 빨강+녹색 화살표 동시 점등은 직진 기준 RED"""
    if crop is None or crop.size == 0 or min(crop.shape[:2]) < 4:
        return 'UNKNOWN'
    h, s, v = cv2.split(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV))
    lit = (s >= 70) & (v >= 140)
    counts = {'RED': int((lit & ((h <= 10) | (h >= 160))).sum()),
              'YELLOW': int((lit & (h >= 15) & (h <= 35)).sum()),
              'GREEN': int((lit & (h >= 40) & (h <= 95)).sum())}      # LED 초록은 청록빛(H≈80~95)
    min_px = max(3, min_ratio * crop.shape[0] * crop.shape[1])
    if counts['RED'] >= min_px:
        return 'RED'
    best = max(counts, key=counts.get)
    return best if counts[best] >= min_px else 'UNKNOWN'


def light_aspect(box):
    w, h = box[2] - box[0], box[3] - box[1]
    return max(w, h) / max(min(w, h), 1.0)


def lamp_size_px(box, cfg=CFG):
    """램프 1칸 크기 = 긴 변 ÷ 램프 개수(긴 변÷짧은 변 반올림, 최소 3구). 가로/세로·3구/4구 공통.
    정사각형에 가까운 박스는 켜진 램프 하나만 잡힌 것 → 박스 자체가 램프 1칸"""
    w, h = box[2] - box[0], box[3] - box[1]
    if light_aspect(box) < cfg['rl_lamp_aspect']:
        return max(w, h)
    return max(w, h) / max(3, int(round(light_aspect(box))))


def is_vehicle_light(L, cfg=CFG):
    """차량 신호등 후보: 가로·세로 3구 이상, 또는 켜진 램프 하나. 세로로 긴 2구(보행자 신호등)는 제외"""
    a, w, h = light_aspect(L[:4]), L[2] - L[0], L[3] - L[1]
    if a >= cfg['rl_min_aspect'] or w >= h:
        return True
    return a < cfg['rl_lamp_aspect'] and L[4] != 'UNKNOWN'


def select_light(lights, cfg=CFG):
    """가장 앞(램프 1칸이 가장 큰) 차량 신호등 1개.
    우선순위: 켜진 3구 이상 > 켜진 램프 하나(가로등 번짐과 헷갈림) > 꺼진 것(옆을 향한 신호등 등)"""
    c = [L for L in lights if is_vehicle_light(L, cfg)]
    lit = [L for L in c if L[4] != 'UNKNOWN']
    multi = [L for L in lit if light_aspect(L[:4]) >= cfg['rl_lamp_aspect']]
    pool = multi or lit or c
    return max(pool, key=lambda L: lamp_size_px(L[:4], cfg)) if pool else None


def content_area(frame, thr=40):
    """레터박스 검은 여백을 뺀 실제 영상 영역"""
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    rows, cols = np.where(g.max(axis=1) > thr)[0], np.where(g.max(axis=0) > thr)[0]
    if not len(rows) or not len(cols):
        return 0, 0, frame.shape[1], frame.shape[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


# ──────────────────────────────────────────────────────────────
# 1회 스캔: 추적 + 차선 + 호박색 신호
# ──────────────────────────────────────────────────────────────
def video_meta(video):
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise FileNotFoundError(f'영상을 열 수 없음: {video}')
    meta = dict(fps=cap.get(cv2.CAP_PROP_FPS) or 30.0, W=int(cap.get(3)), H=int(cap.get(4)),
                n=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    cap.release()
    return meta


def _tracker_yaml(buffer, out_dir):
    import yaml
    import ultralytics
    c = yaml.safe_load(open(os.path.join(os.path.dirname(ultralytics.__file__), 'cfg', 'trackers', 'bytetrack.yaml')))
    c['track_buffer'] = buffer
    path = os.path.join(out_dir, 'bytetrack_custom.yaml')
    with open(path, 'w') as f:
        yaml.safe_dump(c, f)
    return path


def _device():
    import torch
    if torch.cuda.is_available():
        return 0
    return 'mps' if torch.backends.mps.is_available() else 'cpu'


def scan_video(video, out_dir, cfg=CFG, progress=None):
    from ultralytics import YOLO
    meta = video_meta(video)
    rows, raw, ema, lights = [], [], [], []
    L = R = None
    results = YOLO(cfg['yolo_weights']).track(
        source=video, tracker=_tracker_yaml(max(1, int(round(cfg['track_buffer_sec'] * meta['fps']))), out_dir),
        classes=cfg['classes'], conf=cfg['conf'], imgsz=cfg['imgsz'], device=_device(),
        persist=True, stream=True, verbose=False)
    light_model = YOLO(cfg['light_weights'])    # 추적 결과에는 확정된 트랙만 남아 신호등이 빠지므로 따로 탐지
    a = cfg['lane_alpha']
    for i, r in enumerate(results):
        frame = r.orig_img
        if i == 0:
            meta['area'] = content_area(frame)
        l, rr = detect_ego_lanes(frame, cfg['roi_top'], cfg['roi_bot'])
        raw.append([*_nan2(l), *_nan2(rr)])
        L = L if l is None else (l if L is None else (1 - a) * L + a * l)
        R = R if rr is None else (rr if R is None else (1 - a) * R + a * rr)
        ema.append([*_nan2(L), *_nan2(R)])
        if r.boxes.id is not None:
            for tid, cls, box in zip(r.boxes.id.int().tolist(), r.boxes.cls.int().tolist(), r.boxes.xyxy.tolist()):
                rows.append((i, tid, cls, *box, *amber_sides(frame, box)))
        lr = light_model.predict(frame, classes=[cfg['light_class']], conf=cfg['light_scan_conf'], imgsz=cfg['imgsz'],
                                 device=_device(), verbose=False)[0]
        for box, cf in zip(lr.boxes.xyxy.tolist(), lr.boxes.conf.tolist()):
            x1, y1, x2, y2 = [max(0, int(round(v))) for v in box]
            lights.append((i, x1, y1, x2, y2, classify_light_color(frame[y1:y2, x1:x2]), round(cf, 3)))
        if progress and i % 25 == 0:
            progress(min(i / max(meta['n'], 1), 1.0))
    meta['n'] = len(raw)
    df = pd.DataFrame(rows, columns=['frame', 'id', 'cls', 'x1', 'y1', 'x2', 'y2', 'L', 'R'])
    meta['lights'] = pd.DataFrame(lights, columns=['frame', 'x1', 'y1', 'x2', 'y2', 'state', 'conf'])
    return df, np.array(raw, float).reshape(-1, 4), np.array(ema, float).reshape(-1, 4), meta


# ──────────────────────────────────────────────────────────────
# 횡위치 d
# ──────────────────────────────────────────────────────────────
def vanishing_x(lanes_raw, meta, cfg=CFG):
    """프레임별 소실점 x: 좌/우 차선 교점의 이동 중앙값, 없으면 화면 중앙"""
    W, fps = meta['W'], meta['fps']
    aL, bL, aR, bR = lanes_raw.T
    with np.errstate(all='ignore'):
        yv = (bR - bL) / (aL - aR)
        vx = aL * yv + bL
    vx[~((vx > .3 * W) & (vx < .7 * W) & (yv < meta['H'] * cfg['roi_top']))] = np.nan
    s = pd.Series(vx).rolling(int(6 * fps) | 1, center=True, min_periods=max(1, int(fps))).median()
    fill = np.nanmedian(vx) if np.isfinite(vx).sum() >= fps else W / 2
    return s.fillna(fill).to_numpy()


def add_lateral(df, vx, meta, cfg=CFG):
    W, H, fps = meta['W'], meta['H'], meta['fps']
    d = df.copy()
    w, h = d.x2 - d.x1, d.y2 - d.y1
    wr = np.minimum(w, cfg['rear_aspect'] * h)
    v = vx[d.frame.to_numpy(int)]
    # 옆면이 보이는 쪽 반대편이 뒷면 → 화면 왼쪽 차는 박스 오른쪽, 오른쪽 차는 박스 왼쪽이 뒷면
    xr = np.where((d.x1 + d.x2) / 2 < v, d.x2 - wr / 2, d.x1 + wr / 2)
    d['vx'], d['d'] = v, (xr - v) / wr
    e = cfg['edge_px']
    d['ok'] = ((d.x1 > e) & (d.x2 < W - e) & (d.y2 < H - e) & (w >= cfg['min_w_ratio'] * W)
               & (w * h < cfg['max_area_ratio'] * W * H))
    t = d[d.ok].sort_values(['id', 'frame']).copy()
    jump = t.groupby('id').d.diff().abs() > cfg['split_jump']
    gap = t.groupby('id').frame.diff() > cfg['max_gap_sec'] * fps
    t['seg'] = (jump | gap).groupby(t.id).cumsum()
    # 화면에 막 들어오거나 나가는 0.5초는 박스가 불안정 → 제외
    edge_n = int(0.5 * fps)
    g = t.groupby(['id', 'seg']).frame
    t = t[(t.frame - g.transform('min') >= edge_n) & (g.transform('max') - t.frame >= edge_n)].copy()
    k = max(1, int(round(cfg['smooth_sec'] * fps))) | 1
    t['ds'] = t.groupby(['id', 'seg']).d.transform(lambda s: s.rolling(k, center=True, min_periods=1).median())
    return d, t


# ──────────────────────────────────────────────────────────────
# 내 차의 차로 변경 구간
# ──────────────────────────────────────────────────────────────
def ego_lane_changes(lanes_raw, meta, cfg=CFG):
    """내 차가 차선을 넘는 순간 = 차선이 화면 중앙(차로 안 내 위치 c≈0 또는 1)을 지나거나,
    한쪽 끝(c<0.2)에 붙었다가 2초 안에 반대쪽(c>0.8)으로 뒤바뀜 (넘고 나면 좌/우선 배정이 바뀜).
    넘는 동안엔 양쪽 선이 동시에 잡히지 않으므로 한쪽 선 + 평소 차로 폭으로 c 를 계산"""
    W, H, fps = meta['W'], meta['H'], meta['fps']
    yb = H * cfg['roi_bot']
    aL, bL, aR, bR = lanes_raw.T
    xl, xr = aL * yb + bL, aR * yb + bR
    both = np.isfinite(xl) & np.isfinite(xr)
    if both.sum() < fps:
        return []
    lw = np.median((xr - xl)[both])
    cl, cr = (W / 2 - xl) / lw, 1 - (xr - W / 2) / lw
    center = (np.abs(cl) < .08) | (np.abs(cr - 1) < .08)
    low = pd.Series(((cl < .2) | (cr < .2)).astype(int))
    high = pd.Series(((cl > .8) | (cr > .8)).astype(int))
    n = int(2 * fps) | 1
    flip = ((low.rolling(n, center=True, min_periods=1).max() > 0)
            & (high.rolling(n, center=True, min_periods=1).max() > 0)).to_numpy()
    hit = center | (flip & ((low | high).to_numpy() > 0))
    pad = int(cfg['ego_pad_sec'] * fps)
    out = []
    for f in np.flatnonzero(hit):
        if out and f - pad <= out[-1][1]:
            out[-1] = (out[-1][0], int(f + pad))
        else:
            out.append((int(f - pad), int(f + pad)))
    return out


def _in_ego(f, ego):
    return any(a <= f <= b for a, b in ego)


# ──────────────────────────────────────────────────────────────
# 차선 변경 이벤트
# ──────────────────────────────────────────────────────────────
def find_events(t, meta, ego, cfg=CFG):
    fps = meta['fps']
    T, Lw = int(cfg['half_win_sec'] * fps), max(2, int(cfg['level_sec'] * fps))
    cand = []
    for (tid, seg), g in t.groupby(['id', 'seg']):
        f, ds = g.frame.to_numpy(), g.ds.to_numpy()
        n = len(ds)
        Tk = min(T, (n - 1) // 2 - Lw)          # 짧은 궤적(짧은 클립·늦게 잡힌 차)은 비교 간격을 줄여서라도 봄
        if Tk < cfg['min_half_win_sec'] * fps:
            continue
        ks = np.arange(Tk + Lw, n - Tk - Lw)
        bef = np.array([np.median(ds[k - Tk - Lw:k - Tk]) for k in ks])
        aft = np.array([np.median(ds[k + Tk:k + Tk + Lw]) for k in ks])
        delta = aft - bef
        # 이동량이 min_shift 에 못 미쳐도 차로 경계(d=±1,±3)를 여유 있게 넘었으면 인정 (클립이 변경 도중에 시작·끝나는 경우)
        m = cfg['cross_margin']
        crossed = np.zeros(len(ks), bool)
        for bd in (-3, -1, 1, 3):
            crossed |= ((bef < bd - m) & (aft > bd + m)) | ((bef > bd + m) & (aft < bd - m))
        score = np.where(crossed & (np.abs(delta) >= cfg['cross_min_shift']), np.maximum(np.abs(delta), cfg['min_shift']), np.abs(delta))
        used = np.zeros(len(ks), bool)
        while True:
            dd = np.where(used, 0, score)
            j = int(dd.argmax())
            if dd[j] < cfg['min_shift']:
                break
            k = ks[j]
            mid = (bef[j] + aft[j]) / 2
            lo, hi = k - Tk, k + Tk
            cross = lo + int(np.argmin(np.abs(ds[lo:hi + 1] - mid)))   # 중간값을 지나는 순간 = 차선을 넘는 순간
            cand.append(dict(id=int(tid), seg=int(seg), frame=int(f[cross]), sec=round(f[cross] / fps, 1),
                             start=int(f[lo]), end=int(f[hi]), d_before=round(float(bef[j]), 2),
                             d_after=round(float(aft[j]), 2), shift=round(float(delta[j]), 2),
                             dir='R' if delta[j] > 0 else 'L'))
            used |= np.abs(ks - k) <= 2 * Tk + Lw
    ev = pd.DataFrame(cand)
    if ev.empty:
        return ev
    # 천천히 바꾸는 차는 같은 방향 이벤트 두 개로 쪼개짐 → 구간이 이어지면 하나로 병합
    ev = ev.sort_values(['id', 'seg', 'frame']).reset_index(drop=True)
    merged = []
    for _, e in ev.iterrows():
        p = merged[-1] if merged else None
        if p is not None and (p['id'], p['seg'], p['dir']) == (e['id'], e['seg'], e['dir']) and e['start'] <= p['end'] + T:
            p.update(end=e['end'], d_after=e['d_after'], shift=round(e['d_after'] - p['d_before'], 2))
        else:
            merged.append(e.to_dict())
    # 차선을 넘는 순간: 차로 경계(d = ±1, ±3 … 차로 1개 ≈ 2차폭)를 지나는 프레임, 경계가 없으면 중간값
    for p in merged:
        g = t[(t.id == p['id']) & (t.seg == p['seg']) & t.frame.between(p['start'], p['end'])]
        lo, hi = sorted((p['d_before'], p['d_after']))
        bounds = [b for b in (-5, -3, -1, 1, 3, 5) if lo < b < hi]
        target = min(bounds, key=lambda b: abs(b - (lo + hi) / 2)) if bounds else (lo + hi) / 2
        f = int(g.frame.iloc[int(np.argmin(np.abs(g.ds.to_numpy() - target)))])
        p.update(frame=f, sec=round(f / fps, 1))
    ev = pd.DataFrame(merged)
    ev['ego'] = ev.frame.apply(lambda f0: _in_ego(f0, ego))
    # 같은 시간대에 다른 차들도 같은 방향으로 움직였으면 = 내 차가 움직인 것. 두 가지로 봄:
    #  - 차폭 단위(d): 내 차가 옆으로 이동하면 모든 차의 d 가 같이 변함 (크기 절반 미만 먼 차는 잡음이 커서 제외)
    #  - 픽셀 단위: 내 차가 살짝 회전하면 모든 차가 화면에서 같은 픽셀만큼 밀림 (먼 차일수록 d 로는 크게 부풀려짐)
    rw = lambda g: np.minimum(g.x2 - g.x1, cfg['rear_aspect'] * (g.y2 - g.y1)).median()
    follow = []
    for _, e in ev.iterrows():
        a, b = e.start - Lw, e.end + Lw
        me = t[(t.id == e.id) & t.frame.between(a, b)]
        w_ev, px_ev = (me.x2 - me.x1).median(), abs(e['shift']) * rw(me)
        others = t[(t.id != e.id) & t.frame.between(a, b)]
        moved, moved_px = [], []
        for _, g in others.groupby(['id', 'seg']):
            if g.frame.min() > a + Lw or g.frame.max() < b - Lw:
                continue
            m = (g.ds.iloc[-Lw:].median() - g.ds.iloc[:Lw].median()) * np.sign(e['shift'])
            moved_px.append(m * rw(g))
            if (g.x2 - g.x1).median() >= 0.5 * w_ev:
                moved.append(m)
        r = cfg['ego_follow_ratio']
        follow.append((len(moved) >= 1 and np.mean(np.array(moved) > r * abs(e['shift'])) > 0.5)
                      or (len(moved_px) >= 1 and np.mean(np.array(moved_px) > r * px_ev) > 0.5))
    ev['ego'] |= np.array(follow, bool)
    return ev


# ──────────────────────────────────────────────────────────────
# 깜빡이 판정
# ──────────────────────────────────────────────────────────────
def judge(df, ev, meta, cfg=CFG):
    fps = meta['fps']
    rows = []
    for _, e in ev.iterrows():
        a, b = e.frame - int(cfg['sig_pre_sec'] * fps), e.frame + int(cfg['sig_post_sec'] * fps)
        g = df[(df.id == e.id) & df.frame.between(a, b)].drop_duplicates('frame').set_index('frame')
        g = g.reindex(range(int(a), int(b) + 1))
        mv, op = ('R', 'L') if e.dir == 'R' else ('L', 'R')
        bm, bo = blink_test(g[mv], fps, cfg), blink_test(g[op], fps, cfg)
        seen = g[mv].notna().sum() / fps          # 차가 실제로 보인 시간
        signal = ('HAZARD' if bm['blink'] and bo['blink'] else 'ON' if bm['blink']
                  else 'WRONG_SIDE' if bo['blink'] else 'OFF' if seen >= cfg['sig_min_sec'] else 'UNKNOWN')
        rows.append({**e.to_dict(), 'signal': signal, 'pulses': bm['pulses'], 'period': bm['period'],
                     'amber_peak': bm['peak'], 'other_pulses': bo['pulses']})
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────
# 신호위반 판정
# ──────────────────────────────────────────────────────────────
def signal_timeline(lights, meta, cfg=CFG):
    """프레임별 (신호, 기준 신호등 박스, 라인 y). 다수결 안정화 + 잠깐 안 보이면 직전 값 유지"""
    n, fps = meta['n'], meta['fps']
    area = meta.get('area', (0, 0, meta['W'], meta['H']))
    k = max(1, int(round(cfg['rl_smooth_sec'] * fps)))
    hold = int(round(cfg['rl_hold_sec'] * fps))
    if 'conf' in lights:
        lights = lights[lights.conf >= cfg['light_conf']]
    by = {f: list(g[['x1', 'y1', 'x2', 'y2', 'state']].itertuples(index=False, name=None))
          for f, g in lights.groupby('frame')} if len(lights) else {}
    state, box, line = ['UNKNOWN'] * n, [None] * n, np.full(n, np.nan)
    hist, miss_s, miss_l, y, s, b = [], 0, 0, np.nan, 'UNKNOWN', None
    for i in range(n):
        ch = select_light(by.get(i, []), cfg)
        obs = ch[4] if ch else 'UNKNOWN'
        if obs == 'UNKNOWN':
            miss_s += 1
            if miss_s > hold:
                s, hist = 'UNKNOWN', []
        else:
            miss_s = 0
            hist = (hist + [obs])[-k:]
            s = max(set(hist), key=hist.count)
        tol = 3                                    # 화면 가장자리에 잘린 신호등은 라인 기준에서 제외
        ok = ch is not None and ch[0] > area[0] + tol and ch[1] > area[1] + tol and ch[2] < area[2] - tol
        if ok:
            miss_l, b = 0, ch
            yy = ch[3] + cfg['rl_offset_lamps'] * lamp_size_px(ch[:4])
            y = yy if np.isnan(y) else (1 - cfg['rl_line_alpha']) * y + cfg['rl_line_alpha'] * yy
        else:
            miss_l += 1
            if miss_l > hold:
                y, b = np.nan, None
        state[i], box[i], line[i] = s, b, y
    return state, box, line


def _away_on_red(g, state, box, bad, fps, cfg):
    """빨간불 동안 차가 교차로 쪽으로 멀어진 첫 프레임 (없으면 None)"""
    f = g.frame.to_numpy(int)
    y2, w, h = g.y2.to_numpy(), (g.x2 - g.x1).to_numpy(), (g.y2 - g.y1).to_numpy()
    red = np.array([state[i] in bad for i in f])
    win = int(cfg['rl_away_sec'] * fps)
    for a in np.flatnonzero(red):
        b0 = box[f[a]]
        if b0 is None or y2[a] < b0[3] + cfg['rl_near_lamps'] * lamp_size_px(b0[:4]):
            continue
        for b in range(a + 1, len(f)):
            if f[b] - f[a] > win or not red[b]:
                break
            if (y2[a] - y2[b]) >= cfg['rl_away_dy'] * h[a] and w[b] <= cfg['rl_away_shrink'] * w[a]:
                return int(f[b])
    return None


def red_light_events(df, meta, cfg=CFG):
    """차량 접지점이 라인 아래(+1) → 위(-1)로 넘는 순간의 신호. 차량당 1회.
    반환: 통과 기록 전체(violation 열 포함), 프레임별 신호 정보"""
    fps = meta['fps']
    state, box, line = signal_timeline(meta.get('lights', pd.DataFrame()), meta, cfg)
    bad = {'RED', 'YELLOW'} if cfg['rl_yellow'] else {'RED'}
    m = cfg['rl_margin_px']
    rows = []
    e = cfg['edge_px']                             # 화면 테두리에 닿은 박스(잘린 차)·아주 작은 박스 제외
    df = df[(df.x1 > e) & (df.y1 > e) & (df.x2 < meta['W'] - e) & (df.y2 < meta['H'] - e)
            & (df.y2 - df.y1 >= cfg['rl_min_h_ratio'] * meta['H'])]
    for tid, g in df.sort_values('frame').groupby('id'):
        prev, y_below = None, None
        for r in g.itertuples():
            y = line[int(r.frame)]
            side = 0 if np.isnan(y) else 1 if r.y2 > y + m else -1 if r.y2 < y - m else 0
            if side == 0:
                continue
            if side == 1:
                y_below = r.y2 if y_below is None else max(y_below, r.y2)
            if prev == 1 and side == -1 and y_below - r.y2 >= cfg['rl_cross_move'] * (r.y2 - r.y1):
                rows.append(dict(id=int(tid), frame=int(r.frame), sec=round(r.frame / fps, 2), cls=int(r.cls),
                                 signal=state[int(r.frame)], line_y=round(float(y), 1),
                                 violation=state[int(r.frame)] in bad, rule='line'))
                break
            prev = side
        else:
            if cfg['rl_away']:
                hit = _away_on_red(g, state, box, bad, fps, cfg)
                if hit is not None:
                    rows.append(dict(id=int(tid), frame=hit, sec=round(hit / fps, 2), cls=int(g.cls.iloc[0]),
                                     signal=state[hit], line_y=np.nan, violation=True, rule='away'))
    ev = pd.DataFrame(rows, columns=['id', 'frame', 'sec', 'cls', 'signal', 'line_y', 'violation', 'rule'])
    ev['violation'] = ev.violation.astype(bool)    # 빈 표에서도 불리언 인덱싱이 되게
    return ev, dict(state=state, box=box, line=line)


# ──────────────────────────────────────────────────────────────
# 오버레이 그리기 (클립·디버그 영상 공용)
# ──────────────────────────────────────────────────────────────
COL = dict(ON=(0, 200, 0), OFF=(0, 0, 255), WRONG_SIDE=(0, 140, 255), HAZARD=(255, 0, 255), UNKNOWN=(160, 160, 160))
LIGHT_COL = dict(RED=(0, 0, 255), YELLOW=(0, 215, 255), GREEN=(0, 200, 0), UNKNOWN=(180, 180, 180))
SIG_KO = dict(ON='ON', OFF='OFF', WRONG_SIDE='WRONG SIDE', HAZARD='HAZARD', UNKNOWN='UNKNOWN (too short)')


def _text(img, s, org, scale=0.6, col=(255, 255, 255), th=2):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), th + 3, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)


def _plot(img, x0, y0, w, h, series, cur, title, ylim=None):
    """간단한 선 그래프 (series: [(x배열, y배열, 색)], cur: 현재 x)"""
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), (30, 30, 30), -1)
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), (200, 200, 200), 1)
    xs = np.concatenate([s[0] for s in series if len(s[0])]) if any(len(s[0]) for s in series) else np.array([0, 1])
    ys = np.concatenate([s[1] for s in series if len(s[1])]) if any(len(s[1]) for s in series) else np.array([0, 1])
    ys = ys[np.isfinite(ys)] if np.isfinite(ys).any() else np.array([0, 1])
    xa, xb = xs.min(), max(xs.max(), xs.min() + 1e-6)
    ya, yb = ylim if ylim else (ys.min(), max(ys.max(), ys.min() + 1e-6))
    for X, Y, c in series:
        ok = np.isfinite(Y)
        pts = np.stack([x0 + (X[ok] - xa) / (xb - xa) * w, y0 + h - (Y[ok] - ya) / (yb - ya) * h], 1)
        if len(pts) > 1:
            cv2.polylines(img, [np.clip(pts, [x0, y0], [x0 + w, y0 + h]).astype(np.int32)], False, c, 2)
    cx = int(x0 + (cur - xa) / (xb - xa) * w)
    cv2.line(img, (cx, y0), (cx, y0 + h), (255, 255, 255), 1)
    _text(img, title, (x0 + 5, y0 + 16), 0.45, (220, 220, 220), 1)


def draw_signal(img, i, rl):
    """기준 신호등(신호 색 박스) + 신호등 평행 라인 + 현재 신호"""
    st = rl['state'][i]
    col = LIGHT_COL[st]
    b = rl['box'][i]
    if b is not None:
        cv2.rectangle(img, (b[0], b[1]), (b[2], b[3]), col, 3)
    y = rl['line'][i]
    if np.isfinite(y):
        cv2.line(img, (0, int(y)), (img.shape[1], int(y)), (0, 0, 255) if st == 'RED' else (255, 255, 255), 2)
        _text(img, 'LIGHT LINE', (10, int(y) - 6), 0.5, (0, 0, 255) if st == 'RED' else (255, 255, 255), 1)
    _text(img, f'LIGHT {st}', (img.shape[1] - 230, img.shape[0] - 20), 0.8, col)


def draw_frame(img, i, meta, by_frame, lanes_ema, vx, ego, cfg, ev=None, trk=None, rl=None):
    """한 프레임에 디버그 정보 그리기. ev/trk 가 있으면 해당 이벤트 차량 강조 + 신호 그래프"""
    W, H, fps = meta['W'], meta['H'], meta['fps']
    raw = img.copy() if ev is not None else None          # 확대 창은 선을 그리기 전 원본에서 자름
    yt, yb = int(H * cfg['roi_top']), int(H * cfg['roi_bot'])
    roi = np.array([(int(W * .05), yb), (int(W * .45), yt), (int(W * .55), yt), (int(W * .98), yb)], np.int32)
    cv2.polylines(img, [roi], True, (0, 255, 255), 1)
    aL, bL, aR, bR = lanes_ema[i]
    for a, b, c in [(aL, bL, (255, 0, 0)), (aR, bR, (0, 0, 255))]:
        if np.isfinite(a):
            cv2.line(img, (int(a * yb + b), yb), (int(a * yt + b), yt), c, 3)
    v = int(vx[i])
    for y in range(0, H, 16):
        cv2.line(img, (v, y), (v, y + 8), (0, 255, 255), 1)
    rows = by_frame.get(i)
    if rows is not None:
        for r in rows.itertuples():
            if ev is not None and r.id == ev['id']:
                continue
            col = (180, 180, 180) if r.ok else (90, 90, 90)
            cv2.rectangle(img, (int(r.x1), int(r.y1)), (int(r.x2), int(r.y2)), col, 1)
            _text(img, f'id{r.id} d={r.d:+.1f}', (int(r.x1), max(14, int(r.y1) - 4)), 0.45, col, 1)
    _text(img, f'{i / fps:6.1f}s  f{i}', (10, 28), 0.8)
    if _in_ego(i, ego):
        _text(img, 'EGO LANE CHANGE (ignored)', (220, 28), 0.8, (0, 200, 255))
    if rl is not None:
        draw_signal(img, i, rl)
    if ev is None:
        return img

    col = COL[ev['signal']]
    t0, t1 = trk.index.min(), trk.index.max()
    if i in trk.index:
        r = trk.loc[i]
        x1, y1, x2, y2 = int(r.x1), int(r.y1), int(r.x2), int(r.y2)
        z = raw[max(0, y1):y2, max(0, x1):x2].copy()
        if z.size:
            am = amber_map(z) > 0.15                                  # 호박색 픽셀을 주황으로 칠해 보여줌
            img[max(0, y1):y2, max(0, x1):x2][am] = (0, 140, 255)
            s = 200 / max(z.shape[:2])                                # 확대 창 (원본, 주황 표시 없음)
            z = cv2.resize(z, None, fx=s, fy=s)
            cv2.rectangle(z, (0, 0), (z.shape[1] - 1, z.shape[0] - 1), col, 3)
            cv2.line(z, (z.shape[1] // 2, 0), (z.shape[1] // 2, z.shape[0]), col, 1)
            img[45:45 + z.shape[0], W - 10 - z.shape[1]:W - 10] = z
        cv2.rectangle(img, (x1, y1), (x2, y2), col, 3)
        xm = (x1 + x2) // 2
        cv2.line(img, (xm, y1), (xm, y2), col, 1)
        _text(img, f'L {r.L * 1000:.0f}', (x1 + 2, y2 - 6), 0.5, (0, 200, 255), 1)
        _text(img, f'R {r.R * 1000:.0f}', (xm + 2, y2 - 6), 0.5, (0, 200, 255), 1)
        _text(img, f'id{ev["id"]} d={r.d:+.2f}', (x1, max(18, y1 - 30)), 0.6, col)
        _text(img, f'LANE CHANGE {"->R" if ev["dir"] == "R" else "L<-"} | SIGNAL {SIG_KO[ev["signal"]]}',
              (x1, max(38, y1 - 8)), 0.6, col)
    # 그래프: d, 호박색 L/R (클립 구간만)
    trk = trk.loc[ev['f0']:ev['f1']]
    fr = trk.index.to_numpy() / fps
    pw, ph, px = 380, 90, 10
    sa, sb = ev['frame'] - cfg['sig_pre_sec'] * fps, ev['frame'] + cfg['sig_post_sec'] * fps
    _plot(img, px, 45, pw, ph, [(fr, trk.d.to_numpy(), (0, 255, 255)), (fr, trk.ds.to_numpy(), (255, 255, 255))],
          i / fps, f'lateral d (car widths)  {ev["d_before"]:+.1f} -> {ev["d_after"]:+.1f}')
    _plot(img, px, 45 + ph + 8, pw, ph, [(fr, trk.L.to_numpy() * 1000, (255, 160, 0)),
                                         (fr, trk.R.to_numpy() * 1000, (0, 140, 255))],
          i / fps, f'amber L(blue) R(orange)  pulses={ev["pulses"]} '
                   + (f'period={ev["period"]}s' if np.isfinite(ev['period']) else 'no blink'))
    for xx in (sa, sb, ev['frame']):
        X = int(px + (xx / fps - fr.min()) / max(fr.max() - fr.min(), 1e-6) * pw)
        if px <= X <= px + pw:
            cv2.line(img, (X, 45), (X, 45 + 2 * ph + 8), (0, 255, 0) if xx != ev['frame'] else (0, 0, 255), 1)
    return img


# ──────────────────────────────────────────────────────────────
# 출력
# ──────────────────────────────────────────────────────────────
def find_ffmpeg():
    """정상 동작하는 ffmpeg (아나콘다의 고장 난 ffmpeg 회피: 환경변수 → Homebrew → PATH → pip imageio-ffmpeg 내장본)"""
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        bundled = None
    for c in [os.environ.get('FFMPEG'), '/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', shutil.which('ffmpeg'), bundled]:
        if not c or not os.path.exists(c):
            continue
        try:
            subprocess.run([c, '-version'], capture_output=True, check=True, timeout=10)
            return c
        except Exception:
            continue
    raise RuntimeError('동작하는 ffmpeg 를 찾지 못함 (pip install imageio-ffmpeg 또는 brew install ffmpeg)')


def write_video(video, out_path, f0, f1, meta, draw):
    """f0~f1 프레임을 draw(img, i) 로 그려 H.264 mp4 로 저장"""
    tmp = out_path + '.tmp.mp4'
    vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*'mp4v'), meta['fps'], (meta['W'], meta['H']))
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    for i in range(f0, f1 + 1):
        ok, img = cap.read()
        if not ok:
            break
        vw.write(draw(img, i))
    cap.release()
    vw.release()
    subprocess.run([find_ffmpeg(), '-y', '-loglevel', 'error', '-i', tmp, '-c:v', 'libx264', '-preset', 'veryfast',
                    '-crf', '23', '-pix_fmt', 'yuv420p', out_path], check=True)
    os.remove(tmp)
    return out_path


def export_event(video, k, e, d_all, t, ctx, out_dir, cfg=CFG):
    meta = ctx['meta']
    fps = meta['fps']
    trk = d_all[d_all.id == e['id']].drop_duplicates('frame').set_index('frame').sort_index()
    trk = trk.join(t[t.id == e['id']].drop_duplicates('frame').set_index('frame')[['ds']])
    f0 = max(0, int(e['frame'] - (cfg['sig_pre_sec'] + 0.5) * fps))
    f1 = min(meta['n'] - 1, int(e['frame'] + cfg['clip_post_sec'] * fps))
    tag = f'{k:02d}_id{e["id"]}_{e["sec"]:.1f}s_{e["dir"]}_{e["signal"]}'
    os.makedirs(out_dir, exist_ok=True)
    e = {**e.to_dict(), 'f0': f0, 'f1': f1}

    def draw(img, i):
        return draw_frame(img, i, meta, ctx['by_frame'], ctx['lanes_ema'], ctx['vx'], ctx['ego'], cfg, e, trk, ctx.get('rl'))
    if not cfg['overlay']:
        draw = lambda img, i: img                 # noqa: E731  표시 없이 원본
    clip = write_video(video, os.path.join(out_dir, tag + '.mp4'), f0, f1, meta, draw)
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(e['frame']))
    ok, img = cap.read()
    cap.release()
    photo = os.path.join(out_dir, tag + '.jpg')
    if ok:
        cv2.imwrite(photo, draw(img, int(e['frame'])))
    return photo, clip


def export_redlight(video, k, e, d_all, ctx, out_dir, cfg=CFG):
    """신호위반 클립: 위반 차량 빨간 박스 + 접지점 + 신호등·라인"""
    meta = ctx['meta']
    fps = meta['fps']
    trk = d_all[d_all.id == e['id']].drop_duplicates('frame').set_index('frame')
    f0 = max(0, int(e['frame'] - 3 * fps))
    f1 = min(meta['n'] - 1, int(e['frame'] + cfg['clip_post_sec'] * fps))
    tag = f'RL{k:02d}_id{e["id"]}_{e["sec"]:.1f}s_{e["signal"]}'
    os.makedirs(out_dir, exist_ok=True)

    def draw(img, i):
        img = draw_frame(img, i, meta, ctx['by_frame'], ctx['lanes_ema'], ctx['vx'], ctx['ego'], cfg, rl=ctx['rl'])
        if i in trk.index:
            r = trk.loc[i]
            x1, y1, x2, y2 = int(r.x1), int(r.y1), int(r.x2), int(r.y2)
            col = (0, 0, 255) if i >= e['frame'] else (0, 140, 255)
            cv2.rectangle(img, (x1, y1), (x2, y2), col, 3)
            cv2.circle(img, ((x1 + x2) // 2, y2), 6, col, -1)
            _text(img, f'id{e["id"]} RED LIGHT VIOLATION' if i >= e['frame'] else f'id{e["id"]} approaching',
                  (x1, max(20, y1 - 8)), 0.6, col)
        if i >= e['frame']:
            _text(img, f'RED LIGHT VIOLATION  id{e["id"]}  {e["sec"]:.1f}s', (10, 60), 0.9, (0, 0, 255))
        return img
    if not cfg['overlay']:
        draw = lambda img, i: img                 # noqa: E731  표시 없이 원본
    clip = write_video(video, os.path.join(out_dir, tag + '.mp4'), f0, f1, meta, draw)
    cap = cv2.VideoCapture(video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(e['frame']))
    ok, img = cap.read()
    cap.release()
    photo = os.path.join(out_dir, tag + '.jpg')
    if ok:
        cv2.imwrite(photo, draw(img, int(e['frame'])))
    return photo, clip


# ──────────────────────────────────────────────────────────────
# 전체 실행
# ──────────────────────────────────────────────────────────────
def run(video, out_dir, cfg=CFG, progress=None, debug=False, log=None):
    """반환: (이벤트 표, [(사진, 클립), ...], 메타)"""
    log = log or (lambda msg: None)
    os.makedirs(out_dir, exist_ok=True)
    # 스캔(가장 느린 단계) 결과를 저장해 두고, 같은 영상이면 재사용 → 임계값 조정 시 몇 초 만에 재판정
    cache = os.path.join(out_dir, 'scan.pkl')
    key = (os.path.abspath(video), os.path.getsize(video), os.path.basename(cfg['yolo_weights']), cfg['conf'],
           cfg['imgsz'], cfg['roi_top'], cfg['roi_bot'], cfg['lane_alpha'], os.path.basename(cfg['light_weights']),
           cfg['light_scan_conf'])
    hit = os.path.exists(cache) and pd.read_pickle(cache)
    if hit and hit[0] == key:
        log('1/3 이전 스캔 결과 재사용 (scan.pkl)')
        df, lanes_raw, lanes_ema, meta = hit[1]
    else:
        log('1/3 차량 추적·차선·깜빡이 신호 수집 중')
        df, lanes_raw, lanes_ema, meta = scan_video(video, out_dir, cfg, progress)
        pd.to_pickle((key, (df, lanes_raw, lanes_ema, meta)), cache)
    meta = dict(meta)
    vx = vanishing_x(lanes_raw, meta, cfg)
    d_all, t = add_lateral(df, vx, meta, cfg)
    ego = ego_lane_changes(lanes_raw, meta, cfg)
    log('2/3 차선 변경·깜빡이 판정 중')
    ev = find_events(t, meta, ego, cfg)
    res = judge(df, ev[~ev.ego], meta, cfg) if len(ev) else pd.DataFrame()
    d_all.to_csv(os.path.join(out_dir, 'tracks.csv'), index=False)
    if len(ev):
        ev.to_csv(os.path.join(out_dir, 'candidates.csv'), index=False)   # 내 차 이동으로 제외된 것 포함
    rl_all, rl = red_light_events(df, meta, cfg)
    rl_all.to_csv(os.path.join(out_dir, 'light_crossings.csv'), index=False)   # 라인 통과 전체 (초록불 통과 포함)
    pd.DataFrame(dict(state=rl['state'], line_y=rl['line'])).rename_axis('frame').to_csv(
        os.path.join(out_dir, 'signal.csv'))                                      # 프레임별 신호·라인
    ctx = dict(meta=meta, by_frame={f: g for f, g in d_all.groupby('frame')}, lanes_ema=lanes_ema, vx=vx, ego=ego,
               rl=rl)
    viol = rl_all[rl_all.violation].reset_index(drop=True)
    log(f'3/3 클립 저장 중 (차선 변경 {len(res)}건, 신호위반 {len(viol)}건)')
    outs, paths = [], []
    for k, (_, e) in enumerate(res.iterrows(), 1):
        p, c = export_event(video, k, e, d_all, t, ctx, os.path.join(out_dir, 'clips' if cfg['overlay'] else 'clips_plain'), cfg)
        outs.append((p, c))
        paths.append(c)
    if len(res):
        res['clip'] = paths
        res = res.drop(columns=['seg', 'ego'])
    res.to_csv(os.path.join(out_dir, 'events.csv'), index=False)
    vpaths = []
    for k, (_, e) in enumerate(viol.iterrows(), 1):
        p, c = export_redlight(video, k, e, d_all, ctx, os.path.join(out_dir, 'clips' if cfg['overlay'] else 'clips_plain'), cfg)
        outs.append((p, c))
        vpaths.append(c)
    viol['clip'] = vpaths
    viol.to_csv(os.path.join(out_dir, 'red_light.csv'), index=False)
    meta['red_light'] = viol
    if debug:
        log('디버그 영상 저장 중 (전체 프레임)')
        meta['debug_video'] = write_video(
            video, os.path.join(out_dir, 'debug.mp4'), 0, meta['n'] - 1, meta,
            lambda img, i: draw_frame(img, i, meta, ctx['by_frame'], lanes_ema, vx, ego, cfg, rl=rl))
    meta['ego_changes'] = [round((a + b) / 2 / meta['fps'], 1) for a, b in ego]
    return res, outs, meta


# ──────────────────────────────────────────────────────────────
# GUI (Gradio)
# ──────────────────────────────────────────────────────────────
def launch_gui(out_root='outputs', share=False, cfg=CFG):
    import gradio as gr
    os.makedirs(out_root, exist_ok=True)

    def analyze(video, progress=gr.Progress()):
        if video is None:
            raise gr.Error('영상을 올려 주세요')
        out_dir = os.path.join(out_root, 'gui_runs', time.strftime('%Y%m%d_%H%M%S'))
        res, outs, meta = run(video, out_dir, cfg, progress=lambda p: progress(p, desc='분석 중'))
        n_off = int(res.signal.isin(['OFF', 'WRONG_SIDE']).sum()) if len(res) else 0
        n_unk = int((res.signal == 'UNKNOWN').sum()) if len(res) else 0
        summary = (f"영상 {meta['n'] / meta['fps']:.1f}초 | 차선 변경 {len(res)}건 | 깜빡이 미점등·오점등 {n_off}건"
                   + (f" | 관측 부족 판정불가 {n_unk}건" if n_unk else '') + f" | 신호위반 {len(meta['red_light'])}건")
        clips = [c for _, c in outs]
        table = res.drop(columns=['clip']) if len(res) else pd.DataFrame({'결과': ['차선 변경 없음']})
        return summary, [p for p, _ in outs], (clips[0] if clips else None), (clips or None), table

    with gr.Blocks(title='차선 변경·깜빡이·신호위반 판정') as demo:
        gr.Markdown('## 차선 변경 차량 탐지 · 깜빡이 점등 판정 · 신호위반')
        with gr.Row():
            inp = gr.Video(label='주행 영상')
            with gr.Column():
                btn = gr.Button('분석 시작', variant='primary')
                summary = gr.Textbox(label='요약')
        gallery = gr.Gallery(label='차선 변경 · 신호위반 장면', columns=3, height='auto')
        with gr.Row():
            clip_view = gr.Video(label='첫 번째 클립')
            clip_files = gr.File(label='클립 전체', file_count='multiple')
        table = gr.Dataframe(label='판정 내역')
        btn.click(analyze, inp, [summary, gallery, clip_view, clip_files, table])
    demo.launch(share=share, allowed_paths=[os.path.abspath(out_root)])


# ──────────────────────────────────────────────────────────────
# 명령줄
# ──────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='차선 변경 차량 탐지 · 깜빡이 점등 판정 · 신호위반')
    ap.add_argument('--video', help='분석할 주행 영상')
    ap.add_argument('--out', default='outputs', help='결과 폴더')
    ap.add_argument('--debug', action='store_true', help='전체 프레임 디버그 영상(debug.mp4)도 저장')
    ap.add_argument('--gui', action='store_true', help='Gradio 웹 GUI')
    ap.add_argument('--share', action='store_true', help='GUI 외부 공유 링크')
    ap.add_argument('--roi-top', type=float, help=f"차선 탐색 영역 윗선 (기본 {CFG['roi_top']})")
    ap.add_argument('--roi-bot', type=float, help=f"차선 탐색 영역 아랫선 (기본 {CFG['roi_bot']})")
    args = ap.parse_args()
    cfg = dict(CFG)
    if args.roi_top is not None:
        cfg['roi_top'] = args.roi_top
    if args.roi_bot is not None:
        cfg['roi_bot'] = args.roi_bot
    if args.gui:
        return launch_gui(args.out, args.share, cfg)
    if not args.video:
        return ap.print_help()

    def bar(p):
        print(f'\r   진행 {p:5.0%}', end='', flush=True)
    res, outs, meta = run(args.video, args.out, cfg, progress=bar, debug=args.debug, log=lambda m: print('\n' + m))
    print(f"\n완료: {meta['n'] / meta['fps']:.1f}초 {meta['W']}x{meta['H']} {meta['fps']:.0f}fps"
          f" | 내 차 차로 변경(제외): {meta['ego_changes'] or '없음'}")
    if len(res):
        print(res[['id', 'sec', 'dir', 'shift', 'signal', 'pulses', 'period', 'clip']].to_string(index=False))
    else:
        print('차선 변경 없음')
    rlv = meta['red_light']
    print(f'신호위반 {len(rlv)}건' + (':\n' + rlv[['id', 'sec', 'signal', 'clip']].to_string(index=False) if len(rlv) else ''))
    if 'debug_video' in meta:
        print('디버그 영상:', meta['debug_video'])


if __name__ == '__main__':
    main()
