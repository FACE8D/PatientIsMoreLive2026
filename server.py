#!/usr/bin/env python3
"""Local-first patient monitoring MVP. Python standard library only."""
from __future__ import annotations
import os, json, re, hmac, hashlib, secrets, sqlite3, mimetypes, csv, io, base64, uuid
from pathlib import Path
from datetime import datetime, date, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
from interoperability import build_dicom_basic_text_sr, validate_basic_text_sr, to_fhir_r4_bundle, resource_external_id

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'
DATA = BASE / 'data'
QDIR = DATA / 'questionnaires'
DB_PATH = Path(os.environ.get('CLINIC_DB_PATH', str(DATA / 'clinic.db'))).resolve()
HOST = os.environ.get('CLINIC_HOST', '127.0.0.1')
PORT = int(os.environ.get('CLINIC_PORT', '8765'))
COOKIE_NAME = 'care_session'
SESSION_HOURS = 12
DEMO_MODE = os.environ.get('CLINIC_DEMO_MODE', '1') != '0'


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_date():
    return date.today().isoformat()


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 15000')
    return conn


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 310_000)
    return salt.hex() + '$' + digest.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt_hex, digest_hex = encoded.split('$', 1)
        calc = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt_hex), 310_000).hex()
        return hmac.compare_digest(calc, digest_hex)
    except Exception:
        return False


