#!/usr/bin/env python3
"""Build the versioned clinical content packs from attached guideline references."""
from pathlib import Path
import json, hashlib
ROOT=Path(__file__).resolve().parent
SCHEMES=ROOT/'data'/'treatment_schemes'; SCHEMES.mkdir(parents=True,exist_ok=True)
GUIDE=ROOT/'data'/'guidelines'; GUIDE.mkdir(parents=True,exist_ok=True)
def write_json(path,obj): path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def scheme(id,title,category,summary,source_refs,eligibility,steps,monitoring,red_flags,limits,**extra):
 d={'id':id,'title':title,'category':category,'version':'1.0.0','status':'active_reference','summary':summary,
    'intended_for':'Для обсуждения и утверждения лечащим специалистом; не автономное назначение.',
    'source_refs':source_refs,'eligibility_checks':eligibility,'steps':steps,'monitoring':monitoring,
    'red_flags':red_flags,'limits':limits,'approval_required':True,'patient_visible_after_approval':True,
    'editable_fields':['start_date','target','notes','assigned_to','review_date'],'evidence_note':'Не все приложенные материалы являются руководствами с окончательными рекомендациями. Тип источника и его версия указаны в реестре; решение должно соответствовать актуальным локальным требованиям.',**extra}
 write_json(SCHEMES/f'{id}.json',d)

scheme('depression_guided_self_help','Депрессия: сопровождаемая самопомощь','Психологическое вмешательство',
 'Для клинического обсуждения при менее тяжёлой депрессии: структурированные материалы самопомощи на принципах КПТ, поведенческой активации, решения проблем или психообразования; специалист поддерживает выполнение и проверяет прогресс.',
 [{'source_id':'nice_ng222_2022','location':'раздел 1.5.2; таблица 1; печатные страницы 27–29','supports':'выбор лечения совместно с человеком; предпочтение наименее навязчивого и ресурсоёмкого варианта при клинической уместности; guided self-help обычно 6–8 структурированных сессий.'}],
 ['Оценить выраженность симптомов, функционирование, риск самоповреждения/суицида, возможные психотические или маниакальные симптомы, сопутствующие состояния и потребности пациента.',
  'Убедиться, что нет признаков, требующих более срочной или специализированной помощи.',
  'Обсудить предпочтения, доступность, способность заниматься самостоятельно и согласие на программу.'],
 [{'id':'assessment','title':'Оценка и совместная цель','description':'Уточнить ключевые трудности, предпочтительную небольшую цель и способ мониторинга. Не подменять диагноз баллом шкалы.','owner':'clinician','timing':'до старта'},
  {'id':'material','title':'Выбрать структурированный материал','description':'Материал может следовать принципам КПТ, поведенческой активации, решения проблем или психообразования; выбрать разрешённый и подходящий ресурс.','owner':'clinician_patient','timing':'сессия 1'},
  {'id':'support','title':'Поддерживаемое выполнение','description':'Регулярная короткая поддержка выполнения, устранение барьеров и проверка прогресса; NICE описывает обычно 6–8 структурированных сессий для guided self-help.','owner':'clinician_patient','timing':'индивидуально по протоколу'},
  {'id':'review','title':'Проверка ответа и плана','description':'Повторно оценить симптомы, функционирование, выполнение и безопасность; при ухудшении или недостаточном ответе пересмотреть маршрут.','owner':'clinician','timing':'срок задаёт врач'}],
 ['Повторять выбранную валидированную шкалу с соблюдением её периода оценки; сравнивать версии и даты.',
  'Проверять функционирование, повседневную активность, доступность поддержки и барьеры выполнения.',
  'Фиксировать побочные явления и red flags, если они возникли; не считать отсутствие записи отсутствием симптомов.'],
 ['Усиление суицидальных мыслей/намерения, психотические симптомы, возможная мания/гипомания, неспособность обеспечить безопасность или быстрое ухудшение требуют отдельной клинической оценки и изменения маршрута.'],
 ['Не предназначена для средней/тяжёлой/сложной клинической ситуации без отдельного решения врача.',
  'Продолжительность 6–8 сессий — описание NICE для guided self-help, а не универсальный обязательный график.',
  'Не является автоматическим назначением и не гарантирует улучшение.'])

scheme('behavioral_activation','Поведенческая активация','Психологическое вмешательство',
 'Структурированное планирование небольших значимых и потенциально вознаграждающих действий с последующим обсуждением выполнения и влияния на состояние. В источниках описана как компонент КПТ и подход, который может быть проще в освоении, но конкретный протокол выбирает обученный специалист.',
 [{'source_id':'who_behavioural_activation_2012','location':'стр. 1–5','supports':'описание подхода и evidence profile; не задаёт универсальную индивидуальную частоту/дозу сессий.'},
  {'source_id':'nice_ng222_2022','location':'таблицы психологических вмешательств, раздел 1.5','supports':'поведенческая активация как один из структурированных психологических подходов.'}],
 ['Уточнить текущие возможности и ограничения, риски, коморбидность и интересы пациента.',
  'Согласовать цели с пациентом; активности должны быть реалистичными, посильными и выбранными вместе.',
  'При выраженном ухудшении не заменять клиническую оценку самопомощью.'],
 [{'id':'map','title':'Карта активности','description':'Собрать примеры действий, избегания, активности и состояния после действия.','owner':'clinician_patient','timing':'старт'},
  {'id':'plan','title':'Выбрать малое действие','description':'Выбрать конкретную, посильную активность с понятными временем/условием; предусмотреть более лёгкую альтернативу.','owner':'patient','timing':'по согласованному графику'},
  {'id':'record','title':'Отметить выполнение и эффект','description':'Пациент отмечает выполнение, препятствия и самочувствие; пропуск не считается нарушением и не вызывает штрафа.','owner':'patient','timing':'дневник'},
  {'id':'review','title':'Пересмотреть сложность и план','description':'Врач/терапевт помогает изменить барьеры и дозировать задачу, не повышая нагрузку автоматически.','owner':'clinician_patient','timing':'по договорённости'}],
 ['Ведение дневника действий, настроения и функционирования.', 'Обсуждение барьеров и безопасной посильности задания.', 'Повторная оценка симптомов и риска по клиническому плану.'],
 ['Ухудшение, суицидальные мысли/намерение, психотические или маниакальные признаки — внеплановая оценка специалистом.'],
 ['Это описание метода, а не протокол с универсальным количеством сессий.', 'Нельзя использовать поведенческую активацию как замену требуемой неотложной или специализированной помощи.'])

scheme('cbt_structured','КПТ / структурированная психологическая терапия','Психологическое вмешательство',
 'Согласованный со специалистом структурированный курс, направленный на связь мыслей, эмоций, поведения и функционирования; формат, количество сессий и компоненты определяются клинической оценкой и выбранной программой.',
 [{'source_id':'nice_ng222_2022','location':'раздел 1.5 и таблицы психологических вмешательств','supports':'психологические варианты для депрессии и совместный выбор.'},
  {'source_id':'who_brief_structured_psychological_2023','location':'разделы 3–4, evidence profiles/GRADE','supports':'обзор доказательств для КПТ, поведенческой активации, IPT, PST и других подходов; это обзор доказательств, не полный индивидуальный протокол.'},
  {'source_id':'who_cbt_panic_2012','location':'стр. 1–6','supports':'документ о лечении на принципах КПТ у людей, обеспокоенных паническими атаками; доказательства компонентов могут быть косвенными.'}],
 ['Определить целевой симптом, функционирование, риски, предпочтения и доступность терапии.', 'Сопоставить диагноз и подход, квалификацию специалиста, требования к интенсивности и необходимость сочетания методов.', 'Проверить, что выбранные материалы и тесты можно использовать в цифровом формате.'],
 [{'id':'formulation','title':'Совместная формулировка проблемы','description':'Сформулировать целевые проблемы, влияющие факторы, ресурсы и цели вместе с пациентом.','owner':'clinician_patient','timing':'начало'},
  {'id':'treatment','title':'Проведение согласованного курса','description':'Использовать руководство/протокол, соответствующий выбранному методу и квалификации терапевта.','owner':'clinician','timing':'по конкретному протоколу'},
  {'id':'homework','title':'Домашние задачи и дневник','description':'Задачи и материалы выбирает специалист; приложение помогает отмечать выполнение, препятствия и эффект.','owner':'patient','timing':'между сессиями'},
  {'id':'review','title':'Оценка ответа и следующего шага','description':'Сопоставить данные до/после, переносимость, предпочтения и функционирование; изменить план только после обсуждения.','owner':'clinician_patient','timing':'по протоколу'}],
 ['Использовать один и тот же инструмент и идентичную версию при повторных измерениях.', 'Сохранять раздельно симптомы, функционирование, риск и нежелательные явления.', 'Оценивать выполнение, доступность и качество терапевтического контакта.'],
 ['Положительный red flag требует прямого уточнения; при непосредственной угрозе безопасности стандартный план сессий не продолжают без оценки риска.'],
 ['Набор доказательств включает разные методы/популяции и разную определённость; нельзя из обзора выводить единственный лучший метод для конкретного пациента.', 'Приложение не предоставляет сгенерированные LLM терапевтические инструкции.'])

