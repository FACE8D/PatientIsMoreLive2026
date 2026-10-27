"""FHIR R4 interchange and a minimal DICOM Basic Text SR Part-10 writer.

The generated SR uses local 99CLINIC coding for mental-health workflow concepts.
Destination PACS/viewer conformance must be tested before production use.
"""
from __future__ import annotations
import json, hashlib, re, struct, uuid
from datetime import datetime, timezone
from typing import Any

DICOM_SR_BASIC_TEXT = '1.2.840.10008.5.1.4.1.1.88.11'
DICOM_EXPLICIT_VR_LE = '1.2.840.10008.1.2.1'
IMPLEMENTATION_UID = '2.25.329800735698586629295641978511506172918'


def new_uid() -> str:
    return '2.25.' + str(uuid.uuid4().int)


def _tag(tag: tuple[int, int]) -> bytes:
    return struct.pack('<HH', *tag)


def _pad(vr: str, value: bytes) -> bytes:
    if len(value) % 2:
        value += b'\x00' if vr == 'UI' else b' '
    return value


def _encode_value(vr: str, value: Any) -> bytes:
    if isinstance(value, bytes): raw = value
    elif vr == 'UL': raw = struct.pack('<I', int(value))
    elif vr == 'US': raw = struct.pack('<H', int(value))
    elif vr == 'SQ': raw = bytes(value)
    else: raw = str(value if value is not None else '').encode('utf-8')
    return _pad(vr, raw)


def _elem(tag: tuple[int, int], vr: str, value: Any) -> bytes:
    raw = _encode_value(vr, value)
    if vr in {'OB','OD','OF','OL','OV','OW','SQ','UC','UR','UT','UN'}:
        return _tag(tag) + vr.encode('ascii') + b'\x00\x00' + struct.pack('<I', len(raw)) + raw
    if len(raw) > 65535:
        raise ValueError(f'DICOM short-VR value too long for {tag}: {len(raw)}')
    return _tag(tag) + vr.encode('ascii') + struct.pack('<H', len(raw)) + raw


def _item(elements: list[bytes]) -> bytes:
    body = b''.join(elements)
    return _tag((0xFFFE,0xE000)) + struct.pack('<I', len(body)) + body


def _seq(items: list[bytes]) -> bytes:
    # Callers pass already encoded DICOM Item (FFFE,E000) values.
    return b''.join(items)


def _code_item(value: str, scheme: str, meaning: str) -> bytes:
    return _item([
        _elem((0x0008,0x0100),'SH',value),
        _elem((0x0008,0x0102),'SH',scheme),
        _elem((0x0008,0x0104),'LO',meaning[:64]),
    ])


def _content_item(title: str, text: str, code_value: str) -> bytes:
    code_seq = _seq([_code_item(code_value, '99CLINIC', title[:64])])
    body = [
        _elem((0x0040,0xA010),'CS','CONTAINS'),
        _elem((0x0040,0xA040),'CS','TEXT'),
        _elem((0x0040,0xA043),'SQ',code_seq),
        _elem((0x0040,0xA160),'UT',str(text)[:12000]),
    ]
    return _item(body)


def _format_report_lines(report: dict[str, Any]) -> list[tuple[str,str,str]]:
    lines=[]
    def add(title, value, code):
        if value is None or value == '' or value == []: return
        if isinstance(value,(dict,list)): value=json.dumps(value,ensure_ascii=False,indent=2)
        lines.append((title,str(value),code))
    add('Тип документа','Клиническое наблюдение / отчёт из системы сопровождения','D0001')
    add('Статус верификации','Подтверждено врачом' if report.get('verified') else 'Неподтверждённый черновой отчёт','D0002')
    add('Дата оценки',report.get('assessed_at'),'D0003')
    add('Клиническое резюме',report.get('summary'),'D0004')
    add('Клиническая оценка',report.get('assessment'),'D0005')
    add('Результаты шкал',report.get('questionnaire_results'),'D0006')
    add('Динамика дневников',report.get('diary_summary'),'D0007')
    add('Активные планы ведения',report.get('care_plans'),'D0008')
    add('Назначения (только подтверждённые)',report.get('medication_plans'),'D0009')
    add('Нежелательные реакции',report.get('adverse_events'),'D0010')
    add('Сигналы безопасности',report.get('red_flags'),'D0011')
    add('Договорённости и последующее наблюдение',report.get('follow_up'),'D0012')
    add('Ограничение интерпретации','Этот SR экспортирует сохранённые сведения и не создаёт нового диагноза. Интерпретация и любые клинические действия остаются ответственностью медицинского специалиста.','D0013')
    return lines


