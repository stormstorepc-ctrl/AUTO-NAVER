"""Browser smoke test for the local review UI (synthetic products only).
Install requirements-dev.txt and Chromium; set PURCHASING_CHROMIUM to its path.
Run: python scripts/purchasing_browser_smoke.py
"""
import base64, json, os, pathlib, secrets, socket, subprocess, sys, tempfile, time, urllib.request, zipfile
from playwright.sync_api import sync_playwright
root=pathlib.Path(__file__).resolve().parents[1]
artifacts=root/'artifacts'/'purchasing-ui'
artifacts.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='purchasing-browser-') as tmp:
    password=secrets.token_hex(16)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    env={**os.environ,'PURCHASING_DB':str(pathlib.Path(tmp)/'demo.db'),'PURCHASING_REVIEW_PASSWORD':password}
    log=open(artifacts/'server.log','w')
    proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.purchasing.web:app_from_env','--factory','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=log)
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        auth=base64.b64encode(f'reviewer:{password}'.encode()).decode()
        for _ in range(80):
            try:
                opener.open(urllib.request.Request(url,headers={'Authorization':'Basic '+auth}),timeout=1);break
            except Exception:
                if proc.poll() is not None: raise RuntimeError('server exited')
                time.sleep(.1)
        else: raise RuntimeError('server readiness timeout')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('PURCHASING_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
            context=browser.new_context(http_credentials={'username':'reviewer','password':password},viewport={'width':1440,'height':1100})
            page=context.new_page(); errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            sample=context.request.get(url+'/sample.json'); assert sample.ok
            source=pathlib.Path(tmp)/'sample.json';source.write_bytes(sample.body())
            page.goto(url+'/import')
            page.locator('input[name=file]').set_input_files(source)
            page.get_by_role('button',name='상품 가져오기',exact=True).click()
            assert '새 상품 1개' in page.text_content('body')
            page.goto(url+'/product/1')
            page.locator('input[name=rates_confirmed]').check()
            page.get_by_role('button',name='전 옵션 가격 계산',exact=True).click()
            assert '모든 옵션의 가격을 계산했습니다' in page.text_content('body')
            page.get_by_role('link',name='검토 화면으로 돌아가기').click()
            page.locator('input[name=title_ko]').fill('시연용 미니 수납함')
            page.locator('textarea[name=description_ko]').fill('가상 상품. 크기 20×10×5cm, 소형 물품 정리용. 실제 판매 상품이 아닙니다.')
            page.locator('input[name=option_0]').fill('화이트')
            page.locator('input[name=option_1]').fill('블랙')
            page.get_by_role('button',name='번역 초안 저장',exact=True).click()
            page.get_by_role('link',name='검토 화면으로 돌아가기').click()
            page.locator('input[name=confirmed]').check()
            page.get_by_role('button',name='이 번역 검수 완료',exact=True).click()
            page.get_by_role('link',name='검토 화면으로 돌아가기').click()
            page.get_by_role('button',name='이 상품 승인',exact=True).click()
            assert '승인 1건' in page.text_content('body')
            page.goto(url+'/product/1')
            page.get_by_role('button',name='승인본 모의 등록',exact=True).click()
            assert '이번 요청 모의 성공 1건' in page.text_content('body')
            assert '실제 등록 0건' in page.text_content('body')
            page.goto(url+'/product/1')
            with page.expect_download() as info:
                page.get_by_role('button',name='검토용 상세페이지 ZIP 다운로드',exact=True).click()
            download=pathlib.Path(tmp)/'draft.zip'; info.value.save_as(download)
            with zipfile.ZipFile(download) as archive:
                assert '시연용 미니 수납함' in archive.read('description.txt').decode()
            page.goto(url+'/')
            page.screenshot(path=str(artifacts/'review.png'),full_page=True)
            assert not errors,errors
            browser.close()
        print(json.dumps({'browser':'system Chromium, headless Linux','flow':'file import > option price > translation > review > approval > mock publish > ZIP download','result':'passed','real_published':0,'console_page_errors':errors},ensure_ascii=False))
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill();proc.wait()
        log.close()