scheme('relaxation_support','Релаксационные техники как поддерживающий компонент','Поддерживающая методика',
 'Опциональный поддерживающий подход, который обсуждается с пациентом и используется в пределах компетенции специалиста. Загруженный WHO evidence profile (2012) описывает доказательства неоднородной/низкой определённости; метод не представлен здесь как гарантированно эффективная монотерапия.',
 [{'source_id':'who_relaxation_2012','location':'стр. 1–7; GRADE tables','supports':'evidence profile relaxation versus usual care; в файле отмечена низкая определённость по ряду исходов.'}],
 ['Уточнить индивидуальные предпочтения, переносимость и медицинские ограничения.', 'Согласовать метод и остановку при дискомфорте.'],
 [{'id':'agree','title':'Согласовать простой метод','description':'Метод выбирает специалист/пациент с учётом предпочтений и имеющихся инструкций.','owner':'clinician_patient','timing':'до практики'},
  {'id':'practice','title':'Практиковать по согласованной инструкции','description':'Не добавлять универсальные задержки дыхания/нагрузки; использовать проверенный безопасный материал.','owner':'patient','timing':'по согласованному графику'},
  {'id':'review','title':'Проверить пользу и дискомфорт','description':'Отметить переносимость и субъективную пользу; при ухудшении прекратить и обсудить с врачом.','owner':'patient_clinician','timing':'на контрольной связи'}],
 ['Переносимость, влияние на симптомы/функционирование, любое ухудшение.'],
 ['Острый риск, маниакальные/психотические признаки или выраженное ухудшение требуют отдельной оценки.', 'Источник 2012 года — доказательный обзор, не актуальный самостоятельный клинический протокол.'],
 ['Не назначать технику автоматически только из-за суммы шкалы.'])

scheme('physical_activity_support','Поддержка посильной физической активности','Поддерживающая методика',
 'Совместно выбранная, постепенная и медицински уместная активность как часть общего плана. Прикреплённый WHO evidence profile 2012 изучал рекомендации по активности и включал разные виды вмешательств; не задаёт безопасный универсальный объём для каждого пациента.',
 [{'source_id':'who_physical_activity_2012','location':'стр. 1–8; PICO и GRADE tables','supports':'обзор совета по физической активности у взрослых с депрессивным эпизодом/расстройством и неактивным образом жизни.'},
  {'source_id':'nice_ng222_2022','location':'раздел 1.5; варианты психологической/социальной поддержки','supports':'выбор лечения с учётом предпочтений и потребностей.'}],
 ['Уточнить соматические ограничения, доступность, безопасность среды и готовность пациента.', 'Задание должно быть посильным и согласованным; при сомнениях требуется медицинская оценка.'],
 [{'id':'baseline','title':'Оценить исходную активность и барьеры','description':'Уточнить привычную активность, ограничения и то, что пациент считает реалистичным.','owner':'clinician_patient','timing':'старт'},
  {'id':'goal','title':'Согласовать небольшой шаг','description':'Выбрать действие/активность без автоматического наращивания нагрузки.','owner':'patient','timing':'по договорённости'},
  {'id':'record','title':'Отметить факт и переносимость','description':'Записать действие, самочувствие и любые нежелательные симптомы.','owner':'patient','timing':'дневник'},
  {'id':'review','title':'Пересмотреть план','description':'Врач/специалист решает, сохранить, изменить или прекратить план с учётом симптомов и соматических факторов.','owner':'clinician_patient','timing':'по согласованному сроку'}],
 ['Функционирование, переносимость, субъективный эффект, сон и дневниковая динамика.'],
 ['Сильная/новая боль в груди, обморок, выраженная одышка или иные неотложные физические симптомы требуют экстренной оценки по местному протоколу.'],
 ['Не медицинская реабилитационная программа; не содержит назначения нагрузки или противопоказаний по диагнозу.', 'В материалах WHO 2012 обсуждается доказательная база, а не персональное назначение.'])

scheme('antidepressant_start_review','Антидепрессант: согласование начала и мониторинга','Фармакотерапевтический workflow',
 'Чек-лист безопасного назначения, которое выполняет врач. Не содержит выбора препарата или дозы и не заменяет действующую инструкцию, локальные правила и оценку взаимодействий.',
 [{'source_id':'nice_ng222_2022','location':'1.4.10–1.4.12, стр. 17–18','supports':'совместный план, обсуждение пользы/вреда, письменно предоставленная информация, ожидание эффекта и срок первого обзора.'},
  {'source_id':'who_antidepressant_treatment_2023','location':'разделы 1–4; GRADE/evidence-to-decision','supports':'evidence profile о TCA/SSRI и длительности; степень уверенности varies, это не индивидуальная схема дозирования.'},
  {'source_id':'russian_standard_1697','location':'раздел 3, стр. 5–7','supports':'в документе перечислены отдельные лекарственные вещества и средние дозы в рамках стандарта; заголовок/приказ требуют независимой проверки актуального правового статуса. Значения НЕ переносить в индивидуальное назначение.'}],
 ['Подтвердить клиническое показание и рабочую формулировку состояния; оценить суицидальный риск, признаки биполярности/психоза, коморбидность и альтернативы.', 'Проверить актуальную инструкцию в официальном реестре, противопоказания, взаимодействия, другие препараты, соматические риски и предпочтения.', 'Обсудить ожидаемую пользу, нежелательные/отменные явления, приверженность, план контроля и письменную информацию.'],
 [{'id':'shared_decision','title':'Совместное решение и письменный план','description':'Зафиксировать причины выбора, альтернативы, пожелания пациента, цели и план контроля.','owner':'clinician_patient','timing':'до назначения'},
  {'id':'prescriber_check','title':'Проверка инструкции/назначения','description':'Врач сверяет зарегистрированную инструкцию и локальные протоколы. Справочник в приложении не подставляет дозу.','owner':'clinician','timing':'до подтверждения'},
  {'id':'first_review','title':'Первый контроль','description':'NICE NG222 указывает обычно первый обзор в течение 2 недель; через 1 неделю для возраста 18–25 лет или при особом опасении о суицидальном риске. Частоту затем определяет клиническая ситуация.','owner':'clinician_patient','timing':'по NICE NG222, адаптировать к локальному протоколу'},
  {'id':'response','title':'Оценка ответа и переносимости','description':'Проверить симптомы, функционирование, побочные эффекты, приверженность, взаимодействия и необходимость коррекции; действия утверждает врач.','owner':'clinician','timing':'регулярно'},
  {'id':'continuation','title':'Обсуждение поддерживающего этапа','description':'Обсудить пользу/риски продолжения и релапс-профилактики; NG222 отмечает, что лечение может требоваться минимум 6 месяцев после ремиссии с регулярным пересмотром.','owner':'clinician_patient','timing':'после ответа/ремиссии'}],
 ['Регистрировать все нежелательные явления по системам, выраженность, начало, связь по времени и исход.', 'При повышенном риске — чаще контакт/контроль по персональному safety plan.', 'Не считать пропуск опросника или отсутствующую запись доказательством отсутствия побочных эффектов.'],
 ['Суицидальное намерение/план, резкое ухудшение, признаки мании/гипомании/психоза, тяжёлая аллергическая реакция или иной экстренный симптом требуют отдельной срочной оценки.', 'Тяжёлая лекарственная реакция проходит отдельным workflow и не ждёт планового визита.'],
 ['В приложение не перенесены дозировки. Значения средних доз из российских стандартов не являются персональными назначениями.', 'WHO 2023 evidence profiles — обзоры доказательств; окончательную рекомендацию следует брать из соответствующего действующего руководства.', 'Не назначать, не изменять и не отменять препарат автоматически.'])

scheme('antidepressant_relapse_prevention','Депрессия: обсуждение профилактики рецидива','Поддерживающий этап',
 'План обсуждения поддерживающего лечения после полного или частичного улучшения. Учитывает индивидуальный риск, предпочтения пациента, побочные эффекты и доступные психологические опции.',
 [{'source_id':'nice_ng222_2022','location':'раздел 1.8.1–1.8.7, стр. 57–59','supports':'совместное решение о продолжении; факторы повышенного риска рецидива; в определённых случаях продолжение лекарства, группа CBT/MBCT или комбинация; курс профилактики CBT/MBCT обычно 8 сессий за 2–3 месяца с возможными дополнительными сессиями в следующие 12 месяцев.'},
  {'source_id':'who_antidepressant_duration_2023','location':'разделы 3–4, GRADE','supports':'обзор длительности лечения; в документе подчёркнута неопределённость некоторых данных и смешение рецидива с синдромом отмены.'}],
 ['Уточнить достижение ремиссии/остаточные симптомы и историю эпизодов.', 'Проверить частые/недавние рецидивы, неполный ответ, тяжёлое функциональное нарушение, хронические сопутствующие состояния и продолжающиеся стрессоры.', 'Обсудить предпочтение пациента и долгосрочные побочные эффекты.'],
 [{'id':'risk_review','title':'Оценка риска рецидива','description':'Зафиксировать факторы риска/защиты и остаточные симптомы.','owner':'clinician_patient','timing':'после улучшения'},
  {'id':'options','title':'Сравнить варианты','description':'Обсудить продолжение назначенной терапии, согласованный психологический курс (например групповая КПТ/MBCT по локальной доступности) или комбинацию, если клинически уместно.','owner':'clinician_patient','timing':'совместное решение'},
  {'id':'plan','title':'План поддержания достигнутого','description':'Определить способы продолжать полезные стратегии, признаки раннего ухудшения, способ связи и сроки обзора.','owner':'clinician_patient','timing':'после выбора'},
  {'id':'review','title':'Регулярный пересмотр','description':'Балансировать пользу продолжения, риск рецидива, побочные эффекты и предпочтение пациента.','owner':'clinician','timing':'назначает врач'}],
 ['Симптомы, функционирование, остаточная симптоматика, приверженность, нежелательные явления и стрессоры.'],
 ['Возвращение суицидальных мыслей, ухудшение функционирования, психотические/маниакальные признаки требуют внеплановой оценки.'],
 ['Схема не устанавливает обязательную длительность для конкретного человека и не заменяет решение врача.', 'Не отменять/не снижать препарат автоматически.'])

