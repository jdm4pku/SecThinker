"""Verify downloaded bytes and JSON schema; never execute dataset code or tests."""
from pathlib import Path
from datetime import datetime, timezone
import csv, hashlib, json, re

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'provenance/download_manifest.json').read_text())
for f in manifest['files']:
    body = (root / f['path']).read_bytes()
    assert len(body) == f['bytes'], f['path']
    assert hashlib.sha256(body).hexdigest() == f['sha256'], f['path']
fields = ['ID', 'Problem', 'Insecure Code', 'Secure Code', 'Test', 'Test-FP', 'Test-SP', 'Entry_Point']
summary = {}
index = []
all_ids = []
all_cwes = set()
for name, expected in [('SecEvalBase', 115), ('SecEvalPlus', 140)]:
    path = root / 'data' / name / 'test.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) == expected, name
    ids = []
    cwes = set()
    for row in rows:
        assert set(row) == set(fields), (name, row.get('ID'))
        assert all(isinstance(row[k], str) and row[k].strip() for k in fields), row['ID']
        ids.append(row['ID'])
        matches = re.findall(r'CWE-(\d+)', row['ID'])
        assert matches, row['ID']
        normalized = list(dict.fromkeys(map(int, matches)))
        cwes.update(normalized)
        index.append({'subset': name, 'ID': row['ID'], 'CWE_from_ID': ', '.join(f'CWE-{c}' for c in normalized), 'Entry_Point': row['Entry_Point'], 'Problem': row['Problem']})
    assert len(set(ids)) == len(ids), name
    all_ids.extend(ids); all_cwes.update(cwes)
    summary[name] = {'tasks': len(rows), 'unique_ids': len(set(ids)), 'normalized_cwe_count': len(cwes), 'path': str(path.relative_to(root))}
assert len(set(all_ids)) == len(all_ids)
result = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'revision': manifest['revision'], 'checks_passed': True, 'upstream_file_checksums_passed': len(manifest['files']), 'subsets': summary, 'total_tasks': len(all_ids), 'unique_task_ids': len(set(all_ids)), 'fields': fields, 'official_reported_cwe_categories': 77, 'normalized_cwe_categories_from_task_ids': len(all_cwes), 'dataset_code_executed': False, 'tests_executed': False, 'scope': 'Download integrity, JSON parsing, required nonempty string fields, record counts, unique IDs and CWE statistics only.'}
(root / 'provenance/validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
(root / 'review').mkdir(exist_ok=True)
with (root / 'review/task_index.csv').open('w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['subset', 'ID', 'CWE_from_ID', 'Entry_Point', 'Problem'])
    writer.writeheader(); writer.writerows(index)
print(json.dumps(result, ensure_ascii=False, indent=2))
