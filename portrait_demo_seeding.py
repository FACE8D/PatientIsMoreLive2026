"""Seed six synthetic longitudinal patient portraits for the demo environment.

Baseline symptoms and scale scores come from data/demo_patient_cases.json, which
transcribes the uploaded portrait set. All follow-up data, adherence, visits,
appointments and treatment history are explicitly simulated for product testing.
"""
from __future__ import annotations
import json, math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
FIXTURE = BASE / 'data' / 'demo_patient_cases.json'
BASE_ACTIONS = ['drink', 'food', 'wash', 'clothes', 'air', 'move', 'contact', 'therapy']


def _iso_day(start: date, day_offset: int) -> str:
    return (start + timedelta(days=int(day_offset))).isoformat()


def _ts(start: date, day_offset: int, hour: int = 10, minute: int = 0) -> str:
    dt = datetime.combine(start + timedelta(days=int(day_offset)), datetime.min.time()).replace(
        hour=hour, minute=minute, tzinfo=timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def _spread_score_answers(defn: dict, total: int, salt: int = 0) -> dict:
    """Create deterministic valid answer vectors with an exact summed score.

    This is only synthetic fixture data. It is not a clinical response pattern.
    """
    answers = {}
    questions = defn.get('questions', [])
    # Do not fabricate an affirmative answer to a dedicated safety item just to reach a
    # synthetic aggregate score. When the source portrait supplies only a total, keep the
    # direct self-harm item at zero/unknown-safe in this demo vector and distribute points
    # across the other scored items. The saved note still labels all reconstructed answers
    # as synthetic and not a real item-level assessment.
    safety_item = (defn.get('scoring', {}).get('risk_if') or {}).get('question_id')
    scored = [q for q in questions if q.get('scored', True) and q.get('type', 'single') == 'single' and q.get('id') != safety_item]
    caps = []
    for q in scored:
        opts = [int(o['value']) for o in q.get('options', []) if str(o.get('value', '')).lstrip('-').isdigit()]
        caps.append(max(opts) if opts else 0)
    remaining = max(0, int(total))
    n = len(scored)
    values = {q['id']: 0 for q in scored}
    # A deterministic but spread-out distribution, keeping each answer within its scale.
    if n:
        candidates = [x for x in (7, 11, 5, 3, 2, 1) if math.gcd(x, n) == 1]
        stride = candidates[0] if candidates else 1
        order = [((i * stride) + salt) % n for i in range(n)]
        while remaining > 0:
            progressed = False
            for idx in order:
                if values[scored[idx]['id']] < caps[idx] and remaining > 0:
                    values[scored[idx]['id']] += 1
                    remaining -= 1
                    progressed = True
            if not progressed:
                break
    answers.update(values)
    for q in questions:
        qid = q['id']
        if qid in answers:
            continue
        typ = q.get('type', 'single')
        if typ == 'single':
            opts = q.get('options', [])
            answers[qid] = int(opts[0]['value']) if opts and str(opts[0].get('value', '')).lstrip('-').isdigit() else 0
        elif typ == 'yesno_period':
            answers[qid] = {p['id']: 'no' for p in q.get('periods', [])}
        elif typ == 'text':
            answers[qid] = ''
    return answers


def _mood_value(case: dict, day_index: int, case_index: int) -> int:
    tr = case['trajectory']; duration = max(1, int(case['observation_days']))
    t = max(0, min(1, day_index / duration))
    start, end = float(tr['mood_start']), float(tr['mood_end'])
    if tr.get('mood_shape') == 'unstable_worsening':
        trend = start + (end - start) * t
        amp = 1.9
    elif tr.get('mood_shape') == 'stable_worsening':
        trend = start + (end - start) * t
        amp = 0.65
    elif tr.get('mood_shape') == 'improving_fluctuating':
        trend = start + (end - start) * t
        amp = 1.0
    elif tr.get('mood_shape') == 'stagnant':
        trend = start + (end - start) * t
        amp = 0.7
    else:
        trend = start + (end - start) * t
        amp = 0.55
    wave = math.sin((day_index + case_index * 3) * 0.43) * amp
    # An intentional dip late in case 4 makes the dynamic plot show relapse/instability.
    if case['case_id'] == 'anna_vitiligo' and 0.72 < t < 0.9:
        wave -= 1.15
    # A fluctuating activation/sleep pattern for Olga is not scored as a diagnosis.
    if case['case_id'] == 'olga_possible_bipolarity' and 0.22 < t < 0.48:
        wave += 1.45 * math.sin(day_index * 0.78)
    val = int(round(max(1, min(10, trend + wave))))
    return val


def _sleep_value(case: dict, day_index: int, case_index: int) -> float:
    tr = case['trajectory']; duration = max(1, int(case['observation_days']))
    t = max(0, min(1, day_index / duration))
    start, end = float(tr['sleep_start']), float(tr['sleep_end'])
    wave = math.sin((day_index + case_index) * 0.31) * (0.55 if case['case_id'] != 'olga_possible_bipolarity' else 1.1)
    value = start + (end - start) * t + wave
    if case['case_id'] == 'olga_possible_bipolarity' and 0.2 < t < 0.48:
        value -= 1.0
    return round(max(2.5, min(10, value)), 1)


def _seed_patient_answers(conn, case, patient_id, patient_user_id, doctor_id, start_date, helpers):
    get_questionnaire = helpers['get_questionnaire']
    score_questionnaire = helpers['score_questionnaire']
    series = []
    baseline = case['source_baseline'].get('scale_scores', {})
    for qid, total in baseline.items():
        series.append({'day': 0, 'qid': qid, 'total': total, 'source_kind': 'baseline'})
    for point in case.get('followup_scores', []):
        for qid, total in point.get('scores', {}).items():
            series.append({'day': int(point['day']), 'qid': qid, 'total': total, 'source_kind': 'simulated_followup'})
    # Avoid duplicates if the seeder is resumed after an interrupted first run.
    for item in series:
        qid = item['qid']
        exists = conn.execute('SELECT 1 FROM questionnaire_results WHERE patient_id=? AND questionnaire_id=? AND created_at=?',
            (patient_id, qid, _ts(start_date, item['day'], 9))).fetchone()
        if exists:
            continue
        defn = get_questionnaire(qid)
        answers = _spread_score_answers(defn, int(item['total']), salt=(len(qid) + item['day']) % 9)
        score = score_questionnaire(defn, answers)
        score['synthetic_demo'] = True
        score['series_type'] = item['source_kind']
        score['interpretation_note'] = ('Исходный балл указан в приложенном портрете.' if item['source_kind'] == 'baseline'
            else 'Последующее значение полностью смоделировано для демонстрации динамики; это не результат реального пациента.')
        by_patient = defn.get('respondent') != 'clinician'
        completed_by = patient_user_id if by_patient else doctor_id
        conn.execute('''INSERT INTO questionnaire_results(patient_id,completed_by,questionnaire_id,questionnaire_title,version,answers_json,score_json,risk_flag,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)''', (patient_id, completed_by, qid, defn['title'], defn.get('version','demo-1'),
            json.dumps(answers, ensure_ascii=False), json.dumps(score, ensure_ascii=False), int(bool(score.get('risk_flag'))), _ts(start_date, item['day'], 9)))


def _configuration_for_scheme(scheme: dict, case: dict, start_date: date, review_date: date) -> dict:
    custom = {
        'focus': case['clinical_profile'][:450],
        'questionnaires': ', '.join(case['source_baseline'].get('scale_scores', {}).keys()),
        'agreed_options': 'Совместно обсуждать переносимость, повседневное функционирование и предпочтения; все лекарственные решения проверяет врач.',
        'referral_level': 'Желательна консультация психиатра' if case['case_id'] in ('olga_possible_bipolarity','andrey_ssri_intolerance') else 'Плановое наблюдение ведущим врачом',
        'format': 'Индивидуальная',
        'target_symptoms': 'Тревога, сон и влияние на повседневное функционирование; конкретные цели уточняются на приёме.',
        'program': 'План наблюдения по согласованному клиническому руководству; содержание адаптирует специалист.',
        'between_session_tasks': 'Вести короткую запись о сне/настроении и одну посильную задачу между встречами.',
        'technique': 'Дыхательная техника',
        'schedule': 'Короткая практика в согласованное время; частоту пересматривать с пациентом.',
        'adaptations': 'Прекратить упражнение при ухудшении самочувствия и сообщить врачу.',
        'activity_goal': 'Одна небольшая реалистичная активность, выбранная пациентом.',
        'activity_schedule': 'Планировать на удобное время и отмечать препятствия.',
        'easy_alternative': 'Сократить задачу до нескольких минут или выбрать более лёгкий вариант.',
        'review_frequency': 'На каждом плановом контакте',
        'chosen_method': 'Поведенческая активация',
        'goal': 'Наблюдать за самочувствием и постепенно возвращать выбранные повседневные активности.',
        'support_schedule': 'Контакт на каждом плановом приёме; чаще при ухудшении по решению врача.',
        'resource': 'Материалы выдаёт врач после проверки доступности и соответствия.',
        'session_count': 6,
        'relapse_risk': 'Оценивается по динамике симптомов, предыдущим эпизодам, функционированию и предпочтениям пациента.',
        'chosen_approach': 'КПТ/когнитивная терапия на основе осознанности или другой согласованный психологический метод',
        'review_horizon': 'Через 2–4 недели по клинической ситуации',
        'early_warning_signs': 'Ухудшение сна, стойкое снижение настроения, рост тревоги или заметное изменение активности.',
        'source_excerpt': 'Возможный признак требует уточнения в разговоре, а не вывода по автоматическому совпадению.',
        'direct_assessment': 'Провести прямую оценку содержания переживаний, уверенности, влияния на поведение и безопасности.',
        'safety_status': 'Нужно оценить дополнительно',
        'route': 'Следовать локальному протоколу после прямой оценки.',
        'reviewed_directly': False,
        'suspected_product': 'Эсциталопрам (исторически, по портрету)' if case['case_id']=='andrey_ssri_intolerance' else 'Не установлен / требуется сверка',
        'reaction_details': 'Смоделированная история симптомов для обучения интерфейсу.',
        'seriousness_review': 'Оценить серьёзность, сроки, альтернативные причины и связь с препаратом.',
        'action': 'Зафиксировать, связаться с пациентом и принять решение после клинической оценки.',
        'followup': 'Повторная оценка на следующем контакте или раньше по клинической необходимости.',
        'agreed_activity': 'Посильная активность, согласованная с учётом физического состояния и предпочтений.',
        'baseline': 'Исходный уровень фиксируется по рассказу пациента и имеющимся данным.',
        'safety_considerations': 'Учитывать соматическое состояние и прекратить при ухудшении самочувствия.',
        'drug_product': 'Не задано автоматически; конкретный продукт выбирает врач после проверки.',
        'indication': 'Проверить диагностическое основание и зарегистрированное показание.',
        'regimen_from_label': 'Перенести только после проверки действующей инструкции конкретного продукта; числовая дозировка не генерируется системой.',
        'label_checked': False,
        'monitoring_plan': 'Симптомы, переносимость, приверженность и риски на согласованных контрольных точках.',
        'current_product_regimen': 'Историческая терапия по портрету; точная доза и длительность не указаны.',
        'individual_steps': 'Не рассчитывать универсальный график снижения. Решение и этапы индивидуально оформляет врач по инструкции и клинической ситуации.',
        'symptom_plan': 'Фиксировать симптомы после изменения лечения и связаться с врачом при ухудшении.',
        'next_review': review_date.isoformat()
    }
    result = {}
    for spec in scheme.get('configuration_fields', []):
        fid = spec.get('id')
        typ = spec.get('type','text')
        if fid in custom:
            value = custom[fid]
        elif typ == 'select':
            value = (spec.get('options') or [''])[0]
        elif typ == 'checkbox':
            value = False
        elif typ == 'number':
            value = spec.get('min', 4)
        elif typ == 'date':
            value = review_date.isoformat()
        elif typ in ('text','textarea'):
            value = 'Заполняется совместно с пациентом и уточняется врачом.'
        else:
            continue
        if typ == 'select' and value not in spec.get('options',[]):
            value = (spec.get('options') or [''])[0]
        result[fid] = value
    return result


def _seed_care_plan(conn, patient_id, doctor_id, case, item, start_date, helpers):
    load_treatment_scheme = helpers['load_treatment_scheme']
    sid=item['scheme_id']; scheme=load_treatment_scheme(sid)
    start=start_date+timedelta(days=int(item.get('start_day',0)))
    review=start_date+timedelta(days=int(item.get('review_day',case['observation_days'])))
    existing=conn.execute('SELECT id FROM care_plans WHERE patient_id=? AND scheme_id=? AND notes LIKE ?',
        (patient_id,sid,f'%[[portrait_case:{case["case_id"]}]]%')).fetchone()
    if existing: return existing['id']
    configuration=_configuration_for_scheme(scheme,case,start,review)
    plan=json.loads(json.dumps(scheme,ensure_ascii=False))
    plan['configuration']=configuration
    plan['configuration_fields']=scheme.get('configuration_fields',[])
    for ix,step in enumerate(plan.get('steps',[])):
        if item['status']=='completed': step['status']='completed'
        elif item['status']=='paused': step['status']='in_progress' if ix==0 else 'pending'
        else: step['status']='completed' if ix < 1 else 'in_progress' if ix==1 else 'pending'
        step['updated_at']=_ts(start_date,min(int(item.get('start_day',0))+ix*7,case['observation_days']),13)
    notes=f'{item.get("note","")} [[portrait_case:{case["case_id"]}]]'
    created=_ts(start_date,int(item.get('start_day',0)),13)
    conn.execute('''INSERT INTO care_plans(patient_id,scheme_id,scheme_version,title,plan_json,status,start_date,review_date,notes,created_by,approved_by,approved_at,created_at,updated_at)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(patient_id,sid,scheme.get('version','1.0.0'),scheme['title'],json.dumps(plan,ensure_ascii=False),item['status'],start.isoformat(),review.isoformat(),notes,doctor_id,doctor_id if item['status']!='draft' else None,created if item['status']!='draft' else None,created,created))
    return conn.execute('SELECT last_insert_rowid()').fetchone()[0]


def seed_portrait_demo_cases(conn, doctor_id: int, helpers: dict) -> dict:
    """Populate an isolated demo DB with six fictional longitudinal cases, once each."""
    cases_doc=json.loads(FIXTURE.read_text(encoding='utf-8'))
    results={'seeded':0,'skipped':0,'patients':[]}
    existing_default=conn.execute('SELECT id FROM users WHERE email=?',('patient@demo.local',)).fetchone()
    for idx,case in enumerate(cases_doc['patients']):
        email=case['email']; user=conn.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        if user is None:
            cur=conn.execute('INSERT INTO users(email,display_name,role,password_hash,active,must_change_password,created_at) VALUES(?,?,?,?,1,0,?)',
                (email,case['display_name'],'patient',helpers['hash_password']('DemoPatient2026!'),utc_now_safe()))
            user_id=cur.lastrowid
        else:
            user_id=user['id']
        patient=conn.execute('SELECT * FROM patients WHERE user_id=?',(user_id,)).fetchone()
        # Existing non-demo accounts are not repurposed. The default bundled demo account is safe to upgrade.
        if patient and not conn.execute('SELECT 1 FROM demo_portrait_seeds WHERE patient_id=?',(patient['id'],)).fetchone():
            if email!='patient@demo.local' and not str(patient['notes'] or '').startswith('СИНТЕТИЧЕСКИЙ УЧЕБНЫЙ КЕЙС'):
                results['skipped']+=1; continue
            if email=='patient@demo.local':
                # Remove only rows uniquely created by the original sample fixture, not arbitrary medical history.
                for er in conn.execute('SELECT id,data_json FROM entries WHERE patient_id=?',(patient['id'],)).fetchall():
                    try: dat=json.loads(er['data_json'])
                    except Exception: dat={}
                    if dat.get('notes')=='Синтетическая демонстрационная запись.': conn.execute('DELETE FROM entries WHERE id=?',(er['id'],))
                conn.execute("DELETE FROM appointments WHERE patient_id=? AND title='Контрольный приём (демо)' AND notes='Синтетическая демонстрационная запись.'",(patient['id'],))
                conn.execute("DELETE FROM recommendations WHERE patient_id=? AND body LIKE '%Это демонстрационный пример.%'",(patient['id'],))
        if patient is None:
            cur=conn.execute('''INSERT INTO patients(user_id,doctor_user_id,full_name,birth_date,sex,phone,notes,menstrual_enabled,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)''',(user_id,doctor_id,case['full_name'],case['birth_date'],case['sex'],'', '',int(case['case_id'] in ('maria_post_covid','anna_vitiligo')),utc_now_safe()))
            patient_id=cur.lastrowid
        else:
            patient_id=patient['id']
            marker=conn.execute('SELECT 1 FROM demo_portrait_seeds WHERE patient_id=?',(patient_id,)).fetchone()
            if marker:
                # Additive migration for portraits created by an earlier release: keep
                # every existing record untouched, but fill the new wellbeing diary once
                # per scheduled demo date so the new UI works without resetting a DB.
                mood_dates=[r['entry_date'] for r in conn.execute("SELECT entry_date FROM entries WHERE patient_id=? AND entry_type='mood' ORDER BY entry_date",(patient_id,)).fetchall() if r['entry_date']]
                if mood_dates:
                    legacy_start=date.fromisoformat(min(mood_dates))
                    dur=int(case['observation_days']); tr=case['trajectory']
                    existing_wellbeing={r['entry_date'] for r in conn.execute("SELECT entry_date FROM entries WHERE patient_id=? AND entry_type='wellbeing'",(patient_id,)).fetchall()}
                    for day in range(dur+1):
                        if day%5!=0 and day!=dur: continue
                        day_date=_iso_day(legacy_start,day)
                        if day_date in existing_wellbeing: continue
                        if day==0: polarity='positive'
                        elif day==dur: polarity='negative'
                        elif tr.get('mood_end',5)>=tr.get('mood_start',5): polarity='positive' if day>=max(5,dur//3) else ('neutral' if day%10==0 else 'negative')
                        else: polarity='negative' if day>=max(5,dur//3) else 'neutral'
                        choices={'positive':['Меньше тревоги','Лучше настроение','Больше энергии','Лучше засыпаю'],'negative':['Беспокойство усилилось','Сон ухудшился','Сонливость днём','Головокружение'],'neutral':['Пока не замечаю улучшений']}
                        tag=choices[polarity][(day//5+idx)%len(choices[polarity])]
                        note=('Синтетическая демонстрационная отметка: пример улучшения.' if polarity=='positive' else 'Синтетическая демонстрационная отметка: пример ухудшения/нежелательной реакции.' if polarity=='negative' else 'Синтетическая демонстрационная отметка без выраженной оценки.')
                        payload={'polarity':polarity,'tags':[tag],'notes':note,'serious':False,'synthetic_demo':True}
                        conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',(patient_id,user_id,'wellbeing',day_date,json.dumps(payload,ensure_ascii=False),_ts(legacy_start,day,20,20)))
                results['skipped']+=1; results['patients'].append({'case_id':case['case_id'],'patient_id':patient_id,'seeded':False,'migrated_wellbeing':bool(mood_dates)}); continue
            conn.execute('UPDATE patients SET doctor_user_id=?,full_name=?,birth_date=?,sex=?,notes=?,menstrual_enabled=? WHERE id=?',
                (doctor_id,case['full_name'],case['birth_date'],case['sex'],'',int(case['case_id'] in ('maria_post_covid','anna_vitiligo')),patient_id))
        conn.execute('UPDATE users SET display_name=?,active=1 WHERE id=?',(case['display_name'],user_id))
        marker=f'[[portrait_case:{case["case_id"]}]]'
        start_date=date.today()-timedelta(days=int(case['observation_days']))
        source_scores=case['source_baseline'].get('scale_scores',{})
        profile_notes=(f'СИНТЕТИЧЕСКИЙ УЧЕБНЫЙ КЕЙС. Все последующие события и значения после исходной точки смоделированы. Не реальные медицинские данные.\n'
          f'Портрет: {case["source_title"]}.\n\n{case["clinical_profile"]}\n\n'
          f'Исходные данные портрета: {json.dumps(case["source_baseline"],ensure_ascii=False)}\n\n'
          f'Окно демонстрационного наблюдения: {start_date.isoformat()} — {date.today().isoformat()} ({case["observation_days"]} дней).\n'
          f'Обозначение динамики: значения после исходной точки и сведения о соблюдении плана созданы для проверки интерфейса, не для лечебных выводов. {marker}')
        conn.execute('UPDATE patients SET notes=? WHERE id=?',(profile_notes,patient_id))
        conn.execute('INSERT OR IGNORE INTO patient_preferences(patient_id,chat_enabled,chat_mode,notification_preferences_json,updated_at) VALUES(?,1,\'async\',\'{}\',?)',(patient_id,utc_now_safe()))
        # Mood, food and checklist journals of different completeness; gaps remain visible as missing data.
        tr=case['trajectory']; dur=int(case['observation_days'])
        miss_days=set(tr.get('missed_medication_days',[]))
        for day in range(dur+1):
            should_record=((day*37+(idx+1)*19)%100) < int(float(tr['diary_adherence'])*100)
            if day==0 or (day==dur and case['case_id'] not in ('elena_comorbid','andrey_ssri_intolerance')):
                should_record=True
            if should_record:
                mood=_mood_value(case,day,idx); sleep=_sleep_value(case,day,idx)
                appetite='снижен' if mood<=3 or (day*11+idx)%9==0 else 'обычный'
                if case['case_id']=='olga_possible_bipolarity' and 0.22*dur<day<0.48*dur: appetite='изменчивый'
                note='Демонстрационная запись самочувствия.'
                if day in miss_days: note='Сообщено о трудностях с регулярным режимом; требуется обсуждение без обвинения пациента.'
                if case['case_id']=='olga_possible_bipolarity' and sleep<4.5: note='Отмечен короткий сон; в клинической карте это повод уточнить эпизод повышенной активности, не диагностический вывод.'
                payload={'mood':mood,'sleep_hours':sleep,'appetite':appetite,'notes':note,'synthetic_demo':True}
                conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',
                    (patient_id,user_id,'mood',_iso_day(start_date,day),json.dumps(payload,ensure_ascii=False),_ts(start_date,day,20)))
            food_rate=float(tr.get('food_adherence',0.4))
            if ((day*23+(idx+2)*17)%100)<int(food_rate*100):
                meals=("Приёмы пищи частично пропущены из-за усталости; требуется наблюдение без назначения диеты." if case['case_id'] in ('elena_comorbid','olga_possible_bipolarity') and day%3==0 else "Короткая запись питания; оценка субъективная.")
                payload={'meals':meals,'appetite':'снижен' if (day+idx)%5==0 else 'обычный','synthetic_demo':True}
                conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',
                    (patient_id,user_id,'food',_iso_day(start_date,day),json.dumps(payload,ensure_ascii=False),_ts(start_date,day,20,5)))
            checklist_rate=float(tr.get('checklist_adherence',0.4))
            if ((day*31+(idx+4)*13)%100)<int(checklist_rate*100):
                count=(day+idx*2)%9
                # Poor adherence cases often record only one tiny step, rather than being marked as "failed".
                if case['case_id'] in ('elena_comorbid','olga_possible_bipolarity') and day%4==0: count=1
                actions=[BASE_ACTIONS[(j+day+idx)%len(BASE_ACTIONS)] for j in range(min(count,len(BASE_ACTIONS)))]
                payload={'actions':actions,'available_actions':BASE_ACTIONS,'notes':'Выполнено посильное количество действий; пропуски не трактуются как неудача.','synthetic_demo':True}
                conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',
                    (patient_id,user_id,'checklist',_iso_day(start_date,day),json.dumps(payload,ensure_ascii=False),_ts(start_date,day,20,10)))
            # The wellbeing self-report is a distinct patient-facing diary and should be
            # populated in demo portraits so its controls, physician map, filters and
            # temporal plots can be exercised end-to-end. These are simulated examples,
            # not observations from the source portraits or real clinical records.
            if day % 5 == 0 or day == dur:
                if day == 0:
                    polarity = 'positive'
                elif day == dur:
                    polarity = 'negative'
                elif tr.get('mood_end', 5) >= tr.get('mood_start', 5):
                    polarity = 'positive' if day >= max(5, dur // 3) else ('neutral' if day % 10 == 0 else 'negative')
                else:
                    polarity = 'negative' if day >= max(5, dur // 3) else 'neutral'
                tag_options = {
                    'positive': ['Меньше тревоги', 'Лучше настроение', 'Больше энергии', 'Лучше засыпаю'],
                    'negative': ['Беспокойство усилилось', 'Сон ухудшился', 'Сонливость днём', 'Головокружение'],
                    'neutral': ['Пока не замечаю улучшений']
                }
                tag = tag_options[polarity][(day // 5 + idx) % len(tag_options[polarity])]
                note = ('Синтетическая демонстрационная отметка: пример улучшения.' if polarity == 'positive'
                    else 'Синтетическая демонстрационная отметка: пример ухудшения/нежелательной реакции.' if polarity == 'negative'
                    else 'Синтетическая демонстрационная отметка без выраженной оценки.')
                payload = {'polarity': polarity, 'tags': [tag], 'notes': note, 'serious': False, 'synthetic_demo': True}
                conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',
                    (patient_id,user_id,'wellbeing',_iso_day(start_date,day),json.dumps(payload,ensure_ascii=False),_ts(start_date,day,20,20)))
        # A small number of cycle entries tests the optional diary flow; it is synthetic and consent-enabled.
        if case['case_id']=='maria_post_covid':
            for day,status,note in [(16,'start','Демо-запись начала цикла.'),(20,'ongoing','Краткая демо-запись; симптомы не уточнялись.'),(21,'end','Демо-запись окончания цикла.')]:
                payload={'status':status,'notes':note,'synthetic_demo':True}
                conn.execute('INSERT INTO entries(patient_id,author_user_id,entry_type,entry_date,data_json,created_at) VALUES(?,?,?,?,?,?)',
                    (patient_id,user_id,'menstrual',_iso_day(start_date,day),json.dumps(payload,ensure_ascii=False),_ts(start_date,day,20,15)))
        _seed_patient_answers(conn,case,patient_id,user_id,doctor_id,start_date,helpers)
        # Visit history and signed clinical assessments share the same encounter record.
        visit_ids={}
        for vix,visit in enumerate(case.get('visits',[])):
            day=int(visit['day']); visit_date=_iso_day(start_date,day); created=_ts(start_date,day,13)
            notes=visit['summary']+' Все события сверх исходного портрета являются учебной симуляцией.'
            cur=conn.execute('INSERT INTO visits(patient_id,visit_date,kind,notes,followup_date,author_user_id,created_at) VALUES(?,?,?,?,?,?,?)',
                (patient_id,visit_date,visit['kind'],notes,_iso_day(start_date,min(day+14,dur+7)),doctor_id,created))
            visit_id=cur.lastrowid; visit_ids[day]=visit_id
            mood_status='improving' if tr['mood_end']>tr['mood_start'] else 'worsening' if tr['mood_end']<tr['mood_start'] else 'stable'
            mental={'mood':mood_status,'affect':'partial' if case['case_id'] in ('anna_vitiligo','andrey_ssri_intolerance') else 'stable',
                'thought_content':'needs_review' if case['case_id']=='olga_possible_bipolarity' else 'not_reported',
                'perception':'not_assessed','sleep':'worsening' if case['case_id'] in ('olga_possible_bipolarity','elena_comorbid') else mood_status,
                'activity':'needs_review' if case['case_id']=='olga_possible_bipolarity' else mood_status,
                'functioning':'partial' if case['case_id'] in ('maria_post_covid','anna_vitiligo','andrey_ssri_intolerance') else 'improving',
                'insight':'good','suicide_risk':'needs_review' if case['case_id']=='olga_possible_bipolarity' else 'not_assessed',
                'adherence':'poor' if tr.get('medication_adherence',0)<0.6 else 'partial' if tr.get('medication_adherence',0)<0.8 else 'good',
                'social_support':'unknown','side_effects':'present' if case['case_id'] in ('elena_comorbid','andrey_ssri_intolerance') else 'absent',
                'psychosis':'not_assessed'}
            conn.execute('INSERT INTO clinical_assessments(patient_id,visit_id,assessed_at,mental_state_json,summary,plan_notes,assessor_user_id,signed_by,signed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (patient_id,visit_id,_ts(start_date,day,13),json.dumps(mental,ensure_ascii=False),notes,
                 'Следующий шаг: сверить динамику, приверженность, функционирование и риски; изменения лечения — только по отдельному решению врача. '+marker,
                 doctor_id,doctor_id,_ts(start_date,day,14),created))
        # Calendar shows past completed visits, deviations, a completed rescheduled visit, and a future follow-up.
        for day,visit_id in visit_ids.items():
            v=next((x for x in case['visits'] if int(x['day'])==day),None)
            conn.execute('INSERT INTO appointments(patient_id,starts_at,ends_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                (patient_id,f'{_iso_day(start_date,day)}T13:00',f'{_iso_day(start_date,day)}T13:30','appointment',v['kind'] if v else 'Приём',v['summary'] if v else '', 'completed',doctor_id,_ts(start_date,day,13)))
        missed_day=int(tr.get('missed_visit_day',max(2,dur//2)))
        moved_day=int(tr.get('reschedule_day',min(dur-1,missed_day+3)))
        missed_status='missed' if case['case_id'] in ('elena_comorbid','olga_possible_bipolarity','andrey_ssri_intolerance') else 'rescheduled'
        missed_note=('Назначенный приём не состоялся; требуется связаться и уточнить возможность новой даты.' if missed_status=='missed'
                     else f'Слот перенесён на {_iso_day(start_date,moved_day)} по согласованию; исходный слот оставлен в истории.')
        conn.execute('INSERT INTO appointments(patient_id,starts_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (patient_id,f'{_iso_day(start_date,missed_day)}T11:00','appointment','Контрольный приём — отклонение от плана',missed_note,missed_status,doctor_id,_ts(start_date,missed_day,11)))
        # Upcoming appointment beyond the observed period, so it is in the future when the app is opened.
        future_day=dur+4+idx%3
        conn.execute('INSERT INTO appointments(patient_id,starts_at,ends_at,kind,title,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
            (patient_id,f'{_iso_day(start_date,future_day)}T10:00',f'{_iso_day(start_date,future_day)}T10:30','appointment','Следующий контрольный приём',
             'Запланировано врачом. На приёме обсудить последние шкалы, сон, дневник, переносимость и отклонения от плана.', 'scheduled',doctor_id,utc_now_safe()))
        # Clinical plan(s) are isolated per patient and preserve their own configuration.
        for cp in case.get('care_plans',[]): _seed_care_plan(conn,patient_id,doctor_id,case,cp,start_date,helpers)
        # Medication plan(s). Dose numbers are not invented; all are labeled as synthetic examples.
        med=case.get('medication') or {}
        medication_plan_id=None
        if med.get('drug_id'):
            drug_id=med['drug_id']; drug=next((x for x in helpers['load_medications']() if x.get('id')==drug_id),None)
            drug_name=drug.get('name') if drug else ('Эсциталопрам' if drug_id=='escitalopram' else str(drug_id))
            plan_start=start_date+timedelta(days=int(med.get('start_day',0)))
            if med.get('status')=='stopped': plan_end=start_date+timedelta(days=int(med.get('stop_day',-1)))
            else: plan_end=None
            status=med.get('status','draft')
            regimen=med.get('regimen','')
            notes=(med.get('notes','')+' '+marker+' Синтетический учебный план, не предназначен для назначения реальному пациенту.').strip()
            existing=conn.execute('SELECT id FROM medication_plans WHERE patient_id=? AND drug_id=? AND notes LIKE ?',
                (patient_id,drug_id,f'%{marker}%')).fetchone()
            if existing: medication_plan_id=existing['id']
            else:
                cur=conn.execute('''INSERT INTO medication_plans(patient_id,drug_id,drug_name,regimen,times_json,start_date,end_date,notes,status,created_by,approved_by,approved_at,created_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(patient_id,drug_id,drug_name,regimen,json.dumps(['09:00']),plan_start.isoformat(),plan_end.isoformat() if plan_end else None,notes,status,doctor_id,doctor_id if status in ('active','stopped','paused') else None,_ts(start_date,int(med.get('start_day',0)),13) if status in ('active','stopped','paused') else None,_ts(start_date,int(med.get('start_day',0)),13)))
                medication_plan_id=cur.lastrowid
        # Medication-adherence records make adherence, missed logging, and missed doses independently visible.
        if medication_plan_id and med.get('status')=='active':
            adherence=float(med.get('adherence',0.7)); plan_start_day=max(0,int(med.get('start_day',0)))
            for day in range(plan_start_day,dur+1):
                code=(day*37+(idx+1)*23)%100
                if day in set(tr.get('missed_medication_days',[])):
                    log_status='skipped'
                elif code < int(adherence*100): log_status='taken'
                elif code < int(adherence*100+(1-adherence)*56): log_status='skipped'
                else: continue  # Not reported, not automatically treated as a missed dose.
                notes='Отметка внесена в рамках синтетического сценария.'
                if log_status=='skipped': notes='Пациент отметил пропуск. Причина обсуждается без обвинения и требует контекстной оценки.'
                conn.execute('INSERT OR IGNORE INTO medication_logs(plan_id,patient_id,scheduled_date,status,side_effects,notes,logged_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (medication_plan_id,patient_id,_iso_day(start_date,day),log_status,'',notes,user_id,_ts(start_date,day,21)))
        # One or more structured adverse-event examples, deliberately not turned into diagnoses.
        if case['case_id']=='elena_comorbid':
            ae_day=min(34,dur)
            existing=conn.execute('SELECT id FROM adverse_events WHERE patient_id=? AND description LIKE ?', (patient_id,'%[[portrait_case:elena_comorbid]]%')).fetchone()
            if not existing:
                details='Головокружение и сонливость; причинная связь с конкретным препаратом не установлена. Необходимо сверить весь список текущих лекарств, соматические причины и временную последовательность. [[portrait_case:elena_comorbid]]'
                cur=conn.execute('INSERT INTO adverse_events(patient_id,medication_plan_id,reported_by,onset_at,symptoms_json,severity,serious,description,action_taken,outcome,clinician_assessment,review_status,reviewed_by,reviewed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (patient_id,None,user_id,_ts(start_date,ae_day,9),json.dumps(['dizziness','somnolence']), 'mild',0,details,'Запрошен полный список лекарств; до сверки не связывать симптом с отдельным продуктом.','','Причина не подтверждена; требуется сопоставление с хроническими болезнями и назначениями.','pending',None,None,_ts(start_date,ae_day,10)))
                helpers['create_alert'](conn,patient_id,'adverse_event',cur.lastrowid,'review','Головокружение/сонливость: требуется сверка лекарств',details,recipient='doctor',rule_id='demo_polypharmacy_review')
        if case['case_id']=='andrey_ssri_intolerance' and medication_plan_id:
            existing=conn.execute('SELECT id FROM adverse_events WHERE patient_id=? AND description LIKE ?', (patient_id,'%[[portrait_case:andrey_ssri_intolerance]]%')).fetchone()
            if not existing:
                details='По портрету: тошнота, дискомфорт в животе, снижение либидо, трудность достижения оргазма, усиление внутреннего беспокойства и затруднение засыпания на фоне эсциталопрама; после самостоятельной отмены часть симптомов ослабла. История описана пациентом, причинность и альтернативные причины должен оценить врач. [[portrait_case:andrey_ssri_intolerance]]'
                cur=conn.execute('INSERT INTO adverse_events(patient_id,medication_plan_id,reported_by,onset_at,symptoms_json,severity,serious,description,action_taken,outcome,clinician_assessment,review_status,reviewed_by,reviewed_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (patient_id,medication_plan_id,user_id,_ts(start_date,4,9),json.dumps(['nausea','gastrointestinal_discomfort','sexual_dysfunction','activation','insomnia']), 'moderate',0,details,'Зафиксировать в истории; не возобновлять автоматически; обсудить варианты с лечащим врачом.','По описанию пациента тошнота и сексуальные явления постепенно уменьшились после прекращения.','История переносимости документирована; причинность каждого симптома требует клинической оценки.','reviewed',doctor_id,_ts(start_date,8,12),_ts(start_date,4,10)))
                helpers['create_alert'](conn,patient_id,'adverse_event',cur.lastrowid,'review','История непереносимости эсциталопрама',details,recipient='doctor',rule_id='demo_ssri_tolerability_review')
        # A patient message is part of the record so the communication workflow is visible immediately.
        message_day=max(2,dur-8)
        message_text={
          'alexey_gad':'В последние дни легче отключаться от работы, но пару раз пропустил отметку о приёме. На совещаниях тревога всё ещё возвращается.',
          'maria_post_covid':'После плохой ночи снова волновалась о здоровье и не заполнила дневник. В остальные дни постепенно возвращаюсь к рабочему графику.',
          'elena_comorbid':'Сегодня было головокружение и сонливость. Я не уверена, связано ли это с лекарствами. Полный список препаратов ещё собираю.',
          'anna_vitiligo':'На этой неделе пропустила домашнюю задачу, на встрече чувствовала себя неуютно. Попробую в следующий раз более короткий шаг.',
          'olga_possible_bipolarity':'Последние ночи сплю меньше обычного; иногда энергии необычно много, а потом наступает сильная усталость. Хочу обсудить это на приёме.',
          'andrey_ssri_intolerance':'После прекращения эсциталопрама тошнота стала слабее, но тревога осталась. Боюсь повторения побочных эффектов и не хочу начинать другое лекарство без обсуждения.'
        }[case['case_id']]
        existing_msg=conn.execute('SELECT 1 FROM messages WHERE patient_id=? AND body=?',(patient_id,message_text)).fetchone()
        if not existing_msg:
            conn.execute('INSERT INTO messages(patient_id,sender_user_id,body,created_at) VALUES(?,?,?,?)',(patient_id,user_id,message_text,_ts(start_date,message_day,18)))
        # Each case gets a published, patient-visible recommendation; it is a support note, not a prescription.
        recommendation={
          'alexey_gad':'Продолжайте короткие записи о сне, тревоге и том, что помогло не возвращаться к перепроверке. Пропуски стоит открыто обсуждать; не меняйте схему самостоятельно.',
          'maria_post_covid':'Отмечайте сон и возвращение к рабочей активности. В дни усталости достаточно короткой записи; при ухудшении самочувствия сообщите врачу.',
          'elena_comorbid':'Подготовьте актуальный список всех лекарств, включая безрецептурные средства, и отметьте время появления головокружения. Не делайте самостоятельных изменений назначений.',
          'anna_vitiligo':'Выберите один небольшой социальный шаг, который кажется посильным. Если не получилось, запишите препятствие — это информация для совместной корректировки плана.',
          'olga_possible_bipolarity':'До ближайшего контакта отмечайте время сна и изменения энергии. Не начинайте и не отменяйте препараты самостоятельно; при резком ухудшении используйте согласованный план обращения за помощью.',
          'andrey_ssri_intolerance':'Запишите, какие симптомы уменьшились после отмены и что сохраняется. Обсуждайте любые изменения лекарств с врачом; не возобновляйте прежний препарат самостоятельно.'
        }[case['case_id']]
        if not conn.execute('SELECT 1 FROM recommendations WHERE patient_id=? AND body=?',(patient_id,recommendation)).fetchone():
            conn.execute('INSERT INTO recommendations(patient_id,body,visibility,status,created_by,approved_by,created_at,approved_at) VALUES(?,?,?,?,?,?,?,?)',
                (patient_id,recommendation,'patient','published',doctor_id,doctor_id,_ts(start_date,min(dur-1, max(1,dur-7)),14),_ts(start_date,min(dur-1,max(1,dur-7)),14)))
        # Open monitoring deviations that should be visible in the overview; no diagnostic labels are inferred.
        if case['case_id']=='olga_possible_bipolarity':
            res=conn.execute('SELECT id FROM questionnaire_results WHERE patient_id=? AND questionnaire_id="hcl33" ORDER BY created_at LIMIT 1',(patient_id,)).fetchone()
            helpers['create_alert'](conn,patient_id,'questionnaire',res['id'] if res else None,'review','HCL-33 выше порога скрининга: уточнить эпизоды активности',
              'В исходном портрете указано 17 баллов HCL-33. Это скрининг, не диагноз. Нужны прямое клиническое уточнение длительности эпизодов, сна, функционирования и безопасности до выбора терапии.',recipient='doctor',rule_id='demo_hcl33_review')
        if case['case_id']=='elena_comorbid':
            helpers['create_alert'](conn,patient_id,'profile',None,'review','Полипрагмазия: неполный список препаратов',
              'В портрете отмечены сахарный диабет, сердечно-сосудистые заболевания и приём нескольких препаратов. В карточке нет полного списка и данных для проверки взаимодействий; не делать вывод об отсутствии риска.',recipient='doctor',rule_id='demo_polypharmacy_missing_list')
        if case['case_id']=='anna_vitiligo':
            helpers['create_alert'](conn,patient_id,'questionnaire',None,'review','Повторное ухудшение настроения в динамике',
              'В смоделированной серии последний MADRS выше промежуточного значения. Это сигнал перепроверить контекст, функционирование и безопасность, а не готовый диагноз.',recipient='doctor',rule_id='demo_trend_worsening')
        if case['case_id']=='andrey_ssri_intolerance':
            helpers['create_alert'](conn,patient_id,'medication_plan',medication_plan_id,'review','Самостоятельное прекращение эсциталопрама',
              'По портрету пациент самостоятельно прекратил прежний препарат из-за комплекса нежелательных явлений. Обсудить историю переносимости и план последующего лечения; не предлагать автоматическое возобновление.',recipient='doctor',rule_id='demo_self_discontinuation')
        conn.execute('INSERT INTO demo_portrait_seeds(patient_id,case_id,fixture_version,seeded_at) VALUES(?,?,?,?)',
            (patient_id,case['case_id'],cases_doc.get('dataset_version','1.0'),utc_now_safe()))
        results['seeded']+=1; results['patients'].append({'case_id':case['case_id'],'patient_id':patient_id,'seeded':True})
    conn.commit()
    return results


def utc_now_safe():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