scheme('antidepressant_taper_review','Антидепрессант: план постепенного снижения/отмены','Фармакотерапевтический workflow',
 'Планируемое врачом и согласованное с пациентом снижение препарата ступенчато, с учётом фармакокинетики, длительности лечения, симптомов отмены и возврата симптомов. В приложении нет дозировочного календаря.',
 [{'source_id':'nice_ng222_2022','location':'раздел 1.4.13–1.4.20, стр. 18–21','supports':'не прекращать резко; снижать поэтапно; следующую ступень определять с учётом разрешения/переносимости симптомов; мониторить и симптомы отмены, и возврат депрессии.'},
  {'source_id':'who_antidepressant_duration_2023','location':'раздел 3.6 и 4, стр. 21–44','supports':'evidence profile отмечает очень низкую/низкую определённость по нескольким стратегиям и ограничения исследований коротких схем tapering.'}],
 ['Врач подтвердил целесообразность снижения и обсудил риски/альтернативы.', 'Определён текущий препарат и инструкция; оценены прошлые симптомы отмены, состояние, поддержка и риск рецидива.', 'Пациент понимает, что не должен самовольно пропускать дозы или останавливать препарат.'],
 [{'id':'prepare','title':'Совместно составить план','description':'Врач задаёт величину и интервал каждого шага по конкретному препарату и ситуации; универсальный шаблон дозы не применяется.','owner':'clinician_patient','timing':'до начала'},
  {'id':'step','title':'Выполнять только согласованный шаг','description':'Фиксировать дату шага, симптомы отмены, состояние и переносимость.','owner':'patient','timing':'по индивидуальному плану'},
  {'id':'review','title':'Проверить переносимость','description':'Следующий шаг рассматривается после оценки симптомов и их переносимости; темп меняется врачом.','owner':'clinician','timing':'между шагами'},
  {'id':'close','title':'Закрыть план и продолжить наблюдение','description':'Зафиксировать завершение или причину паузы; составить план реагирования при возвращении симптомов.','owner':'clinician_patient','timing':'по результату'}],
 ['Симптомы отмены, настроение, тревога, сон, функционирование, риск и приверженность.'],
 ['Сильные или стойкие симптомы отмены, суицидальные мысли, быстрое ухудшение или иная тяжёлая реакция — срочный контакт/оценка.'],
 ['Нельзя генерировать fixed taper schedule для всех пациентов.', 'WHO 2023 документ — evidence profile, прямо отмечающий очень низкую определённость ряда данных.', 'Вне медицинского надзора приложение не рассчитывает шаги и не предлагает возобновить дозу.'])

scheme('anxiety_assessment_pathway','Тревожные симптомы: оценка и выбор маршрута','Клинический маршрут',
 'Обобщённая карта клинической оценки при тревожных симптомах: уточнить подтип, выраженность, функционирование, сопутствующие состояния и риски; обсуждать психологические и фармакологические варианты по актуальному руководству.',
 [{'source_id':'german_s3_anxiety_2021','location':'Version 2, 06.04.2021; разделы по паническому расстройству/агорафобии, GAD и социальной фобии','supports':'описание вариантов КПТ и отдельных классов препаратов по конкретным расстройствам; сама копия указывает плановую перепроверку 04/2026, поэтому текущий статус требуется проверить.'},
  {'source_id':'who_mhgap_anxiety_evidence_2023','location':'разделы 3–4 по соответствующим PICO-вопросам','supports':'evidence profiles для психологических/фармакологических вмешательств; это обзоры доказательств, не индивидуальные назначения.'}],
 ['Уточнить симптомный профиль, временной ход, функционирование, употребление веществ/лекарств, медицинские причины и сопутствующие состояния.', 'Проверить суицидальный риск, признаки мании/психоза, тяжёлую депрессию и безопасность.', 'Сверить актуальное руководство и правовой статус источника до выбора лечения.'],
 [{'id':'classify','title':'Клиническое уточнение симптомов','description':'Использовать интервью и выбранные валидированные шкалы; не выводить диагноз из одной суммы.','owner':'clinician','timing':'старт'},
  {'id':'preference','title':'Обсудить варианты помощи','description':'Сопоставить психологическую помощь, лекарства и другие подходы с клинической ситуацией и предпочтениями.','owner':'clinician_patient','timing':'после оценки'},
  {'id':'source','title':'Проверить актуальный источник','description':'Сверить текущую редакцию руководства и действующие зарегистрированные инструкции.','owner':'clinician','timing':'перед назначением'},
  {'id':'monitor','title':'Оценить ответ и переносимость','description':'Контроль симптомов, функционирования, приверженности, побочных эффектов и риска.','owner':'clinician_patient','timing':'согласованный график'}],
 ['Динамика шкал, клиническое интервью, функционирование, нежелательные явления и безопасность.'],
 ['Психотические симптомы, мания/гипомания, непосредственный суицидальный риск или быстрое ухудшение требуют срочной клинической оценки.'],
 ['Немецкая S3 копия заявляет дату плановой проверки 04/2026; не считать редакцию 2021 актуальной без независимой проверки.', 'Не содержит дозировок и не автоматизирует выбор препарата.'])

scheme('psychosis_red_flag_review','Подозрение на бредовые/галлюцинаторные переживания: проверка и маршрут','Защитный маршрут',
 'Технический маршрут на случай положительного ответа шкалы/сообщения о необычном содержании мыслей или восприятия. Флаг означает «проверить напрямую», не подтверждает бред или психотическое расстройство.',
 [{'source_id':'who_icd11_cddr_2024','location':'ICD-11 CDDR, соответствующие диагностические разделы','supports':'клиническое описание/диагностические требования; классификация не применяется автоматически по текстовому маркеру.'},
  {'source_id':'clinic_case_todo','location':'обязательные условия и red-flag workflow','supports':'инструмент поддержки принятия решений должен учитывать риски и маршрутизацию и не выполнять клинические действия самостоятельно.'}],
 ['Получен отмеченный ответ опросника или текстовое сообщение по правилу red flag.', 'Специалист проверяет контекст, буквальность/метафору, длительность, убеждённость, дистресс, функционирование, риски и соматические/вещественные факторы.'],
 [{'id':'notify','title':'Создать заметный сигнал','description':'Система сохраняет источник и исходную формулировку, уведомляет назначенного врача и показывает событие в карте пациента.','owner':'system','timing':'сразу после сохранения'},
  {'id':'review','title':'Прямое уточнение врачом','description':'Уточнить, что именно имелось в виду; не ставить диагноз автоматически по совпадению ключевых слов.','owner':'clinician','timing':'по срочности и локальному протоколу'},
  {'id':'route','title':'Принять клиническое решение','description':'Врач фиксирует решение, необходимые меры безопасности и маршрутизацию.','owner':'clinician','timing':'после уточнения'}],
 ['Сохраняется точный источник: сообщение/инструмент/вопрос/ответ/время; отмечается кто подтвердил получение сигнала и дальнейшее решение.'],
 ['Если есть непосредственная угроза жизни, неспособность обеспечить безопасность или резко меняющееся состояние — не ждать чата/планового приёма, действовать по экстренному локальному протоколу.'],
 ['Нельзя считать наличие ключевого слова диагнозом.', 'Внутреннее приложение не является диспетчерской/экстренной службой; без внешнего канала/подтверждения оно не гарантирует доставку врачу.'])

scheme('adverse_event_review','Лекарственная нежелательная реакция: регистрация и review','Безопасность лекарств',
 'Единая запись нежелательной реакции с привязкой к конкретному плану, системным проявлениям, выраженности, времени начала, действию и исходу. Система подсвечивает событие и ставит задачу врачу; не даёт автоматический совет отменить или повторить лекарство.',
 [{'source_id':'nice_ng222_2022','location':'разделы 1.4.10–1.4.19','supports':'обсуждение harms, побочных и отменных явлений, мониторинг и review.'},
  {'source_id':'russian_standard_1697','location':'примечания к перечню лекарственных средств','supports':'препараты применяются по действующей инструкции; стандарт не заменяет индивидуальную оценку.'}],
 ['Проверить название/план, дату/время, симптом, выраженность и наличие экстренных признаков.', 'При необходимости немедленно включить местный протокол неотложной помощи.'],
 [{'id':'report','title':'Зарегистрировать событие','description':'Пациент/врач заполняет симптомы, начало, выраженность, влияние на функционирование и действие/исход.','owner':'patient_clinician','timing':'при событии'},
  {'id':'notify','title':'Создать видимый сигнал','description':'Система направляет уведомление в зависимости от настроенного правила; событие видно в профиле и истории лекарств.','owner':'system','timing':'после сохранения'},
  {'id':'review','title':'Клинический review','description':'Врач оценивает причинность/тяжесть и записывает решение: наблюдение, дополнительная оценка, обращение за неотложной помощью или изменение плана.','owner':'clinician','timing':'по тяжести'},
  {'id':'close','title':'Зафиксировать исход и follow-up','description':'Событие закрывается только после документированного исхода; реакция не исчезает из исторической записи.','owner':'clinician','timing':'после follow-up'}],
 ['Повторный контакт/исход, повторяемость симптома, связь по времени с препаратом, выполнение и последующее состояние.'],
 ['Анафилаксия/тяжёлое затруднение дыхания, потеря сознания, тяжёлые сердечно-сосудистые симптомы, судороги, выраженная спутанность, суицидальный риск или другое неотложное состояние: экстренная помощь согласно местному протоколу, не ожидать ответа в чате.'],
 ['Это workflow регистрации, а не автоматическое заключение о причинности.', 'Система не отменяет препарат и не выдаёт рекомендации по лечению реакции без врача.'])

