"""깜빡이 판정 회귀 점검: .venv/bin/python test_turnsignal.py
마지막 두 개는 실제 영상(real_2min.mp4 Focus 23~27초 우측 램프)에서 측정한 값"""
import numpy as np

import turnsignal_app as tp


def pulses(fps, n, hz, amp=0.5, duty=0.45):
    t = np.arange(n) / fps
    return ((t * hz) % 1 < duty) * amp


assert tp.blink_test(pulses(10, 50, 1.2), 10)['blink']                    # 10fps 1.2Hz
assert tp.blink_test(pulses(24, 120, 1.5, 0.4), 24)['blink']              # 24fps 1.5Hz
assert not tp.blink_test(np.full(50, 0.5), 10)['blink']                   # 계속 켜짐 (주황 차체·브레이크)
one = np.zeros(50); one[20:25] = 0.5
assert not tp.blink_test(one, 10)['blink']                                # 한 번만 번쩍 (반사)
noise = np.zeros(50); noise[[5, 9, 30]] = 0.5
assert not tp.blink_test(noise, 10)['blink']                              # 1프레임 잡음
assert not tp.blink_test(np.zeros(50), 10)['blink']

focus = np.zeros(50)
focus[[4, 5, 6, 7, 12, 13, 14, 15, 21, 22, 23, 24, 29, 30, 31, 32, 33]] = \
    np.array([7, 6, 3, 3, 5, 5, 2, 5, 3, 3, 3, 6, 3, 2, 5, 5, 3]) / 100
r = tp.blink_test(focus, 10)
assert r['blink'] and 0.7 <= r['period'] <= 1.0, r                        # 펄스 안의 출렁임에도 4회로 셈

# 호박색 점수: 점등(H≈10, G-B 큼) > 0, 붉은 미등·흰 차체 = 0  (BGR)
px = np.array([[[96, 137, 214], [142, 190, 233], [101, 97, 136], [200, 200, 200]]], np.uint8)
a = tp.amber_map(px)[0]
assert a[0] > 0.2 and a[1] > 0.2 and a[2] == 0 and a[3] == 0, a

# 차선 변경 검출 (5fps 짧은 궤적, AI Hub 71555 형태)
import pandas as pd
def trk(i, f0, ds):
    n = len(ds)
    return pd.DataFrame(dict(id=i, seg=0, frame=np.arange(f0, f0 + n), ds=ds, x1=100., x2=200., y1=100., y2=180.))
sig = lambda n, a, b: a + (b - a) / (1 + np.exp(-(np.arange(n) - n / 2)))
t = pd.concat([trk(1, 0, sig(40, -1.4, -0.6)),      # 경계 d=-1 을 넘음, 이동 0.8 → 변경
               trk(2, 0, np.full(40, -1.0)),          # 경계 위에 머무름 → 아님
               trk(3, 100, sig(25, 0.2, 2.2))])       # 5초짜리 짧은 궤적, 이동 2.0 → 변경
e = tp.find_events(t, dict(fps=5.0), [])
assert sorted(e.id) == [1, 3] and set(e.dir) == {'R'}, e

# 신호등 색 (노트북 자체 테스트와 같은 가짜 램프)
def lamp(bgr):
    img = np.full((60, 30, 3), 40, np.uint8)
    import cv2
    cv2.circle(img, (15, 30), 10, bgr, -1)
    return img
assert tp.classify_light_color(lamp((0, 0, 255))) == 'RED'
assert tp.classify_light_color(lamp((0, 220, 255))) == 'YELLOW'
assert tp.classify_light_color(lamp((180, 255, 0))) == 'GREEN'                 # 청록빛 LED
assert tp.classify_light_color(np.full((60, 30, 3), 40, np.uint8)) == 'UNKNOWN'
assert tp.lamp_size_px([0, 0, 90, 30]) == 30 and tp.lamp_size_px([0, 0, 80, 20]) == 20

# 신호위반: 가로 3구 신호등(램프 30px, 하단 y=40) → 라인 y = 40 + 14×30 = 460
n = 10
lights = pd.DataFrame([(i, 100, 10, 190, 40, 'RED' if i < 6 else 'GREEN') for i in range(n)],
                      columns=['frame', 'x1', 'y1', 'x2', 'y2', 'state'])
def veh(i, ys):
    return pd.DataFrame(dict(frame=range(len(ys)), id=i, cls=2, x1=300., x2=400., y1=np.array(ys) - 80., y2=ys))
up = [600, 560, 520, 480, 440, 400, 380, 360, 340, 320]
df = pd.concat([veh(1, up),                                   # 빨간불(4프레임)에 라인 통과 → 위반
                veh(2, [600] * 6 + [470, 440, 400, 380]),     # 초록불(7프레임)에 통과 → 정상
                veh(3, [400] * n),                            # 처음부터 라인 위 → 무시
                veh(4, up[::-1])])                            # 반대 방향 → 무시
meta = dict(n=n, fps=10.0, W=1280, H=720, area=(0, 0, 1280, 720), lights=lights)
ev, _ = tp.red_light_events(df, meta)
assert set(ev.id) == {1, 2} and set(ev[ev.violation].id) == {1}, ev
print('OK')
