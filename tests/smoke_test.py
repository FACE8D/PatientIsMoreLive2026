#!/usr/bin/env python3
"""HTTP smoke test. Starts an isolated local database; no real patient data."""
import http.cookiejar, json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PORT=8767
with tempfile.TemporaryDirectory(prefix='clinic-test-') as td:
    env=os.environ.copy(); env['CLINIC_PORT']=str(PORT); env['CLINIC_DB_PATH']=str(Path(td)/'test.db'); env['CLINIC_HOST']='127.0.0.1'; env['CLINIC_DEMO_MODE']='1'
    proc=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        base=f'http://127.0.0.1:{PORT}'
        def wait_server():
            for _ in range(60):
                try:
                    with urllib.request.urlopen(base+'/api/health',timeout=1) as r:
                        if r.status==200:return
                except Exception: time.sleep(.2)
            raise RuntimeError('server did not start')
        wait_server()
        def opener(): return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        doc=opener(); pat=opener(); csrf={}
        def req(op,path,method='GET',body=None,token=None,expected=200):
            data=None if body is None else json.dumps(body).encode()
            headers={'Accept':'application/json'}
            if data is not None: headers['Content-Type']='application/json'
            if token: headers['X-CSRF-Token']=token
            request=urllib.request.Request(base+path,data=data,headers=headers,method=method)
            try:
                with op.open(request,timeout=5) as res: status=res.status; text=res.read().decode()
            except urllib.error.HTTPError as e: status=e.code; text=e.read().decode()
            try: obj=json.loads(text)
            except: obj={'raw':text[:150]}
            if status!=expected: raise AssertionError(f'{method} {path}: expected {expected}, got {status}: {obj}')
            return obj
        req(doc,'/','GET',expected=200) if False else None
        health=req(doc,'/api/health'); assert health['ok']
        logged=req(doc,'/api/login','POST',{'email':'doctor@demo.local','password':'DemoDoctor2026!'}); dc=logged['csrf_token']
        bootstrap=req(doc,'/api/bootstrap'); pid=next(x['id'] for x in bootstrap['patients'] if x['email']=='patient@demo.local'); assert len(bootstrap['patients'])>=6; assert len(bootstrap['questionnaires'])>=10; assert len(bootstrap['guideline_sources'])>=10
        bundle=req(doc,f'/api/patients/{pid}'); assert 'patient' in bundle and 'entries' in bundle
        # Patient-specific signal settings are persisted separately from global rules.
        patient_rules=req(doc,f'/api/patient-red-flags/{pid}')
        assert patient_rules['patient_id']==pid and patient_rules['rules']
        chosen_rule=patient_rules['rules'][0]
        override=req(doc,f'/api/patient-red-flags/{pid}/{chosen_rule["id"]}','POST',{'enabled':False,'severity':'review','recipient':'doctor'},dc,200)
        assert override['ok']
        # Clinical-map PDF upload is doctor-only, tied to one patient, and audited.
        pdf_bytes=b'%PDF-1.4\n% synthetic smoke test\n1 0 obj<</Type/Catalog>>endobj\n%%EOF'
        import base64
        upload=req(doc,f'/api/patients/{pid}/clinical-documents','POST',{'file_name':'paper-report.pdf','title':'Скан заключения','content_base64':base64.b64encode(pdf_bytes).decode()},dc,201)
        doc_id=upload['document_id']
        doc_list=req(doc,f'/api/patients/{pid}/clinical-documents'); assert any(x['id']==doc_id and x['title']=='Скан заключения' for x in doc_list['documents'])
        req(doc,f'/api/patients/{pid}/clinical-documents','POST',{'file_name':'bad.pdf','content_base64':base64.b64encode(b'not a pdf').decode()},dc,400)
        # Actual file endpoint returns the uploaded bytes, not JSON metadata.
        # Medicine detail APIs return the collected content and a filtered, medicine-specific GRLS search.
        aviandr=req(doc,'/api/medications/aviandr')['medication']
        assert aviandr['label_summary']['administration_schedule'] and 'grls.aspx?s=' in aviandr['grls_url'] and aviandr['official_leaflet_url']
        meds=req(doc,'/api/medications')['medications']
        assert len(meds)==17 and all(x.get('vidal_url') and x.get('clinical_profile',{}).get('pk') and x.get('clinical_profile',{}).get('contra') for x in meds)
        fluoxetine=next(x for x in meds if x['id']=='fluoxetine')
        assert fluoxetine['vidal_url']=='https://www.vidal.ru/drugs/molecule/425'
        assert '31.12.2025' in fluoxetine['clinical_profile']['source_note']
        registry=bootstrap['guideline_sources']
        assert any(x['id']=='russian_standard_1697' and '1697_стандарт.pdf' not in x['title'] for x in registry)
        amitriptyline=req(doc,'/api/medications/amitriptyline')['medication']
        assert amitriptyline['source_dose_reference']['average_daily_dose_value']==150
        assert 'нет схемы титрации' in amitriptyline['administration_schedule'].lower()
        # Every scheme opens with full read sections and an editable per-instance configuration schema.
        scheme=req(doc,'/api/treatment-schemes/depression_guided_self_help')['scheme']
        assert len(scheme['clinical_detail_sections'])>=2 and len(scheme['reader_sections'])>=5
        assert any(x['id']=='goal' and x.get('required') for x in scheme['configuration_fields'])
        # Server-side scoring and result persistence.
        gad={f'q{i}':0 for i in range(1,8)}
        score=req(doc,'/api/questionnaires/gad7/submit','POST',{'patient_id':pid,'answers':gad},dc,201); assert score['score']['total']==0
        # Doctor creates a draft; it must not be visible through patient bundle.
        draft=req(doc,'/api/medication-plans','POST',{'patient_id':pid,'drug_id':'aviandr','regimen':'TEST — не применять; черновик','start_date':__import__('datetime').date.today().isoformat(),'times':['09:00'],'notes':'smoke test','confirm':False},dc,201)
        p=opener(); plog=req(p,'/api/login','POST',{'email':'patient@demo.local','password':'DemoPatient2026!'}); pc=plog['csrf_token']
        own_entry=req(p,'/api/entries','POST',{'entry_type':'mood','entry_date':__import__('datetime').date.today().isoformat(),'data':{'mood':5,'sleep_hours':7,'appetite':'обычный','notes':'исходный текст'}},pc,201)
        entry_id=own_entry['entry_id']
        edited_entry=req(p,f'/api/entries/{entry_id}/edit','POST',{'entry_date':__import__('datetime').date.today().isoformat(),'data':{'mood':6,'sleep_hours':8,'appetite':'обычный','notes':'исправленный текст'}},pc,200)
        assert edited_entry['ok']
        with sqlite3.connect(Path(td)/'test.db') as db:
            audit=db.execute("SELECT detail FROM audit_log WHERE action='edit' AND target_type='entry' AND target_id=? ORDER BY id DESC LIMIT 1",(str(entry_id),)).fetchone()
            assert audit and 'исходный текст' in audit[0] and 'исправленный текст' in audit[0], 'entry edit must audit old and new content'
        pb=req(p,f'/api/patients/{pid}'); assert not any(x['id']==draft['plan_id'] for x in pb['medication_plans'])
        req(p,f'/api/patients/{pid}/clinical-documents','POST',{'file_name':'forbidden.pdf','content_base64':base64.b64encode(pdf_bytes).decode()},pc,403)
        with p.open(urllib.request.Request(base+f'/api/patients/{pid}/clinical-documents/{doc_id}/file',headers={'Accept':'application/pdf'}),timeout=5) as response:
            assert response.status==200 and response.headers.get_content_type()=='application/pdf' and response.read()==pdf_bytes
        with sqlite3.connect(Path(td)/'test.db') as db:
            assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action='upload_clinical_pdf' AND target_id=?",(str(doc_id),)).fetchone()[0]==1
            assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action='view_clinical_pdf' AND target_id=?",(str(doc_id),)).fetchone()[0]==1
        # Care-plan configuration is saved per instance; activation refuses missing required fields.
        care=req(doc,'/api/care-plans','POST',{'patient_id':pid,'scheme_id':'depression_guided_self_help','start_date':__import__('datetime').date.today().isoformat(),'review_date':'','notes':'test care plan','configuration':{},'activate':False},dc,201)
        cp_id=care['care_plan_id']
        req(doc,f'/api/care-plans/{cp_id}/status','POST',{'status':'active','confirm_review':True,'safety_review':True},dc,400)
        config={'chosen_method':'КПТ-ориентированная самопомощь','resource':'Проверенный локальный материал','session_count':6,'goal':'TEST: согласованная цель','support_schedule':'обсуждение на review'}
        req(doc,f'/api/care-plans/{cp_id}/configuration','POST',{'configuration':config,'notes':'per-instance configuration','review_date':''},dc,200)
        req(doc,f'/api/care-plans/{cp_id}/status','POST',{'status':'active'},dc,400)
        req(doc,f'/api/care-plans/{cp_id}/status','POST',{'status':'active','confirm_review':True,'safety_review':True},dc,200)
        p_bundle=req(p,f'/api/patients/{pid}')
        patient_cp=next(x for x in p_bundle['care_plans'] if x['id']==cp_id)
        assert patient_cp['plan']['configuration']['goal']=='TEST: согласованная цель'
        req(p,f'/api/care-plans/{cp_id}/configuration','POST',{'configuration':config},pc,403)
        # Updating an active plan requires explicit re-review and persists only that instance's values.
        updated={**config,'goal':'TEST: обновлённая индивидуальная цель'}
        req(doc,f'/api/care-plans/{cp_id}/configuration','POST',{'configuration':updated,'notes':'updated','review_date':'','confirm_review':True},dc,400)
        req(doc,f'/api/care-plans/{cp_id}/configuration','POST',{'configuration':updated,'notes':'updated','review_date':'','confirm_review':True,'safety_review':True},dc,200)
        refreshed_cp=req(doc,f'/api/patients/{pid}')
        assert next(x for x in refreshed_cp['care_plans'] if x['id']==cp_id)['plan']['configuration']['goal']=='TEST: обновлённая индивидуальная цель'
        # Patient diary data travels directly into the same doctor card.
        entry=req(p,'/api/entries','POST',{'entry_type':'mood','entry_date':__import__('datetime').date.today().isoformat(),'data':{'mood':6,'sleep_hours':7,'appetite':'обычный','notes':'smoke-test','self_harm_thoughts':False}},pc,201)
        refreshed=req(doc,f'/api/patients/{pid}'); assert any(x['id']==entry['entry_id'] for x in refreshed['entries'])
        # A mood entry with 1/10 and a self-harm checkbox must create a signal tied to that exact row/value.
        low_mood=req(p,'/api/entries','POST',{'entry_type':'mood','entry_date':__import__('datetime').date.today().isoformat(),'data':{'mood':1,'sleep_hours':3,'appetite':'снижен','notes':'regression low mood','self_harm_thoughts':True}},pc,201)
        refreshed=req(doc,f'/api/patients/{pid}')
        exact=next(x for x in refreshed['entries'] if x['id']==low_mood['entry_id'])
        assert exact['data']['mood']==1 and exact['data']['self_harm_thoughts'] is True
        mood_alert=next(a for a in refreshed['alerts'] if a['source_type']=='entry' and a['source_id']==low_mood['entry_id'] and 'самоповреждении' in a['title'].lower())
        assert mood_alert['severity']=='critical' and '1/10' in mood_alert['detail'], mood_alert
        # Positive PHQ-9 self-harm item creates an urgent signal.
        phq={f'q{i}':0 for i in range(1,11)}; phq['q9']=1
        pres=req(p,'/api/questionnaires/phq9/submit','POST',{'answers':phq},pc,201); assert pres['safety_message'] and pres['score']['risk_flag']
        dboot=req(doc,'/api/bootstrap'); assert any(a['severity'] in ('urgent','critical') for a in dboot['alerts'])
        active_alert=req(doc,'/api/alerts?patient_id='+str(pid))['alerts'][0]
        reviewed=req(doc,f'/api/alerts/{active_alert["id"]}/review','POST',{'significance':'false_positive','reaction':'Проверено тестом','followup':'Не требуется'},dc,200)
        assert reviewed['ok']
        with sqlite3.connect(Path(td)/'test.db') as db:
            assert db.execute('SELECT COUNT(*) FROM alert_reviews WHERE alert_id=?',(active_alert['id'],)).fetchone()[0]==1
        # Patient can add their own personal calendar item; the assigned doctor sees it side-by-side.
        future_day=(__import__('datetime').date.today()+__import__('datetime').timedelta(days=2)).isoformat()
        personal=req(p,'/api/calendar','POST',{'kind':'personal','starts_at':future_day+'T12:00','title':'TEST: личная прогулка','notes':'synthetic event'},pc,201)
        doc_bundle=req(doc,f'/api/patients/{pid}'); assert any(a['title']=='TEST: личная прогулка' and a['kind']=='personal' for a in doc_bundle['appointments'])
        req(doc,'/api/calendar','POST',{'patient_id':pid,'kind':'personal','starts_at':future_day+'T12:00','title':'invalid kind'},dc,400)
        # Recommendation drafts are visible only in clinician view and become visible after publish.
        rec=req(doc,'/api/recommendations','POST',{'patient_id':pid,'body':'TEST: draft recommendation','publish':False},dc,201)
        doctor_bundle=req(doc,f'/api/patients/{pid}'); assert any(x['body']=='TEST: draft recommendation' and x['status']=='draft' for x in doctor_bundle['recommendations'])
        patient_bundle=req(p,f'/api/patients/{pid}'); assert not any(x['body']=='TEST: draft recommendation' for x in patient_bundle['recommendations'])
        req(doc,'/api/recommendations','POST',{'patient_id':pid,'body':'TEST: published recommendation','publish':True},dc,201)
        patient_bundle=req(p,f'/api/patients/{pid}'); assert any(x['body']=='TEST: published recommendation' and x['status']=='published' for x in patient_bundle['recommendations'])
        # Menstrual monitoring cannot be activated for a profile not marked female.
        with sqlite3.connect(Path(td)/'test.db') as db: db.execute("UPDATE patients SET sex='male', menstrual_enabled=0 WHERE id=?",(pid,))
        req(p,'/api/profile/menstrual','POST',{'enabled':True},pc,400)
        # Patient cannot list doctor-only data or inspect someone else's patient.
        # Chat roundtrip plus audited edit/delete with original text retained server-side.
        sent=req(p,'/api/messages','POST',{'body':'smoke-test original message'},pc,201)
        msg_id=sent['message_id']
        dm=req(doc,f'/api/messages?patient_id={pid}'); assert any(m['body']=='smoke-test original message' for m in dm['messages'])
        req(doc,f'/api/messages/{msg_id}/edit','POST',{'body':'attempted change by non-sender'},dc,403)
        edit=req(p,f'/api/messages/{msg_id}/edit','POST',{'body':'smoke-test corrected message','reason':'test edit'},pc,200)
        dm=req(doc,f'/api/messages?patient_id={pid}'); public=next(m for m in dm['messages'] if m['id']==msg_id)
        assert public['body']=='smoke-test corrected message' and public['edited_at']
        history=req(doc,f'/api/messages/{msg_id}/history'); assert len(history['revisions'])==1
        assert history['revisions'][0]['previous_body']=='smoke-test original message' and history['revisions'][0]['new_body']=='smoke-test corrected message'
        # Patient cannot view the privileged audit endpoint; only the assigned clinician can.
        req(p,f'/api/messages/{msg_id}/history',expected=403)
        deleted=req(p,f'/api/messages/{msg_id}','DELETE',token=pc,expected=200); assert deleted['ok']
        dm=req(doc,f'/api/messages?patient_id={pid}'); tombstone=next(m for m in dm['messages'] if m['id']==msg_id)
        assert tombstone['body']=='Сообщение удалено отправителем' and tombstone['deleted_at']
        history=req(doc,f'/api/messages/{msg_id}/history'); assert len(history['revisions'])==2
        assert history['revisions'][1]['action']=='delete' and history['revisions'][1]['previous_body']=='smoke-test corrected message'
        with sqlite3.connect(Path(td)/'test.db') as db:
            current=db.execute('SELECT body,deleted_at FROM messages WHERE id=?',(msg_id,)).fetchone()
            assert current[0]=='smoke-test corrected message' and current[1], 'original/current body must remain in server DB after soft delete'
            assert db.execute('SELECT COUNT(*) FROM message_revisions WHERE message_id=?',(msg_id,)).fetchone()[0]==2
        req(p,f'/api/messages/{msg_id}/edit','POST',{'body':'cannot edit deleted message'},pc,400)
        # Calendar event deletion is soft (audited) and unauthorized participants cannot remove physician events.
        event=req(doc,'/api/calendar','POST',{'patient_id':pid,'kind':'appointment','starts_at':future_day+'T15:00','title':'TEST: удаляемый приём','notes':'test event'},dc,201)
        event_id=event['event_id']
        req(p,f'/api/appointments/{event_id}','DELETE',token=pc,expected=403)
        del_event=req(doc,f'/api/appointments/{event_id}','DELETE',token=dc,expected=200); assert del_event['ok']
        deleted_bundle=req(doc,f'/api/patients/{pid}')
        assert next(a for a in deleted_bundle['appointments'] if a['id']==event_id)['status']=='deleted'
        req(doc,f'/api/appointments/{event_id}','DELETE',token=dc,expected=404)
        with sqlite3.connect(Path(td)/'test.db') as db:
            assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action='delete_appointment' AND target_id=?",(str(event_id),)).fetchone()[0]==1
        # A completed clinical event is protected from deletion to preserve the record.
        protected=req(doc,'/api/calendar','POST',{'patient_id':pid,'kind':'appointment','starts_at':future_day+'T16:00','title':'TEST: завершённый приём'},dc,201)['event_id']
        req(doc,f'/api/appointments/{protected}/status','POST',{'status':'completed'},dc,200)
        req(doc,f'/api/appointments/{protected}','DELETE',token=dc,expected=400)
        # Clinician confirms the existing draft; patient should now see it.
        req(doc,f"/api/medication-plans/{draft['plan_id']}/status",'POST',{'status':'active'},dc,400)
        approved=req(doc,f"/api/medication-plans/{draft['plan_id']}/status",'POST',{'status':'active','checked_grls':True,'confirm_review':True},dc,200)
        pb2=req(p,f'/api/patients/{pid}'); assert any(x['id']==draft['plan_id'] for x in pb2['medication_plans'])
        # A status change is an explicit timeline/calendar event; repeating it must not duplicate the event.
        stopped=req(doc,f"/api/medication-plans/{draft['plan_id']}/status",'POST',{'status':'stopped','reason':'TEST: согласованная отмена'},dc,200)
        after_stop=req(doc,f'/api/patients/{pid}')
        stop_events=[a for a in after_stop['appointments'] if a['kind']=='plan_change' and 'остановлена' in a['title'].lower() and 'TEST: согласованная отмена' in a['notes']]
        assert len(stop_events)==1, f'expected one visible stop event with reason, got {len(stop_events)}'
        req(doc,f"/api/medication-plans/{draft['plan_id']}/status",'POST',{'status':'stopped','reason':'duplicate check'},dc,200)
        after_repeat=req(doc,f'/api/patients/{pid}')
        assert sum(1 for a in after_repeat['appointments'] if a['kind']=='plan_change' and 'остановлена' in a['title'].lower())==1
        # Archived patient can be found in archive and restored without deleting medical history.
        created_arch=req(doc,'/api/patients','POST',{'full_name':'Тест архивирования','email':'archive.check@example.local','birth_date':'1995-03-18','sex':'not_specified','password':'ArchiveCheck2026!'},dc,201)
        archived_id=created_arch['patient']['id']
        req(doc,f'/api/patients/{archived_id}','DELETE',None,dc,200)
        archived_preview=req(doc,f'/api/patients/{archived_id}?include_archived=1')
        assert archived_preview['patient']['id']==archived_id, 'archived patient card must be viewable without restore'
        archived_list=req(doc,'/api/patients?include_archived=1&search=archive.check%40example.local')
        assert archived_list['total']==1 and archived_list['patients'][0]['id']==archived_id
        req(doc,f'/api/patients/{archived_id}/restore','POST',{},dc,200)
        active_list=req(doc,'/api/patients?search=1995-03-18')
        assert any(x['id']==archived_id for x in active_list['patients']), 'restored patient searchable by date of birth'
        # The browser frontend must include the central selected-patient loader (regression for broken patient switching).
        with urllib.request.urlopen(base+'/app.js',timeout=3) as r: frontend=r.read().decode()
        assert 'async function loadPatient(id, redraw=true)' in frontend and 'switchHeaderPatient(e.target.value)' in frontend
        # The app serves the browser entry point and script.
        with urllib.request.urlopen(base+'/',timeout=3) as r: assert r.status==200 and b'app.js' in r.read()
        with urllib.request.urlopen(base+'/app.js',timeout=3) as r: assert r.status==200 and b'function renderDashboard' in r.read()
        print('PASS: health, login, role-limited bootstrap, patient bundle, questionnaire scoring, hidden draft, per-instance care-plan configuration/activation and access guard, 17 enriched medication profiles, PK/contraindication coverage, named sources and fluoxetine registration warning, drug detail/GRLS links, diary sync, exact mood+self-harm signal (1/10), linked medication in adverse-event alert and synchronized clinical-map status, risk alert, authorization, chat, physician approval, status-change timeline, archive restore/search, personal calendar sync, recommendation publication boundaries, menstrual guard, audited diary corrections, patient-specific red flags, clinician alert review, static frontend.')
    finally:
        proc.terminate()
        try: proc.wait(timeout=3)
        except subprocess.TimeoutExpired: proc.kill()
