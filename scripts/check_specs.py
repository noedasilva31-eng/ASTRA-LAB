"""Structural checks, not a complete JSON Schema implementation."""
import json
from pathlib import Path
from astra.contracts import FIELDS, validate
root=Path(__file__).resolve().parents[1]
schemas=list((root/'schemas').glob('*.json'))
for path in schemas:
    schema=json.loads(path.read_text())
    assert schema['$schema']=='https://json-schema.org/draft/2020-12/schema'
    assert set(schema['required'])==set(schema['properties'])
    assert schema['additionalProperties'] is False
assert set(json.loads((root/'schemas/source-record.schema.json').read_text())['required'])==FIELDS
for line in (root/'fixtures/events.jsonl').read_text().splitlines(): validate(json.loads(line))
assert len(list((root/'docs/adr').glob('*.md')))==8
print(f'PASS: {len(schemas)} JSON contracts structurally checked, fixture validated, 8 ADR present. Full JSON Schema meta-validation not run.')