def build_dicom_basic_text_sr(patient: dict[str,Any], report: dict[str,Any], *, verified: bool=False) -> bytes:
    """Create a DICOM Part-10 Basic Text SR with defined-length sequences/items."""
    now=datetime.now(timezone.utc)
    date=now.strftime('%Y%m%d'); tm=now.strftime('%H%M%S.%f')[:13]
    sop_uid=new_uid(); study_uid=str(report.get('study_instance_uid') or new_uid()); series_uid=new_uid()
    patient_id=str(patient.get('external_id') or patient.get('patient_id') or patient.get('id') or 'LOCAL')[:64]
    name=str(patient.get('full_name') or patient.get('name') or 'Unknown')
    birth=str(patient.get('birth_date') or '').replace('-','')[:8]
    sex_map={'female':'F','male':'M','other':'O','not_specified':'','unknown':''}
    sex=sex_map.get(str(patient.get('sex','not_specified')).lower(),'')

    # File Meta Information Group Length is calculated after the other meta elements.
    meta_without_length = b''.join([
      _elem((0x0002,0x0001),'OB',b'\x00\x01'),
      _elem((0x0002,0x0002),'UI',DICOM_SR_BASIC_TEXT),
      _elem((0x0002,0x0003),'UI',sop_uid),
      _elem((0x0002,0x0010),'UI',DICOM_EXPLICIT_VR_LE),
      _elem((0x0002,0x0012),'UI',IMPLEMENTATION_UID),
      _elem((0x0002,0x0013),'SH','CLINIC_SR_1'),
    ])
    meta=_elem((0x0002,0x0000),'UL',len(meta_without_length))+meta_without_length

    content_items=[]
    for i,(title,text,code) in enumerate(_format_report_lines({**report,'verified':verified}),1):
        content_items.append(_content_item(title,text,code))
    content_sequence=_seq(content_items)
    root_code=_seq([_code_item('D0000','99CLINIC','Clinical follow-up report')])
    dataset_elems=[
      _elem((0x0008,0x0005),'CS','ISO_IR 192'),
      _elem((0x0008,0x0016),'UI',DICOM_SR_BASIC_TEXT),
      _elem((0x0008,0x0018),'UI',sop_uid),
      _elem((0x0008,0x0020),'DA',date),
      _elem((0x0008,0x0023),'DA',date),
      _elem((0x0008,0x0030),'TM',tm),
      _elem((0x0008,0x0033),'TM',tm),
      _elem((0x0008,0x0060),'CS','SR'),
      _elem((0x0008,0x0070),'LO','Clinic Companion'),
      _elem((0x0008,0x1030),'LO','Clinical follow-up'),
      _elem((0x0008,0x103E),'LO','Clinical summary (Basic Text SR)'),
      _elem((0x0010,0x0010),'PN',name),
      _elem((0x0010,0x0020),'LO',patient_id),
      _elem((0x0010,0x0030),'DA',birth),
      _elem((0x0010,0x0040),'CS',sex),
      _elem((0x0020,0x000D),'UI',study_uid),
      _elem((0x0020,0x000E),'UI',series_uid),
      _elem((0x0020,0x0010),'SH',str(report.get('study_id') or 'CLINIC')),
      _elem((0x0020,0x0011),'IS','1'),
      _elem((0x0020,0x0013),'IS','1'),
      _elem((0x0040,0xA040),'CS','CONTAINER'),
      _elem((0x0040,0xA043),'SQ',root_code),
      _elem((0x0040,0xA050),'CS','SEPARATE'),
      _elem((0x0040,0xA491),'CS','COMPLETE'),
      _elem((0x0040,0xA493),'CS','VERIFIED' if verified else 'UNVERIFIED'),
      _elem((0x0040,0xA496),'CS','FINAL' if verified else 'PRELIMINARY'),
      _elem((0x0040,0xA730),'SQ',content_sequence),
    ]
    dataset=b''.join(sorted(dataset_elems,key=lambda x: (struct.unpack('<HH',x[:4])[0],struct.unpack('<HH',x[:4])[1])))
    return b'\x00'*128+b'DICM'+meta+dataset


