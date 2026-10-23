import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import extract_sections, digest
def test_manual_has_sections_and_content():
    sections=extract_sections(str(ROOT/'ct200_manual.pdf'))
    assert len(sections)>10
    assert any('Intended Use' in s['heading'] for s in sections)
def test_v2_adds_data_export_section():
    sections=extract_sections(str(ROOT/'ct200_manual_v2.pdf'))
    assert any(s['section_number']=='5.3' and 'Data Export' in s['heading'] for s in sections)
def test_battery_life_change_detected_in_text():
    a=extract_sections(str(ROOT/'ct200_manual.pdf')); b=extract_sections(str(ROOT/'ct200_manual_v2.pdf'))
    x=next(s for s in a if 'Battery Life Under Typical Use' in s['heading'])
    y=next(s for s in b if 'Battery Life Under Typical Use' in s['heading'])
    assert digest(x['body']) != digest(y['body'])
    assert '300 measurement cycles' in x['body'] and '250 measurement cycles' in y['body']
def test_out_of_order_section_number_is_preserved():
    sections=extract_sections(str(ROOT/'ct200_manual.pdf'))
    assert any(s['section_number']=='3.4' and 'Auto Shuto' in s['heading'] for s in sections)
def test_deep_numbering_is_not_flattened():
    sections=extract_sections(str(ROOT/'ct200_manual.pdf'))
    assert any(s['section_number']=='2.1.1.1' for s in sections)
