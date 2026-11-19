"""브라우저 E2E 테스트 (백엔드 :8000 + 프론트 :5173 이 떠 있어야 함, 시연 데이터 필요)
  pip install playwright && playwright install chromium
  python tests/e2e.py        # 시스템 Chrome 을 쓰려면 CHROME=/경로 지정
"""
import re
import sys
from playwright.sync_api import sync_playwright

import os
OUT = os.environ.get('OUT', '.')   # 스크린샷·임시파일 저장 위치
BASE = os.environ.get('BASE', 'http://127.0.0.1:5173')
errors, fails = [], []


def check(name, cond, extra=''):
    print(('PASS' if cond else 'FAIL'), name, extra)
    if not cond:
        fails.append(name)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get('CHROME') or None, args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 1360, 'height': 900})
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    pg.on('response', lambda r: print('   HTTP', r.status, r.url.replace(BASE,'')) if r.status >= 400 else None)
    pg.on('pageerror', lambda e: errors.append(str(e)))

    # 1. 목록
    pg.goto(f'{BASE}/cases')
    pg.wait_for_selector('a.row')
    check('목록 20행 렌더', pg.locator('a.row').count() == 20, pg.locator('a.row').count())
    check('상단 건수 표시', '40건' in pg.locator('.list-head h2').inner_text())
    pg.screenshot(path=f'{OUT}/list.png')

    # 2. 필터 → URL 동기화
    pg.get_by_label('신호위반').check()
    pg.wait_for_function("location.search.includes('type=signal_violation')")
    pg.wait_for_function("document.querySelectorAll('a.row').length > 0 && [...document.querySelectorAll('a.row .badge')].every(b => !b.textContent.includes('깜빡이'))")
    n = pg.locator('a.row').count()
    check('유형 필터 적용', n > 0, f'{n}건')
    check('필터 태그 표시', pg.locator('.tag').count() == 1)

    # 3. 상세 + 영상
    pg.locator('a.row').first.click()
    pg.wait_for_selector('video')
    check('상세 URL', re.search(r'/cases/\d+$', pg.url) is not None, pg.url)
    pg.wait_for_function("document.querySelector('video').readyState >= 2", timeout=10000)
    dur = pg.evaluate("document.querySelector('video').duration")
    check('영상 로드(메타데이터)', dur and dur > 1, f'duration={dur}')
    pg.get_by_role('button', name='0.5x').click()
    check('재생속도 변경', pg.evaluate("document.querySelector('video').playbackRate") == 0.5)
    pg.get_by_role('button', name='1f ▶').click()
    check('프레임 이동', pg.evaluate("document.querySelector('video').currentTime") > 0)
    check('위반 시점 마커', pg.locator('.timeline-marker').count() == 1)
    pg.screenshot(path=f'{OUT}/detail.png', full_page=True)

    # 4. 반려: 사유 필수
    before = pg.locator('.detail-title .badge').nth(1).inner_text()
    pg.get_by_role('button', name='반려', exact=True).click()
    pg.wait_for_selector('.modal')
    check('사유 없으면 확인 비활성', pg.locator('.modal .btn.primary').is_disabled())
    pg.locator('.modal textarea').fill('근거 불충분')
    pg.locator('.modal .btn.primary').click()
    pg.wait_for_selector('.modal', state='detached')
    check('상태 반려로 변경', pg.locator('.detail-title .badge').nth(1).inner_text() == '반려', f'{before}→반려')
    check('처리 이력 추가', pg.locator('.timeline-list li').count() >= 1)
    check('사유가 메모에 기록', '근거 불충분' in pg.locator('.memo-list').inner_text())

    # 5. 메모
    pg.locator('.memo-form textarea').fill('현장 확인 예정')
    pg.get_by_role('button', name='메모 추가').click()
    pg.wait_for_function("document.querySelector('.memo-list').innerText.includes('현장 확인 예정')")
    check('메모 추가', True)

    # 6. 목록 복귀 시 필터 유지
    pg.get_by_text('← 목록으로').click()
    pg.wait_for_selector('a.row')
    check('목록 복귀 시 필터 유지', 'type=signal_violation' in pg.url, pg.url)

    # 7. 필터 초기화
    pg.get_by_role('button', name='전체 초기화').click()
    pg.wait_for_function("document.querySelectorAll('a.row').length === 20")
    check('전체 초기화', 'type=' not in pg.url)

    # 8. 존재하지 않는 케이스 → 404 안내
    pg.goto(f'{BASE}/cases/99999')
    pg.wait_for_selector('.state-box')
    check('404 안내', '존재하지 않는' in pg.locator('.state-box').inner_text())

    # 9. 통계
    pg.goto(f'{BASE}/statistics')
    pg.wait_for_selector('.recharts-surface')
    check('통계 차트 4개', pg.locator('.recharts-wrapper').count() == 4, pg.locator('.recharts-wrapper').count())
    pg.wait_for_timeout(800)
    pg.screenshot(path=f'{OUT}/stats.png', full_page=True)

    # 10. 업로드 (엔진 없음 → 서버 사유 표시)
    pg.goto(f'{BASE}/upload')
    open(f'{OUT}/t.mp4', 'wb').write(b'x')
    pg.set_input_files('input[type=file]', f'{OUT}/t.mp4')
    pg.get_by_role('button', name='업로드 및 분석 시작').click()
    pg.wait_for_selector('.form-error')
    check('엔진 없음 안내', '엔진' in pg.locator('.form-error').inner_text(), pg.locator('.form-error').inner_text())

    b.close()

print('\nconsole/page errors:', errors or 'none')
print('FAILED:', fails or 'none')
sys.exit(1 if fails else 0)