def validate_basic_text_sr(data: bytes) -> dict[str,Any]:
    if len(data)<160 or data[128:132]!=b'DICM': raise ValueError('Missing DICOM Part-10 preamble')
    i=132; found={}; meta_end=None
    while i+8<=len(data):
        group,elem=struct.unpack('<HH',data[i:i+4]); vr=data[i+4:i+6].decode('ascii','replace')
        if group!=0x0002: break
        if vr in {'OB','OD','OF','OL','OV','OW','SQ','UC','UR','UT','UN'}:
            length=struct.unpack('<I',data[i+8:i+12])[0]; start=i+12
        else:
            length=struct.unpack('<H',data[i+6:i+8])[0]; start=i+8
        raw=data[start:start+length]
        if len(raw)!=length: raise ValueError('Truncated DICOM meta element')
        found[(group,elem)]=raw.rstrip(b'\x00 ')
        i=start+length
    needed={(0x0002,0x0002),(0x0002,0x0003),(0x0002,0x0010)}
    if not needed.issubset(found): raise ValueError('Incomplete DICOM file meta information')
    if found[(0x0002,0x0002)].decode() != DICOM_SR_BASIC_TEXT: raise ValueError('Unexpected SOP Class UID')
    if found[(0x0002,0x0010)].decode() != DICOM_EXPLICIT_VR_LE: raise ValueError('Unexpected transfer syntax')
    return {'valid_part10':True,'sop_class_uid':found[(0x0002,0x0002)].decode(),'sop_instance_uid':found[(0x0002,0x0003)].decode(),'transfer_syntax_uid':found[(0x0002,0x0010)].decode(),'byte_length':len(data)}


def _fhir_id(resource_type: str, local_id: Any) -> str:
    base=re.sub(r'[^A-Za-z0-9\-.]', '-', f'{resource_type.lower()}-{local_id}')
    return base[:64] or str(uuid.uuid4())


def _entry(resource: dict[str,Any]) -> dict[str,Any]:
    return {'fullUrl':'urn:uuid:'+str(uuid.uuid4()),'resource':resource}


