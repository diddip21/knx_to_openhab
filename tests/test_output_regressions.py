from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
UPLOAD_PROJECT = TESTS_DIR / "upload.knxprojarchive.json"


@pytest.mark.parametrize(
    "needle",
    [
        "Rollershutter   i_UG_RM3_xxxRechtsM1RolladenRolladenAufAb",
        "Dimmer   i_EG_RM1_xxxSpotsFlurH18DimmenDimmWert",
        "Dimmer   i_EG_RM1_xxxFlurGarderobeWCM20HeizenStatusStellwert",
    ],
)
def test_items_contains_expected_patterns(tmp_path, needle, generate_output_from_json):
    output_dir = generate_output_from_json(UPLOAD_PROJECT, tmp_path)
    items_path = output_dir / "knx.items"
    content = items_path.read_text(encoding="utf-8")
    assert needle in content


@pytest.mark.parametrize(
    "needle",
    [
        "Bridge knx:ip:bridge",
        "Type rollershutter    :   i_UG_RM3_xxxRechtsM1RolladenRolladenAufAb",
        "Type dimmer    :   i_EG_RM1_xxxSpotsFlurH18DimmenDimmWert",
    ],
)
def test_things_contains_expected_patterns(tmp_path, needle, generate_output_from_json):
    output_dir = generate_output_from_json(UPLOAD_PROJECT, tmp_path)
    things_path = output_dir / "knx.things"
    content = things_path.read_text(encoding="utf-8")
    assert needle in content


@pytest.mark.parametrize(
    "needle",
    [
        'sitemap knx label="MiCasa"',
        "Default item=i_UG_RM3_xxxRechtsM1RolladenRolladenAufAb",
        "Default item=i_EG_RM1_xxxSpotsFlurH18DimmenDimmWert",
    ],
)
def test_sitemap_contains_expected_patterns(tmp_path, needle, generate_output_from_json):
    output_dir = generate_output_from_json(UPLOAD_PROJECT, tmp_path)
    sitemap_path = output_dir / "knx.sitemap"
    content = sitemap_path.read_text(encoding="utf-8")
    assert needle in content


def test_persistence_contains_strategy_block(tmp_path, generate_output_from_json):
    output_dir = generate_output_from_json(UPLOAD_PROJECT, tmp_path)
    persist_path = output_dir / "influxdb.persist"
    content = persist_path.read_text(encoding="utf-8")
    assert "Strategies" in content
    assert "Items" in content