sources=[
 {'id':'who_icd11_cddr_2024','title':'Clinical descriptions and diagnostic requirements for ICD-11 mental, behavioural and neurodevelopmental disorders','file':'Clinical_descriptions.pdf','type':'WHO clinical description/diagnostic requirements','year':2024,'status':'reference','licence':'CC BY-NC-ND 3.0 IGO; no adaptations/translations without permission','note':'Use as reference for clinician review, not automated diagnosis.'},
 {'id':'who_mhgap_anxiety_evidence_2023','title':'Evidence profiles for the anxiety module (ANX) of WHO mhGAP guideline update','file':'mhgap-anxiety-evidence-review-report(29012024)_eb.pdf','type':'evidence review/GRADE profile','year':2023,'status':'evidence_profile','note':'Evidence review, not necessarily final recommendations or patient-specific regimen.'},
 {'id':'who_antidepressant_treatment_2023','title':'Antidepressants (TCAs and SSRIs) in adults with depressive episode/disorder','file':'antidepressants_tricyclic_antidepressants_and_selective_serotonin.pdf','type':'WHO mhGAP evidence profile DEP1','year':2023,'status':'evidence_profile','note':'Evidence profile. Do not infer doses or a patient-specific treatment plan from this file.'},
 {'id':'who_antidepressant_duration_2023','title':'Length of treatment with antidepressants for adults with depressive episode/disorder','file':'duration-of-antidepressant-treatment-2023.pdf','type':'WHO mhGAP evidence profile DEP2','year':2023,'status':'evidence_profile','note':'Evidence certainty varies; includes limits in tapering/discontinuation research.'},
 {'id':'who_brief_structured_psychological_2023','title':'Brief, structured psychological treatment for adults with depressive episode/disorder','file':'brief-structured-psychological-treatment-2023.pdf','type':'WHO mhGAP evidence profile DEP3','year':2023,'status':'evidence_profile','note':'Covers different structured psychological modalities and GRADE assessments.'},
 {'id':'who_cbt_panic_2012','title':'Psychological treatment based on CBT principles in people concerned about prior panic attacks','file':'psychological_treatment_based_on_cognitive_behavioural_therapy_principles.pdf','type':'WHO evidence profile/scoping review','year':2012,'status':'older_evidence_profile','note':'The document explicitly notes indirect evidence for certain CBT components.'},
 {'id':'who_behavioural_activation_2012','title':'Behavioural activation','file':'behavioural-activation.pdf','type':'WHO evidence profile/scoping review','year':2012,'status':'older_evidence_profile','note':'Describes the approach and reviewed evidence, not an individual protocol.'},
 {'id':'who_relaxation_2012','title':'Relaxation training','file':'relaxation-training.pdf','type':'WHO evidence profile/scoping review','year':2012,'status':'older_evidence_profile','note':'Evidence quality varies; do not state it as a guaranteed standalone treatment.'},
 {'id':'who_physical_activity_2012','title':'Physical activity','file':'physical-activity.pdf','type':'WHO evidence profile/scoping review','year':2012,'status':'older_evidence_profile','note':'Evidence about advice on activity, not an individual exercise prescription.'},
 {'id':'nice_ng222_2022','title':'Depression in adults: treatment and management (NG222)','file':'Depression_in_adults.pdf','type':'clinical guideline','organization':'NICE','year':2022,'status':'guideline_snapshot','note':'Sections referenced include first-line options for less severe depression, starting antidepressants, stopping medication and relapse prevention. Check current version and local applicability.'},
 {'id':'canmat_mdd_2023_update','title':'CANMAT 2023 Update on Clinical Guidelines for Management of Major Depressive Disorder in Adults','file':'Canadian_Network_for_Mood_and_Anxiety_Treatments_CANMAT_2023_Update.pdf','type':'clinical guideline update/review','organization':'CANMAT','year':2024,'status':'guideline_snapshot','note':'For contextual review; not substituted for local standards.'},
 {'id':'va_dod_mdd_2022','title':'VA/DoD Clinical Practice Guideline for the Management of Major Depressive Disorder, Version 4.0','file':'CLINICAL_PRACTICE.pdf','type':'clinical practice guideline','organization':'VA/DoD','year':2022,'status':'guideline_snapshot','note':'The document says evidence reviewed through January 2021 and that recommendations do not prescribe an exclusive course of management.'},
 {'id':'german_s3_anxiety_2021','title':'S3-Leitlinie Behandlung von Angststörungen, Version 2','file':'051-028l_S3_Behandlung-von-Angststoerungen_04-2021.pdf','type':'clinical guideline','organization':'AWMF','year':2021,'status':'needs_currentness_check','note':'Document shows status 06.04.2021 and next review planned 04/2026; current version must be independently verified.'},
 {'id':'german_nvl_depression_2022','title':'Nationale VersorgungsLeitlinie Unipolare Depression, Langfassung Version 3.2','file':'nvl-005l_S3_Unipolare-Depression_2023-07.pdf','type':'clinical guideline','organization':'NVL/AWMF','year':2022,'status':'guideline_snapshot','note':'Document advises only the documents authorized at its official programme website count as valid; verify current revision.'},
 {'id':'russian_standard_1688','title':'Стандарт первичной медико-санитарной помощи при органических/симптоматических, депрессивных и тревожных расстройствах в связи с эпилепсией','file':'1688_стандарт.pdf','type':'Russian care-standard attachment','year':None,'status':'legal_status_unverified','note':'Order number is blank in the supplied copy. Medication-list averages are not individualized prescription doses; verify legal status.'},
 {'id':'russian_standard_1697','title':'Стандарт первичной медико-санитарной помощи при депрессиях (ремиссии)','file':'1697_стандарт.pdf','type':'Russian care-standard attachment','year':None,'status':'legal_status_unverified','note':'Order number is blank in the supplied copy. The list includes mean daily/course doses; do not use these as patient-specific instructions without current official verification.'},
 {'id':'clinic_case_todo','title':'Кейс: цифровой ассистент врача для ведения пациента с тревожной и депрессивной симптоматикой','file':'TODO(2).pdf','type':'user requirements / clinical demo scenario','year':None,'status':'product_requirements','note':'Requires two roles, linked doctor-patient records, physician confirmation for clinical actions and routes.'}
]
source_urls={
 'nice_ng222_2022':'https://www.nice.org.uk/guidance/ng222',
 'canmat_mdd_2023_update':'https://doi.org/10.1177/07067437241245384',
 'who_icd11_cddr_2024':'https://www.who.int/publications/i/item/9789240077263',
 'who_mhgap_anxiety_evidence_2023':'https://www.who.int/publications/i/item/9789240084278',
 'who_antidepressant_treatment_2023':'https://www.who.int/publications/i/item/9789240084278',
 'who_antidepressant_duration_2023':'https://www.who.int/publications/i/item/9789240084278',
 'who_brief_structured_psychological_2023':'https://www.who.int/publications/i/item/9789240084278',
 'german_s3_anxiety_2021':'https://www.awmf.org/leitlinien/detail/ll/051-028.html',
 'german_nvl_depression_2022':'https://www.leitlinien.de/themen/depression',
 'russian_standard_1688':None,
 'russian_standard_1697':None,
 'clinic_case_todo':None,
 'who_cbt_panic_2012':None,
 'who_behavioural_activation_2012':None,
 'who_relaxation_2012':None,
 'who_physical_activity_2012':None,
 'va_dod_mdd_2022':None,
}
for src in sources:
 src['url']=source_urls.get(src['id'])
 src['path_in_bundle']='data/guidelines/source_registry.json'
write_json(GUIDE/'source_registry.json',{'version':'1.1.0','sources':sources,'policy':'Source registry contains uploaded-document metadata and excerpts referenced by the care pathways. A URL opens the publishing body or a source landing page, not necessarily the exact uploaded PDF. It does not prove currentness or legal authority. Each pathway retains its own location and limits.'})