def to_fhir_r4_bundle(patient: dict[str,Any], bundle: dict[str,Any], *, assessment: dict[str,Any]|None=None) -> dict[str,Any]:
    """Build a patient-scoped FHIR R4 Bundle collection using stored data only."""
    pid=patient.get('id'); patient_id=_fhir_id('Patient',pid)
    patient_res={'resourceType':'Patient','id':patient_id,'active':True,'identifier':[{'system':'urn:clinic-companion:patient-id','value':str(pid)}],
      'name':[{'text':patient.get('full_name') or patient.get('name') or 'Unknown'}]}
    birth=patient.get('birth_date')
    if birth: patient_res['birthDate']=birth
    sex={'female':'female','male':'male','other':'other','not_specified':'unknown'}.get(patient.get('sex'),'unknown')
    patient_res['gender']=sex
    pat_ent=_entry(patient_res); pat_ref=pat_ent['fullUrl']; entries=[pat_ent]
    for r in bundle.get('results',[]):
        answers=r.get('answers') or {}
        items=[]
        for qid,value in answers.items():
            if isinstance(value,dict): val=json.dumps(value,ensure_ascii=False)
            elif isinstance(value,bool): val='true' if value else 'false'
            else: val=str(value)
            items.append({'linkId':str(qid),'answer':[{'valueString':val}]})
        qr={'resourceType':'QuestionnaireResponse','id':_fhir_id('QR',r.get('id')),'status':'completed','subject':{'reference':pat_ref},
            'authored':r.get('created_at'),'item':items,'extension':[{'url':'urn:clinic-companion:questionnaire-version','valueString':str(r.get('version',''))},{'url':'urn:clinic-companion:questionnaire-id','valueString':str(r.get('questionnaire_id',''))}]}
        entries.append(_entry(qr))
        sc=r.get('score') or {}
        if sc.get('type')=='sum' and sc.get('total') is not None:
            obs={'resourceType':'Observation','id':_fhir_id('Observation',r.get('id')),'status':'final','subject':{'reference':pat_ref},
                 'effectiveDateTime':r.get('created_at'),'code':{'coding':[{'system':'urn:clinic-companion:questionnaire','code':str(r.get('questionnaire_id','unknown'))}],'text':r.get('questionnaire_title')},
                 'valueInteger':int(sc['total']),'note':[{'text':'Screening/monitoring metric; not a diagnosis.'}]}
            if sc.get('band'): obs['interpretation']=[{'text':sc['band'].get('label','')}]
            entries.append(_entry(obs))
    for e in bundle.get('entries',[]):
        data=e.get('data') or {}
        for field,code,label in [('mood','mood','Mood self-rating'),('sleep_hours','sleep-hours','Sleep duration')]:
            value=data.get(field)
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                obs={'resourceType':'Observation','id':_fhir_id('Obs',f'{e.get("id")}-{code}'),'status':'final','subject':{'reference':pat_ref},
                  'effectiveDateTime':e.get('entry_date'),'code':{'coding':[{'system':'urn:clinic-companion:diary','code':code}],'text':label},
                  'valueQuantity':{'value':value,'unit':'/10' if field=='mood' else 'h','system':'http://unitsofmeasure.org','code':'1' if field=='mood' else 'h'},
                  'note':[{'text':'Patient-reported diary entry.'}]}
                entries.append(_entry(obs))
    for m in bundle.get('medication_plans',[]):
        if m.get('status')=='draft': continue
        status={'active':'active','paused':'on-hold','stopped':'stopped'}.get(m.get('status'),'unknown')
        med={'resourceType':'MedicationRequest','id':_fhir_id('MedicationRequest',m.get('id')),'status':status,'intent':'order','subject':{'reference':pat_ref},
             'medicationCodeableConcept':{'text':m.get('drug_name')},'authoredOn':m.get('created_at'),
             'dosageInstruction':[{'text':m.get('regimen') or 'See attached clinician-approved plan.'}],
             'note':[{'text':(m.get('notes') or '')+' Schedule times: '+', '.join(m.get('times') or [])}]}
        entries.append(_entry(med))
    for cp in bundle.get('care_plans',[]):
        if cp.get('status')=='draft': continue
        step_list=cp.get('plan',{}).get('steps',[])
        fhirstatus={'active':'active','paused':'on-hold','completed':'completed','stopped':'revoked'}.get(cp.get('status'),'draft')
        care={'resourceType':'CarePlan','id':_fhir_id('CarePlan',cp.get('id')),'status':fhirstatus,'intent':'plan','subject':{'reference':pat_ref},
              'title':cp.get('title'),'description':cp.get('plan',{}).get('summary',''),
              'activity':[{'detail':{'status':{'pending':'not-started','in_progress':'in-progress','completed':'completed','skipped':'not-started'}.get(s.get('status'),'not-started'),'description':s.get('title','')+' — '+s.get('description','')}} for s in step_list]}
        entries.append(_entry(care))
    for ev in bundle.get('adverse_events',[]):
        if ev.get('reporter_id') is None: pass
        ae={'resourceType':'AdverseEvent','id':_fhir_id('AdverseEvent',ev.get('id')),'actuality':'actual','status':'completed' if ev.get('review_status')=='closed' else 'in-progress',
            'subject':{'reference':pat_ref},'date':ev.get('onset_at') or ev.get('created_at'),'event':{'text':'Patient-reported suspected medication adverse event'},
            'seriousness':{'text':'serious' if ev.get('serious') else ev.get('severity','unknown')},'outcome':{'text':ev.get('outcome') or 'unknown'},
            'note':[{'text':ev.get('description','')+' Symptoms: '+', '.join(ev.get('symptoms') or [])+'; action: '+str(ev.get('action_taken') or '')}]}
        entries.append(_entry(ae))
    if assessment:
        report_text=str(assessment.get('summary') or assessment.get('plan_notes') or 'Clinical follow-up report')
        dr={'resourceType':'DiagnosticReport','id':_fhir_id('DiagnosticReport',assessment.get('id')),'status':'final' if assessment.get('signed_at') else 'preliminary',
            'code':{'coding':[{'system':'urn:clinic-companion:report','code':'clinical-follow-up'}],'text':'Clinical follow-up report'},
            'subject':{'reference':pat_ref},'effectiveDateTime':assessment.get('assessed_at') or assessment.get('created_at'),'conclusion':report_text,
            'note':[{'text':'This export reports stored observations; it does not create an autonomous diagnosis.'}]}
        entries.append(_entry(dr))
    for study in bundle.get('imaging_studies',[]):
        study_uid=study.get('study_uid')
        if not study_uid: continue
        im={'resourceType':'ImagingStudy','id':_fhir_id('ImagingStudy',study.get('id')),'status':'available','subject':{'reference':pat_ref},
            'identifier':[{'system':'urn:dicom:uid','value':'urn:oid:'+study_uid}],
            'started':(study.get('study_date')+'T00:00:00Z') if study.get('study_date') and len(study.get('study_date'))==10 else study.get('study_date'),
            'description':study.get('description') or 'Imported imaging study reference','numberOfSeries':study.get('number_of_series') or None,
            'numberOfInstances':study.get('number_of_instances') or None,'note':[{'text':'Only study metadata/reference is stored here; DICOM pixel data remain in the linked PACS/DICOMweb store.'}]}
        if study.get('modality'): im['modality']=[{'system':'http://dicom.nema.org/resources/ontology/DCM','code':study['modality']}]
        im={k:v for k,v in im.items() if v is not None}
        entries.append(_entry(im))
    return {'resourceType':'Bundle','id':str(uuid.uuid4()),'type':'collection','timestamp':datetime.now(timezone.utc).isoformat(),'entry':entries}


def resource_external_id(resource: dict[str,Any]) -> str:
    return str(resource.get('id') or resource.get('identifier',[{}])[0].get('value') or hashlib.sha256(json.dumps(resource,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
