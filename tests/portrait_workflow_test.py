#!/usr/bin/env python3
"""End-to-end test of the six synthetic longitudinal portraits and clinical workflow."""
import http.cookiejar, json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error
from datetime import date, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PORT=8770
FIXTURE=json.loads((ROOT/'data'/'demo_patient_cases.json').read_text(encoding='utf-8'))
with tempfile.TemporaryDirectory(prefix='clinic-portraits-') as td:
    env=os.environ.copy(); env.update(CLINIC_PORT=str(PORT),CLINIC_DB_PATH=str(Path(td)/'portraits.db'),CLINIC_HOST='127.0.0.1',CLINIC_DEMO_MODE='1')
    proc=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        base=f'http://127.0.0.1:{PORT}'
        for _ in range(100):
            try:
                urllib.request.urlopen(base+'/api/health',timeout=1).read(); break
            except Exception: time.sleep(.15)
        else: raise RuntimeError('server did not start')
        def client(): return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def req(op,path,method='GET',body=None,csrf=None,expected=200):
            data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
            headers={'Accept':'application/json'}
            if data is not None: headers['Content-Type']='application/json'
            if csrf: headers['X-CSRF-Token']=csrf
            request=urllib.request.Request(base+path,data=data,headers=headers,method=method)
            try:
                with op.open(request,timeout=12) as r: status=r.status; raw=r.read().decode()
            except urllib.error.HTTPError as e: status=e.code; raw=e.read().decode()
            try: obj=json.loads(raw)
            except Exception: obj={'raw':raw[:200]}
            if status!=expected: raise AssertionError(f'{method} {path}: expected {expected}, got {status}: {obj}')
            return obj

        doctor=client(); dlogin=req(doctor,'/api/login','POST',{'email':'doctor@demo.local','password':'DemoDoctor2026!'}); dc=dlogin['csrf_token']
        boot=req(doctor,'/api/bootstrap'); patients=boot['patients']
        assert len(patients)>=6, f'expected six seeded portraits, got {len(patients)}'
        by_email={p['email']:p for p in patients}; fixture_by_email={c['email']:c for c in FIXTURE['patients']}
        assert all(c['email'] in by_email for c in FIXTURE['patients'])
        trend_directions=[]; metrics=[]
        for email,case in fixture_by_email.items():
            p=by_email[email]; bundle=req(doctor,f"/api/patients/{p['id']}")
            assert 'СИНТЕТИЧЕСКИЙ УЧЕБНЫЙ КЕЙС' in bundle['patient']['notes']
            assert len(bundle['entries'])>=20, f'{email} needs a longitudinal diary'
            entry_types={e.get('entry_type') for e in bundle['entries']}
            assert {"mood","food","checklist","wellbeing"} <= entry_types, f"{case['case_id']} should exercise mood, food, checklist and wellbeing diaries: {entry_types}"
            wellbeing=[e for e in bundle['entries'] if e.get('entry_type')=='wellbeing']
            assert all(e.get('data',{}).get('synthetic_demo') for e in wellbeing), 'synthetic wellbeing examples must be labelled as demo data'
            assert any(e.get('data',{}).get('polarity')=='positive' for e in wellbeing) and any(e.get('data',{}).get('polarity')=='negative' for e in wellbeing), f"{case['case_id']} needs both positive and negative wellbeing examples"
            assert len(bundle['results'])>=8, f'{email} needs repeat measures'
            assert len(bundle['visits'])>=3 and len(bundle['care_plans'])>=1 and len(bundle['appointments'])>=5
            # Preserve the baseline values explicitly stated in the uploaded portrait.
            for qid,total in case['source_baseline'].get('scale_scores',{}).items():
                baseline=next((r for r in bundle['results'] if r['questionnaire_id']==qid and r['score'].get('series_type')=='baseline'),None)
                assert baseline is not None, f'{case["case_id"]} missing baseline {qid}'
                assert baseline['score'].get('total')==total, f'{case["case_id"]} baseline {qid}: {baseline["score"].get("total")} != {total}'
            moods=sorted((e for e in bundle['entries'] if e['entry_type']=='mood'),key=lambda x:x['entry_date'])
            assert moods, f'{email}: no mood diary'
            first=moods[0]['data']['mood']; last=moods[-1]['data']['mood']
            trend_directions.append(last-first)
            active_plans=sum(1 for m in bundle['medication_plans'] if m['status']=='active')
            missed=sum(1 for a in bundle['appointments'] if a['status']=='missed')
            metrics.append({'case':case['case_id'],'patient_id':p['id'],'diary':len(bundle['entries']),'tests':len(bundle['results']),'visits':len(bundle['visits']),'active_plans':active_plans,'missed_visits':missed,'alerts':len(bundle['alerts']),'mood_first_last':(first,last)})
        assert any(x>=2 for x in trend_directions), f'Need visible improvement trend: {trend_directions}'
        assert any(x<=-1 for x in trend_directions), f'Need visible worsening trend: {trend_directions}'
        # Access restriction: the patient account cannot open another portrait.
        alex_case=fixture_by_email['alexey.case@demo.local']; alex=by_email['alexey.case@demo.local']
        alex_user=client(); alogin=req(alex_user,'/api/login','POST',{'email':alex_case['email'],'password':'DemoPatient2026!'}); ac=alogin['csrf_token']
        own=req(alex_user,f"/api/patients/{alex['id']}"); assert own['patient']['full_name']==alex_case['full_name']
        maria=by_email['patient@demo.local']; req(alex_user,f"/api/patients/{maria['id']}",expected=403)
        # Reschedule a future appointment. The original slot must remain in the history.
        alex_bundle=req(doctor,f"/api/patients/{alex['id']}")
        scheduled=next(a for a in alex_bundle['appointments'] if a['status']=='scheduled' and a['title']=='Следующий контрольный приём')
        new_start=(date.today()+timedelta(days=3)).isoformat()+'T11:30'
        moved=req(doctor,f"/api/appointments/{scheduled['id']}/reschedule",'POST',{'starts_at':new_start,'ends_at':(date.today()+timedelta(days=3)).isoformat()+'T12:00','reason':'Пациент попросил изменить время; согласовано в учебном сценарии.'},dc,201)
        moved_bundle=req(doctor,f"/api/patients/{alex['id']}")
        old=next(a for a in moved_bundle['appointments'] if a['id']==scheduled['id'])
        new=next(a for a in moved_bundle['appointments'] if a['id']==moved['appointment_id'])
        assert old['status']=='rescheduled' and 'Перенесено с' in old['notes']
        assert new['status']=='scheduled' and new['starts_at'].startswith(new_start)
        # Mark a separate upcoming appointment as not attended and verify the deviation alert.
        future_req=req(doctor,'/api/calendar','POST',{'patient_id':alex['id'],'kind':'appointment','starts_at':(date.today()+timedelta(days=5)).isoformat()+'T10:00','title':'Тестовый приём для отметки неявки','notes':'workflow regression test'},dc,201)
        status=req(doctor,f"/api/appointments/{future_req['event_id']}/status",'POST',{'status':'missed'},dc,200)
        missed_bundle=req(doctor,f"/api/patients/{alex['id']}")
        assert any(a['source_type']=='appointment' and a['title']=='Приём не состоялся' for a in missed_bundle['alerts'])
        # Patient logs an honest missed dose. The doctor gets the row in the same record.
        active=next(m for m in moved_bundle['medication_plans'] if m['status']=='active')
        req(alex_user,'/api/medication-logs','POST',{'plan_id':active['id'],'scheduled_date':date.today().isoformat(),'status':'skipped','notes':'Тестовая честная отметка о пропуске.'},ac,201)
        d_bundle=req(doctor,f"/api/patients/{alex['id']}")
        assert any(l['plan_id']==active['id'] and l['status']=='skipped' and l['scheduled_date']==date.today().isoformat() for l in d_bundle['medication_logs'])
        # Patient can add an entry/message and it appears in the physician bundle.
        req(alex_user,'/api/entries','POST',{'entry_type':'mood','entry_date':date.today().isoformat(),'data':{'mood':2,'sleep_hours':3.5,'appetite':'снижен','notes':'Демонстрационная регрессия: ухудшение самочувствия.','self_harm_thoughts':False}},ac,201)
        req(alex_user,'/api/messages','POST',{'body':'Сегодня хуже спал, тревога усилилась, пропустил один приём. Хочу обсудить.'},ac,201)
        d_bundle=req(doctor,f"/api/patients/{alex['id']}")
        assert any(e['entry_type']=='mood' and e['data'].get('mood')==2 for e in d_bundle['entries'])
        assert any('тревога усилилась' in m['body'] for m in d_bundle['messages'])
        print('PASS: six source-grounded synthetic portraits; baseline scale scores preserved; longitudinal diary/questionnaire/visit/care-plan coverage; both improvement and deterioration trajectories; role isolation; reschedule preserves original appointment; missed-visit alert; medication adherence record and patient feedback sync to doctor.')
        print(json.dumps(metrics,ensure_ascii=False,indent=2))
    finally:
        proc.terminate()
        try: proc.wait(timeout=4)
        except subprocess.TimeoutExpired: proc.kill()
