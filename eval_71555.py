"""AI Hub 71555 '교통법규 위반 상황' 클립으로 turnsignal_app 일괄 평가

  .venv/bin/python eval_71555.py --frames aihub/vs71555 --labels aihub/l71555 --out eval71555 [--limit 200]
  .venv/bin/python eval_71555.py --kind 신호위반 --frames aihub/vs71555_sig --labels aihub/l71555 --out eval71555_sig

- 클립(연속 jpg, 약 5fps)을 mp4 로 묶어 turnsignal_app.run 실행
- 정답: 라벨의 '진로변경 위반 차량' 박스. 우리 이벤트 차량 궤적과 IoU 0.3 이상 겹치는 프레임이 있으면 '찾음'
- 깜빡이 정답은 없음 → ON/OFF 분포만 집계 (표본은 클립을 직접 보고 확인)
"""
import argparse
import glob
import json
import os
import subprocess
import unicodedata

import pandas as pd

import turnsignal_app as tp

VIOL = {'진로변경위반': '진로변경 위반 차량', '신호위반': '신호 위반 차량'}
LIGHT_GT = {'적색': 'RED', '황색': 'YELLOW', '녹색': 'GREEN', '좌회전': 'GREEN'}


def nfc(s):
    return unicodedata.normalize('NFC', s)


def gt_boxes(label_dir, viol):
    """{프레임번호: [위반 차량 박스]}, {프레임번호: 정답 신호(라벨된 점등 신호등, 빨강 우선)}"""
    out, light = {}, {}
    for f in glob.glob(os.path.join(label_dir, '*.json')):
        k = int(os.path.basename(f).rsplit('_', 1)[1].split('.')[0])
        a = json.load(open(f))['Annotation']['annotations']
        b = [x['Bbox Cordinate'] for x in a if nfc(x['Object Name']).startswith(viol) and 'Bbox Cordinate' in x]
        if b:
            out[k] = b
        st = {v for x in a for kk, v in LIGHT_GT.items() if nfc(x['Object Name']).startswith(kk)}
        if st:
            light[k] = 'RED' if 'RED' in st else sorted(st)[0]
    return out, light


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i + 1e-9)


def to_mp4(frame_dir, mp4, fps):
    if os.path.exists(mp4):
        return mp4
    subprocess.run([tp.find_ffmpeg(), '-y', '-loglevel', 'error', '-framerate', str(fps), '-pattern_type', 'glob',
                    '-i', os.path.join(frame_dir, '*.jpg'), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                    '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', mp4], check=True)
    return mp4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', required=True)
    ap.add_argument('--labels', required=True)
    ap.add_argument('--out', default='eval71555')
    ap.add_argument('--fps', type=float, default=5.0)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--kind', default='진로변경위반', choices=list(VIOL))
    ap.add_argument('--sub', default='', help='세부 유형 폴더만 (예: 적색신호시직진)')
    args = ap.parse_args()

    clips = sorted(d for d in glob.glob(os.path.join(args.frames, '*', '*', '*'))
                   if os.path.isdir(d) and nfc(d.split(os.sep)[-3]) == args.kind
                   and (not args.sub or nfc(d.split(os.sep)[-2]) == args.sub))
    clips = [d for d in clips if glob.glob(os.path.join(d, '*.jpg'))]
    if args.limit:
        clips = clips[::max(1, len(clips) // args.limit)][:args.limit]
    os.makedirs(os.path.join(args.out, 'mp4'), exist_ok=True)
    rows = []
    for n, d in enumerate(clips, 1):
        name = nfc(os.path.basename(d))
        sub = nfc(os.path.basename(os.path.dirname(d)))
        lab = os.path.join(args.labels, args.kind, sub, name)
        gt, gt_light = gt_boxes(lab, nfc(VIOL[args.kind])) if os.path.isdir(lab) else ({}, {})
        mp4 = to_mp4(d, os.path.join(args.out, 'mp4', name + '.mp4'), args.fps)
        try:
            res, _, meta = tp.run(mp4, os.path.join(args.out, 'runs', name))
        except Exception as ex:   # 한 클립 실패로 전체가 멈추지 않게
            print(f'[{n}/{len(clips)}] {name} 실패: {ex!r}', flush=True)
            continue
        trk = pd.read_csv(os.path.join(args.out, 'runs', name, 'tracks.csv'))
        frames = sorted(glob.glob(os.path.join(d, '*.jpg')))
        idx = {int(os.path.basename(f).rsplit('_', 1)[1].split('.')[0]): i for i, f in enumerate(frames)}  # 라벨 번호 → 영상 프레임
        hit_ids = set()
        for k, boxes in gt.items():
            g = trk[trk.frame == idx.get(k, -1)]
            for b in boxes:
                for r in g.itertuples():
                    if iou(b, (r.x1, r.y1, r.x2, r.y2)) >= 0.3:
                        hit_ids.add(int(r.id))
        if args.kind == '신호위반':
            res = meta['red_light']
        ev_ids = set(res.id.astype(int)) if len(res) else set()
        found = bool(hit_ids & ev_ids)
        sig = res[res.id.isin(hit_ids)].signal.tolist() if len(res) else []
        light = dict(light_frames=len(gt_light), light_seen=0, light_ok=0)
        if gt_light:                                    # 정답 신호등 라벨이 있는 프레임에서 우리 신호 판정 비교
            ours = pd.read_csv(os.path.join(args.out, 'runs', name, 'signal.csv')).state.tolist()
            pairs = [(ours[idx[k]], v) for k, v in gt_light.items() if idx.get(k, -1) < len(ours) and k in idx]
            light.update(light_seen=sum(o != 'UNKNOWN' for o, _ in pairs), light_ok=sum(o == v for o, v in pairs))
        rows.append(dict(clip=name, kind=sub, frames=len(frames), W=meta['W'], H=meta['H'], gt_frames=len(gt),
                         gt_tracked=bool(hit_ids), found=found, n_events=len(res),
                         other_events=len(ev_ids - hit_ids), signal=';'.join(sig), **light))
        print(f'[{n}/{len(clips)}] {name} gt={len(gt)} tracked={bool(hit_ids)} found={found} '
              f'events={len(res)} signal={sig}', flush=True)
        pd.DataFrame(rows).to_csv(os.path.join(args.out, 'summary.csv'), index=False)
    s = pd.DataFrame(rows)
    has = s[s.gt_frames > 0]
    print(f'\n클립 {len(s)}개 | 정답 있는 클립 {len(has)} | 위반차 추적됨 {has.gt_tracked.sum()} | '
          f'차선변경 검출 {has.found.sum()} ({has.found.mean():.0%}) | 다른 차 이벤트 {s.other_events.sum()}')
    print('검출된 위반차 판정:', s[s.found].signal.str.split(';').explode().value_counts().to_dict())
    if s.light_frames.sum():
        print(f'신호 판정 (정답 신호등 라벨 {s.light_frames.sum()}프레임): 인식 {s.light_seen.sum() / s.light_frames.sum():.0%}'
              f' | 인식한 것 중 정답 {s.light_ok.sum() / max(s.light_seen.sum(), 1):.0%}')


if __name__ == '__main__':
    main()
