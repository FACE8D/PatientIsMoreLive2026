#!/usr/bin/env python3
"""Validate the clinician-facing medicine data and Russian UI wiring."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
meds_doc=json.loads((ROOT/'data'/'medications.json').read_text(encoding='utf-8'))
registry=json.loads((ROOT/'data'/'guidelines'/'source_registry.json').read_text(encoding='utf-8'))
meds=meds_doc['medications']
sources={x['id']:x for x in registry['sources']}
assert len(meds)==17, f'expected 17 current medication cards (moclobemide and milnacipran excluded), got {len(meds)}'
for m in meds:
    cp=m.get('clinical_profile') or {}
    assert m.get('vidal_url','').startswith('https://www.vidal.ru/'), f'{m["id"]}: missing direct Vidal monograph'
    assert m.get('grls_url','').startswith('https://grls.rosminzdrav.ru/'), f'{m["id"]}: missing GRLS search'
    assert not any('.pdf' in str(m.get(k,'' )).lower() for k in ('description','source_note','administration_schedule','contraindications_and_interactions')), f'{m["id"]}: visible summary mentions an input filename'
    assert cp.get('source_title') and cp.get('source_note'), f'{m["id"]}: missing source name/caveat'
    assert cp.get('pk'), f'{m["id"]}: missing pharmacokinetics'
    assert cp.get('regimen'), f'{m["id"]}: missing reference regimen note'
    assert cp.get('contra'), f'{m["id"]}: missing contraindications'
    assert cp.get('cautions') and cp.get('interactions') and cp.get('adverse') and cp.get('monitor'), f'{m["id"]}: incomplete safety profile'
    for sid in m.get('source_ids',[]):
        assert sid in sources, f'{m["id"]}: missing source registry entry {sid}'
# Product registration status is deliberately not inferred from an active-ingredient monograph.
aviandr=next(m for m in meds if m['id']=='aviandr')
assert aviandr.get('vidal_product_url')=='https://www.vidal.ru/drugs/aviandr'
assert 'Авиандр' in aviandr.get('vidal_product_source_title','')
fluox=next(m for m in meds if m['id']=='fluoxetine')
assert fluox['vidal_url']=='https://www.vidal.ru/drugs/molecule/425'
assert '31.12.2025' in fluox['clinical_profile']['source_note']
assert fluox['grls_specific_registration_verified'] is False
# Doses from the provided Russian care standard remain labelled as average reference values, not product-specific instructions.
standard_meds=[m for m in meds if m.get('source_dose_reference')]
assert len(standard_meds)==16, f'expected 16 standard dose references, got {len(standard_meds)}'
fluox_dose=fluox['source_dose_reference']
assert fluox_dose['unit_verification_required'] is True
assert fluox_dose['average_daily_dose_unit']=='мл'
# UI shows named sources and does not print uploaded PDF filenames in the reader templates.
js=(ROOT/'static'/'app.js').read_text(encoding='utf-8')
assert "${esc(dose.source_file||'')}" not in js
assert 'Файл в исходном комплекте:' not in js
assert 'function modalCompareDrugs()' in js and 'function renderDrugComparison()' in js
assert 'Карточка препарата ↗' in js and 'Открыть карточку конкретного препарата' in js
assert 'последнего сохранённого осмотра' in js and 'DICM' in js
assert 'Сводная справочная карточка не заменяет полный текст актуальной инструкции' in js
assert "data-action=\"low-vision-toggle\"" in js
css=(ROOT/'static'/'app.css').read_text(encoding='utf-8')
assert 'html[data-low-vision="on"]' in css and 'html[data-high-contrast="on"]' in css
assert all(m.get('local_leaflet_url','').startswith('/leaflets/') for m in meds), 'every medicine should link to its local supplied leaflet'
assert not any(m['id'] in ('moclobemide','milnacipran') for m in meds), 'withdrawn drugs must not be available for new plans'
print(f'PASS: {len(meds)} medicine profiles; Vidal and GRLS links; PK, regimes, contraindications, cautions, interactions, adverse reactions and monitoring; named sources; fluoxetine status caveat; comparison UI and low-vision styling.')