# Scheme-specific clinician-configurable fields. Values are saved on each care-plan instance;
# they are configuration inputs, not generated clinical instructions.
CONFIG_FIELDS={
 'depression_guided_self_help':[
  {'id':'chosen_method','label':'Выбранный подход','type':'select','required':True,'options':['КПТ-ориентированная самопомощь','Поведенческая активация','Решение проблем','Психообразование','Комбинированный/другой согласованный подход'],'help':'Выберите метод, соответствующий оценке и доступному разрешённому материалу.'},
  {'id':'resource','label':'Материал/программа','type':'text','max_length':500,'placeholder':'Название, поставщик или ссылка на разрешённый материал'},
  {'id':'session_count','label':'Ориентировочное число структурированных встреч','type':'number','min':1,'max':20,'help':'Для guided self-help NICE описывает обычно 6–8 встреч; это справочное описание, не обязательный график.'},
  {'id':'goal','label':'Согласованная цель пациента','type':'textarea','required':True,'max_length':3000},
  {'id':'support_schedule','label':'График поддержки/пересмотра','type':'text','max_length':500,'placeholder':'Заполняется врачом/терапевтом'}],
 'behavioral_activation':[
  {'id':'activity_goal','label':'Согласованная активность/цель','type':'textarea','required':True,'max_length':3000},
  {'id':'activity_schedule','label':'Когда/как пациент планирует её выполнять','type':'textarea','max_length':3000},
  {'id':'easy_alternative','label':'Более лёгкая альтернатива на трудный день','type':'textarea','max_length':2000},
  {'id':'review_frequency','label':'Когда обсуждаем результат','type':'text','max_length':300,'placeholder':'Согласованный срок, не универсальный интервал'}],
 'cbt_structured':[
  {'id':'format','label':'Формат терапии','type':'select','required':True,'options':['Индивидуальная','Групповая','Сопровождаемая цифровая/самопомощь','Другая согласованная форма']},
  {'id':'target_symptoms','label':'Целевые симптомы/трудности','type':'textarea','required':True,'max_length':3000},
  {'id':'program','label':'Название протокола/программы и специалист','type':'text','max_length':800},
  {'id':'between_session_tasks','label':'Домашние задачи/дневник','type':'textarea','max_length':3000}],
 'physical_activity_support':[
  {'id':'agreed_activity','label':'Согласованная активность','type':'textarea','required':True,'max_length':2000},
  {'id':'baseline','label':'Исходный уровень и ограничения','type':'textarea','max_length':3000},
  {'id':'schedule','label':'Планируемый график','type':'text','max_length':500,'placeholder':'Индивидуально согласованный'},
  {'id':'safety_considerations','label':'Медицинские ограничения/меры предосторожности','type':'textarea','max_length':3000}],
 'relaxation_support':[
  {'id':'technique','label':'Выбранная техника','type':'select','required':True,'options':['Дыхательная техника','Прогрессивная мышечная релаксация','Направляемая образная техника','Другая разрешённая и согласованная техника']},
  {'id':'schedule','label':'Согласованный график/длительность','type':'text','max_length':500,'placeholder':'Определить с пациентом; в источнике нет универсальной дозировки'},
  {'id':'adaptations','label':'Предпочтения, барьеры и адаптации','type':'textarea','max_length':3000}],
 'antidepressant_start_review':[
  {'id':'drug_product','label':'Конкретный препарат/форма/производитель','type':'text','required':True,'max_length':800},
  {'id':'indication','label':'Показание и клиническое обоснование','type':'textarea','required':True,'max_length':3000},
  {'id':'regimen_from_label','label':'Назначенная схема по проверенной инструкции','type':'textarea','required':True,'max_length':3000,'help':'Заполняет врач после сверки конкретного регистрационного продукта; система не вычисляет дозу.'},
  {'id':'label_checked','label':'Конкретная актуальная инструкция сверена','type':'checkbox','required_for_activation':True,'help':'Обязательное условие активации.'},
  {'id':'first_review','label':'Дата первого пересмотра','type':'date','required':True},
  {'id':'monitoring_plan','label':'Что мониторить и какой канал связи согласован','type':'textarea','max_length':3000}],
 'antidepressant_relapse_prevention':[
  {'id':'relapse_risk','label':'Факторы риска/защиты и остаточные симптомы','type':'textarea','required':True,'max_length':3000},
  {'id':'chosen_approach','label':'Согласованный профилактический подход','type':'select','required':True,'options':['Продолжение ранее назначенной терапии после review','КПТ/MBCT или другой согласованный психологический метод','Комбинация методов','Другой индивидуальный план']},
  {'id':'review_horizon','label':'Горизонт и дата пересмотра','type':'text','max_length':500,'help':'Задаётся лечащим врачом индивидуально.'},
  {'id':'early_warning_signs','label':'Ранние признаки ухудшения и план контакта','type':'textarea','required':True,'max_length':3000}],
 'antidepressant_taper_review':[
  {'id':'current_product_regimen','label':'Текущий препарат, форма и подтверждённая схема','type':'textarea','required':True,'max_length':3000},
  {'id':'individual_steps','label':'Согласованный врачом ступенчатый план','type':'textarea','required':True,'max_length':5000,'help':'Заполняет врач по конкретной инструкции и реакции пациента. Автоматического расчёта доз/шага нет.'},
  {'id':'symptom_plan','label':'Как регистрировать симптомы отмены/возврата','type':'textarea','required':True,'max_length':3000},
  {'id':'next_review','label':'Дата следующего контакта/оценки','type':'date','required':True},
  {'id':'label_checked','label':'Инструкция именно этого продукта проверена','type':'checkbox','required_for_activation':True}],
 'anxiety_assessment_pathway':[
  {'id':'focus','label':'Основные домены/жалобы для уточнения','type':'textarea','required':True,'max_length':3000},
  {'id':'questionnaires','label':'Выбранные инструменты и их версия','type':'text','max_length':1000,'placeholder':'Например, GAD-7 v…; не заменяет интервью'},
  {'id':'agreed_options','label':'Варианты помощи, которые будут обсуждены','type':'textarea','required':True,'max_length':3000},
  {'id':'referral_level','label':'Маршрут консультации','type':'select','required':True,'options':['Плановое наблюдение ведущим врачом','Желательна консультация психиатра','Обязательна консультация психиатра','Срочная/экстренная оценка по локальному протоколу']},
  {'id':'source_checked','label':'Проверена текущая редакция локального руководства','type':'checkbox','required_for_activation':True}],
 'psychosis_red_flag_review':[
  {'id':'source_excerpt','label':'Исходный фрагмент/ответ и контекст','type':'textarea','required':True,'max_length':4000},
  {'id':'direct_assessment','label':'Результат прямого уточнения специалистом','type':'textarea','required':True,'max_length':4000},
  {'id':'safety_status','label':'Текущий статус безопасности','type':'select','required':True,'options':['Нужно оценить дополнительно','Непосредственная угроза не исключена','Непосредственная угроза не выявлена по проведённой оценке','Передан на срочную/экстренную оценку']},
  {'id':'route','label':'Решение/маршрут и ответственный','type':'textarea','required':True,'max_length':3000},
  {'id':'reviewed_directly','label':'Проведена прямая клиническая оценка','type':'checkbox','required_for_activation':True}],
 'adverse_event_review':[
  {'id':'suspected_product','label':'Препарат/форма, связанный с реакцией (если установлен)','type':'text','max_length':800},
  {'id':'reaction_details','label':'Симптомы, начало, выраженность и временная связь','type':'textarea','required':True,'max_length':4000},
  {'id':'seriousness_review','label':'Оценка серьёзности/причинности и неопределённости','type':'textarea','required':True,'max_length':4000},
  {'id':'action','label':'Клинические действия и исход','type':'textarea','required':True,'max_length':4000},
  {'id':'followup','label':'Срок и ответственное лицо для follow-up','type':'text','required':True,'max_length':500}],
}
for sf in sorted(SCHEMES.glob('*.json')):
 d=json.loads(sf.read_text(encoding='utf-8'))
 d['configuration_fields']=CONFIG_FIELDS.get(d['id'],[])
 d['reader_sections']=[
  {'id':'purpose','title':'Назначение и область применения','content':d.get('summary','')},
  {'id':'eligibility','title':'Проверки до начала','items':d.get('eligibility_checks',[])},
  {'id':'workflow','title':'Пошаговый маршрут','items':[{'title':x.get('title',''),'description':x.get('description',''),'timing':x.get('timing',''),'owner':x.get('owner','')} for x in d.get('steps',[])]},
  {'id':'monitoring','title':'Мониторинг и оценка результата','items':d.get('monitoring',[])},
  {'id':'red_flags','title':'Красные флаги / защитные условия','items':d.get('red_flags',[])},
  {'id':'limits','title':'Ограничения и что схема не делает','items':d.get('limits',[])},
 ]
 write_json(sf,d)

