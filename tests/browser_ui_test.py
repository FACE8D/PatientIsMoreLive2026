#!/usr/bin/env python3
"""Browser-render smoke test using Chromium and a deterministic mock API."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'static'
qdefs=[]
for p in sorted((ROOT/'data'/'questionnaires').glob('*.json')):
    d=json.loads(p.read_text(encoding='utf-8'))
    qdefs.append({k:d.get(k) for k in ('id','title','category','respondent','instruction','source','version','license_review_required','implementation_notes')})
meds=json.loads((ROOT/'data'/'medications.json').read_text(encoding='utf-8')); meds=meds.get('medications',meds)
schemes=[]; scheme_defs={}
for p in sorted((ROOT/'data'/'treatment_schemes').glob('*.json')):
    d=json.loads(p.read_text(encoding='utf-8')); scheme_defs[d['id']]=d; schemes.append({k:d.get(k) for k in ('id','title','category','version','summary','status','source_refs','approval_required','patient_visible_after_approval')})
guideline_sources=json.loads((ROOT/'data'/'guidelines'/'source_registry.json').read_text(encoding='utf-8')).get('sources',[])
red=json.loads((ROOT/'data'/'red_flags.json').read_text(encoding='utf-8'))
integrations=json.loads((ROOT/'data'/'integrations.json').read_text(encoding='utf-8'))
patient={'id':1,'full_name':'Мария Демонстрационная','birth_date':'1990-04-18','sex':'female','menstrual_enabled':True,'notes':'Синтетическая запись.'}
patient2={'id':2,'full_name':'Алексей Тестовый','birth_date':'1984-03-12','sex':'male','menstrual_enabled':False,'notes':'Вторая тестовая карточка.'}
test_plan=__import__('copy').deepcopy(scheme_defs['depression_guided_self_help'])
for step in test_plan.get('steps',[]): step['status']='pending'
test_plan['configuration']={'chosen_method':'КПТ-ориентированная самопомощь','session_count':6,'goal':'Тестовая согласованная цель','support_schedule':'review'}
test_plan['configuration_fields']=test_plan.get('configuration_fields',[])
test_adverse={'id':44,'patient_id':1,'onset_at':'2026-10-24T10:15:00+00:00','severity':'moderate','serious':False,'symptoms':['nausea','dizziness'],'description':'Тестовая реакция; строка с длинным описанием должна переноситься без наложения слов и кнопок.','action_taken':'Запись создана для UI-теста','review_status':'pending','clinician_assessment':'','outcome':''}
empty_bundle={'patient':patient,'entries':[],'results':[],'appointments':[],'visits':[],'medication_plans':[],'medication_logs':[],'recommendations':[],'messages':[],'alerts':[],'preferences':{'chat_enabled':True,'chat_mode':'async','notification_preferences':{}},'clinical_assessments':[],'adverse_events':[test_adverse],'care_plans':[{'id':7,'scheme_id':'depression_guided_self_help','scheme_version':test_plan.get('version'),'title':test_plan['title'],'status':'active','start_date':'2026-10-24','review_date':'2026-11-07','notes':'Настроенный план для UI-теста','plan':test_plan}],'imaging_studies':[],'notifications':[]}
state={'role':None,'user':None,'nextid':50,'bundle':empty_bundle,'alerts':[],'notifications':[],'red_rules':[{**r,'rule':r} for r in red['rules']]}
def response(body,status=200,headers=None): return {'status':status,'headers':headers or {'Content-Type':'application/json; charset=utf-8'},'body':body if isinstance(body,str) else json.dumps(body,ensure_ascii=False)}

def api_response(path,method,body):
    if path=='/api/health': return response({'ok':True})
    if path=='/api/me' and state['role'] is None: return response({'error':'Требуется вход в систему'},401)
    if path=='/api/login':
        email=body.get('email',''); role='doctor' if 'doctor' in email else 'patient'; state['role']=role
        state['user']={'id':1 if role=='doctor' else 2,'email':email,'display_name':'Демонстрационный врач' if role=='doctor' else patient['full_name'],'role':role,'must_change_password':False}
        state['bundle']={**empty_bundle,'patient':patient}
        state['alerts']=[]; state['notifications']=[]
        return response({'user':state['user'],'csrf_token':'csrf-'+role,'patient':patient if role=='patient' else None,'demo_mode':True})
    if path=='/api/me': return response({'user':state['user'],'csrf_token':'csrf-'+state['role'],'patient':patient if state['role']=='patient' else None})
    if path=='/api/logout': state['role']=None; state['user']=None; return response({'ok':True})
    if path=='/api/bootstrap':
        if state['role']=='doctor':
            return response({'user':state['user'],'patients':[{**patient,'email':'patient@demo.local'}],'alerts':state['alerts'],'notifications':state['notifications'],'unread_notification_count':sum(not n.get('read_at') for n in state['notifications']),'questionnaires':qdefs,'medications':meds,'treatment_schemes':schemes,'guideline_sources':guideline_sources,'integrations':integrations,'patient':None,'scenarios':[],'demo_mode':True})
        return response({'user':state['user'],'patients':[],'alerts':state['alerts'],'notifications':state['notifications'],'unread_notification_count':sum(not n.get('read_at') for n in state['notifications']),'questionnaires':[x for x in qdefs if x['respondent']!='clinician'],'medications':meds,'treatment_schemes':schemes,'guideline_sources':guideline_sources,'integrations':integrations,'patient':patient,'scenarios':[],'demo_mode':True})
    if path=='/api/patients/1': return response(state['bundle'])
    if path=='/api/red-flags':
        if state['role']!='doctor':return response({'error':'Недостаточно прав'},403)
        return response({'rules':state['red_rules'],'delivery_limit':red.get('delivery_limit')})
    if path.startswith('/api/patient-red-flags/'): return response({'patient_id':1,'rules':[{**r,'enabled':bool(r.get('enabled',True)),'overridden':False} for r in state['red_rules']]})
    if path=='/api/notifications':return response({'notifications':state['notifications'],'unread_count':sum(not n.get('read_at') for n in state['notifications'])})
    if path=='/api/integrations':return response(integrations)
    if path=='/api/treatment-schemes':return response({'schemes':schemes})
    if path.startswith('/api/treatment-schemes/'):
        sid=path.rsplit('/',1)[1]; match=scheme_defs.get(sid)
        return response({'scheme':match},200 if match else 404)
    if path.startswith('/api/medications/'):
        mid=path.rsplit('/',1)[1]; match=next((m for m in meds if m.get('id')==mid),None)
        return response({'medication':match} if match else {'error':'not found'},200 if match else 404)
    if path=='/api/push/vapid-public':return response({'configured':False,'public_key':''})
    if path=='/api/medications':return response({'medications':meds})
    if path=='/api/questionnaires':return response({'questionnaires':qdefs})
    if path.startswith('/api/questionnaires/') and path.count('/')==3:
        qid=path.rsplit('/',1)[1]; fn=ROOT/'data'/'questionnaires'/f'{qid}.json'
        return response({'questionnaire':json.loads(fn.read_text(encoding='utf-8'))} if fn.exists() else {'error':'not found'},200 if fn.exists() else 404)
    if path.startswith('/api/patients/1/') and path.endswith('/exchange/fhir'):
        return response({'resourceType':'Bundle','type':'collection','entry':[]})
    if path.startswith('/api/patients/1/') and path.endswith('/reports/clinical.json'):
        return response({'patient':patient,'verified':True})
    if path.startswith('/api/messages'):return response({'messages':state['bundle'].get('messages',[])})
    if path.startswith('/api/ai/analysis'):return response({'summary':'Детерминированная сводка','model_status':'rules_only'})
    if path=='/api/demo-scenarios':return response({'scenarios':[]})
    if path.startswith('/api/notifications/') and path.endswith('/read'):
        n=int(path.split('/')[-2]);
        for item in state['notifications']:
            if item['id']==n:item['read_at']='2026-10-24T00:00:00+00:00'
        return response({'ok':True})
    if method in ('POST','DELETE'):
        state['nextid']+=1
        return response({'ok':True,'id':state['nextid'],'result_id':state['nextid'],'assessment_id':state['nextid'],'care_plan_id':state['nextid'],'plan_id':state['nextid'],'event_id':state['nextid'],'message':'Mock saved','score':{'type':'sum','total':0,'band':None}})
    return response({'error':'mock endpoint not implemented','path':path},404)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,timeout=15000,args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-background-networking','--no-proxy-server','--proxy-bypass-list=<-loopback>'])
    page=browser.new_page(viewport={'width':1400,'height':900})
    page.set_default_timeout(5000)
    page.set_default_navigation_timeout(10000)
    # Fail promptly on a broken selector instead of stalling the whole regression suite.
    page.set_default_timeout(5000)
    page.set_default_navigation_timeout(10000)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('about:blank')
    mock_data={'qdefs':qdefs,'meds':meds,'schemes':schemes,'scheme_defs':scheme_defs,'guideline_sources':guideline_sources,'red':red,'integrations':integrations,'patient':patient,'patient2':patient2,'test_plan':test_plan,'test_adverse':test_adverse}
    js_mock=r"""
      window.__mock = __DATA__;
      window.__mockRole = null; window.__mockUser = null; window.__mockNextId = 100; window.__mockCurrentPatientId=1; window.__messageAudit={};
      window.__mockBundle = {patient:window.__mock.patient, entries:[], results:[], appointments:[], visits:[], medication_plans:[], medication_logs:[], recommendations:[], messages:[], alerts:[], preferences:{chat_enabled:true,chat_mode:'async',notification_preferences:{}},clinical_assessments:[{id:55,patient_id:1,assessed_at:'2026-10-24T10:00:00+00:00',signed_at:'2026-10-24T10:30:00+00:00',summary:'Последний подписанный тестовый осмотр',plan_notes:'Контроль по плану'}],adverse_events:[window.__mock.test_adverse],care_plans:[{id:7,scheme_id:'depression_guided_self_help',scheme_version:window.__mock.test_plan.version,title:window.__mock.test_plan.title,status:'active',start_date:'2026-10-24',review_date:'2026-11-07',notes:'Настроенный план для UI-теста',plan:window.__mock.test_plan}],imaging_studies:[],notifications:[]};
      window.__mockBundle.entries = [
        {id:1,patient_id:1,entry_type:'mood',entry_date:'2026-10-20',data:{mood:6,sleep_hours:7,appetite:'обычный',notes:'Более спокойный день'},created_at:'2026-10-20T18:00:00+00:00'},
        {id:2,patient_id:1,entry_type:'mood',entry_date:'2026-10-22',data:{mood:2,sleep_hours:3,appetite:'снижен',notes:'Ночью почти не спал, тревога усилилась'},created_at:'2026-10-22T19:00:00+00:00'},
        {id:3,patient_id:1,entry_type:'checklist',entry_date:'2026-10-22',data:{actions:['wash']},created_at:'2026-10-22T19:10:00+00:00'},
        {id:4,patient_id:1,entry_type:'wellbeing',entry_date:'2026-10-22',data:{tags:['сон','тревога'],polarity:'negative',notes:'Тестовая запись самочувствия'},created_at:'2026-10-22T19:20:00+00:00'}
      ];
      window.__mockBundle.results = [
        {id:11,patient_id:1,questionnaire_id:'hars14',questionnaire_title:'HARS — Шкала тревоги Гамильтона',version:'1',created_at:'2026-10-01T10:00:00+00:00',answers_json:'{}',score_json:JSON.stringify({type:'sum',total:22,series_type:'baseline',risk_flag:false}),score:{type:'sum',total:22,series_type:'baseline',risk_flag:false}},
        {id:12,patient_id:1,questionnaire_id:'hars14',questionnaire_title:'HARS — Шкала тревоги Гамильтона',version:'1',created_at:'2026-10-22T10:00:00+00:00',answers_json:'{}',score_json:JSON.stringify({type:'sum',total:27,series_type:'simulated_followup',risk_flag:false}),score:{type:'sum',total:27,series_type:'simulated_followup',risk_flag:false}}
      ];
      window.__mockBundle.appointments = [
        {id:19,patient_id:1,starts_at:'2026-10-29T10:00',ends_at:'2026-10-29T10:30',kind:'appointment',title:'Следующий контрольный приём',notes:'Обсудить ухудшение сна и переносимость лечения',status:'scheduled',created_at:'2026-10-20T10:00:00+00:00'},
        {id:18,patient_id:1,starts_at:'2026-10-21T10:00',ends_at:'2026-10-21T10:30',kind:'appointment',title:'Контрольный приём',notes:'Исходный слот, сохранён после переноса',status:'rescheduled',created_at:'2026-10-15T10:00:00+00:00'},
        {id:20,patient_id:1,starts_at:'2026-10-23T10:00',ends_at:'2026-10-23T10:30',kind:'appointment',title:'Пропущенный контроль',notes:'Не удалось связаться в назначенное время',status:'missed',created_at:'2026-10-15T10:00:00+00:00'}
      ];
      window.__mockBundle.visits = [{id:31,patient_id:1,visit_date:'2026-10-15',kind:'Контрольный приём',notes:'Тревога снизилась, переносимость проверена',followup_date:'2026-10-29'}];
      window.__mockBundle.medication_plans = [{id:32,patient_id:1,drug_id:'aviandr',drug_name:'Авиандр',regimen:'По назначению врача; учебный план',times:['09:00'],start_date:'2026-10-10',status:'active',created_at:'2026-10-10T09:00:00+00:00',notes:'Симуляция'}];
      window.__mockBundle.medication_logs = [{id:33,patient_id:1,plan_id:32,scheduled_date:'2026-10-22',status:'skipped',notes:'Забыл принять'}];
      window.__mockBundle.alerts = [{id:34,patient_id:1,source_type:'questionnaire',severity:'review',title:'Рост баллов по шкале тревоги',detail:'Требуется уточнить сон и тревогу.',status:'open',created_at:'2026-10-22T11:00:00+00:00'}];
      window.__mockBundle.messages = [{id:35,patient_id:1,sender_user_id:2,sender_name:'Пациент',sender_role:'patient',body:'Последние два дня сплю хуже, один приём пропустил.',created_at:'2026-10-22T20:00:00+00:00'},{id:36,patient_id:1,sender_user_id:1,sender_name:'Демонстрационный врач',sender_role:'doctor',body:'Рекомендую записать самочувствие и обсудить сон.',created_at:'2026-10-22T21:00:00+00:00'}];
      window.__mockBundle2={...window.__mockBundle,patient:window.__mock.patient2,entries:[{id:70,patient_id:2,entry_type:'mood',entry_date:'2026-10-25',data:{mood:4,sleep_hours:5,appetite:'снижен',notes:'Синтетический пример второго пациента'},created_at:'2026-10-25T12:00:00+00:00'}],results:[],appointments:[],visits:[],medication_plans:[],medication_logs:[],recommendations:[],messages:[],alerts:[],clinical_assessments:[],adverse_events:[],care_plans:[],imaging_studies:[],notifications:[]};
      try { Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}}}); } catch(e) {}
      try { Object.defineProperty(navigator,'serviceWorker',{configurable:true,value:undefined}); } catch(e) {}
      window.fetch = async (url, opts={}) => {
        const path=String(url).split('?')[0]; const method=opts.method||'GET'; let body={}; try{body=JSON.parse(opts.body||'{}')}catch(e){}
        const ok=(x,status=200)=>new Response(JSON.stringify(x),{status,headers:{'Content-Type':'application/json; charset=utf-8'}});
        if(path==='/api/health') return ok({ok:true});
        if(path==='/api/me' && !window.__mockRole) return ok({error:'Требуется вход в систему'},401);
        if(path==='/api/login') {const role=(body.email||'').includes('doctor')?'doctor':'patient';window.__mockRole=role;window.__mockUser={id:role==='doctor'?1:2,email:body.email,display_name:role==='doctor'?'Демонстрационный врач':window.__mock.patient.full_name,role,must_change_password:false};window.__mockBundle.patient=window.__mock.patient;return ok({user:window.__mockUser,csrf_token:'csrf-'+role,patient:role==='patient'?window.__mock.patient:null,demo_mode:true});}
        if(path==='/api/me') return ok({user:window.__mockUser,csrf_token:'csrf-'+window.__mockRole,patient:window.__mockRole==='patient'?window.__mock.patient:null});
        if(path==='/api/logout'){window.__mockRole=null;window.__mockUser=null;return ok({ok:true});}
        if(path==='/api/bootstrap') {const role=window.__mockRole;return ok({user:window.__mockUser,patients:role==='doctor'?[{...window.__mock.patient,email:'patient@demo.local'},{...window.__mock.patient2,email:'alexey.case@demo.local'}]:[],alerts:[],notifications:[],unread_notification_count:0,questionnaires:role==='patient'?window.__mock.qdefs.filter(x=>x.respondent!=='clinician'):window.__mock.qdefs,medications:window.__mock.meds,treatment_schemes:window.__mock.schemes,integrations:window.__mock.integrations,guideline_sources:window.__mock.guideline_sources,patient:role==='patient'?window.__mock.patient:null,scenarios:[],demo_mode:true});}
        if(path.startsWith('/api/patients/1/') && path.endsWith('/reports/clinical.dcm')) { window.__lastDicomUrl=String(url); const bytes=new Uint8Array(256); bytes.set([68,73,67,77],128); return new Response(bytes,{status:200,headers:{'Content-Type':'application/dicom','Content-Disposition':'attachment; filename=\"clinical-report-1-55.dcm\"'}}); }
        if(path.startsWith('/api/patients/1/') && path.endsWith('/reports/clinical.json')) return ok({patient:window.__mock.patient,verified:true});
        if(path.startsWith('/api/patients/1/') && path.endsWith('/exchange/fhir')) return ok({resourceType:'Bundle',type:'collection',entry:[]});
        if(path==='/api/patients/1') {window.__mockCurrentPatientId=1;return ok(window.__mockBundle);}
        if(path==='/api/patients/2') {window.__mockCurrentPatientId=2;return ok(window.__mockBundle2);}
        if(path==='/api/appointments/19' && method==='DELETE'){const event=window.__mockBundle.appointments.find(x=>x.id===19);if(event)event.status='deleted';return ok({ok:true,message:'Событие удалено из календаря.'});}
        const editMessageMatch=path.match(/^\/api\/messages\/(\d+)\/edit$/);
        if(editMessageMatch&&method==='POST'){const mid=Number(editMessageMatch[1]);const msg=window.__mockBundle.messages.find(x=>x.id===mid)||window.__mockBundle2.messages.find(x=>x.id===mid);if(!msg)return ok({error:'not found'},404);window.__messageAudit[mid]??=[];window.__messageAudit[mid].push({action:'edit',previous_body:msg.body,new_body:body.body,reason:body.reason||'',created_at:new Date().toISOString(),actor_name:window.__mockUser.display_name});msg.body=body.body;msg.edited_at=new Date().toISOString();return ok({ok:true,message:'Сообщение исправлено.'});}
        const deleteMessageMatch=path.match(/^\/api\/messages\/(\d+)$/);
        if(deleteMessageMatch&&method==='DELETE'){const mid=Number(deleteMessageMatch[1]);const msg=window.__mockBundle.messages.find(x=>x.id===mid)||window.__mockBundle2.messages.find(x=>x.id===mid);if(!msg)return ok({error:'not found'},404);window.__messageAudit[mid]??=[];window.__messageAudit[mid].push({action:'delete',previous_body:msg.body,new_body:'',reason:'Удалено отправителем',created_at:new Date().toISOString(),actor_name:window.__mockUser.display_name});msg.deleted_at=new Date().toISOString();return ok({ok:true,message:'Сообщение удалено.'});}
        const messageHistoryMatch=path.match(/^\/api\/messages\/(\d+)\/history$/);
        if(messageHistoryMatch&&method==='GET'){const mid=Number(messageHistoryMatch[1]);const msg=window.__mockBundle.messages.find(x=>x.id===mid)||window.__mockBundle2.messages.find(x=>x.id===mid);return ok({message_id:mid,current_body:msg?.body||'',deleted:Boolean(msg?.deleted_at),revisions:window.__messageAudit[mid]||[]});}
        if(path==='/api/red-flags') {if(window.__mockRole!=='doctor')return ok({error:'Нет доступа'},403);return ok({rules:window.__mock.red.rules.map(r=>({...r,rule:r})),delivery_limit:window.__mock.red.delivery_limit});}
        if(path.startsWith('/api/patient-red-flags/')) {const parts=path.split('/').filter(Boolean);if(method==='POST')return ok({ok:true,message:'Настройка сохранена'});return ok({patient_id:Number(parts[3]||1),rules:window.__mock.red.rules.map(r=>({...r,enabled:!!r.enabled,severity:r.severity||'review',recipient:r.recipient||'doctor',overridden:false}))});}
        if(path==='/api/integrations') return ok(window.__mock.integrations);
        if(path==='/api/notifications') return ok({notifications:window.__mockBundle.notifications,unread_count:0});
        if(path==='/api/treatment-schemes') return ok({schemes:window.__mock.schemes});
        if(path.startsWith('/api/treatment-schemes/')) {const id=path.split('/').pop();return ok({scheme:window.__mock.scheme_defs[id]||null});}
        if(path==='/api/push/vapid-public') return ok({configured:false,public_key:''});
        if(path==='/api/medications') return ok({medications:window.__mock.meds});
        if(path.startsWith('/api/medications/')) {const id=path.split('/').pop();return ok({medication:window.__mock.meds.find(x=>x.id===id)||null});}
        if(path==='/api/questionnaires') return ok({questionnaires:window.__mock.qdefs});
        if(path.startsWith('/api/questionnaires/') && !path.endsWith('/submit')) {const id=path.split('/').pop();return ok({questionnaire:{id,title:id,questions:[],instruction:'test',source:'test'}});}
        if(path==='/api/messages' || (path.startsWith('/api/messages/')&&method==='GET'&&!path.endsWith('/history'))){const bundle=window.__mockCurrentPatientId===2?window.__mockBundle2:window.__mockBundle;return ok({messages:bundle.messages.map(m=>m.deleted_at?{...m,body:'Сообщение удалено отправителем'}:m)});}
        if(path.startsWith('/api/ai/analysis')) return ok({summary:'Детерминированная сводка',model_status:'rules_only'});
        if(path==='/api/demo-scenarios') return ok({scenarios:[]});
        if(path.startsWith('/api/notifications/') && path.endsWith('/read')) return ok({ok:true});
        if(method==='POST'||method==='DELETE'){window.__mockNextId++;return ok({ok:true,id:window.__mockNextId,result_id:window.__mockNextId,assessment_id:window.__mockNextId,care_plan_id:window.__mockNextId,plan_id:window.__mockNextId,event_id:window.__mockNextId,message:'Mock saved',score:{type:'sum',total:0,band:null}});}
        return ok({error:'mock endpoint not implemented'},404);
      };
    """.replace('__DATA__',json.dumps(mock_data,ensure_ascii=False))
    page.add_script_tag(content=js_mock)
    page.set_content('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mock</title></head><body><div id="app"></div></body></html>')
    page.add_style_tag(path=str(STATIC/'app.css'))
    page.add_script_tag(path=str(STATIC/'app.js'))
    try:
        page.wait_for_selector('#login-form',timeout=10000)
        page.locator('[data-action="demo-doctor"]').click()
        page.wait_for_selector('[data-nav="clinical-map"]',timeout=10000)
        assert 'Кабинет врача' in page.locator('.role-pill').inner_text()
        # Regression test: header selection really loads a different patient's bundle and can return.
        assert page.locator('#top-patient-select option[value="1"]').count()==1 and page.locator('#top-patient-select option[value="2"]').count()==1, 'header patient selector should include both accessible patients'
        page.locator('#top-patient-select').select_option('2');page.wait_for_timeout(120)
        assert 'Алексей Тестовый' in page.locator('#page-content').inner_text(), 'selecting the second patient did not load their profile'
        assert 'Мария Демонстрационная' not in page.locator('.welcome-card h2').inner_text(), 'selected patient context remained stale after switching'
        page.locator('#top-patient-select').select_option('1');page.wait_for_timeout(120)
        assert 'Мария Демонстрационная' in page.locator('#page-content').inner_text(), 'switching back to the first patient failed'
        # Verify the actual longitudinal timeline, deviation filter, chart detail and visit rescheduling modal.
        page.locator('[data-nav="monitoring"]').click();page.wait_for_timeout(120)
        assert page.locator('.timeline-entry').count() >= 8, 'longitudinal mock history did not render'
        assert page.locator('[data-action="edit-entry"]').count()>=1, 'record correction controls missing from diary history'
        page.locator('[data-action="timeline-filter"][data-filter="deviations"]').click();page.wait_for_timeout(80)
        assert page.locator('.timeline-entry').count() >= 2, 'deviation filter did not retain deteriorating signals'
        assert page.locator('.timeline-entry.timeline-deviation').count() >= 2, 'deviations not visually flagged'
        page.locator('[data-action="timeline-filter"][data-filter="all"]').click()
        page.locator('.timeline-entry').filter(has_text='Пропущенный контроль').first.click();page.wait_for_selector('.modal')
        assert 'Не состоялся' in page.locator('.modal').inner_text() and 'Отметить как не состоявшийся' not in page.locator('.modal').inner_text()
        page.locator('[data-action="close-modal"]').click()
        page.locator('.timeline-entry').filter(has_text='Пропуск приёма').first.click();page.wait_for_selector('.modal')
        assert 'Забыл принять' in page.locator('.modal').inner_text()
        page.locator('[data-action="close-modal"]').click()
        page.locator('.timeline-entry').filter(has_text='Рост баллов по шкале тревоги').first.click();page.wait_for_selector('.modal')
        assert 'Требуется уточнить сон' in page.locator('.modal').inner_text()
        page.locator('[data-action="close-modal"]').click()
        # Existing calendar cards should be clickable; a scheduled slot offers completion and reschedule.
        page.locator('[data-nav="calendar"]').click();page.locator('.calendar-event-click').filter(has_text='Следующий контрольный приём').click();page.wait_for_selector('.modal')
        assert page.locator('[data-action="reschedule-event"]').count()==1
        page.locator('[data-action="reschedule-event"]').click();page.wait_for_selector('#reschedule-form')
        assert page.locator('#reschedule-form input[name="starts_at"]').count()==1
        page.locator('[data-action="close-modal"]').click()
        page.locator('.calendar-event-click').filter(has_text='Следующий контрольный приём').click();page.wait_for_selector('.modal')
        page.once('dialog',lambda dialog:dialog.accept())
        page.locator('[data-action="delete-event"]').click();page.wait_for_timeout(100)
        assert page.locator('.calendar-event-click').filter(has_text='Следующий контрольный приём').count()==0, 'deleted appointment remained visible in the calendar'
        # Own messages can be edited/deleted. The other participant's message has no edit/delete controls.
        page.locator('[data-nav="chat"]').click();page.wait_for_timeout(100)
        assert page.locator('[data-action="edit-message"][data-id="36"]').count()==1
        assert page.locator('[data-action="delete-message"][data-id="36"]').count()==1
        assert page.locator('[data-action="edit-message"][data-id="35"]').count()==0
        page.locator('[data-action="edit-message"][data-id="36"]').click();page.wait_for_selector('#edit-message-form')
        page.locator('#edit-message-form textarea[name="body"]').fill('Исправленный текст врача')
        page.locator('#edit-message-form textarea[name="reason"]').fill('Уточнение формулировки')
        page.locator('#edit-message-form button[type="submit"]').click();page.wait_for_timeout(100)
        assert page.locator('.message').filter(has_text='Исправленный текст врача').count()==1
        assert page.locator('.message').filter(has_text='изменено').count()>=1
        page.once('dialog',lambda dialog:dialog.accept())
        page.locator('[data-action="delete-message"][data-id="36"]').click();page.wait_for_timeout(100)
        deleted_row=page.locator('.message').filter(has_text='Сообщение удалено отправителем')
        assert deleted_row.count()==1, 'deleted message should become a tombstone, not disappear without context'
        page.locator('[data-action="message-history"][data-id="36"]').click();page.wait_for_selector('.modal')
        assert 'Исправленный текст врача' in page.locator('.modal').inner_text() and 'Удаление' in page.locator('.modal').inner_text(), 'clinician audit history did not retain revisions'
        page.locator('[data-action="close-modal"]').click()
        # Return to the previous navigation assertions.
        for key,marker in [
          ('clinical-map','Сводная клиническая оценка'),('questionnaires','Библиотека опросников'),
          ('treatment','Библиотека схем и препараты'),('red-flags','Система флагов и уведомлений'),
          ('integrations','Импорт CSV / старой базы'),('notifications','Уведомления'),('calendar','Календарь пациента'),
          ('monitoring','История и динамика')]:
            page.locator(f'[data-nav="{key}"]').click(); page.wait_for_timeout(100)
            text=page.locator('#page-content').inner_text()
            assert marker in text, f'{key} missing marker {marker}; content starts: {text[:160]}'
        page.locator('[data-nav="clinical-map"]').click();page.wait_for_timeout(100)
        assert page.locator('.temporal-correlation-card').count()==1 and page.locator('#temporal-metric').count()==1, 'time-based parameter chart and date filters missing'
        assert page.locator('#temporal-metric option').count()>=3, 'temporal graph should offer selectable patient/doctor metrics'
        page.locator('#temporal-metric').select_option('sleep');page.wait_for_timeout(80)
        assert 'Продолжительность сна' in page.locator('.temporal-correlation-card').inner_text() and '0–24 часа' in page.locator('.temporal-correlation-card').inner_text(), 'changing the metric should redraw the chart and its scale immediately'
        assert 'Карта реакций и изменений самочувствия' in page.locator('#page-content').inner_text(), 'patient reaction map missing from clinical card'
        assert page.locator('[data-action="temporal-point"]').count()>=1, 'temporal chart observations must be clickable'
        temporal_point=page.locator('[data-action="temporal-point"]').first
        assert temporal_point.get_attribute('tabindex')=='0' and temporal_point.get_attribute('role')=='button'
        temporal_point.click();page.wait_for_selector('.modal')
        assert 'Точка графика' in page.locator('.modal').inner_text() and ('Дневники и самочувствие' in page.locator('.modal').inner_text() or 'Результаты опросников' in page.locator('.modal').inner_text() or 'Связанные записи не найдены' in page.locator('.modal').inner_text()), 'temporal chart point should reveal its value and related source records'
        page.locator('[data-action="close-modal"]').click()
        reaction_tile=page.locator('[data-action="reaction-tag"]').first
        assert reaction_tile.count()==1, 'reaction map tiles should be clickable'
        reaction_tile.click();page.wait_for_selector('.modal')
        assert 'Самочувствие' in page.locator('.modal').inner_text() and 'Тестовая запись самочувствия' in page.locator('.modal').inner_text(), 'reaction map tile should open source wellbeing records'
        page.locator('[data-action="close-modal"]').click()
        assert page.locator('.adverse-event-row .list-title').filter(has_text='тошнота').count() >= 1, 'adverse-reaction cards should name the reported reaction in the title'
        page.locator('[data-nav="monitoring"]').click();page.wait_for_timeout(100)
        visit_details=page.locator('.collapsible-section details').filter(has=page.locator('summary',has_text='История приёмов'))
        assert visit_details.count()==1 and not visit_details.locator('summary').evaluate('(el)=>el.parentElement.open'), 'visit history should be collapsible by default'
        visit_details.locator('summary').click();page.wait_for_timeout(50)
        assert page.locator('.visit-history-chart').count()==1, 'visit history should include monthly chart when expanded'
        assert page.locator('[data-action="visit-month"]').count()==1, 'each visit-history chart bar must be clickable'
        page.locator('[data-action="visit-month"]').first.click();page.wait_for_selector('.modal')
        assert 'Контрольный приём' in page.locator('.modal').inner_text(), 'clicking a monthly visit bar should show the underlying visit'
        page.locator('[data-action="close-modal"]').click()
        # Every chart point opens its underlying source/related records, not just a tooltip.
        mood_point=page.locator('.chart-point').first
        assert mood_point.get_attribute('tabindex')=='0' and mood_point.get_attribute('role')=='button'
        mood_point.click();page.wait_for_selector('.modal')
        assert 'Записи настроения' in page.locator('.modal').inner_text() and 'Более спокойный день' in page.locator('.modal').inner_text(), 'mood chart point should open source diary entries'
        page.locator('[data-action="close-modal"]').click()
        score_point=page.locator('.score-point').first
        assert score_point.get_attribute('tabindex')=='0' and score_point.get_attribute('role')=='button'
        score_point.click();page.wait_for_selector('.modal')
        assert 'Исходные ответы' in page.locator('.modal').inner_text(), 'questionnaire trend point should open the source result'
        page.locator('[data-action="close-modal"]').click()
        search=page.locator('#global-search');search.fill('тошнота');page.wait_for_timeout(50)
        assert page.locator('#global-search-results').inner_text().lower().find('тошнота')>=0, 'global search should find adverse reaction by symptom word'
        search.fill('авиандр');page.wait_for_timeout(50)
        assert page.locator('#global-search-results').inner_text().lower().find('авиандр')>=0 or 'Ничего не найдено' in page.locator('#global-search-results').inner_text(), 'global search should handle medication name without crashing'
        search.fill('')
        page.locator('[data-nav="clinical-map"]').click();page.wait_for_timeout(80)
        with page.expect_download() as download_info:
            page.locator('[data-action="export-dicom"]').last.click()
        dicom_download=download_info.value
        dicom_path=dicom_download.path()
        assert dicom_path and Path(dicom_path).stat().st_size>=160, 'DICOM export download is empty'
        assert page.evaluate('window.__lastDicomUrl').endswith('assessment_id=55'), 'DICOM export did not use the latest saved assessment'
        page.wait_for_timeout(100)
        assert any('DICOM SR' in t for t in page.locator('.toast').all_inner_texts()), 'DICOM export result was not acknowledged; visible toasts=' + repr(page.locator('.toast').all_inner_texts())
        page.locator('[data-action="clinical-assessment"]').first.click()
        assert page.locator('#clinical-assessment-form').count()==1
        page.locator('[data-action="close-modal"]').click()
        page.locator('[data-nav="treatment"]').click();page.wait_for_timeout(150)
        assert page.locator('#page-content').inner_text().find('Библиотека схем и препараты')>=0, 'separate treatment library navigation missing'
        page.locator('[data-nav="treatment-library"]').click();page.wait_for_timeout(150)
        assert page.locator('[data-action="drug-detail"]').count()>=10, 'medicine detail actions missing in separate library'
        assert page.locator('[data-action="compare-drugs"]').count()==1, 'medicine comparison must be available inside the separate library'
        assert page.locator('#drug-library-search').count()==1 and page.locator('#scheme-library-search').count()==1, 'separate library search controls are missing'
        page.locator('#drug-library-search').fill('амитриптилин');page.wait_for_timeout(60)
        visible_drugs=page.locator('#drug-library-grid .searchable-library-card:visible').count()
        assert visible_drugs>=1 and visible_drugs<page.locator('#drug-library-grid .searchable-library-card').count(), 'medicine search should filter the library in place'
        page.locator('#drug-library-search').fill('');page.wait_for_timeout(40)
        page.locator('[data-nav="treatment"]').click();page.wait_for_timeout(150)
        # Regression: selected patient's medication-plan text must occupy the full card width,
        # not collapse to a one-character column when the row contains action buttons.
        plan_block=page.locator('.patient-specific-treatment-block')
        assert plan_block.count()==1, 'patient-specific treatment block missing'
        block_width=plan_block.evaluate('(el) => el.getBoundingClientRect().width')
        content_width=page.locator('#page-content').evaluate('(el) => el.getBoundingClientRect().width')
        assert block_width >= content_width-80, f'patient-specific plan block is unexpectedly narrow: block={block_width}, content={content_width}'
        plan_rows=page.locator('.patient-specific-treatment-block .list-row')
        if plan_rows.count():
            row_width=plan_rows.first.evaluate('(el) => el.getBoundingClientRect().width')
            text_width=plan_rows.first.locator('.list-main-text').evaluate('(el) => el.getBoundingClientRect().width')
            assert row_width>500 and text_width>250, f'medication plan text collapsed: row={row_width}, text={text_width}'
        page.locator('[data-nav="treatment-library"]').click();page.wait_for_timeout(100)
        page.locator('[data-action="drug-detail"][data-drug-id="amitriptyline"]').click();page.wait_for_selector('.drug-detail-section')
        drug_detail=page.locator('.modal').inner_text()
        assert 'ССД — средняя суточная доза' in drug_detail and 'Поиск в ГРЛС' in drug_detail and 'схемы титрации' in drug_detail.lower()
        assert '.pdf' not in drug_detail.lower() and 'todo.pdf' not in drug_detail.lower(), 'uploaded file names should not appear in medication card'
        page.locator('[data-action="close-modal"]').click()
        page.locator('[data-nav="treatment"]').click();page.wait_for_timeout(100)
        page.locator('[data-action="compare-drugs"]').click();page.wait_for_selector('#compare-drugs-form')
        picks=page.locator('input[name="compare-drug"]')
        assert picks.count()>=17, 'expected 17 currently available medicine options in comparison'
        picks.nth(0).check();picks.nth(5).check();page.locator('[data-action="compare-selected"]').click()
        comparison=page.locator('#comparison-content').inner_text()
        assert 'Фармакокинетика' in comparison and 'Противопоказания' in comparison and 'Поиск в ГРЛС' in comparison and 'Карточка препарата' in comparison
        page.locator('[data-action="compare-back"]').click();page.locator('[data-action="close-modal"]').click()
        page.locator('[data-action="low-vision-toggle"]').first.click()
        assert page.locator('html').get_attribute('data-low-vision')=='on' and page.locator('html').get_attribute('data-high-contrast')=='on' and page.locator('html').get_attribute('data-font-scale')=='large'
        page.locator('[data-action="low-vision-toggle"]').first.click()
        assert page.locator('html').get_attribute('data-low-vision')=='off'
        page.locator('[data-nav="treatment-library"]').click();page.wait_for_timeout(100)
        page.locator('[data-action="start-care-scheme"][data-scheme-id="depression_guided_self_help"]').click();page.wait_for_selector('#care-plan-form')
        scheme_detail=page.locator('.modal').inner_text()
        assert 'План будет сохранён для пациента:' in scheme_detail and 'Карточка №1' in scheme_detail, 'scheme plan must visibly identify the selected patient before save'
        assert 'Подробное содержание клинических рекомендаций' in scheme_detail and 'Мониторинг и оценка результата' in scheme_detail and 'Сигналы риска и защитные условия' in scheme_detail
        assert '.pdf' not in scheme_detail.lower() and 'todo.pdf' not in scheme_detail.lower() and 'workflow' not in scheme_detail.lower(), 'scheme reader must use named Russian sources, not input file names or untranslated terms'
        assert page.locator('input[name="cfg-goal"]').count()==0 and page.locator('textarea[name="cfg-goal"]').count()==1
        page.locator('[data-action="close-modal"]').click()
        page.locator('[data-nav="treatment"]').click();page.wait_for_timeout(100)
        page.locator('.collapsible-section details > summary').first.click();page.locator('.care-plan-details > summary').first.click();page.locator('[data-action="edit-care-plan"][data-id="7"]').click();page.wait_for_selector('#care-plan-form')
        assert page.locator('textarea[name="cfg-goal"]').input_value()=='Тестовая согласованная цель'
        page.locator('[data-action="close-modal"]').click()
        page.locator('[data-nav="treatment"]').click();page.wait_for_timeout(100)
        assert page.locator('.configured-field').count()>=2, 'per-plan configuration was not rendered'
        assert page.locator('.ae-detail-line').count()>=4, 'adverse reaction labels are not separated'
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(120)
        ae=page.locator('.adverse-event-row').bounding_box(); details=page.locator('.adverse-event-details').bounding_box()
        assert ae and details and details['x']>=ae['x'] and details['x']+details['width']<=ae['x']+ae['width']+1, 'adverse-event text overflows on mobile'
        page.set_viewport_size({'width':1400,'height':900})
        page.locator('[data-nav="red-flags"]').click();page.wait_for_timeout(200);assert page.locator('[data-redflag-form]').count()>=5, 'forms='+str(page.locator('[data-redflag-form]').count())+' text='+page.locator('#page-content').inner_text()[:500]+' errors='+str(errors)
        assert page.locator('#redflag-patient-select').count()==1 and page.locator('[data-patient-redflag-form]').count()>=1, 'patient-specific red flag settings missing'
        page.locator('[data-nav="integrations"]').click();page.wait_for_timeout(200);assert page.locator('#csv-import-form').count()==1 and page.locator('#fhir-import-form').count()==1, 'integrations='+page.locator('#page-content').inner_text()[:500]+' errors='+str(errors)
        page.locator('.logout').click();page.wait_for_selector('#login-form')
        page.locator('[data-action="demo-patient"]').click();page.wait_for_selector('[data-nav="diary"]',timeout=10000)
        for key,marker in [('dashboard','Добро пожаловать'),('diary','Как вы себя чувствуете?'),('wellbeing','Моё самочувствие'),('questionnaires','Библиотека опросников'),('treatment','Мои планы и препараты'),('notifications','Уведомления'),('settings','Сменить пароль')]:
            page.locator(f'[data-nav="{key}"]').click();page.wait_for_timeout(100)
            text=page.locator('#page-content').inner_text();assert marker in text,f'patient {key} missing {marker}'
        page.locator('[data-nav="wellbeing"]').click();page.wait_for_timeout(100)
        assert page.locator('#wellbeing-form').count()==1 and page.locator('.wellbeing-expanded-catalog').count()==1, 'dedicated wellbeing page or expanded catalogue missing'
        page.locator('.wellbeing-expanded-catalog > summary').click()
        assert page.locator('.wellbeing-expanded-option').count()>60, 'expanded positive examples catalogue is incomplete'
        page.locator('#wellbeing-search').fill('засыпать');page.wait_for_timeout(80)
        assert page.locator('.wellbeing-expanded-option:visible').count()>=1 and page.locator('.wellbeing-expanded-option:visible').count()<10, 'wellbeing search did not filter examples'
        page.locator('#wellbeing-search').fill('')
        page.locator('[data-nav="questionnaires"]').click();page.wait_for_timeout(80)
        page.locator('[data-action="start-q"]').first.click();page.wait_for_timeout(100)
        page.evaluate('history.back()');page.wait_for_timeout(250)
        assert 'Библиотека опросников' in page.locator('#page-content').inner_text(), 'browser back should return from an opened questionnaire to its list'
        page.locator('[data-nav="treatment"]').click();page.locator('[data-action="new-adverse-event"]').first.click()
        assert page.locator('#adverse-modal-form').count()==1 and page.locator('input[name="ae-symptom"]').count()>=20
        # Regression: symptom checkboxes must remain small controls; they must not take 100% width
        # from the general text-input rule and push symptom labels outside their cards.
        for opt in page.locator('.symptom-option').all():
            geom=opt.evaluate('(el)=>({option:el.getBoundingClientRect().toJSON(),input:el.querySelector("input").getBoundingClientRect().toJSON(),text:el.querySelector("span").getBoundingClientRect().toJSON()})')
            assert geom['input']['width']<=22, f"symptom checkbox unexpectedly stretched: {geom}"
            assert geom['text']['left'] < geom['option']['right'] and geom['text']['right'] <= geom['option']['right']+1, f"symptom label exceeds its card: {geom}"
        page.locator('input[name="ae-symptom"]').first.check()
        assert page.locator('input[name="ae-symptom"]').first.is_checked(), 'symptom checkbox did not stay checked after selection'
        # The same options remain readable on a narrow phone-sized viewport and in low-vision mode.
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(80)
        page.locator('html').evaluate('(el)=>el.setAttribute("data-low-vision","on")')
        for opt in page.locator('.symptom-option').all():
            geom=opt.evaluate('(el)=>({option:el.getBoundingClientRect().toJSON(),input:el.querySelector("input").getBoundingClientRect().toJSON(),text:el.querySelector("span").getBoundingClientRect().toJSON()})')
            assert geom['input']['width']<=22, f"low-vision checkbox unexpectedly stretched: {geom}"
            assert geom['text']['left'] < geom['option']['right'] and geom['text']['right'] <= geom['option']['right']+1, f"low-vision symptom label exceeds its card: {geom}"
        page.locator('html').evaluate('(el)=>el.setAttribute("data-low-vision","off")')
        page.set_viewport_size({'width':1400,'height':900})
        page.locator('[data-action="close-modal"]').click()
        assert not errors,f'Browser exceptions: {errors}'
        print('PASS: Chromium patient switching, clickable patient directory, appointment deletion, message edit/delete with audit history, drug cards/GRLS, source-based schemes, accessibility, and doctor/patient views without uncaught exceptions.')
    finally:
        try: page.close(run_before_unload=False)
        except Exception: pass
        try: browser.close()
        except Exception: pass
