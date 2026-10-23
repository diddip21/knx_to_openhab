from pathlib import Path

TESTS_DIR = Path(__file__).parent
MINI_PROJECT = TESTS_DIR / "fixtures" / "mini_project.json"


def test_mini_things_contains_expected_entries(tmp_path, generate_output_from_json):
    output_dir = generate_output_from_json(MINI_PROJECT, tmp_path)
    things = (output_dir / "knx.things").read_text(encoding="utf-8")

    assert "Type dimmer" in things
    assert "Type rollershutter" in things
    assert "Type number" in things
    assert "1/1/1+<1/1/2" in things
    assert 'upDown="1/2/1"' in things


def test_mini_items_contains_expected_entries(tmp_path, generate_output_from_json):
    output_dir = generate_output_from_json(MINI_PROJECT, tmp_path)
    items = (output_dir / "knx.items").read_text(encoding="utf-8")

    assert "Dimmer   i_EG_RM1_DimmenDimmWert" in items
    assert "Rollershutter   i_EG_RM1_JalousieJalousieAufAb" in items
    assert "Number   i_EG_RM1_HeizenBetriebsartvorwahl" in items


def test_mini_sitemap_contains_expected_entries(tmp_path, generate_output_from_json):
    output_dir = generate_output_from_json(MINI_PROJECT, tmp_path)
    sitemap = (output_dir / "knx.sitemap").read_text(encoding="utf-8")

    assert 'Frame label="=EG"' in sitemap
    assert "Default item=i_EG_RM1_DimmenDimmWert" in sitemap
    assert "Default item=i_EG_RM1_JalousieJalousieAufAb" in sitemap
    assert "Default item=i_EG_RM1_HeizenBetriebsartvorwahl" in sitemap