# In-app clinician reading notes. These are short source-grounded summaries with exact references,
# not verbatim reproductions of the copyrighted guidelines and not patient-specific treatment orders.
SCHEME_DETAIL_SECTIONS={
 'depression_guided_self_help':[
  {'title':'Кому и как предлагается выбирать сопровождаемую самопомощь','source_id':'nice_ng222_2022','location':'NG222, §1.5.2, printed pp. 27–29','content':['Рассматривать структурированную сопровождаемую самопомощь как один из вариантов при клинически уместном менее тяжёлом депрессивном состоянии; выбор делается совместно с пациентом и учитывает предпочтения, потребности и доступность ресурсов.','В NICE guided self-help обычно описана как программа из 6–8 структурированных встреч. Это описание конкретного вида вмешательства в руководстве, а не обязательный график для каждого человека.','Программа должна быть основана на структурированном материале, например принципах КПТ, поведенческой активации, решения проблем или психообразования; конкретный разрешённый материал нужно указать в индивидуальной настройке.']},
  {'title':'Что фиксировать до начала и в ходе программы','source_id':'nice_ng222_2022','location':'NG222, §1.4.3–1.4.9 и §1.5','content':['Определить исходные симптомы и функционирование, обсудить цель и способ отслеживания результата; использовать материалы/руководство, подходящие к выбранному вмешательству.','Запланировать регулярный контакт, мониторинг результата и способ связи, если состояние ухудшится или пациенту понадобится помощь до следующей встречи.','Завершение курса должно включать обсуждение того, как поддерживать достигнутый эффект; если прогресс недостаточен или состояние ухудшается, лечащий специалист пересматривает маршрут.']}
 ],
 'behavioral_activation':[
  {'title':'Что означает метод в загруженном обзоре','source_id':'who_behavioural_activation_2012','location':'Behavioural activation, printed pp. 1–5, background/PICO/evidence tables','content':['В загруженном документе поведенческая активация описана как подход, в котором человеку помогают увеличить число потенциально вознаграждающих действий. Авторы отмечают, что это компонент КПТ и что его организация может быть проще, чем более сложных когнитивных компонентов.','Сам документ является evidence profile/scoping review по сравнению с usual care, а не универсальным индивидуальным руководством по частоте сессий, интенсивности нагрузки или темпу повышения активности. Универсальное число действий/сессий из него не выводится.','В индивидуальном плане врач/терапевт и пациент записывают посильную конкретную активность, время/условие, более лёгкую альтернативу и способ наблюдать эффект; план не должен увеличивать нагрузку автоматически.']},
  {'title':'Как наблюдать результат','source_id':'nice_ng222_2022','location':'NG222, §1.4.3–1.4.9 и таблицы психологических вмешательств','content':['Сохранять дневниковые наблюдения о действии, настроении, препятствиях и функционировании. Оценивать не только факт выполнения, но и то, была ли задача реалистичной и подходящей.','Если наблюдаются выраженное ухудшение, суицидальный риск, возможные психотические или маниакальные признаки, не заменять оценку безопасности продолжением дневниковой активности.']}
 ],
 'cbt_structured':[
  {'title':'Структурированная терапия должна следовать выбранному протоколу','source_id':'nice_ng222_2022','location':'NG222, §1.4.5–1.4.9, printed pp. 15–16','content':['Руководство рекомендует использовать руководства/мануалы психологических вмешательств для формы, длительности и завершения курса; обучение, регулярная супервизия и оценка компетенций специалистов также важны.','Не подменять полноценную терапию набором несвязанных цифровых советов. Программа, формат, специалист и домашние задачи фиксируются в плане, а выполняемые задачи обсуждаются по ходу работы.','При приближении к завершению курса обсуждать способы поддержания достигнутых изменений и благополучия; адаптации могут потребоваться с учётом потребностей пациента.']},
  {'title':'Что говорят загруженные evidence profiles','source_id':'who_brief_structured_psychological_2023','location':'DEP3, разделы 3–4, evidence profiles/GRADE','content':['Документ рассматривает доказательства для нескольких кратких структурированных психологических вмешательств, включая КПТ, поведенческую активацию, межличностную терапию и решение проблем; это не один готовый протокол для всех случаев.','Отдельный документ WHO о терапии на принципах КПТ у людей с паническими атаками указывает, что доказательства для некоторых компонентов являются косвенными. Это нельзя выдавать за прямое подтверждение одинакового эффекта всех компонентов у каждого пациента.','В приложении фиксируется название/версия выбранной программы и специалиста; инструмент не генерирует LLM-терапевтические инструкции и не оценивает качество психотерапии автоматически.']}
 ],
 'physical_activity_support':[
  {'title':'Пределы исходного документа','source_id':'who_physical_activity_2012','location':'Physical activity, printed pp. 1–8, PICO and GRADE tables','content':['Вопрос исходного обзора — советы по физической активности для взрослых с депрессивным эпизодом/расстройством и малоподвижным образом жизни; изучаются изменения тяжести симптомов, функционирования, результаты последующего наблюдения и нежелательные эффекты.','Документ не задаёт универсальную безопасную интенсивность/продолжительность нагрузки для конкретного человека. В этой схеме записывается только активность, согласованная специалистом с учётом физического состояния, ограничений и предпочтений пациента.','В индивидуальном плане следует указать исходный уровень, ограничения, согласованный график и способ отмечать переносимость/эффект; нельзя превращать общий совет в медицинское назначение нагрузки автоматически.']},
  {'title':'Мониторинг и безопасность','source_id':'nice_ng222_2022','location':'NG222, общие принципы индивидуального выбора вмешательства','content':['Обсудить с пациентом подходящий и выполнимый вариант, препятствия и потребность в дополнительной помощи.','Новая боль в груди, обморок, выраженная одышка или другое потенциально неотложное физическое состояние не относится к обычному мониторингу активности и требует медицинской оценки по локальному протоколу.']}
 ],
 'relaxation_support':[
  {'title':'Как трактовать источник и доказательства','source_id':'who_relaxation_2012','location':'Relaxation training, printed pp. 1–7, PICO/GRADE/evidence-to-decision','content':['Загруженный документ является обзором доказательств релаксационных техник по сравнению с обычной помощью при депрессивном состоянии. Он не предлагает универсального протокола дозирования или гарантированного эффекта для отдельного пациента.','Релаксация используется только как согласованный поддерживающий компонент, если это подходит пациенту. Выбор техники, адаптации и частота не выводятся автоматически из балла теста.','Фиксировать переносимость, удобство выполнения, эффект на самочувствие и любые ухудшения; при выраженном ухудшении или защитно значимых симптомах приоритет получает клиническая оценка, а не продолжение упражнения.']}
 ],
 'antidepressant_start_review':[
  {'title':'Совместное обсуждение до назначения','source_id':'nice_ng222_2022','location':'NG222, §1.4.10–1.4.12, printed pp. 17–18','content':['Согласованный план должен включать причины предложения лекарства, варианты препаратов, дозу и возможные изменения дозы, ожидаемую пользу, индивидуально значимые нежелательные эффекты и опасения пациента по поводу начала или прекращения лечения. Пациенту нужно предоставить подходящую письменную информацию.','Обсудить начальные эффекты, ожидаемое время до эффекта (в руководстве указано, что если препарат сработает, эффект обычно проявляется в пределах 4 недель), регулярный мониторинг, инструкции по времени приёма/взаимодействиям и симптомы отмены.','Руководство указывает, что лечение может потребоваться продолжать как минимум 6 месяцев после ремиссии симптомов, но его следует регулярно пересматривать. Это не индивидуальный срок для любого пациента и требует совместного решения.']},
  {'title':'Первый обзор и случаи повышенного риска','source_id':'nice_ng222_2022','location':'NG222, §1.4.11 и §1.4.24, printed pp. 17 and 21–22','content':['Первый обзор обычно планируется в течение 2 недель для проверки симптомов и побочных эффектов; для человека 18–25 лет или при особом беспокойстве о суицидальном риске — через 1 неделю.','При повышенном суицидальном риске или возрасте 18–25 лет руководство дополнительно предусматривает оценку состояния до начала, стратегию управления риском и проверку суицидальности через 1 неделю после начала/повышения дозы, затем настолько часто, насколько нужно, не позднее 4 недель после визита начала лечения.','Эти интервалы — рекомендации источника для определённых ситуаций, а не автоматическое расписание: фактические даты и канал связи задаются врачом с учётом клинической ситуации и локальных правил.']},
  {'title':'Лекарственная карточка и безопасный предел приложения','source_id':'russian_standard_1697','location':'1697_стандарт.pdf, раздел лекарственных средств, printed pp. 6–7','content':['В приложенном файле перечислены действующие вещества и средние суточные/курсовые дозы в таблице стандарта. В копии не заполнен номер приказа, поэтому правовой статус и применимость этой редакции требуют отдельной проверки.','Средние значения из стандарта не являются частотой приёма, схемой титрации, индивидуальной дозой или подтверждением инструкции конкретной торговой формы. При назначении врач сверяет актуальную инструкцию именно выбранного регистрационного продукта в ГРЛС.']}
 ],
 'antidepressant_relapse_prevention':[
  {'title':'Факторы повышенного риска рецидива из NICE NG222','source_id':'nice_ng222_2022','location':'NG222, §1.8.1–1.8.12, printed pp. 57–59','content':['Руководство предлагает совместно обсуждать продолжение лечения после полного или частичного улучшения и объяснять, что продолжение антидепрессантов или психологической терапии может уменьшить риск рецидива.','Перечислены факторы, повышающие вероятность рецидива: частые/недавние повторные эпизоды, неполный ответ/остаточные симптомы, избегание или руминации, тяжёлый эпизод/существенное нарушение функционирования, хронические физические/психические состояния и сохраняющиеся личные, социальные или средовые стрессоры.','При выборе продолжения антидепрессанта обсуждают длительные риски, включая нежелательные эффекты и сложность прекращения, и сопоставляют их с риском возврата депрессии.']},
  {'title':'Варианты профилактики и контроль','source_id':'nice_ng222_2022','location':'NG222, §1.8.5–1.8.12, printed pp. 58–59','content':['Для некоторых людей с более высоким риском руководство предлагает рассмотреть продолжение ранее эффективной дозы, групповые КПТ/MBCT для тех, кто не хочет продолжать лекарство, либо комбинацию этих подходов. Это варианты обсуждения, а не автоматический выбор по шкале.','Для групповой КПТ/MBCT с явным фокусом профилактики рецидива NICE описывает обычно 8 встреч за 2–3 месяца, с возможными дополнительными встречами в следующие 12 месяцев. При продолжении уже применявшейся психологической терапии руководство описывает не менее 4 дополнительных встреч с фокусом профилактики.','При продолжающемся антидепрессанте для профилактики рецидива рекомендован обзор как минимум каждые 6 месяцев: валидированная шкала настроения, побочные эффекты, изменение медицинских/личных/социальных факторов и обсуждение желания продолжать лечение. Дату и фактическую частоту устанавливает врач.']}
 ],
 'antidepressant_taper_review':[
  {'title':'Что рекомендует NICE по снижению дозы','source_id':'nice_ng222_2022','location':'NG222, §1.4.13–1.4.23, printed pp. 18–21','content':['Человеку рекомендуют обсуждать прекращение со специалистом, назначившим препарат; обычно дозу снижают ступенчато. Резкое прекращение, пропуски доз или неполный приём могут вызвать симптомы отмены, которые отличаются по типу/тяжести и не возникают у всех.','Руководство советует учитывать период полувыведения и длительность лечения, снижать дозу пошагово и рассматривать меньшие уменьшения по мере приближения к низким дозам; скорость и продолжительность снижения должны согласовываться с пациентом и учитывать разрешение/переносимость симптомов. Если невозможно сделать малые шаги таблетками/капсулами, источник предлагает проверить доступность жидкой формы.','Симптомы отмены могут длиться недели, а иногда месяцы. Следующий шаг не должен автоматически запускаться только по календарю: отслеживают переносимость и клиническое состояние. Более быстрое снижение при тяжёлых/непереносимых побочных эффектах или при переходе на другой препарат требует отдельного врачебного решения.']},
  {'title':'Отмена и возврат симптомов — разные сигналы','source_id':'nice_ng222_2022','location':'NG222, §1.4.18–1.4.22, printed pp. 20–21','content':['Во время снижения/после прекращения необходимо наблюдать одновременно симптомы отмены и возвращение депрессивных симптомов; частота наблюдения зависит от клинических потребностей и доступной поддержки.','Источник перечисляет возможные симптомы отмены, включая головокружение/неустойчивость, необычные ощущения, тревогу/раздражительность, проблемы сна, потливость, желудочно-кишечные симптомы, сердцебиение, усталость и головную боль. Они сами по себе не доказывают рецидив.','При лёгких симптомах источник предлагает мониторинг и контакт с назначившим специалистом при отсутствии улучшения или ухудшении; при тяжёлых симптомах рассматривается клиническая оценка и изменение плана специалистом. В приложении нельзя автоматически возобновлять дозу или вычислять taper schedule.']},
  {'title':'Почему в приложении нет автоматического календаря доз','source_id':'who_antidepressant_duration_2023','location':'DEP2, разделы 3.6 и 4, printed pp. 21–44','content':['Загруженный WHO-документ является evidence profile по длительности лечения и отмечает неопределённость по ряду стратегий и ограничения исследований снижения доз.','Поэтому приложение хранит записанный врачом индивидуальный план и дату следующего review, но не создаёт универсальный процент снижения, не рассчитывает новую дозу и не меняет лекарственный план самостоятельно.']}
 ],
 'anxiety_assessment_pathway':[
  {'title':'Как использовать источники по тревожным расстройствам','source_id':'who_mhgap_anxiety_evidence_2023','location':'ANX evidence profiles, разделы 3–4 (PICO/GRADE/evidence-to-decision)','content':['Загруженный файл — профиль доказательств для отдельных вопросов anxiety-модуля WHO mhGAP, а не единый индивидуальный протокол. Рассматриваемые вмешательства и уверенность в доказательствах зависят от конкретного вопроса и исхода.','Оценка в маршруте должна определить конкретные жалобы и вероятную диагностическую область, длительность, влияние на функционирование, сопутствующие состояния, употребление веществ/лекарств и защитные риски. Самоотчётный опросник помогает стандартизировать часть данных, но не заменяет клиническое интервью.','Перед выбором лечения сравнивают актуальные локальные клинические рекомендации и предпочтения пациента; маршрут не предлагает препарат или дозу автоматически.']},
  {'title':'Важное ограничение версии немецкой S3-линии','source_id':'german_s3_anxiety_2021','location':'Версия 2.0, состояние документа 06.04.2021; титульный лист и профильные главы','content':['Загруженный документ указывает дату состояния 06.04.2021 и плановую дату проверки 04/2026. Эта дата уже наступила; текущая редакция не подтверждена данным комплектом.','Используйте документ как исторический источник до независимой проверки на официальной странице издателя. Не трактуйте его как автоматически актуальное руководство и не выводите индивидуальную схему фармакотерапии из одного файла.']}
 ],
 'psychosis_red_flag_review':[
  {'title':'Флаг — это основание для прямой оценки, не диагноз','source_id':'who_icd11_cddr_2024','location':'ICD-11 CDDR, 2024, соответствующие клинические описания и диагностические требования','content':['CDDR содержит клинические описания и диагностические требования для профессиональной оценки. Его нельзя применять автоматически по одному слову, баллу опросника или текстовому совпадению.','При срабатывании правила сохранить точный источник, цитату/ответ, контекст и время; затем специалист проводит прямую оценку, документирует своё заключение и маршрутизацию. Система не ставит диагноз «бред/психоз» по маркеру.','Если невозможно обеспечить безопасность, наблюдается непосредственная угроза или быстрое ухудшение, обычный плановый workflow прекращается в пользу локального срочного/экстренного протокола. Внутреннее уведомление не заменяет телефонный контакт и не гарантирует доставку при закрытом приложении.']}
 ],
 'adverse_event_review':[
  {'title':'Структура записи о нежелательной реакции','source_id':'nice_ng222_2022','location':'NG222, §1.4.10–1.4.19, printed pp. 17–20','content':['До/при назначении важно обсудить потенциальные нежелательные эффекты и эффекты отмены, индивидуально значимые риски и план связи/мониторинга. При наблюдении необходимо фиксировать выраженность, время появления, сопутствующие факторы и последующий исход.','Приложение хранит отдельные модальности симптомов, описание, дату начала, серьёзность по сообщению пациента, связь с планом препарата, действия, оценку врача и исход. Это структура клинической документации, а не автоматическое доказательство причинности.','Серьёзность, причинность и дальнейшее действие подтверждает специалист. Система не даёт автоматическую рекомендацию отменить, возобновить или изменить препарат. При возможной неотложной реакции пациенту сообщается не ждать чата.']},
  {'title':'Назначение только по актуальной инструкции продукта','source_id':'russian_standard_1697','location':'1697_стандарт.pdf, примечания к перечню лекарственных средств','content':['В предоставленном тексте стандарта указано, что зарегистрированные препараты применяются согласно инструкции к конкретному препарату и фармакотерапевтической группе; исключения/назначения вне стандарта требуют предусмотренного законодательством медицинского решения.','Копия файла имеет незаполненный номер приказа. Поэтому этот документ нельзя автоматически считать подтверждением текущей нормативной версии. Перед реальным назначением проверяйте актуальную регистрацию и инструкцию в ГРЛС.']}
 ]
}
for scheme_id, sections in SCHEME_DETAIL_SECTIONS.items():
 path=SCHEMES/f'{scheme_id}.json'
 data=json.loads(path.read_text(encoding='utf-8'))
 data['clinical_detail_sections']=sections
 write_json(path,data)


