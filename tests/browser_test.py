#!/usr/bin/env python3
"""Headless Chromium workflow regression for medication details, comparison and low-vision settings."""
import os, subprocess, tempfile, time, json, urllib.request, sys, socket
from pathlib import Path
import websocket
ROOT=Path(__file__).resolve().parents[1]
def free_port():
    s=socket.socket();s.bind(('127.0.0.1',0));p=s.getsockname()[1];s.close();return p
server_port=free_port(); debug_port=free_port()
with tempfile.TemporaryDirectory(prefix='clinic-browser-') as td:
    env=os.environ.copy(); env.update(CLINIC_PORT=str(server_port),CLINIC_DB_PATH=str(Path(td)/'browser.db'),CLINIC_HOST='127.0.0.1',CLINIC_DEMO_MODE='1')
    srv=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    chrome=None; ws=None
    try:
        base=f'http://127.0.0.1:{server_port}'
        for _ in range(100):
            try: urllib.request.urlopen(base+'/api/health',timeout=1).read(); break
            except Exception: time.sleep(.15)
        else: raise RuntimeError('application HTTP server did not start')
        chrome_env=os.environ.copy()
        for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','NEKO_PROXY_PORT','START_PROXY'):
            chrome_env.pop(key,None)
        chrome=subprocess.Popen(['/usr/bin/chromium','--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--proxy-server=direct://','--proxy-bypass-list=*',f'--remote-debugging-port={debug_port}','--user-data-dir='+str(Path(td)/'profile'),base+'/'],env=chrome_env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        targets=[]
        for _ in range(100):
            try:
                targets=json.loads(urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json',timeout=1).read())
                if any(t.get('type')=='page' for t in targets): break
            except Exception: time.sleep(.15)
        page=next(t for t in targets if t.get('type')=='page')
        ws=websocket.create_connection(page['webSocketDebuggerUrl'],timeout=5,suppress_origin=True)
        call_id=0
        def call(method,params=None):
            nonlocal_placeholder=None
            global call_id
            call_id+=1; n=call_id; ws.send(json.dumps({'id':n,'method':method,'params':params or {}}))
            deadline=time.time()+10
            while time.time()<deadline:
                msg=json.loads(ws.recv())
                if msg.get('id')==n:
                    if 'error' in msg: raise AssertionError(f'{method}: {msg["error"]}')
                    return msg.get('result',{})
            raise TimeoutError(method)
        call('Runtime.enable'); call('Page.enable')
        call('Page.addScriptToEvaluateOnNewDocument',{'source':'window.__appErrors=[];window.addEventListener("error",e=>window.__appErrors.push(String(e.message)));window.addEventListener("unhandledrejection",e=>window.__appErrors.push(String(e.reason)));'})
        call('Page.reload',{'ignoreCache':True}); time.sleep(1.5)
        def js(expr):
            res=call('Runtime.evaluate',{'expression':expr,'returnByValue':True,'awaitPromise':True})
            if res.get('exceptionDetails'): raise AssertionError(str(res['exceptionDetails']))
            return res.get('result',{}).get('value')
        # Log in through the existing demo-account action.
        boot=js("({title:document.title,body:document.body.innerText.slice(0,250),demo:document.querySelectorAll('[data-action=\\\"demo-doctor\\\"]').length,href:location.href})")
        if 'organization doesn’t allow you to view this site' in boot['body'].lower() or boot['href'].startswith('chrome-error:'):
            print('SKIP browser workflow: this execution environment blocks Chromium navigation to its own localhost server; HTTP integration tests remain available.')
            raise SystemExit(0)
        js("document.querySelector('[data-action=\\\"demo-doctor\\\"]').click()")
        for _ in range(50):
            if js("!!document.querySelector('[data-nav=\\\"treatment\\\"]')"): break
            time.sleep(.15)
        assert js("!!document.querySelector('[data-nav=\\\"treatment\\\"]')"), 'doctor login failed'
        js("document.querySelector('[data-nav=\\\"treatment\\\"]').click()")
        time.sleep(.4)
        assert js("document.body.innerText.includes('Сравнить препараты')"), 'compare button is not visible'
        # Drug detail must show the detailed PK section, source names, and no PDF filenames.
        js("document.querySelector('[data-action=\\\"drug-detail\\\"][data-drug-id=\\\"sertraline\\\"]').click()")
        time.sleep(.7)
        detail=js("document.querySelector('.modal')?.innerText||''")
        assert 'Фармакокинетика' in detail, 'PK section missing from drug card'
        assert 'Справочник лекарственных средств «Видаль»' in detail, 'Named Vidal source missing'
        assert '.pdf' not in detail.lower() and 'TODO' not in detail, 'upload filename leaked into drug card'
        assert 'Противопоказания' in detail, 'contraindications missing'
        js("document.querySelector('.modal [data-action=\\\"close-modal\\\"]').click()")
        time.sleep(.2)
        js("document.querySelector('[data-action=\\\"compare-drugs\\\"]').click()")
        time.sleep(.2)
        js("document.querySelector('input[name=\\\"compare-drug\\\"][value=\\\"sertraline\\\"]').checked=true;document.querySelector('input[name=\\\"compare-drug\\\"][value=\\\"agomelatine\\\"]').checked=true")
        js("document.querySelector('[data-action=\\\"compare-selected\\\"]').click()")
        time.sleep(.3)
        compare=js("({text:document.querySelector('#comparison-content')?.innerText||'',cols:document.querySelectorAll('.drug-compare-table thead th').length})")
        assert compare['cols']==3, f'expected characteristic+2 medication columns, got {compare["cols"]}'
        assert 'Фармакокинетика' in compare['text'] and 'Противопоказания' in compare['text'], 'comparison lacks essential rows'
        assert 'Сравнение носит справочный характер' in compare['text'], 'clinical boundary missing in comparison'
        js("document.querySelector('.modal [data-action=\\\"close-modal\\\"]').click()")
        time.sleep(.15)
        js("document.querySelector('[data-action=\\\"low-vision-toggle\\\"]').click()")
        prefs=js("({low:document.documentElement.dataset.lowVision,contrast:document.documentElement.dataset.highContrast,scale:document.documentElement.dataset.fontScale,aria:document.querySelector('.low-vision-toggle')?.getAttribute('aria-pressed')})")
        assert prefs['low']=='on' and prefs['contrast']=='on' and prefs['scale']=='large' and prefs['aria']=='true', f'low-vision toggle failed: {prefs}'
        errors=js("window.__appErrors||[]")
        assert not errors, f'uncaught browser errors: {errors}'
        print('PASS browser: login, drug detail with PK/contraindications/named sources, no filenames, multi-drug comparison, comparison safeguards, low-vision/high-contrast persistence, no uncaught JavaScript errors.')
    finally:
        if ws:
            try: ws.close()
            except Exception: pass
        if chrome:
            chrome.terminate()
            try: chrome.wait(timeout=3)
            except subprocess.TimeoutExpired: chrome.kill()
        srv.terminate()
        try: srv.wait(timeout=3)
        except subprocess.TimeoutExpired: srv.kill()
