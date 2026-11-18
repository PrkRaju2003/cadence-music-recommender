"""Set the local CSV path in the semantic model before opening Power BI Desktop."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--data-dir', type=Path, required=True)
args = parser.parse_args()
folder = args.data_dir.resolve()
if not (folder / 'Playback.csv').is_file():
    parser.error('Playback.csv not found; run python -m cadence.export first')
target = Path(__file__).resolve().parents[1] / 'powerbi/Cadence.SemanticModel/model.bim'
model = json.loads(target.read_text())
parameter = next(e for e in model['model']['expressions'] if e['name'] == 'DataFolder')
path_text = str(folder).replace('\\', '/').replace('"', '""')
parameter['expression'] = f'"{path_text}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'
target.write_text(json.dumps(model, indent=2) + '\n')
print('Configured DataFolder. Open powerbi/Cadence.pbip in Power BI Desktop, then Refresh.')