# Medicine names and average daily/course values transcribed from the user-provided Russian standard 1697_стандарт.pdf, printed pages 6–7.
# The source states ССД (average daily dose) and СКД (average course dose). These are not individual prescriptions or administration schedules.
from urllib.parse import quote
raw_doses={
 'amitriptyline':(150,'мг',4500,'мг'), 'imipramine':(150,'мг',4500,'мг'), 'clomipramine':(150,'мг',4500,'мг'),
 'paroxetine':(150,'мг',4500,'мг'), 'sertraline':(300,'мг',9000,'мг'), 'fluoxetine':(40,'мл',1200,'мл'),
 'citalopram':(60,'мг',1800,'мг'), 'escitalopram':(20,'мг',600,'мг'),
 'mirtazapine':(45,'мг',1350,'мг'), 'pipofezine':(37.5,'мг',1125,'мг'), 'duloxetine':(120,'мг',3600,'мг'),
 'venlafaxine':(150,'мг',4500,'мг'), 'mianserin':(90,'мг',2700,'мг'),
 'agomelatine':(25,'мг',750,'мг'), 'pirlindole':(75,'мг',2250,'мг'), 'trazodone':(300,'мг',9000,'мг')}
drugs=[
 ('amitriptyline','Амитриптилин','N06AA','Трициклический антидепрессант'),('imipramine','Имипрамин','N06AA','Трициклический антидепрессант'),('clomipramine','Кломипрамин','N06AA','Трициклический антидепрессант'),
 ('paroxetine','Пароксетин','N06AB','СИОЗС'),('sertraline','Сертралин','N06AB','СИОЗС'),('fluoxetine','Флуоксетин','N06AB','СИОЗС'),('citalopram','Циталопрам','N06AB','СИОЗС'),('escitalopram','Эсциталопрам','N06AB','СИОЗС'),
 ('mirtazapine','Миртазапин','N06AX','Другой антидепрессант'),('pipofezine','Пипофезин','N06AX','Другой антидепрессант'),('duloxetine','Дулоксетин','N06AX','СИОЗСН'),('venlafaxine','Венлафаксин','N06AX','СИОЗСН'),('mianserin','Миансерин','N06AX','Другой антидепрессант'),('agomelatine','Агомелатин','N06AX','Другой антидепрессант'),('pirlindole','Пирлиндол','N06AX','Другой антидепрессант'),('trazodone','Тразодон','N06AX','Другой антидепрессант')]
meds=[]
for id_,name,atc,group in drugs:
 daily,daily_unit,course,course_unit=raw_doses[id_]
 grls_url='https://grls.rosminzdrav.ru/grls.aspx?s='+quote(name,safe='')+'&m=mnn'
 notes='Упоминается в приложенном файле 1697_стандарт.pdf, таблица лекарственных препаратов, печатные стр. 6–7. В копии стандарта не заполнен номер приказа; актуальный правовой статус и инструкция конкретного продукта не подтверждены.'
 unit_warning = None
 if id_=='fluoxetine':
  unit_warning='В приложенной таблице 1697_стандарт.pdf (печатная стр. 6) для флуоксетина единица напечатана как «мл», включая курсовое значение. Она сохранена буквально по источнику и НЕ была исправлена предположением. Требуется проверка по оригиналу/официальной действующей редакции стандарта и инструкции конкретного продукта в ГРЛС. Не использовать эти значения для назначения.'
 dose_ref={'source_id':'russian_standard_1697','source_file':'1697_стандарт.pdf','printed_pages':'6–7','average_daily_dose_value':daily,'average_daily_dose_unit':daily_unit,'average_course_dose_value':course,'average_course_dose_unit':course_unit,'source_terms':{'ССД':'средняя суточная доза','СКД':'средняя курсовая доза'},'warning':'Эти значения из таблицы стандарта не являются индивидуальной дозой или расписанием приёма. Не преобразовывать их в назначение.'}
 if unit_warning:
  dose_ref['unit_verification_required']=True
  dose_ref['unit_warning']=unit_warning
 meds.append({'id':id_,'name':name,'generic_name':name,'atc_code':atc,'group':group,'label_status':'needs_review','registration_number':None,
   'source_ids':['russian_standard_1697'],'source_note':notes,
   'description':f'{name} указан в приложенном стандарте в группе «{group}» (код ATC в таблице: {atc}). Это описание справочного упоминания, а не подтверждение показания для конкретного продукта.',
   'source_dose_reference':dose_ref,
   'administration_schedule':'В предоставленном стандарте нет схемы титрации, частоты приёма, времени приёма, продолжительности для конкретной торговой формы или пропущенной дозы. Сверьте инструкцию конкретного регистрационного продукта в ГРЛС; назначение вводит и подтверждает врач.',
   'contraindications_and_interactions':'В приложенном наборе нет инструкции конкретного зарегистрированного продукта для этой записи. До назначения проверьте разделы инструкции: показания, противопоказания, взаимодействия, особые предупреждения, беременность/лактацию и коррекцию при сопутствующих состояниях.',
   'grls_url':grls_url,'grls_link_type':'filtered_search_by_inn','dose_template':None,'automatic_recommendation_allowed':False,'active_prescribing_requires_manual_source_check':True})