def create_schema():
    conn = get_db()
    try:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          email TEXT NOT NULL UNIQUE,
          display_name TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('doctor','patient')),
          password_hash TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          must_change_password INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS patients (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
          doctor_user_id INTEGER NOT NULL REFERENCES users(id),
          full_name TEXT NOT NULL,
          birth_date TEXT,
          sex TEXT NOT NULL DEFAULT 'not_specified',
          phone TEXT,
          notes TEXT NOT NULL DEFAULT '',
          menstrual_enabled INTEGER NOT NULL DEFAULT 0,
          archived INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf_token TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          author_user_id INTEGER NOT NULL REFERENCES users(id),
          entry_type TEXT NOT NULL,
          entry_date TEXT NOT NULL,
          data_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questionnaire_results (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          completed_by INTEGER NOT NULL REFERENCES users(id),
          questionnaire_id TEXT NOT NULL,
          questionnaire_title TEXT NOT NULL,
          version TEXT NOT NULL,
          answers_json TEXT NOT NULL,
          score_json TEXT NOT NULL,
          risk_flag INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS appointments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          starts_at TEXT NOT NULL,
          ends_at TEXT,
          kind TEXT NOT NULL DEFAULT 'appointment',
          title TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'scheduled',
          created_by INTEGER NOT NULL REFERENCES users(id),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS visits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          visit_date TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'Приём',
          notes TEXT NOT NULL DEFAULT '',
          followup_date TEXT,
          author_user_id INTEGER NOT NULL REFERENCES users(id),
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS medication_plans (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          drug_id TEXT NOT NULL,
          drug_name TEXT NOT NULL,
          regimen TEXT NOT NULL,
          times_json TEXT NOT NULL DEFAULT '[]',
          start_date TEXT NOT NULL,
          end_date TEXT,
          notes TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','paused','stopped')),
          created_by INTEGER NOT NULL REFERENCES users(id),
          approved_by INTEGER REFERENCES users(id),
          approved_at TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS medication_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          plan_id INTEGER NOT NULL REFERENCES medication_plans(id),
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          scheduled_date TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('taken','skipped','side_effect')),
          side_effects TEXT NOT NULL DEFAULT '',
          notes TEXT NOT NULL DEFAULT '',
          logged_by INTEGER NOT NULL REFERENCES users(id),
          created_at TEXT NOT NULL,
          UNIQUE(plan_id, patient_id, scheduled_date)
        );
        CREATE TABLE IF NOT EXISTS recommendations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          body TEXT NOT NULL,
          visibility TEXT NOT NULL DEFAULT 'patient',
          status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('draft','published','archived')),
          created_by INTEGER NOT NULL REFERENCES users(id),
          approved_by INTEGER REFERENCES users(id),
          created_at TEXT NOT NULL,
          approved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          sender_user_id INTEGER NOT NULL REFERENCES users(id),
          body TEXT NOT NULL,
          read_at TEXT,
          created_at TEXT NOT NULL,
          edited_at TEXT,
          deleted_at TEXT,
          deleted_by INTEGER REFERENCES users(id),
          last_modified_by INTEGER REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS message_revisions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_id INTEGER NOT NULL REFERENCES messages(id),
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          actor_user_id INTEGER NOT NULL REFERENCES users(id),
          action TEXT NOT NULL CHECK(action IN ('edit','delete')),
          previous_body TEXT NOT NULL,
          new_body TEXT NOT NULL DEFAULT '',
          reason TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alerts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          source_type TEXT NOT NULL,
          source_id INTEGER,
          severity TEXT NOT NULL CHECK(severity IN ('info','review','urgent','critical')),
          title TEXT NOT NULL,
          detail TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','acknowledged','resolved')),
          created_at TEXT NOT NULL,
          acknowledged_by INTEGER REFERENCES users(id),
          acknowledged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS patient_red_flag_overrides (
          patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
          rule_id TEXT NOT NULL REFERENCES red_flag_rules(id) ON DELETE CASCADE,
          enabled INTEGER NOT NULL DEFAULT 1,
          severity TEXT NOT NULL DEFAULT 'review' CHECK(severity IN ('info','review','urgent','critical')),
          recipient TEXT NOT NULL DEFAULT 'doctor' CHECK(recipient IN ('doctor','patient','both','care_team')),
          updated_by INTEGER REFERENCES users(id),
          updated_at TEXT NOT NULL,
          PRIMARY KEY(patient_id,rule_id)
        );
        CREATE TABLE IF NOT EXISTS alert_reviews (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          alert_id INTEGER NOT NULL REFERENCES alerts(id),
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          reviewer_user_id INTEGER NOT NULL REFERENCES users(id),
          significance TEXT NOT NULL,
          reaction TEXT NOT NULL DEFAULT '',
          followup TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          actor_user_id INTEGER REFERENCES users(id),
          action TEXT NOT NULL,
          target_type TEXT NOT NULL,
          target_id TEXT,
          detail TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clinical_assessments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          visit_id INTEGER REFERENCES visits(id),
          assessed_at TEXT NOT NULL,
          mental_state_json TEXT NOT NULL,
          summary TEXT NOT NULL DEFAULT '',
          plan_notes TEXT NOT NULL DEFAULT '',
          assessor_user_id INTEGER NOT NULL REFERENCES users(id),
          signed_by INTEGER REFERENCES users(id),
          signed_at TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS adverse_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          medication_plan_id INTEGER REFERENCES medication_plans(id),
          reported_by INTEGER NOT NULL REFERENCES users(id),
          onset_at TEXT NOT NULL,
          symptoms_json TEXT NOT NULL,
          severity TEXT NOT NULL CHECK(severity IN ('mild','moderate','severe','life_threatening','unknown')),
          serious INTEGER NOT NULL DEFAULT 0,
          description TEXT NOT NULL DEFAULT '',
          action_taken TEXT NOT NULL DEFAULT '',
          outcome TEXT NOT NULL DEFAULT '',
          clinician_assessment TEXT NOT NULL DEFAULT '',
          review_status TEXT NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending','reviewed','closed')),
          reviewed_by INTEGER REFERENCES users(id),
          reviewed_at TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER REFERENCES patients(id),
          recipient_user_id INTEGER NOT NULL REFERENCES users(id),
          rule_id TEXT,
          source_type TEXT NOT NULL,
          source_id TEXT,
          severity TEXT NOT NULL DEFAULT 'info' CHECK(severity IN ('info','review','urgent','critical')),
          title TEXT NOT NULL,
          body TEXT NOT NULL,
          read_at TEXT,
          delivery_status TEXT NOT NULL DEFAULT 'in_app',
          push_sent_at TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS red_flag_rules (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          source_type TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          severity TEXT NOT NULL DEFAULT 'review' CHECK(severity IN ('info','review','urgent','critical')),
          recipient TEXT NOT NULL DEFAULT 'doctor' CHECK(recipient IN ('doctor','patient','both','care_team')),
          rule_json TEXT NOT NULL,
          updated_by INTEGER REFERENCES users(id),
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS patient_preferences (
          patient_id INTEGER PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE,
          chat_enabled INTEGER NOT NULL DEFAULT 1,
          chat_mode TEXT NOT NULL DEFAULT 'async' CHECK(chat_mode IN ('off','async','standard')),
          notification_preferences_json TEXT NOT NULL DEFAULT '{}',
          updated_by INTEGER REFERENCES users(id),
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS care_plans (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          scheme_id TEXT NOT NULL,
          scheme_version TEXT NOT NULL,
          title TEXT NOT NULL,
          plan_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','paused','completed','stopped')),
          start_date TEXT NOT NULL,
          review_date TEXT,
          notes TEXT NOT NULL DEFAULT '',
          created_by INTEGER NOT NULL REFERENCES users(id),
          approved_by INTEGER REFERENCES users(id),
          approved_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS imaging_studies (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          study_uid TEXT NOT NULL,
          modality TEXT NOT NULL DEFAULT 'OT',
          study_date TEXT,
          accession_number TEXT NOT NULL DEFAULT '',
          description TEXT NOT NULL DEFAULT '',
          number_of_series INTEGER,
          number_of_instances INTEGER,
          endpoint TEXT NOT NULL DEFAULT '',
          source_system TEXT NOT NULL DEFAULT 'manual_manifest',
          metadata_json TEXT NOT NULL DEFAULT '{}',
          imported_by INTEGER NOT NULL REFERENCES users(id),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(patient_id, study_uid)
        );
        CREATE TABLE IF NOT EXISTS clinical_documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
          uploaded_by INTEGER NOT NULL REFERENCES users(id),
          title TEXT NOT NULL DEFAULT '',
          file_name TEXT NOT NULL,
          mime_type TEXT NOT NULL DEFAULT 'application/pdf',
          size_bytes INTEGER NOT NULL,
          sha256 TEXT NOT NULL,
          content BLOB NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_clinical_documents_patient ON clinical_documents(patient_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS external_imports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          patient_id INTEGER NOT NULL REFERENCES patients(id),
          source_system TEXT NOT NULL,
          resource_type TEXT NOT NULL,
          external_id TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          target_table TEXT NOT NULL,
          target_id TEXT,
          imported_by INTEGER NOT NULL REFERENCES users(id),
          imported_at TEXT NOT NULL,
          UNIQUE(patient_id, source_system, resource_type, external_id)
        );
        CREATE TABLE IF NOT EXISTS push_subscriptions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          endpoint TEXT NOT NULL UNIQUE,
          subscription_json TEXT NOT NULL,
          platform TEXT NOT NULL DEFAULT 'web',
          created_at TEXT NOT NULL,
          last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS demo_portrait_seeds (
          patient_id INTEGER PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE,
          case_id TEXT NOT NULL UNIQUE,
          fixture_version TEXT NOT NULL,
          seeded_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mobile_push_tokens (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token TEXT NOT NULL UNIQUE,
          platform TEXT NOT NULL DEFAULT 'android',
          created_at TEXT NOT NULL,
          last_seen TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_patients_doctor ON patients(doctor_user_id, archived);
        CREATE INDEX IF NOT EXISTS idx_entries_patient_date ON entries(patient_id, entry_date DESC);
        CREATE INDEX IF NOT EXISTS idx_results_patient_date ON questionnaire_results(patient_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_patient_date ON messages(patient_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status, severity, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_user_id, read_at, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_assessments_patient ON clinical_assessments(patient_id, assessed_at DESC);
        CREATE INDEX IF NOT EXISTS idx_adverse_patient ON adverse_events(patient_id, review_status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_careplans_patient ON care_plans(patient_id, status, created_at DESC);
        ''')
        # Upgrade existing local databases without deleting or recreating messages.
        message_columns={row['name'] for row in conn.execute('PRAGMA table_info(messages)').fetchall()}
        for column, declaration in (
            ('edited_at','TEXT'),
            ('deleted_at','TEXT'),
            ('deleted_by','INTEGER REFERENCES users(id)'),
            ('last_modified_by','INTEGER REFERENCES users(id)'),
        ):
            if column not in message_columns:
                conn.execute(f'ALTER TABLE messages ADD COLUMN {column} {declaration}')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_message_revisions_message ON message_revisions(message_id, created_at DESC, id DESC)')
        conn.commit()
    finally:
        conn.close()


def load_json(path: Path, default=None):
    if not path.exists(): return default
    return json.loads(path.read_text(encoding='utf-8'))



def load_medications():
    payload=load_json(DATA/'medications.json', [])
    return payload.get('medications', []) if isinstance(payload,dict) else payload


def load_treatment_scheme(scheme_id):
    if not re.fullmatch(r'[a-z0-9_-]{2,64}', str(scheme_id or '')): raise ValueError('Некорректный ID схемы')
    path=DATA/'treatment_schemes'/f'{scheme_id}.json'
    if not path.exists(): raise LookupError('Схема ведения не найдена')
    return json.loads(path.read_text(encoding='utf-8'))


def validate_scheme_configuration(scheme, configuration, activating=False):
    """Validate per-patient/per-plan editable values against the versioned scheme schema."""
    if configuration is None:
        configuration = {}
    if not isinstance(configuration, dict):
        raise ValueError('Параметры схемы должны быть объектом JSON.')
    fields = scheme.get('configuration_fields', [])
    allowed = {str(f.get('id')): f for f in fields if f.get('id')}
    unknown = sorted(set(configuration) - set(allowed))
    if unknown:
        raise ValueError('Неизвестные параметры схемы: ' + ', '.join(unknown))
    clean = {}
    for fid, spec in allowed.items():
        raw = configuration.get(fid, None)
        typ = spec.get('type', 'text')
        if typ == 'checkbox':
            if raw is not None and not isinstance(raw, bool):
                raise ValueError(f'Параметр «{spec.get("label", fid)}» должен быть Да/Нет.')
            val = bool(raw) if raw is not None else False
        elif typ == 'number':
            if raw in (None, ''):
                val = None
            elif isinstance(raw, bool) or not isinstance(raw, (int, float)):
                try: val = float(raw)
                except (TypeError, ValueError): raise ValueError(f'Параметр «{spec.get("label", fid)}» должен быть числом.')
            else: val = raw
            if val is not None:
                if spec.get('min') is not None and val < spec['min']: raise ValueError(f'Параметр «{spec.get("label", fid)}»: минимум {spec["min"]}.')
                if spec.get('max') is not None and val > spec['max']: raise ValueError(f'Параметр «{spec.get("label", fid)}»: максимум {spec["max"]}.')
                if isinstance(val, float) and val.is_integer(): val = int(val)
        elif typ == 'select':
            if raw in (None, ''): val = ''
            else:
                if not isinstance(raw, str): raise ValueError(f'Параметр «{spec.get("label", fid)}» имеет неверный формат.')
                if raw not in spec.get('options', []): raise ValueError(f'Недопустимый вариант для «{spec.get("label", fid)}».')
                val = raw
        elif typ == 'date':
            val = '' if raw is None else str(raw)
            if val:
                try: date.fromisoformat(val)
                except ValueError: raise ValueError(f'Параметр «{spec.get("label", fid)}» должен быть датой ГГГГ-ММ-ДД.')
        elif typ in ('text', 'textarea'):
            if raw is None: val = ''
            elif not isinstance(raw, str): raise ValueError(f'Параметр «{spec.get("label", fid)}» должен быть текстом.')
            else: val = raw.strip()
            max_len = int(spec.get('max_length', 5000 if typ == 'textarea' else 1000))
            if len(val) > max_len: raise ValueError(f'Параметр «{spec.get("label", fid)}» превышает {max_len} символов.')
        else:
            raise ValueError(f'Неизвестный тип параметра в схеме: {typ}.')
        if activating and spec.get('required') and val in (None, '', False):
            raise ValueError(f'Для активации заполните поле «{spec.get("label", fid)}».')
        if activating and spec.get('required_for_activation') and val is not True:
            raise ValueError(f'Для активации требуется подтверждение: «{spec.get("label", fid)}».')
        if raw is not None or typ == 'checkbox': clean[fid] = val
    return clean


def ensure_clinical_data():
    """Seed config/relations on first run without overwriting clinician-edited rules."""
    conn=get_db()
    try:
        rules=load_json(DATA/'red_flags.json',{}).get('rules',[])
        for r in rules:
            if not conn.execute('SELECT 1 FROM red_flag_rules WHERE id=?',(r['id'],)).fetchone():
                conn.execute('INSERT INTO red_flag_rules(id,title,source_type,enabled,severity,recipient,rule_json,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                  (r['id'],r['title'],r.get('source_type','system'),int(bool(r.get('enabled',True))),r.get('severity','review'),r.get('recipient','doctor'),json.dumps(r,ensure_ascii=False),utc_now()))
        pats=conn.execute('SELECT id FROM patients').fetchall()
        for patient in pats:
            conn.execute("INSERT OR IGNORE INTO patient_preferences(patient_id,chat_enabled,chat_mode,notification_preferences_json,updated_at) VALUES(?,1,'async','{}',?)",(patient['id'],utc_now()))
        conn.commit()
    finally: conn.close()


def get_active_flag_rules(conn, source_type=None, patient_id=None):
    sql='SELECT * FROM red_flag_rules WHERE 1=1'
    args=[]
    if source_type:
        sql+=' AND source_type=?'; args.append(source_type)
    rows=conn.execute(sql,args).fetchall()
    result=[]
    for row in rows:
        try: rule=json.loads(row['rule_json'])
        except Exception: rule={}
        rule.update({'id':row['id'],'title':row['title'],'source_type':row['source_type'],'enabled':bool(row['enabled']),'severity':row['severity'],'recipient':row['recipient']})
        if patient_id is not None:
            override=conn.execute('SELECT enabled,severity,recipient FROM patient_red_flag_overrides WHERE patient_id=? AND rule_id=?',(patient_id,row['id'])).fetchone()
            if override:
                rule.update({'enabled':bool(override['enabled']),'severity':override['severity'],'recipient':override['recipient']})
            elif not rule['enabled']:
                continue
        elif not rule['enabled']:
            continue
        if not rule['enabled']: continue
        result.append(rule)
    return result


def create_notification(conn, patient_id, recipient, source_type, source_id, severity, title, body, rule_id=None):
    patient=conn.execute('SELECT user_id,doctor_user_id FROM patients WHERE id=?',(patient_id,)).fetchone() if patient_id is not None else None
    if not patient: return []
    if recipient=='doctor': roles=[patient['doctor_user_id']]
    elif recipient=='patient': roles=[patient['user_id']]
    elif recipient=='both': roles=[patient['doctor_user_id'],patient['user_id']]
    elif recipient=='care_team': roles=[patient['doctor_user_id']]
    else: roles=[patient['doctor_user_id']]
    made=[]
    for uid in sorted(set(roles)):
        sid=str(source_id) if source_id is not None else None
        exists=conn.execute('SELECT id FROM notifications WHERE recipient_user_id=? AND source_type=? AND source_id IS ? AND title=? AND rule_id IS ?',(uid,source_type,sid,title,rule_id)).fetchone()
        if exists:
            made.append(exists['id']); continue
        cur=conn.execute('INSERT INTO notifications(patient_id,recipient_user_id,rule_id,source_type,source_id,severity,title,body,delivery_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
          (patient_id,uid,rule_id,source_type,sid,severity,title,body,'in_app',utc_now()))
        made.append(cur.lastrowid)
        try: send_web_push_if_configured(conn,cur.lastrowid,uid,title,body,{'patient_id':patient_id,'source_type':source_type,'source_id':sid})
        except Exception: pass
    return made


def apply_message_red_flags(conn, patient_id, message_id, body):
    text=body.casefold(); made=[]
    for rule in get_active_flag_rules(conn,'message_text',patient_id):
        matches=[p for p in rule.get('patterns',[]) if str(p).casefold() in text]
        if not matches: continue
        severity=rule.get('severity','urgent')
        title=rule.get('title','Сообщение требует клинической проверки')
        detail='Текстовое правило сработало по совпадению: '+', '.join(matches[:8])+'. Это технический флаг для прямого уточнения, не диагноз; возможны ложные совпадения.'
        create_alert(conn,patient_id,'message',message_id,severity,title,detail,recipient=rule.get('recipient','doctor'),rule_id=rule['id'])
        made.append(rule['id'])
    return made


def apply_entry_red_flags(conn, patient_id, entry_id, entry_type, payload):
    matched_rules=[]
    # A self-reported self-harm/suicidal-thought signal must not depend on a
    # configurable rule being enabled. Keep the alert tied to this exact entry.
    if entry_type == 'mood' and payload.get('self_harm_thoughts') is True:
        mood = payload.get('mood')
        sleep = payload.get('sleep_hours')
        detail = (f'Пациент отметил мысли о самоповреждении в дневнике настроения. '
                  f'Оценка настроения в этой же записи: {mood}/10. '
                  f'Сон: {sleep if sleep is not None else "не указан"} ч. '
                  'Нужен прямой контакт и клиническая оценка; не трактовать этот сигнал как диагноз.')
        create_alert(conn, patient_id, 'entry', entry_id, 'critical',
                     'Пациент отметил мысли о самоповреждении', detail,
                     recipient='both', rule_id='mandatory_mood_self_harm_safety')
        matched_rules.append('mandatory_mood_self_harm_safety')
    for rule in get_active_flag_rules(conn,'entry',patient_id):
        if rule.get('entry_type') not in (None,entry_type): continue
        threshold=rule.get('threshold','any')
        match=(threshold=='any' or (threshold=='self_harm_thoughts' and payload.get('self_harm_thoughts') is True) or (threshold=='severe' and payload.get('severity') in ('severe','life_threatening')))
        if not match: continue
        create_alert(conn,patient_id,'entry',entry_id,rule.get('severity','review'),rule.get('title','Запись требует клинического уточнения'),rule.get('detail') or 'Настроенное правило совпало с записью; требуется клиническое уточнение.',recipient=rule.get('recipient','doctor'),rule_id=rule['id'])
        matched_rules.append(rule['id'])
    return matched_rules


def apply_adverse_event_rules(conn, patient_id, event_id, severity, serious=False, symptoms=None):
    symptoms=set(symptoms or []); matched=[]
    severity_rank={'info':0,'review':1,'urgent':2,'critical':3}
    min_level='critical' if severity=='life_threatening' else 'urgent' if severity=='severe' or serious else 'review'
    # Clinician-configured rules are honoured, but a life-threatening report cannot be demoted below critical.
    for rule in get_active_flag_rules(conn,'adverse_event',patient_id):
        threshold=rule.get('threshold','any')
        applies=(threshold=='any' or (threshold=='severe' and (severity in ('severe','life_threatening') or serious)) or (threshold=='life_threatening' and severity=='life_threatening') or (threshold.startswith('symptom:') and threshold.split(':',1)[1] in symptoms))
        if not applies: continue
        sev=rule.get('severity','review')
        if severity_rank.get(min_level,1)>severity_rank.get(sev,1): sev=min_level
        recipient=rule.get('recipient','doctor')
        if severity=='life_threatening' and recipient=='patient': recipient='both'
        detail=(rule.get('detail') or 'Нежелательное явление требует клинической оценки.')+f' Уровень по сообщению пациента: {severity}; серьёзность отмечена: {"да" if serious else "нет"}; симптомы: {", ".join(sorted(symptoms)) or "не указаны"}.'
        detail += ' ' + adverse_event_medication_context(conn, patient_id, event_id)
        create_alert(conn,patient_id,'adverse_event',event_id,sev,rule.get('title','Нежелательная реакция требует оценки'),detail,recipient=recipient,rule_id=rule['id'])
        matched.append(rule['id'])
    if not matched and (severity in ('severe','life_threatening') or serious):
        detail='Базовое защитное правило: врач должен оценить реакцию; при непосредственной угрозе жизни требуется экстренная помощь. ' + adverse_event_medication_context(conn, patient_id, event_id)
        create_alert(conn,patient_id,'adverse_event',event_id,min_level,'Серьёзная нежелательная реакция требует оценки',detail,recipient='both',rule_id='mandatory_adverse_event_safety_floor')
    return matched


def adverse_event_medication_context(conn, patient_id, event_id):
    # Describe linked and current plans without implying causality.
    event = conn.execute('SELECT medication_plan_id FROM adverse_events WHERE id=? AND patient_id=?', (event_id, patient_id)).fetchone()
    linked_id = event['medication_plan_id'] if event else None
    linked = conn.execute('SELECT drug_name,regimen,status FROM medication_plans WHERE id=? AND patient_id=?', (linked_id, patient_id)).fetchone() if linked_id else None
    current = conn.execute('SELECT id,drug_name,regimen,status FROM medication_plans WHERE patient_id=? AND status IN (?,?,?) ORDER BY created_at DESC,id DESC', (patient_id,'active','paused','stopped')).fetchall()
    if linked:
        primary = f'Пациент связал реакцию с планом: {linked["drug_name"]} — {linked["regimen"] or "режим не указан"} (статус: {linked["status"]}).'
    else:
        primary = 'Пациент не указал конкретный препарат, связанный с реакцией; причинная связь не установлена.'
    if current:
        listed = '; '.join(f'{r["drug_name"]} — {r["regimen"] or "режим не указан"} ({r["status"]})' for r in current)
        return primary + ' Планы препаратов в карточке пациента: ' + listed + '.'
    return primary + ' В карточке нет текущих/исторических лекарственных планов.'


def apply_questionnaire_red_flags(conn, patient_id, result_id, qid, answers):
    made=[]
    for rule in get_active_flag_rules(conn,'questionnaire_answer',patient_id):
        if rule.get('questionnaire_id') not in (None,qid): continue
        matched=[]
        for item in rule.get('items',[]):
            if answers.get(item.get('question_id')) in item.get('values',[]): matched.append(item.get('question_id'))
        if not matched: continue
        title=rule.get('title','Ответ опросника требует клинического уточнения')
        detail=(rule.get('detail') or 'Ответ соответствует настроенному правилу; требуется прямое клиническое уточнение.')+' Пункты: '+', '.join(matched)+'. Совпадение не является диагнозом.'
        create_alert(conn,patient_id,'questionnaire',result_id,rule.get('severity','review'),title,detail,recipient=rule.get('recipient','doctor'),rule_id=rule['id'])
        made.append(rule['id'])
    return made


def patient_preferences(conn, patient_id):
    conn.execute('INSERT OR IGNORE INTO patient_preferences(patient_id,updated_at) VALUES(?,?)',(patient_id,utc_now()))
    row=conn.execute('SELECT * FROM patient_preferences WHERE patient_id=?',(patient_id,)).fetchone()
    return {'chat_enabled':bool(row['chat_enabled']),'chat_mode':row['chat_mode'],'notification_preferences':json.loads(row['notification_preferences_json'] or '{}'),'updated_at':row['updated_at']}


def _json_hash(value):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def source_exists(conn, patient_id, source_system, resource_type, external_id):
    return conn.execute('SELECT id FROM external_imports WHERE patient_id=? AND source_system=? AND resource_type=? AND external_id=?',(patient_id,source_system,resource_type,external_id)).fetchone()


def record_import(conn, patient_id, source_system, resource_type, external_id, content_hash, target_table, target_id, user_id):
    conn.execute('INSERT INTO external_imports(patient_id,source_system,resource_type,external_id,content_hash,target_table,target_id,imported_by,imported_at) VALUES(?,?,?,?,?,?,?,?,?)',
      (patient_id,source_system,resource_type,external_id,content_hash,target_table,str(target_id) if target_id is not None else None,user_id,utc_now()))

def ensure_demo_data():
    if not DEMO_MODE: return
    conn = get_db()
    try:
        doctor = conn.execute('SELECT id FROM users WHERE email=?', ('doctor@demo.local',)).fetchone()
        if not doctor:
            cur = conn.execute('INSERT INTO users(email,display_name,role,password_hash,active,created_at) VALUES(?,?,?,?,1,?)',
                ('doctor@demo.local','Доктор Демонстрационный','doctor',hash_password('DemoDoctor2026!'),utc_now()))
            doctor_id = cur.lastrowid
        else: doctor_id = doctor['id']
        pat_user = conn.execute('SELECT id FROM users WHERE email=?', ('patient@demo.local',)).fetchone()
        if not pat_user:
            cur = conn.execute('INSERT INTO users(email,display_name,role,password_hash,active,created_at) VALUES(?,?,?,?,1,?)',
                ('patient@demo.local','Мария Демонстрационная','patient',hash_password('DemoPatient2026!'),utc_now()))
            patient_user_id = cur.lastrowid
        else: patient_user_id = pat_user['id']
        profile = conn.execute('SELECT id FROM patients WHERE user_id=?', (patient_user_id,)).fetchone()
        if not profile:
            cur = conn.execute('''INSERT INTO patients(user_id,doctor_user_id,full_name,birth_date,sex,notes,menstrual_enabled,created_at)
                VALUES(?,?,?,?,?,?,?,?)''', (patient_user_id, doctor_id, 'Мария Демонстрационная', '1990-04-18', 'female',
                'Синтетический демонстрационный профиль. Не является реальной медицинской записью.', 1, utc_now()))
            patient_id = cur.lastrowid
            # Example entries and low-risk historical scores are clearly synthetic.
            for offset, mood, sleep, appetite in [(6,4,5.5,'снижен'),(5,5,6.0,'обычный'),(4,4,6.5,'обычный'),(3,6,7.0,'обычный'),(2,5,7.0,'снижен'),(1,6,7.5,'обычный'),(0,7,7.0,'обычный')]:
                d=(date.today()-timedelta(days=offset)).isoformat()
                payload={'mood':mood,'sleep_hours':sleep,'appetite':appetite,'notes':'Синтетическая демонстрационная запись.'}
                conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',
                    (patient_id,patient_user_id,'mood',d,json.dumps(payload,ensure_ascii=False),utc_now()))
            now = datetime.now().replace(hour=15,minute=30,second=0,microsecond=0).isoformat(timespec='minutes')
            conn.execute('INSERT INTO appointments(patient_id,starts_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
                (patient_id, now, 'appointment', 'Контрольный приём (демо)', 'Синтетическая демонстрационная запись.', 'scheduled', doctor_id, utc_now()))
            # One sample published recommendation, no drug regimen.
            conn.execute('INSERT INTO recommendations(patient_id,body,visibility,status,created_by,approved_by,created_at,approved_at) VALUES(?,?,?,?,?,?,?,?)',
                (patient_id,'Попробуйте выбрать одно небольшое посильное действие на день. Пропуск не является неудачей; обсудите трудности на следующем приёме. Это демонстрационный пример.', 'patient','published',doctor_id,doctor_id,utc_now(),utc_now()))
        conn.commit()
    finally: conn.close()


def log_audit(conn, actor, action, target_type, target_id=None, detail=''):
    conn.execute('INSERT INTO audit_log(actor_user_id,action,target_type,target_id,detail,created_at) VALUES(?,?,?,?,?,?)',
                 (actor, action, target_type, str(target_id) if target_id is not None else None, detail[:2000], utc_now()))


def serial(row):
    return dict(row) if row is not None else None


def user_public(user):
    return {'id':user['id'],'email':user['email'],'display_name':user['display_name'],'role':user['role'],
            'must_change_password':bool(user['must_change_password'])}


def get_questionnaire(qid):
    if not re.fullmatch(r'[a-z0-9_-]{2,40}', qid): raise ValueError('Некорректный идентификатор опросника')
    p=QDIR/f'{qid}.json'
    if not p.exists(): raise LookupError('Опросник не найден')
    return json.loads(p.read_text(encoding='utf-8'))


def questionnaire_catalog(role):
    result=[]
    for p in sorted(QDIR.glob('*.json')):
        d=json.loads(p.read_text(encoding='utf-8'))
        if role=='patient' and d['respondent']=='clinician': continue
        entry={k:d.get(k) for k in ('id','title','category','respondent','instruction','source','version','license_review_required','implementation_notes')}
        scoring=d.get('scoring',{}) or {}
        entry['scoring_type']=scoring.get('type')
        entry['interpretation_bands']=scoring.get('bands',[])
        entry['interpretation_groups']=scoring.get('groups',[])
        if scoring.get('type')=='sum':
            minima=[]; maxima=[]
            for question in d.get('questions',[]):
                if question.get('scored',True) and question.get('type','single')=='single':
                    vals=[]
                    for option in question.get('options',[]):
                        try: vals.append(int(option.get('value')))
                        except (TypeError,ValueError): pass
                    if vals: minima.append(min(vals)); maxima.append(max(vals))
            entry['score_range']={'min':sum(minima),'max':sum(maxima)} if minima else None
        elif scoring.get('type')=='groups_sum':
            entry['score_range']={'min':0,'max':sum(int(g.get('max',0)) for g in scoring.get('groups',[]))}
        elif scoring.get('type')=='scl90':
            entry['score_range']={'min':0,'max':4,'indices':['GSI: 0–4','PSI: 0–90','PDSI: 0–4']}
        else: entry['score_range']=None
        result.append(entry)
    return result


def patient_for_user(conn,user_id):
    return conn.execute('SELECT * FROM patients WHERE user_id=? AND archived=0',(user_id,)).fetchone()


def get_patient(conn,user,patient_id):
    try: pid=int(patient_id)
    except (TypeError,ValueError): raise ValueError('Некорректный идентификатор пациента')
    row=conn.execute('SELECT * FROM patients WHERE id=? AND archived=0',(pid,)).fetchone()
    if not row: raise LookupError('Пациент не найден')
    if user['role']=='doctor' and row['doctor_user_id']!=user['id']:
        raise PermissionError('Нет доступа к этому пациенту')
    if user['role']=='patient' and row['user_id']!=user['id']:
        raise PermissionError('Нет доступа к этому пациенту')
    return row


def patient_view(row):
    out=dict(row)
    out['menstrual_enabled']=bool(out['menstrual_enabled'])
    out.pop('user_id',None)
    out.pop('doctor_user_id',None)
    return out


def create_alert(conn, patient_id, source_type, source_id, severity, title, detail, *, recipient='doctor', rule_id=None):
    # Alerts and notifications are separate: alerts belong to the clinical record,
    # notifications are per-recipient delivery items. Existing alerts are not duplicated.
    existing=conn.execute('SELECT id FROM alerts WHERE source_type=? AND source_id IS ? AND patient_id=? AND title=?',
        (source_type,source_id,patient_id,title)).fetchone()
    if existing: alert_id=existing['id']
    else:
        cur=conn.execute('INSERT INTO alerts(patient_id,source_type,source_id,severity,title,detail,status,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (patient_id,source_type,source_id,severity,title,detail,'open',utc_now()))
        alert_id=cur.lastrowid
    create_notification(conn,patient_id,recipient,source_type,source_id,severity,title,detail,rule_id=rule_id)
    return alert_id


def _num(value, qid):
    if isinstance(value,bool): raise ValueError(f'Ответ {qid}: некорректное значение')
    try: return int(value)
    except (TypeError,ValueError): raise ValueError(f'Ответ {qid}: требуется числовой вариант')


def score_questionnaire(defn, answers):
    if not isinstance(answers,dict): raise ValueError('Ответы должны быть объектом')
    qmap={x['id']:x for x in defn['questions']}
    # Validate recognized questions, required answers, and allowed values server-side.
    for qid, qd in qmap.items():
        val=answers.get(qid)
        if val is None or val=='':
            if qd.get('required',True): raise ValueError(f'Не заполнен обязательный пункт: {qd["text"]}')
            continue
        typ=qd.get('type','single')
        if typ=='single':
            n=_num(val,qid)
            allowed=[int(x['value']) for x in qd.get('options',[]) if str(x['value']).lstrip('-').isdigit()]
            if n not in allowed: raise ValueError(f'Недопустимый вариант ответа в пункте {qid}')
        elif typ=='yesno_period':
            if not isinstance(val,dict): raise ValueError(f'Пункт {qid}: ожидаются ответы по периодам')
            for period in qd.get('periods',[]):
                pv=val.get(period['id'])
                if pv not in ('yes','no') and qd.get('required',True):
                    raise ValueError(f'Пункт {qid}: заполните период «{period["label"]}»')
        elif typ=='text':
            if not isinstance(val,str): raise ValueError(f'Пункт {qid}: ожидается текст')
            if len(val)>6000: raise ValueError(f'Пункт {qid}: слишком длинный текст')
        else:
            raise ValueError(f'Неподдерживаемый тип пункта: {typ}')
    st=defn.get('scoring',{}); typ=st.get('type','sum')
    if typ=='sum':
        total=0
        for qd in defn['questions']:
            if qd.get('scored',True) and qd.get('type','single')=='single' and answers.get(qd['id']) not in (None,''):
                total+=_num(answers[qd['id']],qd['id'])
        band=next((b for b in st.get('bands',[]) if b['min']<=total<=b['max']),None)
        result={'type':'sum','total':total,'metric_label':st.get('metric_label','Сумма баллов'), 'band':band}
        for sub in st.get('subscales',[]):
            ids=sub.get('question_ids',[])
            result.setdefault('subscales',[]).append({'label':sub['label'],'total':sum(_num(answers.get(x,0),x) for x in ids if answers.get(x) not in (None,''))})
    elif typ=='groups_sum':
        groups=[]
        for gd in st.get('groups',[]):
            total=sum(_num(answers.get(qd['id'],0),qd['id']) for qd in defn['questions'] if qd.get('scoring_group')==gd['question_group'] and answers.get(qd['id']) not in (None,''))
            band=next((b for b in gd.get('bands',[]) if b['min']<=total<=b['max']),None)
            groups.append({'id':gd['id'],'label':gd['label'],'total':total,'max':gd['max'],'band':band})
        result={'type':'groups_sum','groups':groups,'metric_label':'Баллы по подшкалам'}
    elif typ=='scl90':
        vals=[_num(answers.get(f'q{i}',0),f'q{i}') for i in range(1,91)]
        total=sum(vals); psi=sum(1 for x in vals if x>0); gsi=total/90; pdsi=(total/psi) if psi else 0
        subs=[]
        for sub in st.get('subscales',[]):
            nums=[_num(answers.get(qid,0),qid) for qid in sub['question_ids']]
            subs.append({'id':sub['id'],'label':sub['label'],'mean':round(sum(nums)/len(nums),3) if nums else 0,'items':len(nums)})
        result={'type':'scl90','raw_total':total,'gsi':round(gsi,3),'psi':psi,'pdsi':round(pdsi,3),'subscales':subs,
                'metric_label':'Описательные индексы; не диагноз'}
    elif typ=='cssrs':
        rules=st.get('risk_rules',{})
        def recent_yes(qid): return isinstance(answers.get(qid),dict) and answers[qid].get('recent')=='yes'
        critical=any(recent_yes(x) for x in rules.get('critical_if_recent_yes',[]))
        urgent=any(recent_yes(x) for x in rules.get('urgent_if_recent_yes',[]))
        review=any(recent_yes(x) for x in rules.get('any_recent_yes',[]))
        result={'type':'cssrs','total':None,'metric_label':'Клиническая оценка; суммарный балл не рассчитывается',
                'alert_level':'critical' if critical else 'urgent' if urgent else 'review' if review else 'none',
                'note':'Автоматический приоритет является техническим правилом эскалации, не валидированной оценкой риска и не заменяет клиническое заключение.'}
    else:
        raise ValueError('Неизвестный алгоритм подсчёта')
    risk=False; risk_rule=st.get('risk_if')
    if risk_rule:
        val=answers.get(risk_rule.get('question_id'))
        risk=(val in risk_rule.get('values',[]))
    if typ=='cssrs': risk=result['alert_level']!='none'
    result['risk_flag']=bool(risk)
    result['completed_question_count']=sum(1 for qd in defn['questions'] if answers.get(qd['id']) not in (None,''))
    return result


def result_alert_info(defn, answers, score):
    qid=defn['id']
    if qid=='cssrs':
        level=score.get('alert_level')
        if level=='critical': return ('critical','C-SSRS: недавнее намерение/план','Недавний ответ о намерении, плане или соответствующем поведении требует немедленной оценки специалистом и действий по локальному протоколу безопасности. Суммарный балл не рассчитывается.')
        if level=='urgent': return ('urgent','C-SSRS: срочная клиническая оценка','Отмечен недавний ответ о суицидальном мышлении с высоким приоритетом или суицидальном поведении. Нужна срочная оценка специалистом по локальному протоколу.')
        if level=='review': return ('review','C-SSRS: требуется клиническая проверка','Отмечен недавний ответ в скрининге. Проверьте ответы и текущую безопасность пациента; инструмент не заменяет интервью.')
        return None
    st=defn.get('scoring',{}); rule=st.get('risk_if')
    if rule:
        val=answers.get(rule.get('question_id'))
        if val in rule.get('values',[]):
            if qid=='phq9': title='PHQ-9: положительный ответ на пункт о смерти/самоповреждении'
            elif qid=='bdi21': title='BDI: положительный ответ на пункт о суицидальных мыслях'
            elif qid=='hdrs17': title='HDRS-17: отмечен пункт о суицидальных тенденциях'
            elif qid=='madrs': title='MADRS: отмечены суицидальные мысли'
            else: title=f'{defn["title"]}: требуется проверка безопасности'
            return ('urgent',title,'Сработало правило безопасности по ответу опросника. Это не диагноз и не автоматический вывод о немедленной опасности; специалист должен оценить актуальный риск и связаться с пациентом по принятому протоколу. Пациенту показана информация о получении срочной помощи.')
    if qid=='scl90r':
        vals=[answers.get('q15'),answers.get('q59'),answers.get('q63')]
        if any(v not in (None,'',0,'0') for v in vals):
            return ('urgent','SCL-90-R: ответ, требующий проверки безопасности','В скрининге отмечены мысли о самоубийстве/смерти или импульсы причинения вреда. Необходимо прямое клиническое уточнение; автоматическая оценка не заменяет индивидуальную оценку риска.')
    # Mild/severe totals are monitoring signals, never diagnoses.
    if score.get('type')=='sum' and score.get('band'):
        band=score['band']
        label=(band.get('label') or '').lower()
        if any(word in label for word in ('тяжёл','тяжел','выражен')) and score.get('total',0)>0:
            return ('review',f'{defn["title"]}: выраженные симптомы по ключу источника','Автоматический сигнал для проверки динамики и клинического контекста, а не диагноз и не назначение лечения.')
    return None


def get_bundle(conn,user,patient_row):
    pid=patient_row['id']
    entries=conn.execute('SELECT * FROM entries WHERE patient_id=? ORDER BY entry_date DESC, id DESC LIMIT 1200',(pid,)).fetchall()
    all_res=conn.execute('SELECT * FROM questionnaire_results WHERE patient_id=? ORDER BY created_at DESC LIMIT 100',(pid,)).fetchall()
    # Patient sees their self-report questionnaires; clinician-rated/safety interviews stay in the clinician view.
    if user['role']=='patient':
        res=[r for r in all_res if (get_questionnaire(r['questionnaire_id']).get('respondent')=='patient' and r['completed_by']==user['id'])]
    else:
        res=all_res
    aps=conn.execute('SELECT * FROM appointments WHERE patient_id=? ORDER BY starts_at ASC LIMIT 100',(pid,)).fetchall()
    if user['role']=='patient':
        # A clinical encounter created as part of an unsigned assessment is not yet patient-visible.
        visits=conn.execute('''SELECT v.* FROM visits v WHERE v.patient_id=? AND NOT EXISTS
            (SELECT 1 FROM clinical_assessments ca WHERE ca.visit_id=v.id AND ca.signed_at IS NULL)
            ORDER BY v.visit_date DESC,v.id DESC LIMIT 100''',(pid,)).fetchall()
    else:
        visits=conn.execute('SELECT * FROM visits WHERE patient_id=? ORDER BY visit_date DESC,id DESC LIMIT 100',(pid,)).fetchall()
    # Never expose unapproved drafts through a patient-facing bundle.
    if user['role']=='patient':
        plans=conn.execute('SELECT * FROM medication_plans WHERE patient_id=? AND status!="draft" ORDER BY created_at DESC',(pid,)).fetchall()
    else:
        plans=conn.execute('SELECT * FROM medication_plans WHERE patient_id=? ORDER BY created_at DESC',(pid,)).fetchall()
    logs=conn.execute('SELECT * FROM medication_logs WHERE patient_id=? ORDER BY scheduled_date DESC,id DESC LIMIT 100',(pid,)).fetchall()
    recs=(conn.execute('SELECT * FROM recommendations WHERE patient_id=? AND status IN (?,?) ORDER BY created_at DESC',(pid,'published','draft')).fetchall() if user['role']=='doctor' else conn.execute('SELECT * FROM recommendations WHERE patient_id=? AND status=? ORDER BY created_at DESC',(pid,'published')).fetchall())
    msgs=conn.execute('''SELECT m.*,u.display_name AS sender_name,u.role AS sender_role FROM messages m JOIN users u ON u.id=m.sender_user_id WHERE m.patient_id=? ORDER BY m.created_at DESC LIMIT 100''',(pid,)).fetchall()
    public_messages=[]
    for row in reversed(msgs):
        item=dict(row)
        if item.get('deleted_at'):
            item['body']='Сообщение удалено отправителем'
        public_messages.append(item)
    alerts=conn.execute('SELECT * FROM alerts WHERE patient_id=? ORDER BY created_at DESC LIMIT 100',(pid,)).fetchall()
    # Keep the original signal and its latest clinician processing result together in the patient chart.
    alert_items=[]
    for alert_row in alerts:
        alert_item=dict(alert_row)
        latest_review=conn.execute('''SELECT ar.id,ar.significance,ar.reaction,ar.followup,ar.created_at,
                    u.display_name AS reviewer_name
                FROM alert_reviews ar JOIN users u ON u.id=ar.reviewer_user_id
                WHERE ar.alert_id=? ORDER BY ar.created_at DESC,ar.id DESC LIMIT 1''',(alert_row['id'],)).fetchone()
        alert_item['latest_review']=dict(latest_review) if latest_review else None
        alert_items.append(alert_item)
    prefs=patient_preferences(conn,pid)
    if user['role']=='patient':
        assessments=conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? AND signed_at IS NOT NULL ORDER BY assessed_at DESC,id DESC LIMIT 100',(pid,)).fetchall()
    else:
        assessments=conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? ORDER BY assessed_at DESC,id DESC LIMIT 100',(pid,)).fetchall()
    adverse=conn.execute('SELECT * FROM adverse_events WHERE patient_id=? ORDER BY created_at DESC LIMIT 100',(pid,)).fetchall()
    if user['role']=='patient':
        care=conn.execute('SELECT * FROM care_plans WHERE patient_id=? AND status IN (?,?,?) ORDER BY created_at DESC',(pid,'active','paused','completed')).fetchall()
    else:
        care=conn.execute('SELECT * FROM care_plans WHERE patient_id=? ORDER BY created_at DESC',(pid,)).fetchall()
    studies=conn.execute('SELECT * FROM imaging_studies WHERE patient_id=? ORDER BY study_date DESC,created_at DESC',(pid,)).fetchall()
    notes=conn.execute('SELECT * FROM notifications WHERE patient_id=? AND recipient_user_id=? ORDER BY created_at DESC LIMIT 100',(pid,user['id'])).fetchall()
    return {'patient':patient_view(patient_row),
      'entries':[dict(x, data=json.loads(x['data_json'])) for x in entries],
      'results':[dict(x, answers=json.loads(x['answers_json']), score=json.loads(x['score_json'])) for x in res],
      'appointments':[dict(x) for x in aps], 'visits':[dict(x) for x in visits],
      'medication_plans':[dict(x, times=json.loads(x['times_json'])) for x in plans],
      'medication_logs':[dict(x) for x in logs], 'recommendations':[dict(x) for x in recs],
      'messages':public_messages, 'alerts':alert_items,
      'preferences':prefs, 'clinical_assessments':[dict(x, mental_state=json.loads(x['mental_state_json'])) for x in assessments],
      'adverse_events':[dict(x, symptoms=json.loads(x['symptoms_json'])) for x in adverse],
      'care_plans':[dict(x, plan=json.loads(x['plan_json'])) for x in care],
      'imaging_studies':[dict(x, metadata=json.loads(x['metadata_json'])) for x in studies],
      'notifications':[dict(x) for x in notes]}


def demo_scenarios():
    return load_json(DATA/'demo_scenarios.json', [])



def list_treatment_schemes():
    out=[]
    for f in sorted((DATA/'treatment_schemes').glob('*.json')):
        d=json.loads(f.read_text(encoding='utf-8'))
        out.append({k:d.get(k) for k in ('id','title','category','version','summary','status','source_refs','approval_required','patient_visible_after_approval')})
    return out


def compose_clinical_report(conn, user, patient_row, assessment=None):
    pid=patient_row['id']
    if assessment is None:
        if user['role']=='patient':
            assessment=conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? AND signed_at IS NOT NULL ORDER BY assessed_at DESC,id DESC LIMIT 1',(pid,)).fetchone()
        else:
            assessment=conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? ORDER BY assessed_at DESC,id DESC LIMIT 1',(pid,)).fetchone()
    if assessment is not None and not isinstance(assessment,dict):
        assessment=dict(assessment)
        assessment['mental_state']=json.loads(assessment.get('mental_state_json') or '{}')
    results=conn.execute('SELECT id,questionnaire_title,questionnaire_id,created_at,score_json FROM questionnaire_results WHERE patient_id=? ORDER BY created_at DESC LIMIT 10',(pid,)).fetchall()
    entries=conn.execute('SELECT entry_date,entry_type,data_json FROM entries WHERE patient_id=? ORDER BY entry_date DESC,id DESC LIMIT 30',(pid,)).fetchall()
    care=conn.execute('SELECT id,title,status,plan_json FROM care_plans WHERE patient_id=? AND status IN (?,?,?) ORDER BY created_at DESC',(pid,'active','paused','completed')).fetchall()
    meds=conn.execute('SELECT id,drug_name,regimen,status,start_date,end_date,notes FROM medication_plans WHERE patient_id=? AND status IN (?,?,?) ORDER BY created_at DESC',(pid,'active','paused','stopped')).fetchall()
    adverse=conn.execute('SELECT id,onset_at,severity,serious,symptoms_json,description,review_status,outcome FROM adverse_events WHERE patient_id=? ORDER BY created_at DESC LIMIT 20',(pid,)).fetchall()
    alerts=conn.execute('SELECT severity,title,detail,created_at,status FROM alerts WHERE patient_id=? AND status!=? ORDER BY created_at DESC LIMIT 30',(pid,'resolved')).fetchall()
    questionnaire_results=[]
    for r in results:
        score=json.loads(r['score_json'])
        questionnaire_results.append({'id':r['id'],'title':r['questionnaire_title'],'questionnaire_id':r['questionnaire_id'],'created_at':r['created_at'],'score':score})
    mood=[]
    for r in reversed(entries):
        if r['entry_type'] in ('mood','food','checklist','menstrual','side_effect'):
            d=json.loads(r['data_json'])
            mood.append({'date':r['entry_date'],'type':r['entry_type'],'mood':d.get('mood'),'sleep_hours':d.get('sleep_hours'),'notes':d.get('notes') or d.get('meals') or ''})
    careplans=[]
    for r in care:
        pj=json.loads(r['plan_json'])
        careplans.append({'id':r['id'],'title':r['title'],'status':r['status'],'steps':[{'title':x.get('title'),'status':x.get('status')} for x in pj.get('steps',[])]})
    medication_plans=[dict(r) for r in meds]
    adverse_events=[dict(r,symptoms=json.loads(r['symptoms_json'])) for r in adverse]
    red_flags=[dict(r) for r in alerts]
    mental=(assessment.get('mental_state') or {}) if assessment else {}
    summary=(assessment.get('summary') or '') if assessment else ''
    follow=(assessment.get('plan_notes') or '') if assessment else ''
    return {'patient':patient_view(patient_row),'assessed_at':assessment.get('assessed_at') if assessment else None,
       'assessment_id':assessment.get('id') if assessment else None,'verified':bool(assessment and assessment.get('signed_at')),
       'summary':summary,'assessment':mental,'follow_up':follow,'questionnaire_results':questionnaire_results,
       'diary_summary':mood,'care_plans':careplans,'medication_plans':medication_plans,'adverse_events':adverse_events,'red_flags':red_flags,
       'disclaimer':'Сформированный отчёт объединяет сохранённые данные, не устанавливает диагноз и не создаёт новое назначение.'}


def _external_uid(value):
    value=str(value or '').strip()
    if len(value)>64 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+',value): raise ValueError('StudyInstanceUID должен быть UID из цифр и точек (до 64 символов)')
    return value


def send_web_push_if_configured(conn, notification_id, user_id, title, body, data=None):
    """Best-effort push. Notifications remain persisted in-app even if provider is absent."""
    vapid_private=os.environ.get('VAPID_PRIVATE_KEY','').strip()
    vapid_claims_email=os.environ.get('VAPID_CLAIMS_EMAIL','').strip()
    if vapid_private and vapid_claims_email:
        try:
            from pywebpush import webpush, WebPushException
            subs=conn.execute('SELECT * FROM push_subscriptions WHERE user_id=?',(user_id,)).fetchall()
            payload=json.dumps({'title':title,'body':body,'data':data or {}},ensure_ascii=False)
            for sub in subs:
                try:
                    webpush(subscription_info=json.loads(sub['subscription_json']),data=payload,vapid_private_key=vapid_private,vapid_claims={'sub':f'mailto:{vapid_claims_email}'},ttl=60)
                    conn.execute('UPDATE notifications SET push_sent_at=?,delivery_status=? WHERE id=?',(utc_now(),'push_sent',notification_id))
                except Exception:
                    # Remove subscriptions that are permanently gone; otherwise retain for later retries.
                    continue
        except Exception:
            pass
    firebase_json=os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON','').strip()
    if firebase_json:
        try:
            import firebase_admin
            from firebase_admin import credentials, messaging
            try: app=firebase_admin.get_app()
            except ValueError: app=firebase_admin.initialize_app(credentials.Certificate(json.loads(firebase_json)))
            tokens=conn.execute('SELECT * FROM mobile_push_tokens WHERE user_id=?',(user_id,)).fetchall()
            for token_row in tokens:
                try:
                    messaging.send(messaging.Message(notification=messaging.Notification(title=title,body=body),data={str(k):str(v) for k,v in (data or {}).items()},token=token_row['token']),app=app)
                    conn.execute('UPDATE notifications SET push_sent_at=?,delivery_status=? WHERE id=?',(utc_now(),'push_sent',notification_id))
                except Exception:
                    continue
        except Exception:
            pass


def ai_summary(conn, patient_row):
    pid=patient_row['id']
    latest=conn.execute('SELECT questionnaire_title,score_json,created_at FROM questionnaire_results WHERE patient_id=? ORDER BY created_at DESC LIMIT 8',(pid,)).fetchall()
    alerts=conn.execute('SELECT severity,title,created_at FROM alerts WHERE patient_id=? AND status="open" ORDER BY created_at DESC',(pid,)).fetchall()
    entries=conn.execute('SELECT entry_date,data_json FROM entries WHERE patient_id=? AND entry_type="mood" ORDER BY entry_date DESC LIMIT 7',(pid,)).fetchall()
    lines=[]
    lines.append('Предварительная структурированная сводка. Это алгоритмический прототип, не клиническая модель ИИ.')
    if alerts:
        top=alerts[0]
        lines.append(f'Открытые сигналы безопасности: {len(alerts)}. Приоритет последнего: {top["severity"]}; {top["title"]}. Сначала разберите сигналы, не переходите сразу к подбору терапии.')
    else: lines.append('Открытых сигналов безопасности сейчас нет в системе. Это не доказывает отсутствие риска.')
    if latest:
        lines.append('Последние результаты опросников:')
        for row in latest[:5]:
            s=json.loads(row['score_json'])
            if s.get('type')=='sum': display=f'{s.get("total")} баллов'+(f' — {s["band"].get("label")}' if s.get('band') else '')
            elif s.get('type')=='groups_sum': display='; '.join(f'{g["label"]}: {g["total"]}/21 — {g["band"].get("label") if g.get("band") else "без категории"}' for g in s.get('groups',[]))
            elif s.get('type')=='scl90': display=f'GSI {s.get("gsi")}; PSI {s.get("psi")}; PDSI {s.get("pdsi")}'
            else: display=s.get('note','Клиническая оценка; суммарный балл не рассчитывается')
            lines.append(f'• {row["questionnaire_title"]}: {display} ({row["created_at"][:10]}).')
    else: lines.append('Нет завершённых опросников. Предложите базовую оценку и уточните актуальные жалобы.')
    if entries:
        moods=[json.loads(e['data_json']).get('mood') for e in reversed(entries)]
        moods=[int(x) for x in moods if str(x).isdigit()]
        if moods:
            trend='повышается' if len(moods)>1 and moods[-1]>moods[0] else 'снижается' if len(moods)>1 and moods[-1]<moods[0] else 'без однозначного направления'
            lines.append(f'Дневник настроения за последние записи: {" → ".join(map(str,moods))}; направление {trend}. Интерпретируйте вместе с качественными записями, сном и функционированием.')
    lines.append('Безопасные следующие шаги: (1) перепроверить качество и дату данных; (2) проверить суицидальный риск и признаки гипомании, если клинически уместно; (3) сопоставить динамику симптомов, функционирование, приверженность и нежелательные явления; (4) принять или отклонить клиническое решение должен врач.')
    return {'summary':'\n'.join(lines),'model_status':'rules_only','disclaimer':'Локальная обученная модель пока не подключена. Автоматическая сводка не ставит диагноз и не назначает препараты.'}


class AppHandler(BaseHTTPRequestHandler):
    server_version = 'ClinicCompanion/0.1'

    def log_message(self, fmt, *args):
        # No request body or patient information is logged.
        super().log_message(fmt, *args)

    def send_bytes(self, status, body, content_type='application/json; charset=utf-8', headers=None):
        if isinstance(body,str): body=body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('Cache-Control','no-store')
        if headers:
            for k,v in headers.items(): self.send_header(k,v)
        self.end_headers()
        self.wfile.write(body)

    def json(self,status,obj,headers=None):
        self.send_bytes(status,json.dumps(obj,ensure_ascii=False,separators=(',',':')),headers=headers)

    def read_json(self):
        try: n=int(self.headers.get('Content-Length','0'))
        except ValueError: raise ValueError('Некорректный размер запроса')
        if n<0 or n>2_000_000: raise ValueError('Размер запроса превышает лимит 2 МБ')
        raw=self.rfile.read(n) if n else b'{}'
        try: data=json.loads(raw.decode('utf-8'))
        except Exception: raise ValueError('Тело запроса должно быть корректным JSON')
        if not isinstance(data,dict): raise ValueError('Тело запроса должно быть JSON-объектом')
        return data

    def session(self,conn):
        cookie=self.headers.get('Cookie','')
        token=None
        for item in cookie.split(';'):
            if '=' in item:
                key,val=item.strip().split('=',1)
                if key==COOKIE_NAME: token=val
        if not token or len(token)>128: return None,None
        token_hash=hashlib.sha256(token.encode()).hexdigest()
        row=conn.execute('SELECT s.*,u.id AS id,u.email,u.display_name,u.role,u.active,u.must_change_password FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?',(token_hash,)).fetchone()
        if not row: return None,None
        if row['expires_at']<utc_now() or not row['active']:
            conn.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash,)); conn.commit()
            return None,None
        # Archived patients are effectively deactivated.
        if row['role']=='patient':
            p=conn.execute('SELECT archived FROM patients WHERE user_id=?',(row['user_id'],)).fetchone()
            if not p or p['archived']:
                conn.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash,)); conn.commit()
                return None,None
        return dict(row),token_hash

    def require_user(self,conn,roles=None,csrf=False):
        user,token_hash=self.session(conn)
        if not user: raise PermissionError('Требуется вход в систему')
        if roles and user['role'] not in roles: raise PermissionError('Недостаточно прав для этой операции')
        if csrf and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),user['csrf_token']):
            raise PermissionError('CSRF-проверка не пройдена; обновите страницу и повторите действие')
        return user

    def do_GET(self): self.route_request('GET')
    def do_POST(self): self.route_request('POST')
    def do_DELETE(self): self.route_request('DELETE')

    def route_request(self,method):
        parsed=urlparse(self.path); path=unquote(parsed.path); query=parse_qs(parsed.query)
        pdfm=re.fullmatch(r'/api/patients/(\d+)/clinical-documents/(\d+)/file',path) if method=='GET' else None
        if pdfm:
            conn=get_db()
            try:
                user=self.require_user(conn)
                patient=get_patient(conn,user,pdfm.group(1))
                doc=conn.execute('SELECT * FROM clinical_documents WHERE patient_id=? AND id=?',(patient['id'],pdfm.group(2))).fetchone()
                if not doc: raise LookupError('Документ не найден')
                log_audit(conn,user['id'],'view_clinical_pdf','clinical_document',doc['id'],f'patient_id={patient["id"]}')
                conn.commit()
                safe_name=re.sub(r'[^A-Za-z0-9._ -]','_',doc['file_name'])[:120] or 'document.pdf'
                self.send_bytes(200,bytes(doc['content']),'application/pdf',{'Content-Disposition':f'inline; filename="{safe_name}"','X-Content-Type-Options':'nosniff'})
            except PermissionError as e: self.json(401 if str(e)=='Требуется вход в систему' else 403,{'error':str(e)})
            except LookupError as e: self.json(404,{'error':str(e)})
            except Exception:
                self.json(500,{'error':'Не удалось открыть PDF-документ'})
            finally: conn.close()
            return
        md=re.fullmatch(r'/api/patients/(\d+)/reports/clinical\.dcm',path) if method=='GET' else None
        if md:
            conn=get_db()
            try:
                user=self.require_user(conn)
                patient=get_patient(conn,user,md.group(1))
                assessment_id=query.get('assessment_id',[None])[0]
                if assessment_id:
                    assessment=conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? AND id=?',(patient['id'],int(assessment_id))).fetchone()
                else:
                    assessment=(conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? AND signed_at IS NOT NULL ORDER BY assessed_at DESC,id DESC LIMIT 1',(patient['id'],)).fetchone() if user['role']=='patient' else conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? ORDER BY assessed_at DESC,id DESC LIMIT 1',(patient['id'],)).fetchone())
                if not assessment: raise LookupError('Сначала врач должен сохранить структурированную клиническую оценку')
                assessment=dict(assessment); assessment['mental_state']=json.loads(assessment.get('mental_state_json') or '{}')
                verified=bool(assessment.get('signed_at'))
                if user['role']=='patient' and not verified: raise PermissionError('Пациенту доступен только подтверждённый врачом клинический отчёт')
                bundle=get_bundle(conn,user,patient)
                report=compose_clinical_report(conn,user,patient,assessment)
                dicom_patient={**report['patient'],'id':patient['id'],'external_id':f'CLINIC-{patient["id"]}'}
                payload=build_dicom_basic_text_sr(dicom_patient,report,verified=verified)
                validate_basic_text_sr(payload)
                log_audit(conn,user['id'],'export_dicom_sr','clinical_assessment',assessment['id'],'Basic Text SR')
                conn.commit()
                self.send_bytes(200,payload,'application/dicom',{'Content-Disposition':f'attachment; filename="clinical-report-{patient["id"]}-{assessment["id"]}.dcm"'})
            except PermissionError as e: self.json(401 if str(e)=='Требуется вход в систему' else 403,{'error':str(e)})
            except LookupError as e: self.json(404,{'error':str(e)})
            except ValueError as e: self.json(400,{'error':str(e)})
            except Exception:
                self.json(500,{'error':'Не удалось сформировать DICOM SR. Отчёт не был выдан.'})
            finally: conn.close()
            return
        if not path.startswith('/api/'):
            self.serve_static(path); return
        conn=get_db()
        try:
            body=self.read_json() if method=='POST' else {}
            if method=='GET': obj,status=self.api_get(conn,path,query)
            elif method=='POST': obj,status,headers=self.api_post(conn,path,body); self.json(status,obj,headers); conn.close(); return
            elif method=='DELETE': obj,status=self.api_delete(conn,path)
            else: raise LookupError('Метод не поддерживается')
            self.json(status,obj)
        except PermissionError as e:
            self.json(401 if str(e)=='Требуется вход в систему' else 403,{'error':str(e)})
        except LookupError as e:
            self.json(404,{'error':str(e)})
        except ValueError as e:
            self.json(400,{'error':str(e)})
        except sqlite3.IntegrityError as e:
            msg='Запись конфликтует с существующими данными; проверьте e-mail, план или дату.'
            self.json(409,{'error':msg})
        except Exception as e:
            self.json(500,{'error':'Внутренняя ошибка. Подробности не раскрыты для защиты медицинских данных.'})
        finally:
            try: conn.close()
            except Exception: pass

    def serve_static(self,path):
        if path=='/': path='/index.html'
        relative=path.lstrip('/')
        target=(STATIC/relative).resolve()
        try: target.relative_to(STATIC.resolve())
        except ValueError:
            self.send_bytes(403,'Forbidden','text/plain; charset=utf-8'); return
        if not target.is_file():
            self.send_bytes(404,'Not found','text/plain; charset=utf-8'); return
        ctype=mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype in ('application/javascript','application/json'): ctype+='; charset=utf-8'
        self.send_bytes(200,target.read_bytes(),ctype)

    def api_get(self,conn,path,q):
        if path=='/api/health':
            return {'ok':True,'app':'Clinic Companion','version':'0.1','mode':'demo-local' if DEMO_MODE else 'local'},200
        user=self.require_user(conn)
        if path=='/api/me':
            patient=patient_for_user(conn,user['id']) if user['role']=='patient' else None
            out={'user':user_public(user),'csrf_token':user['csrf_token'],'demo_mode':DEMO_MODE}
            if patient: out['patient']=patient_view(patient)
            return out,200
        md=re.fullmatch(r'/api/patients/(\d+)/clinical-documents',path)
        if md:
            patient=get_patient(conn,user,md.group(1))
            docs=conn.execute('SELECT id,title,file_name,mime_type,size_bytes,sha256,uploaded_by,created_at FROM clinical_documents WHERE patient_id=? ORDER BY created_at DESC,id DESC',(patient['id'],)).fetchall()
            return {'documents':[dict(d) for d in docs]},200
        if path=='/api/bootstrap':
            catalog=questionnaire_catalog(user['role'])
            meds=load_medications()
            alerts=[]; patients=[]; current=None
            patient_count=0; archived_patient_count=0
            if user['role']=='doctor':
                patient_count=conn.execute('SELECT COUNT(*) n FROM patients WHERE doctor_user_id=? AND archived=0',(user['id'],)).fetchone()['n']
                archived_patient_count=conn.execute('SELECT COUNT(*) n FROM patients WHERE doctor_user_id=? AND archived=1',(user['id'],)).fetchone()['n']
                rows=conn.execute('SELECT p.*,u.email FROM patients p JOIN users u ON u.id=p.user_id WHERE p.doctor_user_id=? AND p.archived=0 ORDER BY p.full_name LIMIT 100',(user['id'],)).fetchall()
                patients=[dict(patient_view(x),email=x['email']) for x in rows]
                alerts=[dict(a) for a in conn.execute('''SELECT a.*,p.full_name FROM alerts a JOIN patients p ON p.id=a.patient_id WHERE p.doctor_user_id=? AND p.archived=0 AND a.status!='resolved' ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 WHEN 'review' THEN 2 ELSE 3 END,a.created_at DESC LIMIT 50''',(user['id'],)).fetchall()]
            else:
                p=patient_for_user(conn,user['id']); current=patient_view(p) if p else None
                if p: alerts=[dict(a) for a in conn.execute('SELECT * FROM alerts WHERE patient_id=? AND status!=? ORDER BY created_at DESC LIMIT 20',(p['id'],'resolved')).fetchall()]
            notifications=[dict(n) for n in conn.execute('SELECT * FROM notifications WHERE recipient_user_id=? ORDER BY created_at DESC LIMIT 25',(user['id'],)).fetchall()]
            unread_count=conn.execute('SELECT COUNT(*) n FROM notifications WHERE recipient_user_id=? AND read_at IS NULL',(user['id'],)).fetchone()['n']
            return {'user':user_public(user),'patients':patients,'alerts':alerts,'notifications':notifications,'unread_notification_count':unread_count,'questionnaires':catalog,'medications':meds,'treatment_schemes':list_treatment_schemes(),'guideline_sources':load_json(DATA/'guidelines'/'source_registry.json',{}).get('sources',[]),'integrations':load_json(DATA/'integrations.json',{}),'patient_count':patient_count,'archived_patient_count':archived_patient_count,'patient':current,'scenarios':demo_scenarios(),'demo_mode':DEMO_MODE},200
        if path=='/api/treatment-schemes':
            return {'schemes':list_treatment_schemes()},200
        m=re.fullmatch(r'/api/treatment-schemes/([a-z0-9_-]+)',path)
        if m:
            scheme=load_treatment_scheme(m.group(1))
            return {'scheme':scheme},200
        if path=='/api/integrations':
            return load_json(DATA/'integrations.json',{}),200
        if path=='/api/red-flags':
            if user['role']!='doctor': raise PermissionError('Настраивать red flags может только врач')
            rows=conn.execute('SELECT * FROM red_flag_rules ORDER BY source_type,title').fetchall()
            return {'rules':[dict(r,enabled=bool(r['enabled']),rule=json.loads(r['rule_json'])) for r in rows], 'delivery_limit':load_json(DATA/'red_flags.json',{}).get('delivery_limit','In-app only')},200
        m=re.fullmatch(r'/api/patient-red-flags/(\d+)',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Настройка доступна только врачу')
            p=get_patient(conn,user,m.group(1))
            rows=conn.execute('SELECT * FROM red_flag_rules ORDER BY source_type,title').fetchall()
            overrides={r['rule_id']:dict(r) for r in conn.execute('SELECT * FROM patient_red_flag_overrides WHERE patient_id=?',(p['id'],)).fetchall()}
            rules=[]
            for r in rows:
                ov=overrides.get(r['id'])
                rules.append({'id':r['id'],'title':r['title'],'source_type':r['source_type'],'enabled':bool(ov['enabled']) if ov else bool(r['enabled']),'severity':ov['severity'] if ov else r['severity'],'recipient':ov['recipient'] if ov else r['recipient'],'overridden':bool(ov)})
            return {'patient_id':p['id'],'rules':rules},200
        if path=='/api/push/vapid-public':
            public_key=os.environ.get('VAPID_PUBLIC_KEY','').strip()
            return {'configured':bool(public_key and os.environ.get('VAPID_PRIVATE_KEY','').strip()),'public_key':public_key},200
        if path=='/api/notifications':
            rows=conn.execute("""SELECT * FROM notifications WHERE recipient_user_id=? ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 WHEN 'review' THEN 2 ELSE 3 END,created_at DESC LIMIT 200""",(user['id'],)).fetchall()
            return {'notifications':[dict(r) for r in rows], 'unread_count':sum(1 for r in rows if not r['read_at'])},200
        if path=='/api/dashboard':
            if user['role']=='doctor':
                n=conn.execute('SELECT COUNT(*) n FROM patients WHERE doctor_user_id=? AND archived=0',(user['id'],)).fetchone()['n']
                open_alerts=conn.execute('SELECT COUNT(*) n FROM alerts a JOIN patients p ON p.id=a.patient_id WHERE p.doctor_user_id=? AND p.archived=0 AND a.status="open"',(user['id'],)).fetchone()['n']
                upcoming=conn.execute('SELECT COUNT(*) n FROM appointments a JOIN patients p ON p.id=a.patient_id WHERE p.doctor_user_id=? AND p.archived=0 AND a.starts_at>=?',(user['id'],datetime.now().isoformat(timespec='minutes'))).fetchone()['n']
                unread=conn.execute('SELECT COUNT(*) n FROM notifications WHERE recipient_user_id=? AND read_at IS NULL',(user['id'],)).fetchone()['n']
                return {'role':'doctor','patient_count':n,'open_alert_count':open_alerts,'upcoming_count':upcoming,'unread_notifications':unread},200
            p=patient_for_user(conn,user['id'])
            if not p: raise LookupError('Карточка пациента не найдена')
            streak=conn.execute('SELECT COUNT(DISTINCT entry_date) n FROM entries WHERE patient_id=? AND entry_date>=?',(p['id'],(date.today()-timedelta(days=6)).isoformat())).fetchone()['n']
            tests=conn.execute('SELECT COUNT(*) n FROM questionnaire_results WHERE patient_id=?',(p['id'],)).fetchone()['n']
            active=conn.execute('SELECT COUNT(*) n FROM medication_plans WHERE patient_id=? AND status="active"',(p['id'],)).fetchone()['n']
            unread=conn.execute('SELECT COUNT(*) n FROM notifications WHERE recipient_user_id=? AND read_at IS NULL',(user['id'],)).fetchone()['n']
            return {'role':'patient','entry_days_7':streak,'test_count':tests,'active_plans':active,'patient_id':p['id'],'unread_notifications':unread},200
        if path=='/api/alerts':
            include_resolved=q.get('include_resolved',['0'])[0].lower() in ('1','true','yes')
            try: limit=max(1,min(100,int(q.get('limit',['50'])[0])))
            except (TypeError,ValueError): limit=50
            try: offset=max(0,min(1_000_000,int(q.get('offset',['0'])[0])))
            except (TypeError,ValueError): offset=0
            patient_filter=q.get('patient_id',[None])[0]
            where=[]; args=[]
            if user['role']=='doctor':
                where.append('p.doctor_user_id=? AND p.archived=0'); args.append(user['id'])
                if patient_filter:
                    patient_row=get_patient(conn,user,patient_filter)
                    where.append('a.patient_id=?'); args.append(patient_row['id'])
            else:
                own=patient_for_user(conn,user['id'])
                if not own: raise LookupError('Карточка пациента не найдена')
                where.append('a.patient_id=?'); args.append(own['id'])
            if not include_resolved: where.append('a.status!=?'); args.append('resolved')
            where_sql=' AND '.join(where) if where else '1=1'
            total=conn.execute(f'SELECT COUNT(*) n FROM alerts a JOIN patients p ON p.id=a.patient_id WHERE {where_sql}',args).fetchone()['n']
            rows=conn.execute(f'''SELECT a.*,p.full_name FROM alerts a JOIN patients p ON p.id=a.patient_id
                WHERE {where_sql}
                ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 WHEN 'review' THEN 2 ELSE 3 END,
                         CASE a.status WHEN 'open' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END,a.created_at DESC
                LIMIT ? OFFSET ?''',(*args,limit,offset)).fetchall()
            alert_items=[]
            for row in rows:
                item=dict(row)
                review=conn.execute('''SELECT ar.id,ar.significance,ar.reaction,ar.followup,ar.created_at,u.display_name AS reviewer_name
                    FROM alert_reviews ar JOIN users u ON u.id=ar.reviewer_user_id
                    WHERE ar.alert_id=? ORDER BY ar.created_at DESC,ar.id DESC LIMIT 1''',(row['id'],)).fetchone()
                item['latest_review']=dict(review) if review else None
                alert_items.append(item)
            return {'alerts':alert_items,'total':total,'offset':offset,'limit':limit,'include_resolved':include_resolved},200
        if path=='/api/patients':
            if user['role']!='doctor': raise PermissionError('Только врач может просматривать список пациентов')
            archived=q.get('include_archived',['0'])[0].lower() in ('1','true','yes')
            search=(q.get('search',[''])[0] or '').strip()[:200]
            try: limit=max(1,min(100,int(q.get('limit',['25'])[0])))
            except (TypeError,ValueError): limit=25
            try: offset=max(0,min(1_000_000,int(q.get('offset',['0'])[0])))
            except (TypeError,ValueError): offset=0
            archive_value=1 if archived else 0
            where='p.doctor_user_id=? AND p.archived=?'
            args=[user['id'],archive_value]
            if search:
                where+=" AND (p.full_name LIKE ? OR u.email LIKE ? OR COALESCE(p.phone, '') LIKE ? OR COALESCE(p.birth_date, '') LIKE ?)"
                pattern='%'+search+'%'
                args.extend([pattern,pattern,pattern,pattern])
            total=conn.execute(f'SELECT COUNT(*) n FROM patients p JOIN users u ON u.id=p.user_id WHERE {where}',args).fetchone()['n']
            rows=conn.execute(f'SELECT p.*,u.email FROM patients p JOIN users u ON u.id=p.user_id WHERE {where} ORDER BY p.full_name COLLATE NOCASE,p.id LIMIT ? OFFSET ?',(*args,limit,offset)).fetchall()
            patients=[]
            for row in rows:
                item=dict(patient_view(row),email=row['email'])
                plan=conn.execute('SELECT drug_name,regimen FROM medication_plans WHERE patient_id=? AND status="active" ORDER BY created_at DESC,id DESC LIMIT 1',(row['id'],)).fetchone()
                item['summary_drug']=plan['drug_name'] if plan else None
                item['summary_regimen']=plan['regimen'] if plan else None
                care=conn.execute('SELECT COUNT(*) n FROM care_plans WHERE patient_id=? AND status="active"',(row['id'],)).fetchone()['n']
                item['summary_type']='Медикаментозная' if plan and not care else 'Комбинированная' if plan and care else 'Психологическое сопровождение' if care else 'Не указана'
                mood=conn.execute('SELECT entry_date,data_json FROM entries WHERE patient_id=? AND entry_type="mood" ORDER BY entry_date DESC,id DESC LIMIT 30',(row['id'],)).fetchall()
                values=[]
                for entry in mood:
                    try:
                        value=json.loads(entry['data_json'] or '{}').get('mood')
                        if isinstance(value,(int,float)): values.append((entry['entry_date'],float(value)))
                    except Exception: pass
                latest=[v for d,v in values if d >= (date.today()-timedelta(days=6)).isoformat()]
                previous=[v for d,v in values if (date.today()-timedelta(days=13)).isoformat() <= d < (date.today()-timedelta(days=6)).isoformat()]
                if len(latest)>=2 and len(previous)>=2:
                    delta=sum(latest)/len(latest)-sum(previous)/len(previous)
                    item['summary_response']='Самооценка улучшилась' if delta>=0.6 else 'Самооценка снизилась' if delta<=-0.6 else 'Самооценка стабильна'
                elif latest: item['summary_response']='Есть свежие отметки; сравнения пока мало'
                else: item['summary_response']='Нет свежих отметок настроения'
                patients.append(item)
            return {'patients':patients, 'total':total, 'offset':offset, 'limit':limit, 'archived':archived},200
        m=re.fullmatch(r'/api/patients/(\d+)/exchange/fhir',path)
        if m:
            p=get_patient(conn,user,m.group(1)); bundle=get_bundle(conn,user,p)
            ass=(conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? AND signed_at IS NOT NULL ORDER BY assessed_at DESC,id DESC LIMIT 1',(p['id'],)).fetchone() if user['role']=='patient' else conn.execute('SELECT * FROM clinical_assessments WHERE patient_id=? ORDER BY assessed_at DESC,id DESC LIMIT 1',(p['id'],)).fetchone())
            if ass:
                ass=dict(ass); ass['mental_state']=json.loads(ass['mental_state_json'])
            clinical=compose_clinical_report(conn,user,p,ass)
            if ass and clinical:
                clinical['signed_at']=ass.get('signed_at')
            fhir=to_fhir_r4_bundle({**patient_view(p),'id':p['id']},bundle,assessment=clinical if ass else None)
            log_audit(conn,user['id'],'export_fhir','patient',p['id'],'FHIR R4 Bundle')
            conn.commit()
            return fhir,200
        m=re.fullmatch(r'/api/patients/(\d+)/reports/clinical.json',path)
        if m:
            p=get_patient(conn,user,m.group(1)); report=compose_clinical_report(conn,user,p)
            if user['role']=='patient' and not report.get('verified'): raise PermissionError('Пациенту доступен только подтверждённый врачом клинический отчёт')
            return report,200
        m=re.fullmatch(r'/api/patients/(\d+)/imaging-studies',path)
        if m:
            p=get_patient(conn,user,m.group(1))
            rows=conn.execute('SELECT * FROM imaging_studies WHERE patient_id=? ORDER BY study_date DESC,created_at DESC',(p['id'],)).fetchall()
            return {'imaging_studies':[dict(r,metadata=json.loads(r['metadata_json'])) for r in rows]},200
        m=re.fullmatch(r'/api/patients/(\d+)/exchange/import-history',path)
        if m:
            p=get_patient(conn,user,m.group(1))
            rows=conn.execute('SELECT source_system,resource_type,external_id,target_table,target_id,imported_at FROM external_imports WHERE patient_id=? ORDER BY imported_at DESC LIMIT 300',(p['id'],)).fetchall()
            return {'imports':[dict(r) for r in rows]},200
        m=re.fullmatch(r'/api/patients/(\d+)/care-plans',path)
        if m:
            p=get_patient(conn,user,m.group(1))
            statuses=('active','paused','completed') if user['role']=='patient' else ('draft','active','paused','completed','stopped')
            marks=','.join('?' for _ in statuses)
            rows=conn.execute(f'SELECT * FROM care_plans WHERE patient_id=? AND status IN ({marks}) ORDER BY created_at DESC',(p['id'],*statuses)).fetchall()
            return {'care_plans':[dict(r,plan=json.loads(r['plan_json'])) for r in rows]},200
        m=re.fullmatch(r'/api/patients/(\d+)/preferences',path)
        if m:
            p=get_patient(conn,user,m.group(1)); return {'preferences':patient_preferences(conn,p['id'])},200
        m=re.fullmatch(r'/api/patients/(\d+)',path)
        if m:
            if user['role']=='doctor' and q.get('include_archived',['0'])[0] in ('1','true'):
                p=conn.execute('SELECT * FROM patients WHERE id=? AND doctor_user_id=? AND archived=1',(int(m.group(1)),user['id'])).fetchone()
                if not p: raise LookupError('Архивированная карточка не найдена')
                return get_bundle(conn,user,p),200
            p=get_patient(conn,user,m.group(1)); return get_bundle(conn,user,p),200
        if path=='/api/questionnaires': return {'questionnaires':questionnaire_catalog(user['role'])},200
        m=re.fullmatch(r'/api/questionnaires/([a-z0-9_-]+)',path)
        if m:
            d=get_questionnaire(m.group(1))
            if user['role']=='patient' and d['respondent']=='clinician': raise PermissionError('Эта шкала предназначена для специалиста')
            return {'questionnaire':d},200
        if path=='/api/medications': return {'medications':load_medications()},200
        m=re.fullmatch(r'/api/medications/([a-z0-9_-]+)',path)
        if m:
            medication=next((x for x in load_medications() if x.get('id')==m.group(1)),None)
            if medication is None: raise LookupError('Карточка препарата не найдена')
            return {'medication':medication},200
        if path=='/api/demo-scenarios':
            if user['role']!='doctor': raise PermissionError('Только врач')
            return {'scenarios':demo_scenarios()},200
        if path=='/api/calendar':
            pid=q.get('patient_id',[None])[0]
            if user['role']=='patient': p=patient_for_user(conn,user['id']); pid=p['id'] if p else None
            p=get_patient(conn,user,pid)
            bundle=get_bundle(conn,user,p)
            return {'patient':bundle['patient'],'appointments':bundle['appointments'],'medication_plans':bundle['medication_plans'],'medication_logs':bundle['medication_logs']},200
        if path=='/api/recommendations':
            pid=q.get('patient_id',[None])[0]
            if user['role']=='patient': p=patient_for_user(conn,user['id']); pid=p['id'] if p else None
            p=get_patient(conn,user,pid)
            return {'recommendations':[dict(x) for x in conn.execute('SELECT * FROM recommendations WHERE patient_id=? AND status=? ORDER BY created_at DESC',(p['id'],'published')).fetchall()]},200
        m=re.fullmatch(r'/api/messages/(\d+)/history',path)
        if m:
            if user['role']!='doctor': raise PermissionError('История изменений сообщений доступна врачу.')
            message=conn.execute('SELECT * FROM messages WHERE id=?',(int(m.group(1)),)).fetchone()
            if not message: raise LookupError('Сообщение не найдено.')
            p=get_patient(conn,user,message['patient_id'])
            revisions=conn.execute('''SELECT r.*,u.display_name AS actor_name,u.role AS actor_role
                FROM message_revisions r JOIN users u ON u.id=r.actor_user_id
                WHERE r.message_id=? ORDER BY r.created_at ASC,r.id ASC''',(message['id'],)).fetchall()
            # Current/original body is deliberately exposed only to the assigned clinician.
            return {'message_id':message['id'],'current_body':message['body'],'deleted':bool(message['deleted_at']),
                    'revisions':[dict(x) for x in revisions]},200
        if path=='/api/messages':
            pid=q.get('patient_id',[None])[0]
            if user['role']=='patient': p=patient_for_user(conn,user['id']); pid=p['id'] if p else None
            p=get_patient(conn,user,pid)
            rows=conn.execute('''SELECT m.*,u.display_name AS sender_name,u.role AS sender_role FROM messages m JOIN users u ON u.id=m.sender_user_id WHERE m.patient_id=? ORDER BY m.created_at ASC LIMIT 300''',(p['id'],)).fetchall()
            messages=[]
            for row in rows:
                item=dict(row)
                if item.get('deleted_at'): item['body']='Сообщение удалено отправителем'
                messages.append(item)
            return {'messages':messages},200
        if path=='/api/ai/analysis':
            if user['role']!='doctor': raise PermissionError('Анализ профиля доступен врачу')
            pid=q.get('patient_id',[None])[0]; p=get_patient(conn,user,pid)
            return ai_summary(conn,p),200
        raise LookupError('API endpoint не найден')

    def api_post(self,conn,path,b):
        if path=='/api/login':
            email=str(b.get('email','')).strip().lower()
            password=b.get('password','')
            if not isinstance(password,str) or not email or len(email)>254 or len(password)>1024:
                raise ValueError('Введите e-mail и пароль')
            user=conn.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
            if not user or not user['active'] or not verify_password(password,user['password_hash']):
                # Keep errors identical to limit account enumeration.
                raise PermissionError('Неверный e-mail или пароль')
            if user['role']=='patient':
                p=conn.execute('SELECT archived FROM patients WHERE user_id=?',(user['id'],)).fetchone()
                if not p or p['archived']: raise PermissionError('Учётная запись недоступна')
            raw=secrets.token_urlsafe(32); token_hash=hashlib.sha256(raw.encode()).hexdigest(); csrf=secrets.token_urlsafe(24)
            expires=(datetime.now(timezone.utc)+timedelta(hours=SESSION_HOURS)).replace(microsecond=0).isoformat()
            conn.execute('INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)',(token_hash,user['id'],csrf,expires,utc_now()))
            log_audit(conn,user['id'],'login','session',None,'successful login')
            conn.commit()
            secure='; Secure' if os.environ.get('CLINIC_HTTPS','0')=='1' else ''
            cookie=f'{COOKIE_NAME}={raw}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_HOURS*3600}{secure}'
            p=patient_for_user(conn,user['id']) if user['role']=='patient' else None
            out={'user':user_public(user),'csrf_token':csrf,'patient':patient_view(p) if p else None,'demo_mode':DEMO_MODE}
            return out,200,{'Set-Cookie':cookie}
        conn_user=self.require_user(conn,csrf=True)
        if path=='/api/logout':
            token_hash=hashlib.sha256(self._cookie_raw().encode()).hexdigest() if self._cookie_raw() else ''
            conn.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash,)); conn.commit()
            return {'ok':True},200,{'Set-Cookie':f'{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'}
        user=conn_user
        md=re.fullmatch(r'/api/patients/(\d+)/clinical-documents',path)
        if md:
            patient=get_patient(conn,user,md.group(1))
            if user['role']!='doctor': raise PermissionError('Прикреплять документы к клинической карте может врач')
            file_name=str(b.get('file_name') or 'document.pdf').replace('\\','/').split('/')[-1][:180]
            title=str(b.get('title') or '').strip()[:200]
            encoded=b.get('content_base64')
            if not isinstance(encoded,str) or len(encoded)>1900000: raise ValueError('PDF отсутствует или превышает допустимый размер')
            try: content=base64.b64decode(encoded,validate=True)
            except Exception: raise ValueError('Не удалось прочитать PDF-файл')
            if not content.startswith(b'%PDF-'): raise ValueError('Файл не похож на PDF-документ')
            if len(content)>1400000: raise ValueError('Размер PDF не должен превышать 1,4 МБ')
            sha=hashlib.sha256(content).hexdigest()
            cur=conn.execute('INSERT INTO clinical_documents(patient_id,uploaded_by,title,file_name,mime_type,size_bytes,sha256,content,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(patient['id'],user['id'],title,file_name,'application/pdf',len(content),sha,sqlite3.Binary(content),utc_now()))
            log_audit(conn,user['id'],'upload_clinical_pdf','clinical_document',cur.lastrowid,f'patient_id={patient["id"]}; size={len(content)}; sha256={sha}')
            conn.commit()
            return {'ok':True,'document_id':cur.lastrowid,'message':'PDF прикреплён к клинической карте'},201,{}
        # Persisted notification inbox and mobile/web push registration.
        m=re.fullmatch(r'/api/notifications/(\d+)/read',path)
        if m:
            row=conn.execute('SELECT * FROM notifications WHERE id=? AND recipient_user_id=?',(int(m.group(1)),user['id'])).fetchone()
            if not row: raise LookupError('Уведомление не найдено')
            conn.execute('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=?',(utc_now(),row['id']))
            conn.commit(); return {'ok':True,'message':'Уведомление отмечено прочитанным.'},200,{}
        if path=='/api/push/vapid-public':
            # A public key is safe to expose; no subscription can be activated without server credentials.
            return {'configured':bool(os.environ.get('VAPID_PUBLIC_KEY','').strip()),'public_key':os.environ.get('VAPID_PUBLIC_KEY','').strip()},200,{}
        if path=='/api/push/subscribe':
            sub=b.get('subscription')
            if not isinstance(sub,dict) or not isinstance(sub.get('endpoint'),str) or not sub['endpoint'].startswith('https://') or len(sub['endpoint'])>3000:
                raise ValueError('Некорректная push-подписка; ожидается HTTPS endpoint.')
            keys=sub.get('keys')
            if not isinstance(keys,dict) or not all(isinstance(keys.get(k),str) and len(keys[k])<512 for k in ('p256dh','auth')):
                raise ValueError('В push-подписке отсутствуют ключи p256dh/auth.')
            payload=json.dumps(sub,ensure_ascii=False,separators=(',',':'))
            conn.execute('INSERT INTO push_subscriptions(user_id,endpoint,subscription_json,platform,created_at,last_seen) VALUES(?,?,?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,subscription_json=excluded.subscription_json,platform=excluded.platform,last_seen=excluded.last_seen',
                (user['id'],sub['endpoint'],payload,str(b.get('platform','web'))[:30],utc_now(),utc_now()))
            log_audit(conn,user['id'],'register_push','push_subscription',None,str(b.get('platform','web'))); conn.commit()
            return {'ok':True,'configured':bool(os.environ.get('VAPID_PRIVATE_KEY','').strip()),'message':'Подписка сохранена. Отправка push требует настройки VAPID на сервере.'},201,{}
        if path=='/api/mobile/register':
            token=str(b.get('token','')).strip(); platform=str(b.get('platform','android')).strip().lower()
            if platform not in ('android','ios') or not token or len(token)>4096 or any(ord(c)<32 for c in token):
                raise ValueError('Некорректный mobile push token.')
            conn.execute('INSERT INTO mobile_push_tokens(user_id,token,platform,created_at,last_seen) VALUES(?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET user_id=excluded.user_id,platform=excluded.platform,last_seen=excluded.last_seen',
                (user['id'],token,platform,utc_now(),utc_now()))
            log_audit(conn,user['id'],'register_mobile_push','mobile_push_token',None,platform); conn.commit()
            return {'ok':True,'configured':bool(os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON','').strip()),'message':'Токен сохранён. Фоновая доставка требует настройки Firebase Admin на сервере.'},201,{}
        # Chat is optional, but messages are never silently dropped when a user disabled it.
        m=re.fullmatch(r'/api/patients/(\d+)/preferences',path)
        if m:
            p=get_patient(conn,user,m.group(1)); current=patient_preferences(conn,p['id'])
            if user['role']=='patient':
                allowed={'chat_enabled','chat_mode','notification_preferences'}
                if not set(b).issubset(allowed): raise ValueError('Неизвестное поле настроек.')
                next_enabled=bool(b.get('chat_enabled',current['chat_enabled']))
                next_mode=b.get('chat_mode',current['chat_mode'])
                if next_mode not in ('off','async','standard'): raise ValueError('Режим чата должен быть off, async или standard.')
                notif=b.get('notification_preferences',current['notification_preferences'])
            else:
                if not set(b).issubset({'chat_enabled','chat_mode','notification_preferences'}): raise ValueError('Неизвестное поле настроек.')
                next_enabled=bool(b.get('chat_enabled',current['chat_enabled']))
                next_mode=b.get('chat_mode',current['chat_mode'])
                if next_mode not in ('off','async','standard'): raise ValueError('Режим чата должен быть off, async или standard.')
                notif=b.get('notification_preferences',current['notification_preferences'])
            if not isinstance(notif,dict) or len(json.dumps(notif,ensure_ascii=False))>5000: raise ValueError('Некорректные настройки уведомлений.')
            conn.execute('UPDATE patient_preferences SET chat_enabled=?,chat_mode=?,notification_preferences_json=?,updated_by=?,updated_at=? WHERE patient_id=?',
                (int(next_enabled),next_mode,json.dumps(notif,ensure_ascii=False),user['id'],utc_now(),p['id']))
            log_audit(conn,user['id'],'update_preferences','patient',p['id']); conn.commit()
            return {'ok':True,'preferences':patient_preferences(conn,p['id'])},200,{}
        # One structured encounter is the source of truth for the clinical map, JSON/FHIR and DICOM SR.
        m=re.fullmatch(r'/api/patients/(\d+)/clinical-assessments',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Структурированную клиническую оценку может оформлять только врач.')
            p=get_patient(conn,user,m.group(1))
            mental=b.get('mental_state',{})
            allowed_domains={'mood','affect','thought_content','perception','sleep','activity','functioning','insight','suicide_risk','adherence','social_support','side_effects','psychosis'}
            allowed_values={'not_assessed','not_reported','possible','observed','not_applicable','improving','stable','worsening','good','partial','poor','unknown','absent','present','low','moderate','high','needs_review','not_applicable'}
            if not isinstance(mental,dict) or not set(mental).issubset(allowed_domains): raise ValueError('Некорректная клиническая карта: проверьте домены.')
            if any(v not in allowed_values for v in mental.values()): raise ValueError('Некорректное значение в клинической карте.')
            summary=str(b.get('summary','')).strip(); plan_notes=str(b.get('plan_notes','')).strip()
            if len(summary)>8000 or len(plan_notes)>8000: raise ValueError('Текст оценки слишком длинный.')
            assessment_date=str(b.get('assessed_at') or utc_now())
            try: datetime.fromisoformat(assessment_date.replace('Z','+00:00'))
            except ValueError: raise ValueError('Дата оценки должна быть ISO 8601.')
            visit_date=str(b.get('visit_date') or local_date())
            try: date.fromisoformat(visit_date)
            except ValueError: raise ValueError('Некорректная дата приёма.')
            followup_date=str(b.get('followup_date') or '').strip() or None
            if followup_date:
                try: date.fromisoformat(followup_date)
                except ValueError: raise ValueError('Некорректная дата follow-up.')
                if followup_date<visit_date: raise ValueError('Дата follow-up не может быть раньше даты приёма.')
            visit_kind=str(b.get('visit_kind') or 'Структурированная оценка')[:120]
            visit_notes=str(b.get('visit_notes') or summary)[:8000]
            signed=b.get('sign') is True
            needs_safety_review=any(mental.get(k) in ('possible','observed','present','high','needs_review') for k in ('thought_content','perception','psychosis','suicide_risk'))
            if signed and needs_safety_review and b.get('safety_review') is not True:
                raise ValueError('Перед подписанием оценки с защитно значимым доменом подтвердите отдельную проверку безопасности.')
            cur=conn.execute('INSERT INTO visits(patient_id,visit_date,kind,notes,followup_date,author_user_id,created_at) VALUES(?,?,?,?,?,?,?)',
                (p['id'],visit_date,visit_kind,visit_notes,followup_date,user['id'],utc_now()))
            visit_id=cur.lastrowid
            cur=conn.execute('INSERT INTO clinical_assessments(patient_id,visit_id,assessed_at,mental_state_json,summary,plan_notes,assessor_user_id,signed_by,signed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (p['id'],visit_id,assessment_date,json.dumps(mental,ensure_ascii=False),summary,plan_notes,user['id'],user['id'] if signed else None,utc_now() if signed else None,utc_now()))
            assessment_id=cur.lastrowid
            # Conservative safety flags: require human confirmation; these are not diagnostic classifiers.
            red_keys={'thought_content','perception','psychosis','suicide_risk'}
            suspicious=any(mental.get(k) in ('possible','observed','present','high','needs_review') for k in red_keys)
            if suspicious:
                create_alert(conn,p['id'],'clinical_assessment',assessment_id,'urgent','Клиническая карта: отмечен домен, требующий проверки','Врач отметил возможные психотические/суицидальные или иные защитно значимые признаки. Проведите прямую оценку и зафиксируйте решение; технический флаг не является диагнозом.',recipient='doctor',rule_id='clinical_map_review')
            log_audit(conn,user['id'],'create_clinical_assessment','clinical_assessment',assessment_id,'signed' if signed else 'draft'); conn.commit()
            return {'ok':True,'visit_id':visit_id,'assessment_id':assessment_id,'signed':signed,'message':'Единая клиническая оценка и запись приёма сохранены. Все экспорты формируются из этой записи.'},201,{}
        # Versioned guideline schemes become available as structured care plans, but not active until a doctor signs them.
        if path=='/api/care-plans':
            if user['role']!='doctor': raise PermissionError('Создавать планы ведения может только врач.')
            p=get_patient(conn,user,b.get('patient_id')); sid=str(b.get('scheme_id',''))
            scheme=load_treatment_scheme(sid)
            start=str(b.get('start_date') or local_date()); review=str(b.get('review_date') or '') or None
            try: date.fromisoformat(start)
            except ValueError: raise ValueError('Некорректная дата начала плана.')
            if review:
                try: date.fromisoformat(review)
                except ValueError: raise ValueError('Некорректная дата пересмотра.')
                if review<start: raise ValueError('Дата пересмотра не может быть раньше даты начала.')
            notes=str(b.get('notes','')).strip()
            if len(notes)>8000: raise ValueError('Примечание слишком длинное.')
            activate=b.get('activate') is True
            if activate and (b.get('confirm_review') is not True or b.get('safety_review') is not True): raise ValueError('Для активации требуется отдельное подтверждение клинической пригодности и проверки безопасности.')
            configuration=validate_scheme_configuration(scheme,b.get('configuration',{}),activating=activate)
            plan=json.loads(json.dumps(scheme,ensure_ascii=False))
            plan['configuration']=configuration
            plan['configuration_fields']=scheme.get('configuration_fields',[])
            for step in plan.get('steps',[]): step['status']='pending'
            status='active' if activate else 'draft'
            cur=conn.execute('INSERT INTO care_plans(patient_id,scheme_id,scheme_version,title,plan_json,status,start_date,review_date,notes,created_by,approved_by,approved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (p['id'],sid,scheme.get('version','1.0.0'),scheme['title'],json.dumps(plan,ensure_ascii=False),status,start,review,notes,user['id'],user['id'] if activate else None,utc_now() if activate else None,utc_now(),utc_now()))
            care_id=cur.lastrowid
            log_audit(conn,user['id'],'activate_care_plan' if activate else 'draft_care_plan','care_plan',care_id,sid)
            if activate:
                create_notification(conn,p['id'],'patient','care_plan',care_id,'info','План ведения подтверждён врачом',f'Врач активировал план: {scheme["title"]}. Откройте раздел «Мои планы» и обсудите вопросы с врачом.')
            conn.commit()
            return {'ok':True,'care_plan_id':care_id,'status':status,'message':'План активирован и виден пациенту.' if activate else 'Черновик плана сохранён; пациент его не видит.'},201,{}
        m=re.fullmatch(r'/api/care-plans/(\d+)/configuration',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Настраивать параметры плана может только врач.')
            row=conn.execute('SELECT * FROM care_plans WHERE id=?',(int(m.group(1)),)).fetchone()
            if not row: raise LookupError('План ведения не найден.')
            p=get_patient(conn,user,row['patient_id'])
            scheme=load_treatment_scheme(row['scheme_id'])
            plan=json.loads(row['plan_json'] or '{}')
            activating=row['status']=='active'
            if activating and (b.get('confirm_review') is not True or b.get('safety_review') is not True):
                raise ValueError('Изменение активного плана требует повторного подтверждения врачом и проверки безопасности.')
            configuration=validate_scheme_configuration(scheme,b.get('configuration',{}),activating=activating)
            plan['configuration']=configuration
            plan['configuration_fields']=scheme.get('configuration_fields',[])
            notes=str(b.get('notes',row['notes'] or '')).strip()
            if len(notes)>8000: raise ValueError('Примечание слишком длинное.')
            review=str(b.get('review_date',row['review_date'] or '')).strip() or None
            if review:
                try: date.fromisoformat(review)
                except ValueError: raise ValueError('Некорректная дата пересмотра.')
                if review<row['start_date']: raise ValueError('Дата пересмотра не может быть раньше даты начала.')
            conn.execute('UPDATE care_plans SET plan_json=?,notes=?,review_date=?,updated_at=? WHERE id=?',
                (json.dumps(plan,ensure_ascii=False),notes,review,utc_now(),row['id']))
            log_audit(conn,user['id'],'configure_care_plan','care_plan',row['id'],json.dumps(configuration,ensure_ascii=False)[:1500])
            conn.commit()
            return {'ok':True,'message':'Параметры этого плана сохранены. Они не изменяют другие экземпляры схемы.'},200,{}
        m=re.fullmatch(r'/api/care-plans/(\d+)/status',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Изменять статус плана может только врач.')
            row=conn.execute('SELECT * FROM care_plans WHERE id=?',(int(m.group(1)),)).fetchone()
            if not row: raise LookupError('План ведения не найден.')
            p=get_patient(conn,user,row['patient_id']); status=b.get('status')
            if status not in ('active','paused','completed','stopped'): raise ValueError('Недопустимый статус плана.')
            plan=json.loads(row['plan_json'] or '{}')
            if status=='active':
                if b.get('confirm_review') is not True or b.get('safety_review') is not True: raise ValueError('Для активации/возобновления требуется повторный клинический и safety review.')
                scheme=load_treatment_scheme(row['scheme_id'])
                plan['configuration']=validate_scheme_configuration(scheme,plan.get('configuration',{}),activating=True)
                plan['configuration_fields']=scheme.get('configuration_fields',[])
                conn.execute('UPDATE care_plans SET plan_json=?,status=?,approved_by=?,approved_at=?,updated_at=? WHERE id=?',
                    (json.dumps(plan,ensure_ascii=False),status,user['id'],utc_now(),utc_now(),row['id']))
            else:
                conn.execute('UPDATE care_plans SET status=?,updated_at=? WHERE id=?',(status,utc_now(),row['id']))
            log_audit(conn,user['id'],'change_care_plan_status','care_plan',row['id'],status); conn.commit()
            return {'ok':True,'message':'Статус плана обновлён.'},200,{}
        m=re.fullmatch(r'/api/care-plans/(\d+)/step',path)
        if m:
            row=conn.execute('SELECT * FROM care_plans WHERE id=?',(int(m.group(1)),)).fetchone()
            if not row: raise LookupError('План ведения не найден.')
            p=get_patient(conn,user,row['patient_id'])
            if user['role']=='patient' and row['status']!='active': raise PermissionError('Отмечать шаги можно только в активном плане.')
            if user['role']=='doctor' and p['doctor_user_id']!=user['id']: raise PermissionError('Нет доступа к этому плану.')
            try: step_index=int(b.get('step_index'))
            except (TypeError,ValueError): raise ValueError('Укажите номер шага.')
            plan=json.loads(row['plan_json']); steps=plan.get('steps',[])
            if step_index<0 or step_index>=len(steps): raise ValueError('Номер шага вне диапазона.')
            next_status=b.get('status','completed')
            if next_status not in ('pending','completed','skipped','in_progress'): raise ValueError('Недопустимый статус шага.')
            steps[step_index]['status']=next_status; steps[step_index]['updated_at']=utc_now(); steps[step_index]['updated_by_role']=user['role']
            conn.execute('UPDATE care_plans SET plan_json=?,updated_at=? WHERE id=?',(json.dumps(plan,ensure_ascii=False),utc_now(),row['id']))
            log_audit(conn,user['id'],'update_care_plan_step','care_plan',row['id'],f'{step_index}:{next_status}'); conn.commit()
            return {'ok':True,'message':'Шаг плана отмечен.'},200,{}
        # Clinician-configurable red-flag rules: only existing rules can be changed through this UI.
        m=re.fullmatch(r'/api/patient-red-flags/(\d+)/([a-z0-9_-]+)',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Настройка доступна только врачу')
            p=get_patient(conn,user,m.group(1)); rule=conn.execute('SELECT * FROM red_flag_rules WHERE id=?',(m.group(2),)).fetchone()
            if not rule: raise LookupError('Правило не найдено')
            enabled=1 if b.get('enabled',True) else 0; severity=str(b.get('severity',rule['severity'])); recipient=str(b.get('recipient',rule['recipient']))
            if severity not in ('info','review','urgent','critical') or recipient not in ('doctor','patient','both','care_team'): raise ValueError('Проверьте приоритет и получателя')
            conn.execute('INSERT INTO patient_red_flag_overrides(patient_id,rule_id,enabled,severity,recipient,updated_by,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(patient_id,rule_id) DO UPDATE SET enabled=excluded.enabled,severity=excluded.severity,recipient=excluded.recipient,updated_by=excluded.updated_by,updated_at=excluded.updated_at',(p['id'],rule['id'],enabled,severity,recipient,user['id'],utc_now()))
            log_audit(conn,user['id'],'configure_patient_red_flag','patient_red_flag_override',f'{p["id"]}:{rule["id"]}',json.dumps({'enabled':bool(enabled),'severity':severity,'recipient':recipient},ensure_ascii=False));conn.commit()
            return {'ok':True,'message':'Настройка сигнала для пациента сохранена.'},200,{}
        m=re.fullmatch(r'/api/red-flags/([a-z0-9_-]+)',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Настраивать red flags может только врач.')
            rule_row=conn.execute('SELECT * FROM red_flag_rules WHERE id=?',(m.group(1),)).fetchone()
            if not rule_row: raise LookupError('Правило не найдено.')
            title=str(b.get('title',rule_row['title'])).strip()[:200]
            if len(title)<3: raise ValueError('Название правила должно содержать не менее 3 символов.')
            severity=b.get('severity',rule_row['severity']); recipient=b.get('recipient',rule_row['recipient'])
            enabled=bool(b.get('enabled',rule_row['enabled']))
            if severity not in ('info','review','urgent','critical'): raise ValueError('Недопустимый уровень флага.')
            if recipient not in ('doctor','patient','both'): raise ValueError('Допустимые получатели: врач, пациент, врач и пациент. Команда ухода пока не реализована.')
            rule=json.loads(rule_row['rule_json'])
            if 'patterns' in b:
                patterns=b['patterns']
                if not isinstance(patterns,list) or len(patterns)>100 or any(not isinstance(x,str) or len(x)>150 for x in patterns): raise ValueError('patterns должен быть списком строк до 150 символов.')
                rule['patterns']=[x.strip() for x in patterns if x.strip()]
            if 'items' in b:
                items=b['items']
                if not isinstance(items,list) or len(items)>100: raise ValueError('items должен быть списком объектов.')
                for it in items:
                    if not isinstance(it,dict) or not isinstance(it.get('question_id'),str) or not isinstance(it.get('values'),list): raise ValueError('Некорректный элемент правила questionnaire.')
                rule['items']=items
            rule.update({'id':rule_row['id'],'title':title,'severity':severity,'recipient':recipient,'enabled':enabled})
            conn.execute('UPDATE red_flag_rules SET title=?,enabled=?,severity=?,recipient=?,rule_json=?,updated_by=?,updated_at=? WHERE id=?',
                (title,int(enabled),severity,recipient,json.dumps(rule,ensure_ascii=False),user['id'],utc_now(),rule_row['id']))
            log_audit(conn,user['id'],'update_red_flag_rule','red_flag_rule',rule_row['id']); conn.commit()
            return {'ok':True,'message':'Правило red flag обновлено.'},200,{}
        # Structured adverse-event capture makes every symptom and severity visible to both roles.
        if path=='/api/adverse-events':
            pid=b.get('patient_id')
            if user['role']=='patient':
                patient=patient_for_user(conn,user['id']); pid=patient['id'] if patient else None
            p=get_patient(conn,user,pid)
            medication_plan_id=b.get('medication_plan_id')
            if medication_plan_id:
                plan_row=conn.execute('SELECT id FROM medication_plans WHERE id=? AND patient_id=? AND status IN (?,?,?)',(medication_plan_id,p['id'],'active','paused','stopped')).fetchone()
                if not plan_row: raise ValueError('Выбранная схема не относится к пациенту.')
                medication_plan_id=plan_row['id']
            symptoms=b.get('symptoms',[])
            permitted_symptoms={'nausea','vomiting','diarrhea','constipation','dizziness','drowsiness','agitation','confusion','insomnia','nightmares','sexual_function','palpitations','chest_pain','rash','swelling','breathing_difficulty','bleeding','seizure','suicidal_thoughts','manic_symptoms','weight_change','headache','dry_mouth','tremor','other'}
            if not isinstance(symptoms,list) or not symptoms or len(symptoms)>30 or any(x not in permitted_symptoms for x in symptoms): raise ValueError('Выберите хотя бы один симптом из списка.')
            severity=b.get('severity','unknown')
            if severity not in ('mild','moderate','severe','life_threatening','unknown'): raise ValueError('Некорректная выраженность реакции.')
            onset=str(b.get('onset_at') or utc_now())
            try: datetime.fromisoformat(onset.replace('Z','+00:00'))
            except ValueError: raise ValueError('Дата начала симптомов должна быть ISO 8601.')
            description=str(b.get('description','')).strip(); action_taken=str(b.get('action_taken','')).strip()
            if max(len(description),len(action_taken))>5000: raise ValueError('Описание слишком длинное.')
            serious=bool(b.get('serious')) or severity in ('severe','life_threatening') or any(x in symptoms for x in ('breathing_difficulty','chest_pain','seizure','swelling','bleeding','suicidal_thoughts'))
            cur=conn.execute('INSERT INTO adverse_events(patient_id,medication_plan_id,reported_by,onset_at,symptoms_json,severity,serious,description,action_taken,outcome,clinician_assessment,review_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (p['id'],medication_plan_id,user['id'],onset,json.dumps(symptoms),severity,int(serious),description,action_taken,'','','pending',utc_now()))
            event_id=cur.lastrowid
            apply_adverse_event_rules(conn,p['id'],event_id,severity,serious,symptoms)
            if severity=='life_threatening' or any(x in symptoms for x in ('breathing_difficulty','chest_pain','seizure','swelling')):
                create_notification(conn,p['id'],'patient','adverse_event',event_id,'critical','Симптомы могут требовать экстренной оценки','Если симптомы тяжёлые, быстро ухудшаются или угрожают жизни, немедленно обращайтесь в местную экстренную службу; не ждите ответа в приложении.',rule_id='adverse_event_emergency')
            log_audit(conn,user['id'],'report_adverse_event','adverse_event',event_id,severity); conn.commit()
            return {'ok':True,'event_id':event_id,'serious':serious,'message':'Нежелательная реакция сохранена и направлена по настроенным правилам уведомления. Не меняйте лечение без связи с врачом.','emergency_message':'При тяжёлом затруднении дыхания, боли в груди, судорогах, быстро распространяющемся отёке или непосредственной угрозе жизни обратитесь в экстренную службу; не ждите ответа в чате.' if severity=='life_threatening' or any(x in symptoms for x in ('breathing_difficulty','chest_pain','seizure','swelling')) else None},201,{}
        m=re.fullmatch(r'/api/adverse-events/(\d+)/review',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Проверку нежелательной реакции проводит врач.')
            ev=conn.execute('SELECT * FROM adverse_events WHERE id=?',(int(m.group(1)),)).fetchone()
            if not ev: raise LookupError('Нежелательная реакция не найдена.')
            p=get_patient(conn,user,ev['patient_id'])
            status=b.get('review_status','reviewed')
            if status not in ('reviewed','closed','pending'): raise ValueError('Недопустимый статус проверки.')
            assessment=str(b.get('clinician_assessment','')).strip(); outcome=str(b.get('outcome','')).strip()
            if max(len(assessment),len(outcome))>6000: raise ValueError('Комментарий проверки слишком длинный.')
            conn.execute('UPDATE adverse_events SET review_status=?,clinician_assessment=?,outcome=?,reviewed_by=?,reviewed_at=? WHERE id=?',
                (status,assessment,outcome,user['id'],utc_now(),ev['id']))
            if status=='closed': conn.execute('UPDATE alerts SET status="resolved",acknowledged_by=?,acknowledged_at=? WHERE source_type="adverse_event" AND source_id=?',(user['id'],utc_now(),ev['id']))
            log_audit(conn,user['id'],'review_adverse_event','adverse_event',ev['id'],status); conn.commit()
            return {'ok':True,'message':'Проверка нежелательной реакции сохранена.'},200,{}
        # Study metadata link. Pixel data remain in PACS/DICOMweb; this endpoint does not store DICOM objects.
        m=re.fullmatch(r'/api/patients/(\d+)/imaging-studies',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Добавлять исследования может врач.')
            p=get_patient(conn,user,m.group(1)); study_uid=_external_uid(b.get('study_uid'))
            modality=str(b.get('modality') or 'OT').upper()
            if not re.fullmatch(r'[A-Z0-9]{1,16}',modality): raise ValueError('Некорректная модальность DICOM.')
            study_date=str(b.get('study_date') or '') or None
            if study_date:
                try: date.fromisoformat(study_date)
                except ValueError: raise ValueError('study_date должна быть YYYY-MM-DD.')
            metadata=b.get('metadata',{})
            if not isinstance(metadata,dict) or len(json.dumps(metadata,ensure_ascii=False))>20000: raise ValueError('Метаданные исследования некорректны/слишком велики.')
            endpoint=str(b.get('endpoint','')).strip()
            if endpoint and not endpoint.startswith('https://') and not endpoint.startswith('http://localhost') and not endpoint.startswith('http://127.0.0.1'):
                raise ValueError('DICOMweb endpoint должен использовать HTTPS (кроме локального теста).')
            values=(p['id'],study_uid,modality,study_date,str(b.get('accession_number',''))[:64],str(b.get('description',''))[:200],b.get('number_of_series'),b.get('number_of_instances'),endpoint,str(b.get('source_system') or 'manual_manifest')[:100],json.dumps(metadata,ensure_ascii=False),user['id'],utc_now(),utc_now())
            conn.execute('INSERT INTO imaging_studies(patient_id,study_uid,modality,study_date,accession_number,description,number_of_series,number_of_instances,endpoint,source_system,metadata_json,imported_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(patient_id,study_uid) DO UPDATE SET modality=excluded.modality,study_date=excluded.study_date,accession_number=excluded.accession_number,description=excluded.description,number_of_series=excluded.number_of_series,number_of_instances=excluded.number_of_instances,endpoint=excluded.endpoint,source_system=excluded.source_system,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at',values)
            row=conn.execute('SELECT id FROM imaging_studies WHERE patient_id=? AND study_uid=?',(p['id'],study_uid)).fetchone()
            log_audit(conn,user['id'],'link_imaging_study','imaging_study',row['id'],study_uid); conn.commit()
            return {'ok':True,'study_id':row['id'],'message':'Метаданные исследования связаны с карточкой; сами пиксельные данные остаются в PACS/DICOMweb.'},201,{}
        # CSV import: explicit mapped rows, immutable source IDs and idempotent repeated imports.
        m=re.fullmatch(r'/api/patients/(\d+)/exchange/csv/import',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Импортировать внешние базы может врач.')
            p=get_patient(conn,user,m.group(1)); source_system=str(b.get('source_system') or '').strip()
            records=b.get('records',[])
            if not re.fullmatch(r'[A-Za-z0-9_.-]{2,80}',source_system): raise ValueError('source_system обязателен и должен быть стабильным.')
            if not isinstance(records,list) or not records or len(records)>1000: raise ValueError('Передайте 1–1000 строк после предпросмотра.')
            imported=skipped=0
            for item in records:
                if not isinstance(item,dict): raise ValueError('Каждая строка должна быть объектом.')
                external_id=str(item.get('external_id') or '').strip()
                if not external_id or len(external_id)>200: raise ValueError('Каждой строке нужен внешний ID.')
                content={'entry_date':item.get('entry_date') or local_date(),'entry_type':item.get('entry_type') or 'external_observation','data':item.get('data') or {}}
                existing=source_exists(conn,p['id'],source_system,'Entry',external_id)
                digest=_json_hash(content)
                if existing:
                    skipped+=1; continue
                try: date.fromisoformat(str(content['entry_date']))
                except ValueError: raise ValueError(f'Некорректная дата в записи {external_id}.')
                if content['entry_type'] not in ('mood','food','checklist','external_observation','external_note'): raise ValueError('Импорт допускает mood, food, checklist, external_observation или external_note.')
                if not isinstance(content['data'],dict) or len(json.dumps(content['data'],ensure_ascii=False))>8000: raise ValueError(f'Некорректные данные в записи {external_id}.')
                cur=conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',(p['id'],user['id'],content['entry_type'],content['entry_date'],json.dumps({**content['data'],'source_system':source_system,'external_id':external_id,'imported':True},ensure_ascii=False),utc_now()))
                record_import(conn,p['id'],source_system,'Entry',external_id,digest,'entries',cur.lastrowid,user['id']); imported+=1
            log_audit(conn,user['id'],'import_csv','patient',p['id'],f'{source_system}; imported={imported}; skipped={skipped}'); conn.commit()
            return {'ok':True,'imported':imported,'skipped_duplicates':skipped,'message':f'Импортировано строк: {imported}; пропущено повторов: {skipped}.'},200,{}
        # FHIR R4 import supports selected resources; external resources are never silently activated as treatment.
        m=re.fullmatch(r'/api/patients/(\d+)/exchange/fhir/import',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Импорт FHIR выполняет врач.')
            p=get_patient(conn,user,m.group(1)); payload=b.get('bundle')
            if not isinstance(payload,dict) or payload.get('resourceType')!='Bundle' or not isinstance(payload.get('entry'),list): raise ValueError('Ожидается FHIR R4 Bundle с entry[].')
            source_system=str(b.get('source_system') or 'fhir_external').strip()
            if not re.fullmatch(r'[A-Za-z0-9_.:-]{2,100}',source_system): raise ValueError('Некорректный source_system.')
            entries=payload['entry']
            if len(entries)>1000: raise ValueError('Bundle слишком большой: максимум 1000 ресурсов.')
            imported=skipped=unsupported=0
            for entry in entries:
                resource=entry.get('resource') if isinstance(entry,dict) else None
                if not isinstance(resource,dict): unsupported+=1; continue
                rtype=resource.get('resourceType'); external_id=str(resource.get('id') or resource_external_id(resource) or '').strip()
                if not external_id: external_id=_json_hash(resource)[:32]
                if len(external_id)>200: external_id=external_id[:200]
                digest=_json_hash(resource)
                if source_exists(conn,p['id'],source_system,str(rtype),external_id): skipped+=1; continue
                target_table='entries'; target_id=None
                if rtype=='ImagingStudy':
                    uid=''
                    for ident in resource.get('identifier',[]):
                        if 'dicom' in str(ident.get('system','')).lower() or str(ident.get('value','')).startswith('urn:oid:'):
                            uid=str(ident.get('value','')).removeprefix('urn:oid:'); break
                    if not uid: uid=(resource.get('series') or [{}])[0].get('instance', [{}])[0].get('uid') or ''
                    if not uid: unsupported+=1; continue
                    uid=_external_uid(uid)
                    metadata={'status':resource.get('status'),'description':resource.get('description'),'series':resource.get('series',[]),'identifier':resource.get('identifier',[])}
                    conn.execute('INSERT INTO imaging_studies(patient_id,study_uid,modality,study_date,accession_number,description,number_of_series,number_of_instances,endpoint,source_system,metadata_json,imported_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(patient_id,study_uid) DO UPDATE SET metadata_json=excluded.metadata_json,updated_at=excluded.updated_at',
                        (p['id'],uid,','.join((s.get('modality') or 'OT') for s in resource.get('series',[])[:5]) or 'OT',str(resource.get('started',''))[:10] or None,'',str(resource.get('description',''))[:200],len(resource.get('series',[])),sum(len(s.get('instance',[])) for s in resource.get('series',[])),'',source_system,json.dumps(metadata,ensure_ascii=False),user['id'],utc_now(),utc_now()))
                    studyrow=conn.execute('SELECT id FROM imaging_studies WHERE patient_id=? AND study_uid=?',(p['id'],uid)).fetchone(); target_table='imaging_studies'; target_id=studyrow['id']
                elif rtype in ('Observation','QuestionnaireResponse','DiagnosticReport','DocumentReference'):
                    d=resource.get('effectiveDateTime') or resource.get('authored') or resource.get('issued') or utc_now()
                    try: entry_date=str(d)[:10]; date.fromisoformat(entry_date)
                    except ValueError: entry_date=local_date()
                    cur=conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',(p['id'],user['id'],'external_observation',entry_date,json.dumps({'resourceType':rtype,'resource':resource,'source_system':source_system,'external_id':external_id,'imported':True},ensure_ascii=False),utc_now()))
                    target_id=cur.lastrowid
                elif rtype=='MedicationRequest':
                    drug=(resource.get('medicationCodeableConcept') or {}).get('text') or ((resource.get('medicationCodeableConcept') or {}).get('coding') or [{}])[0].get('display') or 'Внешнее лекарственное назначение'
                    dosage='; '.join(x.get('text','') for x in resource.get('dosageInstruction',[]) if x.get('text')) or 'Импортировано из FHIR; требуется проверка врачом'
                    cur=conn.execute('INSERT INTO medication_plans(patient_id,drug_id,drug_name,regimen,times_json,start_date,end_date,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(p['id'],'external_'+_json_hash(resource)[:12],str(drug)[:250],dosage,'[]',local_date(),None,'Внешний импорт: не активировать до сверки с оригиналом и врачебного подтверждения. FHIR status: '+str(resource.get('status','unknown')),'draft',user['id'],utc_now()))
                    target_table='medication_plans'; target_id=cur.lastrowid
                elif rtype=='CarePlan':
                    scheme={'resourceType':'CarePlan','imported_resource':resource,'steps':[],'limits':['Внешний план импортирован как черновик; проверьте источник и не считайте активным клиническим планом.']}
                    cur=conn.execute('INSERT INTO care_plans(patient_id,scheme_id,scheme_version,title,plan_json,status,start_date,notes,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(p['id'],'external_fhir','unknown',str(resource.get('title') or 'Импортированный CarePlan')[:200],json.dumps(scheme,ensure_ascii=False),'draft',local_date(),'Внешний FHIR импорт; требует проверки врача.',user['id'],utc_now(),utc_now()))
                    target_table='care_plans'; target_id=cur.lastrowid
                elif rtype=='AdverseEvent':
                    codes=resource.get('event',{}).get('coding',[]) if isinstance(resource.get('event'),dict) else []
                    symptoms=[str(c.get('code') or c.get('display') or 'other') for c in codes[:25]] or ['other']
                    symptoms=[s if s in {'nausea','vomiting','diarrhea','constipation','dizziness','drowsiness','agitation','confusion','insomnia','nightmares','sexual_function','palpitations','chest_pain','rash','swelling','breathing_difficulty','bleeding','seizure','suicidal_thoughts','manic_symptoms','weight_change','headache','dry_mouth','tremor','other'} else 'other' for s in symptoms]
                    severity_code=(resource.get('seriousness') or {}).get('coding',[{}])[0].get('code','') if isinstance(resource.get('seriousness'),dict) else ''
                    sev='unknown'
                    if severity_code in ('fatal','life-threatening'): sev='life_threatening'
                    elif severity_code in ('hospitalization','disabling'): sev='severe'
                    cur=conn.execute('INSERT INTO adverse_events(patient_id,reported_by,onset_at,symptoms_json,severity,serious,description,review_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(p['id'],user['id'],str(resource.get('date') or utc_now()),json.dumps(symptoms),sev,int(sev in ('severe','life_threatening')),str(resource.get('description') or 'Импортировано из FHIR; требуется проверка.')[:5000],'pending',utc_now()))
                    target_table='adverse_events'; target_id=cur.lastrowid
                    create_alert(conn,p['id'],'adverse_event',target_id,'urgent' if sev in ('severe','life_threatening') else 'review','Импортированная нежелательная реакция требует проверки',f'FHIR AdverseEvent {external_id}; статус/причинность сверить с оригинальным ресурсом.',recipient='doctor',rule_id='fhir_import_adverse_event')
                else:
                    unsupported+=1; continue
                record_import(conn,p['id'],source_system,str(rtype),external_id,digest,target_table,target_id,user['id']); imported+=1
            log_audit(conn,user['id'],'import_fhir','patient',p['id'],f'{source_system}; imported={imported}; skipped={skipped}; unsupported={unsupported}'); conn.commit()
            return {'ok':True,'imported':imported,'skipped_duplicates':skipped,'unsupported':unsupported,'message':'Импорт завершён; лекарственные и лечебные планы остаются черновиками.'},200,{}
        if path=='/api/change-password':
            old=b.get('old_password',''); new=b.get('new_password','')
            dbu=conn.execute('SELECT * FROM users WHERE id=?',(user['id'],)).fetchone()
            if not verify_password(old,dbu['password_hash']): raise PermissionError('Текущий пароль не совпадает')
            if not isinstance(new,str) or len(new)<12 or len(new)>1024: raise ValueError('Новый пароль должен содержать не менее 12 символов')
            conn.execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?',(hash_password(new),user['id']))
            log_audit(conn,user['id'],'change_password','user',user['id']); conn.commit()
            return {'ok':True,'message':'Пароль изменён.'},200,{}
        m=re.fullmatch(r'/api/patients/(\d+)/restore',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Только врач может восстанавливать пациента из архива')
            row=conn.execute('SELECT p.*,u.email FROM patients p JOIN users u ON u.id=p.user_id WHERE p.id=? AND p.doctor_user_id=? AND p.archived=1',(int(m.group(1)),user['id'])).fetchone()
            if not row: raise LookupError('Архивная карточка не найдена или недоступна этому врачу')
            conn.execute('UPDATE patients SET archived=0 WHERE id=?',(row['id'],))
            conn.execute('UPDATE users SET active=1 WHERE id=?',(row['user_id'],))
            log_audit(conn,user['id'],'restore','patient',row['id'],'restore from archive')
            conn.commit()
            return {'ok':True,'patient':dict(patient_view(conn.execute('SELECT * FROM patients WHERE id=?',(row['id'],)).fetchone()),email=row['email']),'message':'Пациент восстановлен из архива. История сохранена.'},200,{}
        if path=='/api/patients':
            if user['role']!='doctor': raise PermissionError('Только врач может добавлять пациентов')
            name=str(b.get('full_name','')).strip(); email=str(b.get('email','')).strip().lower()
            if len(name)<2 or len(name)>200: raise ValueError('Введите имя пациента (2–200 символов)')
            if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email) or len(email)>254: raise ValueError('Введите корректный e-mail пациента')
            birth=str(b.get('birth_date','')).strip() or None
            if birth:
                try: date.fromisoformat(birth)
                except ValueError: raise ValueError('Дата рождения должна быть в формате ГГГГ-ММ-ДД')
                if birth>date.today().isoformat(): raise ValueError('Дата рождения не может быть в будущем')
            sex=b.get('sex','not_specified')
            if sex not in ('female','male','not_specified'): raise ValueError('Некорректное значение пола')
            if bool(b.get('menstrual_enabled',False)) and sex!='female': raise ValueError('Мониторинг цикла доступен только при выборе женского пола в профиле')
            initial=str(b.get('password','')).strip() or secrets.token_urlsafe(9)+'Aa!'
            if len(initial)<12 or len(initial)>128: raise ValueError('Начальный пароль должен содержать не менее 12 символов')
            cur=conn.execute('INSERT INTO users(email,display_name,role,password_hash,active,must_change_password,created_at) VALUES(?,?,?,?,1,1,?)',
                (email,name,'patient',hash_password(initial),utc_now()))
            uid=cur.lastrowid
            cur=conn.execute('''INSERT INTO patients(user_id,doctor_user_id,full_name,birth_date,sex,phone,notes,menstrual_enabled,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)''',(uid,user['id'],name,birth,sex,str(b.get('phone',''))[:80],str(b.get('notes',''))[:2000],int(bool(b.get('menstrual_enabled',False))),utc_now()))
            pid=cur.lastrowid; log_audit(conn,user['id'],'create','patient',pid); conn.commit()
            return {'patient':dict(patient_view(get_patient(conn,user,pid)),email=email),'initial_password':initial,'message':'Пациент добавлен. Передайте пароль по защищённому каналу и попросите его сменить.'},201,{}
        if path.startswith('/api/patients/') and path.endswith('/visits'):
            if user['role']!='doctor': raise PermissionError('Только врач может записывать приём')
            m=re.fullmatch(r'/api/patients/(\d+)/visits',path)
            if not m: raise LookupError('Маршрут не найден')
            p=get_patient(conn,user,m.group(1)); visit_date=str(b.get('visit_date') or local_date())
            try: date.fromisoformat(visit_date)
            except ValueError: raise ValueError('Некорректная дата приёма')
            kind=str(b.get('kind','Приём')).strip()[:120]; notes=str(b.get('notes','')).strip()
            if len(notes)>8000: raise ValueError('Заметка слишком длинная')
            follow=str(b.get('followup_date','')).strip() or None
            if follow:
                try: date.fromisoformat(follow)
                except ValueError: raise ValueError('Некорректная дата следующего приёма')
            conn.execute('INSERT INTO visits(patient_id,visit_date,kind,notes,followup_date,author_user_id,created_at) VALUES(?,?,?,?,?,?,?)',(p['id'],visit_date,kind,notes,follow,user['id'],utc_now()))
            log_audit(conn,user['id'],'create','visit',p['id']); conn.commit()
            return {'ok':True,'message':'Приём добавлен в историю.'},201,{}
        em=re.fullmatch(r'/api/entries/(\d+)/edit',path)
        if em:
            row=conn.execute('SELECT * FROM entries WHERE id=?',(int(em.group(1)),)).fetchone()
            if not row: raise LookupError('Запись не найдена')
            p=get_patient(conn,user,row['patient_id'])
            if user['role']=='patient' and int(row['author_user_id'])!=int(user['id']):
                raise PermissionError('Пациент может исправлять только собственные записи')
            kind=row['entry_type']
            if user['role']=='doctor' and kind not in ('doctor_note',):
                # A clinician may correct a patient record, with an explicit server audit trail.
                pass
            entry_date=str(b.get('entry_date') or row['entry_date'])
            try: date.fromisoformat(entry_date)
            except ValueError: raise ValueError('Дата записи должна быть в формате ГГГГ-ММ-ДД')
            payload=b.get('data',{})
            if not isinstance(payload,dict) or len(json.dumps(payload,ensure_ascii=False))>10000:
                raise ValueError('Проверьте содержание записи')
            if kind=='mood':
                mood=payload.get('mood'); sleep=payload.get('sleep_hours')
                if not isinstance(mood,int) or isinstance(mood,bool) or not 1<=mood<=10: raise ValueError('Настроение должно быть числом от 1 до 10')
                if sleep is not None and (not isinstance(sleep,(int,float)) or not 0<=sleep<=24): raise ValueError('Сон должен быть в диапазоне 0–24 часа')
            if kind=='wellbeing':
                if payload.get('polarity') not in ('positive','negative','neutral') or not isinstance(payload.get('tags',[]),list): raise ValueError('Проверьте тип изменения и выбранные пункты')
                if len(str(payload.get('notes','')))>2500: raise ValueError('Комментарий слишком длинный')
            previous={'entry_date':row['entry_date'],'data':json.loads(row['data_json'] or '{}')}
            updated={'entry_date':entry_date,'data':payload}
            conn.execute('UPDATE entries SET entry_date=?,data_json=? WHERE id=?',(entry_date,json.dumps(payload,ensure_ascii=False),row['id']))
            log_audit(conn,user['id'],'edit','entry',row['id'],json.dumps({'before':previous,'after':updated},ensure_ascii=False)[:4000])
            conn.commit()
            return {'ok':True,'message':'Запись исправлена; предыдущая версия сохранена в журнале сервера.'},200,{}
        if path=='/api/entries':
            if user['role']=='patient':
                p=patient_for_user(conn,user['id']); pid=p['id'] if p else None
                kind=str(b.get('entry_type',''))
                if kind not in ('mood','food','checklist','menstrual','side_effect','wellbeing'): raise PermissionError('Недопустимый тип записи пациента')
            else:
                pid=b.get('patient_id'); kind=str(b.get('entry_type',''))
                if kind not in ('doctor_note',): raise PermissionError('Врач добавляет клинические заметки через историю приёмов')
            p=get_patient(conn,user,pid)
            entry_date=str(b.get('entry_date') or local_date())
            try: date.fromisoformat(entry_date)
            except ValueError: raise ValueError('Дата записи должна быть в формате ГГГГ-ММ-ДД')
            payload=b.get('data',{})
            if not isinstance(payload,dict): raise ValueError('data должно быть объектом')
            if len(json.dumps(payload,ensure_ascii=False))>10000: raise ValueError('Запись слишком объёмная')
            if kind=='mood':
                mood=payload.get('mood')
                if not isinstance(mood,int) or isinstance(mood,bool) or not 1<=mood<=10: raise ValueError('Настроение должно быть числом от 1 до 10')
                sleep=payload.get('sleep_hours')
                if sleep is not None and (not isinstance(sleep,(int,float)) or not 0<=sleep<=24): raise ValueError('Сон должен быть в диапазоне 0–24 часа')
            if kind=='wellbeing':
                polarity=payload.get('polarity'); tags=payload.get('tags',[])
                if polarity not in ('positive','negative','neutral'): raise ValueError('Выберите тип изменения самочувствия')
                if not isinstance(tags,list) or len(tags)>30 or any(not isinstance(x,str) or len(x)>100 for x in tags): raise ValueError('Проверьте список отметок')
                if len(str(payload.get('notes','')))>2500: raise ValueError('Комментарий слишком длинный')
            if kind=='food':
                meals=payload.get('meals','')
                if not isinstance(meals,str) or len(meals)>4000: raise ValueError('Проверьте запись питания')
            if kind=='checklist':
                actions=payload.get('actions',[])
                if not isinstance(actions,list) or any(not isinstance(x,str) or len(x)>80 for x in actions): raise ValueError('Некорректный чек-лист')
            if kind=='menstrual':
                if not p['menstrual_enabled']: raise PermissionError('Сначала включите мониторинг цикла в настройках профиля')
                status=payload.get('status','')
                if status not in ('start','ongoing','end','symptoms'): raise ValueError('Некорректный тип записи цикла')
            cur=conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',(p['id'],user['id'],kind,entry_date,json.dumps(payload,ensure_ascii=False),utc_now()))
            apply_entry_red_flags(conn,p['id'],cur.lastrowid,kind,payload)
            log_audit(conn,user['id'],'create','entry',cur.lastrowid,kind); conn.commit()
            return {'ok':True,'entry_id':cur.lastrowid,'message':'Запись сохранена. Спасибо за этот шаг.'},201,{}
        m=re.fullmatch(r'/api/questionnaires/([a-z0-9_-]+)/submit',path)
        if m:
            qid=m.group(1); d=get_questionnaire(qid)
            if user['role']=='patient':
                if d['respondent']=='clinician': raise PermissionError('Эта шкала предназначена для врача')
                p=patient_for_user(conn,user['id']); pid=p['id'] if p else None
            else:
                pid=b.get('patient_id')
                # Clinician may enter clinician-rated scales and review self-report forms.
            p=get_patient(conn,user,pid)
            answers=b.get('answers',{})
            score=score_questionnaire(d,answers)
            result_created_at=utc_now()
            cur=conn.execute('''INSERT INTO questionnaire_results(patient_id,completed_by,questionnaire_id,questionnaire_title,version,answers_json,score_json,risk_flag,created_at)
              VALUES(?,?,?,?,?,?,?,?,?)''',(p['id'],user['id'],qid,d['title'],d['version'],json.dumps(answers,ensure_ascii=False),json.dumps(score,ensure_ascii=False),int(score.get('risk_flag',False)),result_created_at))
            result_id=cur.lastrowid
            alert_info=result_alert_info(d,answers,score)
            safety_message=None
            if alert_info:
                sev,title,detail=alert_info
                create_alert(conn,p['id'],'questionnaire',result_id,sev,title,detail)
                if user['role']=='patient' and sev in ('critical','urgent'):
                    safety_message='Ваш ответ может требовать срочного внимания специалиста. Если вы сейчас можете причинить себе вред или не уверены, что останетесь в безопасности, не ждите ответа в чате: позвоните в местную экстренную службу (в РФ — 112) или обратитесь в ближайшее отделение неотложной помощи и свяжитесь с лечащим врачом.'
            custom_flags=apply_questionnaire_red_flags(conn,p['id'],result_id,qid,answers)
            if custom_flags:
                # Persist matched configurable red flags with the questionnaire result itself,
                # so the risk marker remains visible in the result history, not only in alerts.
                score['risk_flag']=True
                score['red_flag_rules']=custom_flags
                conn.execute('UPDATE questionnaire_results SET score_json=?,risk_flag=1 WHERE id=?',
                    (json.dumps(score,ensure_ascii=False),result_id))
            if user['role']=='patient' and custom_flags and not safety_message:
                safety_message='Некоторые ответы отмечены правилом безопасности и переданы врачу для уточнения. Это не диагноз. Если вы сейчас не уверены в своей безопасности, не ждите ответа в чате и обратитесь за срочной помощью.'
            log_audit(conn,user['id'],'submit','questionnaire',result_id,qid); conn.commit()
            return {'ok':True,'result_id':result_id,'questionnaire_id':qid,'title':d['title'],'created_at':result_created_at,'score':score,'safety_message':safety_message,'message':'Результат сохранён в истории пациента.'},201,{}
        m=re.fullmatch(r'/api/appointments/(\d+)/status',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Менять статус приёма может только врач.')
            appointment=conn.execute('SELECT * FROM appointments WHERE id=?',(int(m.group(1)),)).fetchone()
            if not appointment: raise LookupError('Событие календаря не найдено.')
            patient=get_patient(conn,user,appointment['patient_id'])
            status=str(b.get('status','')).strip()
            if status not in ('scheduled','completed','missed','cancelled'):
                raise ValueError('Допустимые статусы: запланировано, завершено, не состоялось, отменено.')
            if appointment['status']=='rescheduled': raise ValueError('Этот слот уже перенесён; откройте новое событие.')
            conn.execute('UPDATE appointments SET status=? WHERE id=?',(status,appointment['id']))
            log_audit(conn,user['id'],'change_appointment_status','appointment',appointment['id'],status)
            if status=='missed':
                detail=f'Приём «{appointment["title"]}» на {appointment["starts_at"]} отмечен как не состоявшийся. Это отклонение от плана; свяжитесь с пациентом и согласуйте дальнейший контакт.'
                create_alert(conn,patient['id'],'appointment',appointment['id'],'review','Приём не состоялся',detail,recipient='doctor',rule_id='appointment_missed')
            elif status=='cancelled':
                create_notification(conn,patient['id'],'patient','appointment',appointment['id'],'info','Приём отменён',f'Врач отменил событие «{appointment["title"]}». Свяжитесь с врачом для согласования новой даты.')
            elif status=='completed':
                create_notification(conn,patient['id'],'patient','appointment',appointment['id'],'info','Приём отмечен как завершённый',f'Событие «{appointment["title"]}» отмечено врачом как завершённое.')
            conn.commit()
            return {'ok':True,'message':{'scheduled':'Статус события обновлён.','completed':'Приём отмечен как завершённый.','missed':'Приём отмечен как несостоявшийся; создан сигнал для последующего контакта.','cancelled':'Приём отменён; пациент уведомлён внутри приложения.'}[status]},200,{}
        m=re.fullmatch(r'/api/appointments/(\d+)/reschedule',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Переносить приём может только врач.')
            old=conn.execute('SELECT * FROM appointments WHERE id=?',(int(m.group(1)),)).fetchone()
            if not old: raise LookupError('Событие календаря не найдено.')
            patient=get_patient(conn,user,old['patient_id'])
            if old['status']!='scheduled':
                raise ValueError('Перенести можно только запланированный слот; завершённое/пропущенное событие остаётся в истории, для него создайте новый приём.')
            starts=str(b.get('starts_at','')).strip()
            try: new_dt=datetime.fromisoformat(starts)
            except ValueError: raise ValueError('Введите новую дату и время приёма.')
            ends=str(b.get('ends_at','')).strip() or None
            if ends:
                try: end_dt=datetime.fromisoformat(ends)
                except ValueError: raise ValueError('Некорректное время окончания.')
                if end_dt<=new_dt: raise ValueError('Время окончания должно быть позже начала.')
            reason=str(b.get('reason','')).strip()[:1500]
            if new_dt.isoformat(timespec='minutes')==old['starts_at'][:16]: raise ValueError('Новая дата и время совпадают с исходным слотом.')
            moved_note=f'Перенесено с {old["starts_at"]}. Причина: {reason or "не указана"}. Исходный слот сохранён в истории.'
            conn.execute('UPDATE appointments SET status=?,notes=? WHERE id=?',('rescheduled',(old['notes']+'\n'+moved_note).strip(),old['id']))
            cur=conn.execute('INSERT INTO appointments(patient_id,starts_at,ends_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (old['patient_id'],new_dt.isoformat(timespec='minutes'),end_dt.isoformat(timespec='minutes') if ends else None,old['kind'],old['title'],
                 (old['notes']+'\nПеренесено врачом. '+reason).strip(),'scheduled',user['id'],utc_now()))
            new_id=cur.lastrowid
            log_audit(conn,user['id'],'reschedule_appointment','appointment',old['id'],f'new_appointment_id={new_id}; reason={reason}')
            create_notification(conn,patient['id'],'patient','appointment',new_id,'info','Приём перенесён',f'Новая дата приёма «{old["title"]}»: {new_dt.strftime("%d.%m.%Y %H:%M")}. {reason}')
            conn.commit()
            return {'ok':True,'old_appointment_id':old['id'],'appointment_id':new_id,'message':'Приём перенесён. Исходный слот сохранён в истории.'},201,{}
        if path=='/api/calendar':
            requested_kind=str(b.get('kind','appointment'))
            if user['role']=='patient':
                p=patient_for_user(conn,user['id'])
                if not p: raise LookupError('Карточка пациента не найдена')
                if requested_kind!='personal': raise PermissionError('Пациент может добавлять только личные события')
                kind='personal'
            else:
                p=get_patient(conn,user,b.get('patient_id'))
                kind=requested_kind
                if kind not in ('appointment','reminder','call'): raise ValueError('Врач может создавать только клинические события и напоминания')
            starts=str(b.get('starts_at','')).strip()
            try: datetime.fromisoformat(starts)
            except ValueError: raise ValueError('Введите дату и время события')
            ends=str(b.get('ends_at','')).strip() or None
            if ends:
                try: datetime.fromisoformat(ends)
                except ValueError: raise ValueError('Некорректное время окончания')
                if ends<starts: raise ValueError('Окончание не может быть раньше начала')
            title=str(b.get('title','')).strip()
            if not title or len(title)>180: raise ValueError('Название события обязательно (до 180 символов)')
            notes=str(b.get('notes',''))[:4000]
            cur=conn.execute('INSERT INTO appointments(patient_id,starts_at,ends_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (p['id'],starts,ends,kind,title,notes,'scheduled',user['id'],utc_now()))
            event_id=cur.lastrowid
            log_audit(conn,user['id'],'create','appointment',event_id,kind); conn.commit()
            return {'ok':True,'event_id':event_id,'message':'Личное событие добавлено в календарь.' if kind=='personal' else 'Событие добавлено в календарь.'},201,{}
        if path=='/api/medication-plans':
            if user['role']!='doctor': raise PermissionError('Назначение оформляет только врач')
            p=get_patient(conn,user,b.get('patient_id'))
            drug_id=str(b.get('drug_id','')).strip(); meds=load_medications()
            drug=next((x for x in meds if x.get('id')==drug_id),None)
            if not drug: raise ValueError('Препарат отсутствует в подключённой библиотеке')
            regimen=str(b.get('regimen','')).strip(); notes=str(b.get('notes','')).strip()
            if not regimen or len(regimen)>1500: raise ValueError('Укажите схему/назначение (до 1500 символов)')
            start=str(b.get('start_date') or local_date()); end=str(b.get('end_date') or '').strip() or None
            try: date.fromisoformat(start)
            except ValueError: raise ValueError('Некорректная дата начала')
            if end:
                try: date.fromisoformat(end)
                except ValueError: raise ValueError('Некорректная дата окончания')
                if end<start: raise ValueError('Дата окончания раньше начала')
            times=b.get('times',[])
            if not isinstance(times,list) or len(times)>8 or any(not isinstance(t,str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',t) for t in times): raise ValueError('Время приёма должно быть в формате ЧЧ:ММ')
            if len(notes)>4000: raise ValueError('Примечание слишком длинное')
            confirm=b.get('confirm') is True
            if confirm and b.get('checked_grls') is not True: raise ValueError('Для подтверждения необходимо явно подтвердить проверку актуальной инструкции ГРЛС')
            if confirm and b.get('confirm_review') is not True: raise ValueError('Для активации требуется отдельное подтверждение врача')
            status='active' if confirm else 'draft'
            cur=conn.execute('''INSERT INTO medication_plans(patient_id,drug_id,drug_name,regimen,times_json,start_date,end_date,notes,status,created_by,approved_by,approved_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(p['id'],drug_id,drug['name'],regimen,json.dumps(times),start,end,notes,status,user['id'],user['id'] if confirm else None,utc_now() if confirm else None,utc_now()))
            log_audit(conn,user['id'],'confirm_prescription' if confirm else 'draft_prescription','medication_plan',cur.lastrowid,drug_id); conn.commit()
            if confirm:
                # Add one visible calendar reminder on start date; daily reminders derive from plan schedule.
                for t in (times[:1] or ['09:00']):
                    conn.execute('INSERT INTO appointments(patient_id,starts_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
                      (p['id'],f'{start}T{t}','reminder',f'Начало схемы: {drug["name"]}','Напоминание о назначенной схеме. Следуйте плану, подтверждённому врачом.','scheduled',user['id'],utc_now()))
                conn.commit()
            return {'ok':True,'plan_id':cur.lastrowid,'status':status,'message':'Назначение подтверждено врачом и сохранено.' if confirm else 'Черновик схемы сохранён; пациенту пока не виден.'},201,{}
        m=re.fullmatch(r'/api/medication-plans/(\d+)/status',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Изменять статус схемы может только врач')
            plan=conn.execute('SELECT * FROM medication_plans WHERE id=?',(int(m.group(1)),)).fetchone()
            if not plan: raise LookupError('Схема не найдена')
            p=get_patient(conn,user,plan['patient_id']); status=b.get('status')
            if status not in ('active','paused','stopped'): raise ValueError('Недопустимый статус схемы')
            old_status=plan['status']
            if status=='active':
                if b.get('checked_grls') is not True: raise ValueError('Перед активацией подтвердите проверку актуальной инструкции ГРЛС')
                if b.get('confirm_review') is not True: raise ValueError('Для активации требуется отдельное подтверждение врача')
                conn.execute('UPDATE medication_plans SET status=?,approved_by=?,approved_at=? WHERE id=?',(status,user['id'],utc_now(),plan['id']))
                times=json.loads(plan['times_json'] or '[]')
                start_time=times[0] if times else '09:00'
                reminder_title=f'Начало схемы: {plan["drug_name"]}'
                existing=conn.execute('SELECT id FROM appointments WHERE patient_id=? AND kind=? AND title=? AND starts_at=? AND status=?',
                    (plan['patient_id'],'reminder',reminder_title,f'{plan["start_date"]}T{start_time}','scheduled')).fetchone()
                if not existing:
                    conn.execute('INSERT INTO appointments(patient_id,starts_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
                        (plan['patient_id'],f'{plan["start_date"]}T{start_time}','reminder',reminder_title,
                         'Напоминание о начале назначенной схемы. Повторяющийся график показан отдельно и не создаёт отдельное событие на каждый день.','scheduled',user['id'],utc_now()))
            else:
                conn.execute('UPDATE medication_plans SET status=? WHERE id=?',(status,plan['id']))
            if status!=old_status:
                timestamp=utc_now()
                labels={'active':'возобновлена','paused':'приостановлена','stopped':'остановлена'}
                if old_status=='draft' and status=='active': action_title=f'Схема активирована: {plan["drug_name"]}'
                else: action_title=f'Схема {labels[status]}: {plan["drug_name"]}'
                reason=str(b.get('reason','')).strip()[:1500]
                note=f'Статус изменён врачом: {old_status} → {status}.'+(f' Причина/комментарий: {reason}' if reason else '')
                conn.execute('INSERT INTO appointments(patient_id,starts_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (p['id'],timestamp,'plan_change',action_title,note,'change_recorded',user['id'],timestamp))
            log_audit(conn,user['id'],'change_plan_status','medication_plan',plan['id'],f'{old_status} -> {status}'); conn.commit()
            return {'ok':True,'old_status':old_status,'status':status,'event_created':status!=old_status,'message':'Статус схемы обновлён; изменение добавлено в историю и календарь.' if status!=old_status else 'Схема уже имеет этот статус; дубликат события не создан.'},200,{}
        if path=='/api/medication-logs':
            if user['role']!='patient': raise PermissionError('Отметку приёма в этой версии вносит пациент')
            p=patient_for_user(conn,user['id']); pid=p['id'] if p else None
            plan=conn.execute('SELECT * FROM medication_plans WHERE id=? AND patient_id=? AND status="active"',(b.get('plan_id'),pid)).fetchone()
            if not plan: raise ValueError('Активная схема не найдена')
            scheduled=str(b.get('scheduled_date') or local_date())
            try: date.fromisoformat(scheduled)
            except ValueError: raise ValueError('Некорректная дата')
            status=b.get('status')
            if status not in ('taken','skipped','side_effect'): raise ValueError('Выберите статус приёма')
            side=str(b.get('side_effects','')).strip()[:1500]; notes=str(b.get('notes','')).strip()[:1500]
            cur=conn.execute('''INSERT INTO medication_logs(plan_id,patient_id,scheduled_date,status,side_effects,notes,logged_by,created_at) VALUES(?,?,?,?,?,?,?,?)
              ON CONFLICT(plan_id,patient_id,scheduled_date) DO UPDATE SET status=excluded.status,side_effects=excluded.side_effects,notes=excluded.notes,logged_by=excluded.logged_by,created_at=excluded.created_at''',
              (plan['id'],pid,scheduled,status,side,notes,user['id'],utc_now()))
            if status=='side_effect':
                evcur=conn.execute('INSERT INTO adverse_events(patient_id,medication_plan_id,reported_by,onset_at,symptoms_json,severity,serious,description,review_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (pid,plan['id'],user['id'],utc_now(),json.dumps(['other']), 'unknown',0,side or notes or 'Пациент отметил нежелательную реакцию в журнале приёма. Требуется уточнение.', 'pending',utc_now()))
                create_alert(conn,pid,'adverse_event',evcur.lastrowid,'review','Пациент сообщил о нежелательной реакции',f'Препарат: {plan["drug_name"]}. Подробности: {side or notes or "не указаны"}. Требуется клиническое уточнение.',recipient='doctor',rule_id='adverse_event_any')
            log_audit(conn,user['id'],'medication_log','medication_plan',plan['id'],status); conn.commit()
            return {'ok':True,'message':'Отметка сохранена.'},201,{}
        if path=='/api/recommendations':
            if user['role']!='doctor': raise PermissionError('Рекомендацию публикует только врач')
            p=get_patient(conn,user,b.get('patient_id')); body=str(b.get('body','')).strip()
            if len(body)<3 or len(body)>5000: raise ValueError('Текст рекомендации должен содержать 3–5000 символов')
            confirm=b.get('publish') is True
            status='published' if confirm else 'draft'
            cur=conn.execute('INSERT INTO recommendations(patient_id,body,visibility,status,created_by,approved_by,created_at,approved_at) VALUES(?,?,?,?,?,?,?,?)',
              (p['id'],body,'patient',status,user['id'],user['id'] if confirm else None,utc_now(),utc_now() if confirm else None))
            log_audit(conn,user['id'],'publish_recommendation' if confirm else 'draft_recommendation','recommendation',cur.lastrowid); conn.commit()
            return {'ok':True,'message':'Рекомендация опубликована пациенту.' if confirm else 'Черновик сохранён. Пациент его не видит.'},201,{}
        m=re.fullmatch(r'/api/messages/(\d+)/edit',path)
        if m:
            message=conn.execute('SELECT * FROM messages WHERE id=?',(int(m.group(1)),)).fetchone()
            if not message: raise LookupError('Сообщение не найдено.')
            patient=get_patient(conn,user,message['patient_id'])
            if int(message['sender_user_id'])!=int(user['id']):
                raise PermissionError('Изменить можно только собственное сообщение.')
            if message['deleted_at']:
                raise ValueError('Удалённое сообщение нельзя изменить.')
            new_body=str(b.get('body','')).strip()
            if not new_body or len(new_body)>4000: raise ValueError('Сообщение должно содержать 1–4000 символов.')
            if new_body==message['body']: return {'ok':True,'message':'Текст не изменился.','message_id':message['id']},200,{}
            reason=str(b.get('reason','')).strip()[:1000]
            timestamp=utc_now()
            conn.execute('''INSERT INTO message_revisions(message_id,patient_id,actor_user_id,action,previous_body,new_body,reason,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',(message['id'],patient['id'],user['id'],'edit',message['body'],new_body,reason,timestamp))
            conn.execute('UPDATE messages SET body=?,edited_at=?,last_modified_by=? WHERE id=?',(new_body,timestamp,user['id'],message['id']))
            flags=apply_message_red_flags(conn,patient['id'],message['id'],new_body)
            log_audit(conn,user['id'],'edit_message','message',message['id'],f'revisions_preserved=1; red_flags={",".join(flags)}; reason={reason}')
            recipient='patient' if user['role']=='doctor' else 'doctor'
            create_notification(conn,patient['id'],recipient,'message',message['id'],'info','Сообщение изменено',f'Участник диалога изменил сообщение от {message["created_at"]}.',rule_id='message_edited')
            conn.commit()
            return {'ok':True,'message_id':message['id'],'edited_at':timestamp,'message':'Сообщение изменено. Исходный текст сохранён в истории сервера.'},200,{}
        if path=='/api/messages':
            pid=b.get('patient_id')
            if user['role']=='patient':
                p=patient_for_user(conn,user['id']); pid=p['id'] if p else None
            p=get_patient(conn,user,pid)
            pref=patient_preferences(conn,p['id'])
            if not pref['chat_enabled'] or pref['chat_mode']=='off':
                create_notification(conn,p['id'],'doctor','system',None,'info','Чат отключён для пациента','Попытка отправить сообщение при отключённом чате. Используйте согласованный альтернативный канал связи.',rule_id='chat_unavailable_notice')
                conn.commit()
                raise PermissionError('Чат отключён в настройках. Используйте согласованный альтернативный способ связи; приложение не принимает экстренные сообщения.')
            body=str(b.get('body','')).strip()
            if not body or len(body)>4000: raise ValueError('Сообщение должно содержать 1–4000 символов')
            cur=conn.execute('INSERT INTO messages(patient_id,sender_user_id,body,created_at) VALUES(?,?,?,?)',(p['id'],user['id'],body,utc_now()))
            message_id=cur.lastrowid
            flags=apply_message_red_flags(conn,p['id'],message_id,body)
            log_audit(conn,user['id'],'send_message','message',message_id,('red_flags='+','.join(flags)) if flags else ''); conn.commit()
            return {'ok':True,'message_id':cur.lastrowid,'created_at':utc_now()},201,{}
        if path=='/api/ai/chat':
            if user['role']!='doctor': raise PermissionError('ИИ-чат доступен врачу')
            p=get_patient(conn,user,b.get('patient_id')); message=str(b.get('message','')).strip()
            if not message or len(message)>3000: raise ValueError('Введите вопрос (до 3000 символов)')
            summary=ai_summary(conn,p)['summary']
            # A deterministic safe stand-in for the future local model.
            low=message.lower()
            if any(x in low for x in ('препарат','назнач','доз','схем','лекар')):
                answer='Локальная обученная модель ещё не подключена. Этот модуль не выбирает лекарство и не рассчитывает персональную дозу. Для обсуждения схемы проверьте актуальную инструкцию ГРЛС, показания, противопоказания, взаимодействия, сопутствующие заболевания и клинические рекомендации. Черновик может утвердить только врач после клинической оценки.\n\n' + summary
            elif any(x in low for x in ('суиц','самоповреж','умереть','план безопасности','риск')):
                answer='При подозрении на актуальный риск суицида не полагайтесь на автоматическое резюме: немедленно проведите прямую клиническую оценку по утверждённому протоколу и обеспечьте контакт/маршрутизацию пациента. При угрозе жизни используйте местную экстренную службу.\n\n' + summary
            else:
                answer='Пока отвечает детерминированный прототип, а не обученная локальная LLM. Я могу показать сводку записанных данных и подсветить незакрытые сигналы, но не ставлю диагноз.\n\n' + summary
            return {'answer':answer,'model_status':'rules_only','disclaimer':'Не является клиническим заключением. Перед использованием в реальной практике требуется локальная валидация и подтверждение врачом.'},200,{}
        m=re.fullmatch(r'/api/alerts/(\d+)/review',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Сигналы обрабатывает только врач')
            alert=conn.execute('SELECT a.* FROM alerts a JOIN patients p ON p.id=a.patient_id WHERE a.id=? AND p.doctor_user_id=? AND p.archived=0',(int(m.group(1)),user['id'])).fetchone()
            if not alert: raise LookupError('Сигнал не найден')
            significance=str(b.get('significance','unconfirmed'))
            if significance not in ('unconfirmed','clinically_significant','false_positive','resolved'): raise ValueError('Некорректная оценка значимости')
            reaction=str(b.get('reaction','')).strip()[:3000];followup=str(b.get('followup','')).strip()[:1500]
            conn.execute('INSERT INTO alert_reviews(alert_id,patient_id,reviewer_user_id,significance,reaction,followup,created_at) VALUES(?,?,?,?,?,?,?)',(alert['id'],alert['patient_id'],user['id'],significance,reaction,followup,utc_now()))
            status='resolved' if significance in ('false_positive','resolved') else 'acknowledged'
            reviewed_at=utc_now()
            conn.execute('UPDATE alerts SET status=?,acknowledged_by=?,acknowledged_at=? WHERE id=?',(status,user['id'],reviewed_at,alert['id']))
            # Keep the clinical map's adverse-event review state consistent with signal review.
            if alert['source_type']=='adverse_event' and alert['source_id'] is not None:
                adverse_status='closed' if significance in ('false_positive','resolved') else 'pending' if significance=='unconfirmed' else 'reviewed'
                conn.execute('UPDATE adverse_events SET review_status=?,reviewed_by=?,reviewed_at=? WHERE id=? AND patient_id=?',
                             (adverse_status,user['id'],reviewed_at,alert['source_id'],alert['patient_id']))
            log_audit(conn,user['id'],'review_alert','alert',alert['id'],json.dumps({'significance':significance,'reaction':reaction,'followup':followup,'status':status},ensure_ascii=False));conn.commit()
            return {'ok':True,'message':'Оценка сигнала сохранена.'},200,{}
        m=re.fullmatch(r'/api/alerts/(\d+)/ack',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Только врач может подтверждать получение сигнала')
            alert=conn.execute('SELECT a.* FROM alerts a JOIN patients p ON p.id=a.patient_id WHERE a.id=? AND p.doctor_user_id=? AND p.archived=0',(int(m.group(1)),user['id'])).fetchone()
            if not alert: raise LookupError('Сигнал не найден')
            status=b.get('status','acknowledged')
            if status not in ('acknowledged','resolved'): raise ValueError('Недопустимый статус сигнала')
            reviewed_at=utc_now()
            conn.execute('UPDATE alerts SET status=?,acknowledged_by=?,acknowledged_at=? WHERE id=?',(status,user['id'],reviewed_at,alert['id']))
            if status=='resolved' and alert['source_type']=='adverse_event' and alert['source_id'] is not None:
                conn.execute('UPDATE adverse_events SET review_status="closed",reviewed_by=?,reviewed_at=? WHERE id=? AND patient_id=?',
                             (user['id'],reviewed_at,alert['source_id'],alert['patient_id']))
            log_audit(conn,user['id'],'ack_alert','alert',alert['id'],status); conn.commit()
            return {'ok':True,'message':'Статус сигнала сохранён.'},200,{}
        if path=='/api/profile/menstrual':
            if user['role']!='patient': raise PermissionError('Настройка доступна пациенту')
            p=patient_for_user(conn,user['id']); enabled=bool(b.get('enabled'))
            if not p: raise LookupError('Карточка пациента не найдена')
            if enabled and p['sex']!='female': raise ValueError('Мониторинг цикла доступен только для профиля с женским полом')
            conn.execute('UPDATE patients SET menstrual_enabled=? WHERE id=?',(int(enabled),p['id']))
            log_audit(conn,user['id'],'toggle_menstrual','patient',p['id'],str(enabled)); conn.commit()
            return {'ok':True,'enabled':enabled},200,{}
        raise LookupError('API endpoint не найден')

    def api_delete(self,conn,path):
        user=self.require_user(conn,csrf=True)
        m=re.fullmatch(r'/api/appointments/(\d+)',path)
        if m:
            appointment=conn.execute('SELECT * FROM appointments WHERE id=?',(int(m.group(1)),)).fetchone()
            if not appointment or appointment['status']=='deleted': raise LookupError('Событие календаря не найдено.')
            patient=get_patient(conn,user,appointment['patient_id'])
            if appointment['kind']=='plan_change': raise PermissionError('Системные записи об изменении лечения нельзя удалять.')
            if user['role']=='doctor':
                if appointment['status'] not in ('scheduled','cancelled'):
                    raise ValueError('Завершённые, пропущенные и перенесённые события сохраняются в истории и не удаляются.')
            elif user['role']=='patient':
                if appointment['kind']!='personal' or int(appointment['created_by'])!=int(user['id']):
                    raise PermissionError('Пациент может удалить только собственное личное событие.')
            else:
                raise PermissionError('Недостаточно прав для удаления события.')
            timestamp=utc_now()
            conn.execute('UPDATE appointments SET status=? WHERE id=?',('deleted',appointment['id']))
            log_audit(conn,user['id'],'delete_appointment','appointment',appointment['id'],
                      f'title={appointment["title"]}; starts_at={appointment["starts_at"]}; soft_delete=1')
            if user['role']=='doctor':
                create_notification(conn,patient['id'],'patient','appointment',appointment['id'],'info','Событие календаря удалено',
                    f'Врач удалил событие «{appointment["title"]}» на {appointment["starts_at"]}. Если это был приём, согласуйте новую дату с врачом.',rule_id='appointment_deleted')
            conn.commit()
            return {'ok':True,'message':'Событие удалено из календаря. Запись и действие сохранены в журнале аудита.'},200
        m=re.fullmatch(r'/api/messages/(\d+)',path)
        if m:
            message=conn.execute('SELECT * FROM messages WHERE id=?',(int(m.group(1)),)).fetchone()
            if not message or message['deleted_at']: raise LookupError('Сообщение не найдено.')
            patient=get_patient(conn,user,message['patient_id'])
            if int(message['sender_user_id'])!=int(user['id']):
                raise PermissionError('Удалить можно только собственное сообщение.')
            reason='Удалено отправителем'
            timestamp=utc_now()
            conn.execute('''INSERT INTO message_revisions(message_id,patient_id,actor_user_id,action,previous_body,new_body,reason,created_at)
                VALUES(?,?,?,?,?,?,?,?)''',(message['id'],patient['id'],user['id'],'delete',message['body'],'',reason,timestamp))
            # Keep the original message body in the protected database and revision log;
            # API responses replace it with a tombstone after deletion.
            conn.execute('UPDATE messages SET deleted_at=?,deleted_by=?,last_modified_by=? WHERE id=?',(timestamp,user['id'],user['id'],message['id']))
            log_audit(conn,user['id'],'delete_message','message',message['id'],'original_body_preserved=1; soft_delete=1')
            recipient='patient' if user['role']=='doctor' else 'doctor'
            create_notification(conn,patient['id'],recipient,'message',message['id'],'info','Сообщение удалено',
                f'Участник диалога удалил сообщение от {message["created_at"]}.',rule_id='message_deleted')
            conn.commit()
            return {'ok':True,'message':'Сообщение скрыто из переписки; оригинал сохранён в защищённой истории сервера.'},200
        m=re.fullmatch(r'/api/patients/(\d+)',path)
        if m:
            if user['role']!='doctor': raise PermissionError('Только врач может архивировать пациента')
            p=get_patient(conn,user,m.group(1))
            conn.execute('UPDATE patients SET archived=1 WHERE id=?',(p['id'],))
            conn.execute('UPDATE users SET active=0 WHERE id=?',(p['user_id'],))
            conn.execute('DELETE FROM sessions WHERE user_id=?',(p['user_id'],))
            log_audit(conn,user['id'],'archive','patient',p['id']); conn.commit()
            return {'ok':True,'message':'Пациент архивирован. Медицинская история сохранена.'},200
        raise LookupError('API endpoint не найден')

    def _cookie_raw(self):
        for item in self.headers.get('Cookie','').split(';'):
            if '=' in item:
                k,v=item.strip().split('=',1)
                if k==COOKIE_NAME: return v
        return None


def ensure_portrait_demo_cases():
    """Seed the six longitudinal portrait cases only in the synthetic demo mode."""
    if not DEMO_MODE:
        return {'seeded': 0, 'skipped': 0, 'patients': []}
    from portrait_demo_seeding import seed_portrait_demo_cases
    conn = get_db()
    try:
        doctor = conn.execute('SELECT id FROM users WHERE email=? AND role=?', ('doctor@demo.local', 'doctor')).fetchone()
        if not doctor:
            return {'seeded': 0, 'skipped': 0, 'patients': []}
        return seed_portrait_demo_cases(conn, doctor['id'], {
            'hash_password': hash_password,
            'get_questionnaire': get_questionnaire,
            'score_questionnaire': score_questionnaire,
            'load_treatment_scheme': load_treatment_scheme,
            'load_medications': load_medications,
            'create_alert': create_alert,
        })
    finally:
        conn.close()


def main():
    create_schema(); ensure_demo_data(); ensure_clinical_data(); seed_result = ensure_portrait_demo_cases()
    server=ThreadingHTTPServer((HOST,PORT),AppHandler)
    print(f'Локальное приложение «Контур» запущено: http://{HOST}:{PORT}/')
    if DEMO_MODE:
        print('Демо-врач: doctor@demo.local / DemoDoctor2026!')
        print('Демо-пациент: patient@demo.local / DemoPatient2026!')
    if DEMO_MODE: print(f'Учебные синтетические карточки: создано {seed_result.get("seeded", 0)}, доступно в этом запуске {len(seed_result.get("patients", []))}.')
    print(f'База данных: {DB_PATH}')
    print('Только для демонстрации и локального использования. Не публикуйте HTTP-сервер в Интернете.')
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nОстановка…')
    finally: server.server_close()

if __name__=='__main__': main()
