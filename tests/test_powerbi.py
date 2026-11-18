import csv
import json

from cadence.db import ROOT


def test_visuals_reference_real_semantic_fields_and_measures():
    model = json.loads((ROOT / 'powerbi/Cadence.SemanticModel/model.bim').read_text())['model']
    columns = {t['name']: {c['name'] for c in t['columns']} for t in model['tables']}
    measures = {t['name']: {m['name'] for m in t.get('measures', [])} for t in model['tables']}
    visuals = list((ROOT / 'powerbi/Cadence.Report/definition').rglob('visual.json'))
    assert len(visuals) == 13
    for path in visuals:
        document = json.loads(path.read_text())
        for role in document['visual']['query']['queryState'].values():
            for p in role['projections']:
                kind, value = next(iter(p['field'].items()))
                table = value['Expression']['SourceRef']['Entity']
                assert value['Property'] in (measures if kind == 'Measure' else columns)[table]
    for relationship in model['relationships']:
        assert relationship['fromColumn'] in columns[relationship['fromTable']]
        assert relationship['toColumn'] in columns[relationship['toTable']]


def test_csv_headers_match_semantic_model_columns():
    model = json.loads((ROOT / 'powerbi/Cadence.SemanticModel/model.bim').read_text())['model']
    for table in model['tables']:
        with (ROOT / 'exports' / (table['name'] + '.csv')).open() as stream:
            headers = next(csv.reader(stream))
        assert headers == [c['name'] for c in table['columns']]
