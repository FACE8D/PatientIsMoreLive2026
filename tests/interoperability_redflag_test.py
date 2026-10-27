#!/usr/bin/env python3
"""Integration test for clinical map, red flags, adverse events and data exchange."""
import http.cookiejar, json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error
from datetime import date, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from interoperability import validate_basic_text_sr
PORT=8769

with tempfile.TemporaryDirectory(prefix='clinic-interoperability-') as td:
    dbpath=Path(td)/'test.db'
    env=os.environ.copy(); env.update(CLINIC_PORT=str(PORT),CLINIC_DB_PATH=str(dbpath),CLINIC_HOST='127.0.0.1',CLINIC_DEMO_MODE='1')
    proc=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        base=f'http://127.0.0.1:{PORT}'
        for _ in range(90):
            try:
                urllib.request.urlopen(base+'/api/health',timeout=1).read(); break
            except Exception: time.sleep(.15)
        else: raise RuntimeError('server did not start')
        def client(): return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        doc,pat=client(),client()
        def req(op,path,method='GET',body=None,csrf=None,expected=200,raw=False):
            data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
            headers={'Accept':'application/json'}
            if data is not None: headers['Content-Type']='application/json'
            if csrf: headers['X-CSRF-Token']=csrf
            q=urllib.request.Request(base+path,data=data,headers=headers,method=method)
            try:
                with op.open(q,timeout=8) as r: status=r.status; content_type=r.headers.get('Content-Type',''); content=r.read()
            except urllib.error.HTTPError as e: status=e.code; content_type=e.headers.get('Content-Type',''); content=e.read()
            if status!=expected:
                try: detail=json.loads(content.decode())
                except Exception: detail=content[:160]
                raise AssertionError(f'{method} {path} expected {expected}, got {status}: {detail}')
            if raw: return status,content_type,content
            return json.loads(content.decode())

        dl=req(doc,'/api/login','POST',{'email':'doctor@demo.local','password':'DemoDoctor2026!'},expected=200); dc=dl['csrf_token']
        boot=req(doc,'/api/bootstrap'); assert len(boot['patients'])>=6
        # Use an isolated non-portrait patient for this integration test so seeded signed
        # encounters and pre-existing safety flags do not bias authorization assertions.
        created=req(doc,'/api/patients','POST',{'full_name':'Тест обмена, синтетический','email':'interop.patient@example.local','birth_date':'1990-01-01','sex':'not_specified','password':'InteropPatient2026!','notes':'Техническая изолированная запись для интеграционного теста.'},dc,201)
        pid=created['patient']['id']
        pl=req(pat,'/api/login','POST',{'email':'interop.patient@example.local','password':'InteropPatient2026!'},expected=200); pc=pl['csrf_token']
        assert len(boot.get('treatment_schemes',[]))>=10
        assert isinstance(boot.get('medications'),list) and len(boot['medications'])>=10
        assert len(boot.get('questionnaires',[]))>=10
        req(pat,'/api/red-flags',expected=403)

        # Editable rules and message red flag notification.
        rules=req(doc,'/api/red-flags'); msg_rule=next(r for r in rules['rules'] if r['id']=='message_delusion_terms')
        assert msg_rule['enabled'] is True
        req(doc,'/api/red-flags/message_delusion_terms','POST',{'recipient':'care_team'},dc,400)
        req(pat,'/api/messages','POST',{'body':'Я слышу голоса, которые говорят со мной.'},pc,201)
        bundle=req(doc,f'/api/patients/{pid}')
        assert any(a['source_type']=='message' and 'возможное' in a['title'].lower() for a in bundle['alerts'])
        dnotes=req(doc,'/api/notifications'); assert any('Сообщение:' in n['title'] for n in dnotes['notifications'])
        note=next(n for n in dnotes['notifications'] if 'Сообщение:' in n['title'])
        req(doc,f"/api/notifications/{note['id']}/read",'POST',{},dc,200)
        req(pat,f"/api/notifications/{note['id']}/read",'POST',{},pc,404)

        # A configurable questionnaire red flag is persisted on the test result itself.
        scl_answers={f'q{i}':0 for i in range(1,91)}
        scl_answers['q7']=1  # one of the imported symptom items covered by the psychosis review rule
        scl=req(pat,'/api/questionnaires/scl90r/submit','POST',{'answers':scl_answers},pc,201)
        assert scl['score']['risk_flag'] is True
        assert scl['score'].get('red_flag_rules'), 'matched red-flag identifiers must persist with score'
        pat_after=req(pat,f'/api/patients/{pid}')
        saved=next(r for r in pat_after['results'] if r['id']==scl['result_id'])
        assert saved['score']['risk_flag'] is True and saved['score'].get('red_flag_rules')

        # One structured clinical encounter drives chart, JSON/FHIR and DICOM exports.
        draft=req(doc,f'/api/patients/{pid}/clinical-assessments','POST',{
            'mental_state':{'mood':'worsening','affect':'partial','thought_content':'not_reported','perception':'not_assessed','sleep':'unknown','activity':'unknown','functioning':'needs_review','insight':'partial','suicide_risk':'not_assessed','adherence':'unknown','social_support':'unknown','side_effects':'unknown','psychosis':'not_assessed'},
            'summary':'INTEGRATION TEST — draft encounter','plan_notes':'draft only','visit_date':date.today().isoformat(),'sign':False
        },dc,201)
        doc_bundle=req(doc,f'/api/patients/{pid}')
        pat_bundle=req(pat,f'/api/patients/{pid}')
        assert any(x['id']==draft['assessment_id'] for x in doc_bundle['clinical_assessments'])
        assert not any(x['id']==draft['assessment_id'] for x in pat_bundle['clinical_assessments'])
        assert all('draft encounter' not in x['notes'].lower() for x in pat_bundle['visits'])
        req(pat,f'/api/patients/{pid}/reports/clinical.json',expected=403)
        req(pat,f'/api/patients/{pid}/reports/clinical.dcm',expected=404)
        # Signing a safety-relevant assessment requires its own confirmation.
        req(doc,f'/api/patients/{pid}/clinical-assessments','POST',{
            'mental_state':{'thought_content':'possible','psychosis':'possible','suicide_risk':'not_assessed'},
            'summary':'INTEGRATION TEST — signed encounter','plan_notes':'review directly','sign':True,'safety_review':False
        },dc,400)
        signed=req(doc,f'/api/patients/{pid}/clinical-assessments','POST',{
            'mental_state':{'thought_content':'possible','psychosis':'possible','suicide_risk':'not_assessed'},
            'summary':'INTEGRATION TEST — signed encounter','plan_notes':'review directly','sign':True,'safety_review':True
        },dc,201)
        assert signed['signed'] is True
        doc_bundle=req(doc,f'/api/patients/{pid}')
        pat_bundle=req(pat,f'/api/patients/{pid}')
        assert any(x['id']==signed['assessment_id'] for x in pat_bundle['clinical_assessments'])
        assert any(a['source_type']=='clinical_assessment' for a in doc_bundle['alerts'])
        report=req(doc,f'/api/patients/{pid}/reports/clinical.json'); assert report['verified'] is True
        fhir=req(doc,f'/api/patients/{pid}/exchange/fhir'); assert fhir['resourceType']=='Bundle'
        types=[e['resource']['resourceType'] for e in fhir.get('entry',[])]
        assert 'Patient' in types and 'DiagnosticReport' in types
        status,ct,blob=req(doc,f'/api/patients/{pid}/reports/clinical.dcm',raw=True)
        assert status==200 and 'application/dicom' in ct
        meta=validate_basic_text_sr(blob); assert meta['valid_part10'] and meta['byte_length']==len(blob)
        assert len(blob)>500 and blob[128:132]==b'DICM', 'DICOM SR should be non-empty Part-10 with DICM marker'
        status2,ct2,explicit_blob=req(doc,f"/api/patients/{pid}/reports/clinical.dcm?assessment_id={signed['assessment_id']}",raw=True)
        assert status2==200 and explicit_blob[128:132]==b'DICM' and len(explicit_blob)>500
        # Patient may export only a signed report.
        status,ct,pblob=req(pat,f'/api/patients/{pid}/reports/clinical.dcm',raw=True)
        assert status==200 and validate_basic_text_sr(pblob)['valid_part10']

        # Configurable adverse events: all symptom selections persist; severe reactions notify both sides.
        symptoms=['nausea','dizziness','insomnia','manic_symptoms','sexual_function','other']
        ae=req(pat,'/api/adverse-events','POST',{'symptoms':symptoms,'severity':'severe','serious':True,'description':'synthetic structured event'},pc,201)
        p_bundle=req(pat,f'/api/patients/{pid}'); d_bundle=req(doc,f'/api/patients/{pid}')
        ev=next(x for x in p_bundle['adverse_events'] if x['id']==ae['event_id'])
        assert all(s in ev['symptoms'] for s in symptoms)
        assert any(n['source_type']=='adverse_event' and n['patient_id']==pid for n in req(pat,'/api/notifications')['notifications'])
        assert any(n['source_type']=='adverse_event' for n in req(doc,'/api/notifications')['notifications'])
        req(pat,f"/api/adverse-events/{ae['event_id']}/review",'POST',{'review_status':'reviewed'},pc,403)
        req(doc,f"/api/adverse-events/{ae['event_id']}/review",'POST',{'review_status':'reviewed','clinician_assessment':'reviewed in test','outcome':'documented'},dc,200)

        # Signal includes linked medication; resolving it closes the same event in the clinical map.
        linked_plan=req(doc,'/api/medication-plans','POST',{'patient_id':pid,'drug_id':'aviandr','regimen':'ТЕСТ: 25 мг вечером','start_date':date.today().isoformat(),'times':['21:00'],'notes':'тест связанной реакции','confirm':True,'checked_grls':True,'confirm_review':True},dc,201)
        linked_event=req(pat,'/api/adverse-events','POST',{'medication_plan_id':linked_plan['plan_id'],'symptoms':['nausea'],'severity':'severe','serious':True,'description':'Связанная реакция — регрессионный тест'},pc,201)
        alert_bundle=req(doc,f'/api/patients/{pid}')
        linked_alert=next(a for a in alert_bundle['alerts'] if a['source_type']=='adverse_event' and a['source_id']==linked_event['event_id'])
        assert 'Авиандр' in linked_alert['detail'] and '25 мг вечером' in linked_alert['detail'], linked_alert['detail']
        req(doc,f"/api/alerts/{linked_alert['id']}/review",'POST',{'significance':'resolved','reaction':'Тестовое документирование','followup':'Контроль завершён'},dc,200)
        synced=req(doc,f'/api/patients/{pid}')
        linked_ev=next(x for x in synced['adverse_events'] if x['id']==linked_event['event_id'])
        linked_al=next(x for x in synced['alerts'] if x['id']==linked_alert['id'])
        assert linked_ev['review_status']=='closed' and linked_al['status']=='resolved', (linked_ev['review_status'],linked_al['status'])
        assert linked_al['latest_review']['significance']=='resolved'
        assert linked_al['latest_review']['reaction']=='Тестовое документирование'
        assert linked_al['latest_review']['followup']=='Контроль завершён'
        listed=req(doc,f'/api/alerts?patient_id={pid}&include_resolved=1')['alerts']
        listed_alert=next(x for x in listed if x['id']==linked_alert['id'])
        assert listed_alert['latest_review']['reaction']=='Тестовое документирование'

        # Treatment scheme remains a draft until explicitly activated; patient can then mark a step.
        schemes=req(doc,'/api/treatment-schemes')['schemes']; sid='depression_guided_self_help'
        plan=req(doc,'/api/care-plans','POST',{'patient_id':pid,'scheme_id':sid,'start_date':date.today().isoformat(),'activate':False,'notes':'synthetic test','configuration':{'chosen_method':'КПТ-ориентированная самопомощь','goal':'synthetic test goal'}},dc,201)
        assert plan['status']=='draft'
        assert not any(x['id']==plan['care_plan_id'] for x in req(pat,f'/api/patients/{pid}/care-plans')['care_plans'])
        req(doc,f"/api/care-plans/{plan['care_plan_id']}/status",'POST',{'status':'active'},dc,400)
        req(doc,f"/api/care-plans/{plan['care_plan_id']}/status",'POST',{'status':'active','confirm_review':True,'safety_review':True},dc,200)
        pplans=req(pat,f'/api/patients/{pid}/care-plans')['care_plans']
        active=next(x for x in pplans if x['id']==plan['care_plan_id']); assert active['status']=='active'
        if active['plan'].get('steps'):
            req(pat,f"/api/care-plans/{plan['care_plan_id']}/step",'POST',{'step_index':0,'status':'completed'},pc,200)

        # Manual DICOM study metadata is linked by UID; repeat insert is an upsert, not a duplicate.
        study={'study_uid':'1.2.840.99999.1.20261024','modality':'MR','study_date':date.today().isoformat(),'description':'synthetic MRI reference','endpoint':'https://pacs.example.invalid/dicom-web','source_system':'test_pacs','metadata':{'access':'metadata-only'}}
        req(doc,f'/api/patients/{pid}/imaging-studies','POST',study,dc,201)
        req(doc,f'/api/patients/{pid}/imaging-studies','POST',study,dc,201)
        studies=req(doc,f'/api/patients/{pid}/imaging-studies')['imaging_studies']
        assert sum(1 for s in studies if s['study_uid']==study['study_uid'])==1

        # Mapped CSV import is idempotent; second import will not duplicate or overwrite values.
        csv_body={'source_system':'source_ehr_test','records':[{'external_id':'row-001','entry_date':date.today().isoformat(),'entry_type':'external_observation','data':{'label':'bp','value':'120/80'}},{'external_id':'row-002','entry_date':date.today().isoformat(),'entry_type':'external_note','data':{'note':'external note'}}]}
        first=req(doc,f'/api/patients/{pid}/exchange/csv/import','POST',csv_body,dc,200)
        second=req(doc,f'/api/patients/{pid}/exchange/csv/import','POST',csv_body,dc,200)
        assert first['imported']==2 and second['imported']==0 and second['skipped_duplicates']==2
        with sqlite3.connect(dbpath) as db: assert db.execute("SELECT COUNT(*) FROM entries WHERE json_extract(data_json,'$.source_system')='source_ehr_test'").fetchone()[0]==2

        # FHIR R4 selected-resource import is idempotent; medication is a draft only.
        fhir_in={'resourceType':'Bundle','type':'collection','entry':[
          {'resource':{'resourceType':'Observation','id':'obs-001','status':'final','code':{'text':'test observation'},'valueString':'synthetic'}},
          {'resource':{'resourceType':'MedicationRequest','id':'medreq-001','status':'active','medicationCodeableConcept':{'text':'External medicine'},'dosageInstruction':[{'text':'from source; review'}]}},
          {'resource':{'resourceType':'ImagingStudy','id':'study-001','status':'available','identifier':[{'system':'urn:dicom:uid','value':'urn:oid:1.2.840.99999.2.3'}],'series':[{'modality':'CT','instance':[{'uid':'1.2.840.99999.2.4'}]}]}},
          {'resource':{'resourceType':'AdverseEvent','id':'ae-001','event':{'coding':[{'code':'nausea','display':'Nausea'}]},'date':date.today().isoformat(),'seriousness':{'coding':[{'code':'non-serious'}]}}}
        ]}
        imp=req(doc,f'/api/patients/{pid}/exchange/fhir/import','POST',{'source_system':'fhir_test','bundle':fhir_in},dc,200)
        imp2=req(doc,f'/api/patients/{pid}/exchange/fhir/import','POST',{'source_system':'fhir_test','bundle':fhir_in},dc,200)
        assert imp['imported']==4 and imp2['imported']==0 and imp2['skipped_duplicates']==4
        doctor_bundle=req(doc,f'/api/patients/{pid}')
        assert any(x['drug_name']=='External medicine' and x['status']=='draft' for x in doctor_bundle['medication_plans'])
        with sqlite3.connect(dbpath) as db: assert db.execute("SELECT COUNT(*) FROM imaging_studies WHERE study_uid='1.2.840.99999.2.3'").fetchone()[0]==1

        # Chat preference is optional and enforced server-side; an attempt while disabled creates a notification.
        req(pat,f'/api/patients/{pid}/preferences','POST',{'chat_enabled':False,'chat_mode':'off'},pc,200)
        req(pat,'/api/messages','POST',{'body':'should be blocked'},pc,403)
        req(pat,f'/api/patients/{pid}/preferences','POST',{'chat_enabled':True,'chat_mode':'async'},pc,200)
        # UI/static files, including PWA and accessibility resources.
        for path,marker in [('/','app.js'),('/app.js','renderClinicalMap'),('/app.css','prefers-reduced-motion'),('/manifest.webmanifest','start_url'),('/service-worker.js','push')]:
            with urllib.request.urlopen(base+path,timeout=4) as r: assert r.status==200 and marker.encode() in r.read(), path
        print('PASS: clinical map single-source workflow, patient signed-data access, red flags persisted on test results, recipient notifications, adverse-event completeness, treatment gates, DICOM SR Part-10, FHIR R4 exports/imports, CSV deduplication, DICOM study UID upsert, optional chat, PWA resources.')
    finally:
        proc.terminate()
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired: proc.kill()
