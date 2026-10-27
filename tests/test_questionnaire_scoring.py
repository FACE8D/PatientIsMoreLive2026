#!/usr/bin/env python3
"""Unit checks for the separately loaded questionnaire JSON files."""
import json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
QDIR=ROOT/'data'/'questionnaires'
files=sorted(QDIR.glob('*.json'))
assert len(files)>=10, f'Expected questionnaire set, found {len(files)}'
seen=set()
for path in files:
    d=json.loads(path.read_text(encoding='utf-8'))
    assert d['id'] not in seen, f'duplicate id {d["id"]}'
    seen.add(d['id'])
    assert d['id']==path.stem, f'file name/id mismatch: {path.name}'
    assert d['questions'], f'{path.name} has no questions'
    assert all(q.get('id') and q.get('text') for q in d['questions']), f'missing question id/text in {path.name}'
    answers={}
    for q in d['questions']:
        typ=q.get('type','single')
        if typ=='single': answers[q['id']]=q['options'][0]['value']
        elif typ=='yesno_period': answers[q['id']]={p['id']:'no' for p in q.get('periods',[])}
        elif typ=='text': answers[q['id']]=''
        else: raise AssertionError(f'unknown question type {typ} in {path.name}')
    # Make required text fields an explicit empty string; this satisfies the schema validator.
    score=server.score_questionnaire(d,answers)
    assert 'risk_flag' in score, f'{path.name} missing safety output'
    expected_completed=sum(1 for value in answers.values() if value not in (None, ''))
    assert score['completed_question_count']==expected_completed, f'{path.name} response count mismatch'
    print(f'PASS {path.name}: {len(d["questions"])} questions, score type={score["type"]}')
assert len(seen)==len(files)
assert len(json.loads((QDIR/'hcl32.json').read_text())['questions'])==32
assert len(json.loads((QDIR/'hcl33.json').read_text())['questions'])==33
# Safety escalation regression: one non-zero answer on PHQ-9 item 9 must flag review.
phq=json.loads((QDIR/'phq9.json').read_text(encoding='utf-8'))
answers={q['id']:0 for q in phq['questions']}
riskq=phq.get('scoring',{}).get('risk_if',{}).get('question_id')
assert riskq, 'PHQ-9 safety rule is missing'
answers[riskq]=1
s=server.score_questionnaire(phq,answers)
assert s['risk_flag'] is True, 'PHQ-9 safety rule did not flag a positive response'
print('PASS PHQ-9 positive safety item raises risk_flag')
print(f'PASS all {len(files)} questionnaire definitions validated')
