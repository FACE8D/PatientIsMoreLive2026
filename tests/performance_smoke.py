#!/usr/bin/env python3
"""Repeatable local API latency/concurrency smoke benchmark; synthetic DB only.

Reports p50/p95/p99 and errors. This is a smoke benchmark, not a production load test.
"""
import concurrent.futures, http.cookiejar, json, os, statistics, subprocess, sys, tempfile, time, urllib.request, urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PORT=8768
N=int(os.environ.get('CLINIC_BENCH_REQUESTS','40'))
WORKERS=int(os.environ.get('CLINIC_BENCH_WORKERS','5'))

def pct(xs,p):
    ys=sorted(xs)
    if not ys:return float('nan')
    return ys[min(len(ys)-1, max(0, int((len(ys)-1)*p+0.5)))]*1000
with tempfile.TemporaryDirectory(prefix='clinic-bench-') as td:
    env=os.environ.copy(); env.update(CLINIC_PORT=str(PORT),CLINIC_DB_PATH=str(Path(td)/'bench.sqlite3'),CLINIC_HOST='127.0.0.1',CLINIC_DEMO_MODE='1')
    proc=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    base=f'http://127.0.0.1:{PORT}'
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(base+'/api/health',timeout=1) as r:
                    if r.status==200:break
            except Exception: time.sleep(.1)
        else: raise RuntimeError('server startup timeout')
        def make_opener(): return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def req(op,path,body=None,token=None):
            data=json.dumps(body).encode() if body is not None else None
            headers={'Accept':'application/json'}
            if data is not None: headers['Content-Type']='application/json'
            if token: headers['X-CSRF-Token']=token
            r=urllib.request.Request(base+path,data=data,headers=headers,method='POST' if data is not None else 'GET')
            with op.open(r,timeout=8) as res: return res.status,res.read()
        op=make_opener(); status,body=req(op,'/api/login',{'email':'doctor@demo.local','password':'DemoDoctor2026!'})
        assert status==200, f'login failed: {status}'
        csrf=json.loads(body)['csrf_token']
        bootstrap=json.loads(req(op,'/api/bootstrap')[1]); pid=next(p['id'] for p in bootstrap['patients'] if p.get('email')=='patient@demo.local')
        # Reuse one authenticated session for read-only API timings. Login/PBKDF2 is deliberately
        # outside the timed window; including it would measure password hashing, not API latency.
        cookies='; '.join(f'{c.name}={c.value}' for h in op.handlers if isinstance(h, urllib.request.HTTPCookieProcessor) for c in h.cookiejar)
        paths=['/api/health','/api/bootstrap',f'/api/patients/{pid}']
        def timed_req(path):
            headers={'Accept':'application/json','Cookie':cookies}
            request=urllib.request.Request(base+path,headers=headers,method='GET')
            with urllib.request.urlopen(request,timeout=8) as response:
                return response.status,response.read()
        for path in paths: timed_req(path)
        timings={p:[] for p in paths}; errors=[]
        def sample(i):
            path=paths[i%len(paths)]
            try:
                start=time.perf_counter(); status,_=timed_req(path); elapsed=time.perf_counter()-start
                if status!=200: return path,None,f'HTTP {status}'
                return path,elapsed,None
            except Exception as e:return path,None,repr(e)
        wall=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for path,elapsed,error in pool.map(sample,range(N)):
                if error:errors.append((path,error))
                else:timings[path].append(elapsed)
        wall=time.perf_counter()-wall
        print(f'API benchmark: requests={N}, workers={WORKERS}, wall={wall:.3f}s, throughput={N/wall:.2f} req/s, errors={len(errors)}')
        for path,vals in timings.items():
            if vals: print(f'{path}: n={len(vals)} p50={pct(vals,.50):.1f}ms p95={pct(vals,.95):.1f}ms p99={pct(vals,.99):.1f}ms max={max(vals)*1000:.1f}ms')
        if errors: print('Errors:',errors[:5]); raise SystemExit(1)
        if sum(map(len,timings.values()))!=N: raise AssertionError('not all requests accounted for')
        print('PASS: local API latency/concurrency smoke benchmark (not a production capacity certification)')
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
