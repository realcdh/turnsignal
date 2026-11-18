"""교통법규 위반 탐지 GUI
영상 1개 → ① 신호위반 차량 클립  ② 깜빡이 없이 차선 변경한 차량 클립 (반대쪽 깜빡이 포함)

  .venv/bin/python gui_app.py            # 브라우저에서 http://127.0.0.1:7860
  .venv/bin/python gui_app.py --share    # 외부 공유 링크

분석 엔진은 turnsignal_app.py. 같은 영상은 스캔 결과(scan.pkl)를 재사용하므로
'바운딩박스 표시'만 바꿔 다시 누르면 클립만 새로 만듦 (수 초~수십 초).

프로젝트 폴더만 있으면 실행됨 (다운로드 없음): 모델 yolo11n.pt·yolo11s.pt, 예시 영상 samples/*.mp4 포함
"""
import argparse
import glob
import hashlib
import os
import shutil

import gradio as gr
import pandas as pd

import turnsignal_app as tp

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, 'gui_outputs')
SAMPLES = sorted(glob.glob(os.path.join(HERE, 'samples', '*.mp4')))
NO_SIGNAL = {'OFF': '미점등', 'WRONG_SIDE': '반대쪽 깜빡이'}


def _workdir(video):
    """영상 내용 기준 작업 폴더 (같은 영상을 다시 올려도 같은 폴더 → 스캔 재사용)"""
    h = hashlib.md5()
    with open(video, 'rb') as f:
        h.update(f.read(1 << 20))
        f.seek(max(0, os.path.getsize(video) - (1 << 20)))
        h.update(f.read())
    name = os.path.splitext(os.path.basename(video))[0][:40]
    d = os.path.join(OUT_ROOT, f'{name}_{h.hexdigest()[:8]}')
    os.makedirs(d, exist_ok=True)
    src = os.path.join(d, 'input' + os.path.splitext(video)[1].lower())
    if not os.path.exists(src):
        shutil.copy(video, src)
    return d, src


def analyze(video, show_boxes, progress=gr.Progress()):
    if not video:
        raise gr.Error('영상을 올려 주세요')
    out_dir, src = _workdir(video)
    cfg = {**tp.CFG, 'overlay': bool(show_boxes)}
    progress(0, desc='분석 시작')
    res, _, meta = tp.run(src, out_dir, cfg, progress=lambda p: progress(p * 0.9, desc='차량·신호등 분석 중'))

    rl = meta['red_light']
    red = [(c, f'신호위반 · {s:.1f}초 · id{i}') for c, s, i in zip(rl['clip'], rl['sec'], rl['id'])]
    lc = res[res.signal.isin(list(NO_SIGNAL))] if len(res) else res
    lane = [(c, f'깜빡이 {NO_SIGNAL[g]} · {s:.1f}초 · {"우측" if d == "R" else "좌측"} 변경 · id{i}')
            for c, s, d, g, i in zip(lc['clip'], lc['sec'], lc['dir'], lc['signal'], lc['id'])] if len(lc) else []

    table = pd.DataFrame(
        [dict(구분='신호위반', 시각_초=s, 차량id=i, 판정=g, 클립=os.path.basename(c))
         for c, s, i, g in zip(rl['clip'], rl['sec'], rl['id'], rl['signal'])] +
        ([dict(구분='깜빡이 없이 차선변경', 시각_초=s, 차량id=i, 판정=NO_SIGNAL[g], 클립=os.path.basename(c))
          for c, s, i, g in zip(lc['clip'], lc['sec'], lc['id'], lc['signal'])] if len(lc) else []),
        columns=['구분', '시각_초', '차량id', '판정', '클립'])
    summary = (f"영상 {meta['n'] / meta['fps']:.1f}초 | 신호위반 {len(red)}건 | "
               f"깜빡이 없이 차선변경 {len(lane)}건 (전체 차선변경 {len(res)}건) | "
               f"바운딩박스 {'표시' if show_boxes else '없음'}\n결과 폴더: {out_dir}")
    files = [c for c, _ in red + lane] or None
    return summary, red or None, lane or None, table, files


def build():
    with gr.Blocks(title='교통법규 위반 탐지') as demo:
        gr.Markdown('## 교통법규 위반 탐지\n블랙박스 영상을 올리면 **신호위반** 차량과 '
                    '**깜빡이 없이 차선 변경**한 차량의 클립을 만들어 줍니다.')
        with gr.Row():
            inp = gr.Video(label='입력 영상', sources=['upload'])
            with gr.Column():
                boxes = gr.Checkbox(value=True, label='출력 클립에 바운딩박스·판정 표시')
                btn = gr.Button('분석 시작', variant='primary')
                summary = gr.Textbox(label='요약', lines=2)
        red = gr.Gallery(label='신호위반 차량', columns=3, height='auto', preview=False)
        lane = gr.Gallery(label='깜빡이 없이 차선 변경한 차량', columns=3, height='auto', preview=False)
        table = gr.Dataframe(label='판정 내역')
        files = gr.File(label='클립 다운로드', file_count='multiple')
        if SAMPLES:
            gr.Examples([[v] for v in SAMPLES], [inp], label='예시 영상 (눌러서 선택 → 분석 시작)',
                        example_labels=[os.path.splitext(os.path.basename(v))[0] for v in SAMPLES])
        btn.click(analyze, [inp, boxes], [summary, red, lane, table, files])
    return demo


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='교통법규 위반 탐지 GUI')
    ap.add_argument('--share', action='store_true', help='외부 공유 링크')
    ap.add_argument('--port', type=int, default=7860)
    a = ap.parse_args()
    os.makedirs(OUT_ROOT, exist_ok=True)
    build().launch(share=a.share, server_port=a.port, inbrowser=True, allowed_paths=[OUT_ROOT, os.path.join(HERE, 'samples')])