aviandr_grls='https://grls.rosminzdrav.ru/grls.aspx?s='+quote('Маритупирдин',safe='')+'&m=mnn'
meds.insert(0,{'id':'aviandr','name':'Авиандр®','generic_name':'Маритупирдин','atc_code':'N05BX','group':'Другие анксиолитические средства','label_status':'needs_review','registration_number':'ЛП-№(002445)-(РГ-RU)','registration_date':'31.05.2023','registration_expiry_reported':'31.05.2028','source_ids':['clinic_case_todo'],'source_note':'Препарат указан в исходном ТЗ. Публичная инструкция, помеченная как инструкция, зарегистрированная Минздравом РФ, открывается по отдельной ссылке; перед назначением повторно проверьте актуальную редакцию и статус в ГРЛС.',
 'description':'Маритупирдин, таблетки 20 мг, анксиолитическое средство. По опубликованной инструкции: показания включают генерализованное тревожное расстройство у взрослых старше 18 лет и некоторые тревожные состояния после COVID-19 при стрессовой реакции/нарушении адаптации лёгкой или средней выраженности. Применимость к конкретному пациенту проверяет врач.',
 'label_summary':{'source_title':'Инструкция по применению, опубликованная МЕДИ РУ и обозначенная как зарегистрированная Минздравом РФ','source_url':'https://medi.ru/instrukciya/aviandr_27908/','leaflet_revision':'21.07.2023 (по странице инструкции; перепроверить актуальность в ГРЛС)','indications':['Генерализованное тревожное расстройство у взрослых старше 18 лет.','Некоторые тревожные состояния после COVID-19 при стрессовой реакции и нарушении адаптации лёгкой/средней степени выраженности.'],'administration_schedule':['По опубликованной инструкции: внутрь по 1 таблетке 20 мг два раза в сутки (утром и вечером).','Принимать за 30 минут до еды.','При генерализованном тревожном расстройстве продолжительность определяет врач.','Для тревожных состояний, описанных в инструкции в связи со стрессовой реакцией/нарушением адаптации после COVID-19: курс 4 недели; при необходимости врач может увеличить до 6 недель.'],'contraindications':['Аллергия на действующее вещество или вспомогательные вещества.','Эпилепсия или органические поражения головного мозга.','Приём ингибиторов МАО и период 2 недели после их отмены.','Почечная недостаточность средней/тяжёлой степени (СКФ < 60 мл/мин).','Печёночная недостаточность классов A, B или C по Child–Pugh.','Беременность; грудное вскармливание (по инструкции).'],'precautions_and_interactions':['С осторожностью при сердечно-сосудистых и эндокринных заболеваниях, алкогольной или наркотической зависимости.','Проверить седативные средства, антипсихотики, снотворные, антигистаминные препараты, антидепрессанты, триптаны, опиоиды и ингибиторы CYP2D6.','В инструкции указано противопоказание к управлению транспортом/механизмами во время применения.','В период лечения инструкция рекомендует воздерживаться от алкоголя.'],'reported_adverse_reactions':['Часто: сонливость, головная боль, головокружение, общая слабость, парестезии.','Нечасто: бессонница/снижение качества сна, усиление тревоги, нарушение внимания/реакции, дисгевзия, тошнота, боль в верхней части живота, запор, гипергидроз и другие реакции согласно листку-вкладышу.'],'missed_dose':'Не принимать двойную дозу для компенсации пропуска; следовать инструкции и обратиться к врачу при вопросах.','warning':'Это сжатое изложение публичной инструкции, не персональное назначение. Перед применением откройте актуальный листок-вкладыш и сверяйте его в ГРЛС.'},
 'administration_schedule':'Смотрите раздел «Схема приёма по опубликованной инструкции» в карточке. Перед реальным назначением повторно сверить актуальную редакцию в ГРЛС.',
 'contraindications_and_interactions':'Смотрите структурированные противопоказания/взаимодействия в карточке и полную инструкцию по ссылке. Данные онлайн-источника не заменяют текущую запись ГРЛС.',
 'grls_url':aviandr_grls,'grls_link_type':'filtered_search_by_inn','official_leaflet_url':'https://medi.ru/instrukciya/aviandr_27908/','dose_template':None,'automatic_recommendation_allowed':False,'active_prescribing_requires_manual_source_check':True})
write_json(ROOT/'data'/'medications.json',{'version':'2.1.0','source_policy':'The 18 generic substances and their average daily/course figures are transcribed from the user-provided copy of 1697_стандарт.pdf, printed pages 6–7. The copy has a blank order number and is not proof of current registration. Its mean daily/course values are not individual dosing instructions. AvianDr summary is additionally based on the linked published patient leaflet; it must be checked against the current product record and leaflet in GRLS before clinical use. Drug search links are filtered GRLS searches by INN, not a selected brand/form/registration; where a single specific product is not identified in the uploaded documents, do not imply a unique product registration. No automatic prescribing is allowed.','medications':meds})

# Configurable flags; the active defaults notify the assigned doctor in the application only.
flags=[
 {'id':'message_delusion_terms','title':'Сообщение: возможное бредовое/галлюцинаторное содержание','source_type':'message_text','enabled':True,'severity':'urgent','recipient':'doctor','patterns':['слышу голоса','голоса говорят','голоса приказывают','мне приказывают голоса','бред','за мной следят','контролируют мои мысли','вкладывают мысли','читают мои мысли','кто-то управляет моими мыслями','видения'], 'case_sensitive':False,'threshold':'any','detail':'Совпадение текстового правила требует прямого уточнения врачом; не является диагнозом. Возможны ложные совпадения в цитате/обсуждении.'},
 {'id':'scl90_psychotic_experience','title':'SCL-90-R: ответы на пункты о необычных переживаниях мыслей/голосов','source_type':'questionnaire_answer','questionnaire_id':'scl90r','enabled':True,'severity':'review','recipient':'doctor','items':[{'question_id':'q7','values':[1,2,3,4]},{'question_id':'q16','values':[1,2,3,4]},{'question_id':'q35','values':[1,2,3,4]},{'question_id':'q62','values':[1,2,3,4]}], 'threshold':'any','detail':'Положительный ответ выделяется и требует клинического уточнения. Не означает подтверждённый бред/психоз.'},
 {'id':'phq9_self_harm','title':'PHQ-9: ответ выше нуля на пункт о смерти/самоповреждении','source_type':'questionnaire_answer','questionnaire_id':'phq9','enabled':True,'severity':'urgent','recipient':'doctor','items':[{'question_id':'q9','values':[1,2,3]}],'threshold':'any','detail':'Сигнал для прямой оценки актуального риска и локального протокола.'},
 {'id':'bdi_self_harm','title':'BDI: ответ выше нуля на пункт суицидальных мыслей','source_type':'questionnaire_answer','questionnaire_id':'bdi21','enabled':True,'severity':'urgent','recipient':'doctor','items':[{'question_id':'q9','values':[1,2,3]}],'threshold':'any','detail':'Сигнал безопасности, не диагноз.'},
 {'id':'hars_psychotic_review','title':'Клиническая шкала содержит необычное содержание, требующее уточнения','source_type':'questionnaire_answer','questionnaire_id':'scl90r','enabled':True,'severity':'review','recipient':'doctor','items':[{'question_id':'q85','values':[2,3,4]}],'threshold':'any','detail':'Содержимое о наказании/вине требует контекстного уточнения; совпадение не означает бредовую убеждённость.'},
 {'id':'adverse_event_any','title':'Лекарственная нежелательная реакция','source_type':'adverse_event','enabled':True,'severity':'review','recipient':'doctor','threshold':'any','detail':'Любое сообщение о побочном эффекте должно быть видно и доступно для клинического review.'},
 {'id':'adverse_event_severe','title':'Выраженная/серьёзная лекарственная нежелательная реакция','source_type':'adverse_event','enabled':True,'severity':'urgent','recipient':'both','threshold':'severe','detail':'В приложении создаётся срочный сигнал и уведомление пациенту об обращении за экстренной помощью при угрожающем/быстро ухудшающемся состоянии.'},
 {'id':'diary_self_harm','title':'Дневник: мысли о самоповреждении','source_type':'entry','entry_type':'mood','enabled':True,'severity':'urgent','recipient':'doctor','threshold':'self_harm_thoughts','detail':'Прямое уточнение безопасности; приложение не заменяет экстренную службу.'},
 {'id':'chat_unavailable_notice','title':'Сообщение в чат при отключённом чате','source_type':'system','enabled':True,'severity':'info','recipient':'doctor','threshold':'any','detail':'Использовать другой согласованный способ связи. Не гарантируется доставка экстренных сообщений.'}
]
write_json(ROOT/'data'/'red_flags.json',{'version':'1.0.0','delivery_limit':'In-app notifications persist in the database. Phone push is sent only if a push provider and credentials are configured; this is not an emergency dispatch service.','rules':flags})

write_json(ROOT/'data'/'integrations.json',{
 'version':'1.0.0','formats':[
  {'id':'fhir_r4','name':'HL7 FHIR R4','direction':['import','export'],'implemented':'Bundle export (Patient, QuestionnaireResponse, Observation, MedicationRequest/Statement, CarePlan, AdverseEvent, DiagnosticReport, ImagingStudy); import for selected resources into existing patient, idempotent by external identifier/hash.','limits':'Target FHIR server profile/terminologies must be agreed before production.'},
  {'id':'dicom_sr','name':'DICOM Basic Text SR','direction':['export'],'implemented':'Generated Part-10 DICOM SR using local concept codes; report is built from the single stored encounter/assessment + linked observations.','limits':'Acceptance varies by PACS/viewer; validate against the destination modality and its required DICOM SR template/profile. A locally coded report is not an official diagnostic code.'},
  {'id':'dicomweb','name':'DICOMweb / PACS study references','direction':['import_manifest','export_report'],'implemented':'Import DICOM Study/Series/Instance metadata manifest or FHIR ImagingStudy and link by StudyInstanceUID. Image retrieval remains in the configured PACS/DICOMweb endpoint.','limits':'This local release does not implement a DICOMweb QIDO/WADO/STOW server or store pixel data; configure a PACS/DICOMweb endpoint.'},
  {'id':'csv_json','name':'CSV/JSON existing databases','direction':['import','export'],'implemented':'Import structured diary rows idempotently using source system + external ID; JSON export/import for patient-scoped data.','limits':'Column mapping must be agreed; import previews/mappings are explicit to prevent duplicate records and overwrites.'},
  {'id':'android_webview','name':'Android WebView + FCM','direction':['mobile_shell','push'],'implemented':'Native wrapper source + WebView bridge and notification channel included.','limits':'Firebase project, google-services.json, server-side Firebase credentials and signed Android build are required for background push.'}
 ]})
print('Generated schemes:',len(list(SCHEMES.glob('*.json'))),'sources:',len(sources),'medications:',len(meds),'red flag rules:',len(flags))
