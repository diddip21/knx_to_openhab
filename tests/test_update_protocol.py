import copy
import json

import pytest

from installer.update_core.artifacts import select_release
from installer.update_core.protocol import parse_contract, parse_request, validate_config_copy

REQUEST = {
    "format_version": 1,
    "request_id": "12345678-1234-4234-8234-123456789abc",
    "channel": "stable",
}
CONTRACT = {
    "updater_protocol": 1,
    "config_copy_protocol": 1,
    "accepted_input_schema_versions": [0, 1],
    "output_schema_version": 1,
    "runtime_backward_compatible": True,
}


def release(version, *, draft=False, prerelease=False):
    name = f"knx_to_openhab-{version}.tar.gz"
    base = f"https://github.com/diddip21/knx_to_openhab/releases/download/v{version}/"
    return {
        "tag_name": f"v{version}",
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            {"name": name, "browser_download_url": base + name},
            {"name": name + ".sha256", "browser_download_url": base + name + ".sha256"},
        ],
    }


def test_request_accepts_only_the_fixed_protocol():
    request = parse_request(json.dumps(REQUEST).encode())
    assert (request.format_version, request.request_id, request.channel) == (
        1,
        REQUEST["request_id"],
        "stable",
    )
    assert parse_request(json.dumps({**REQUEST, "channel": "prerelease"}).encode()).channel == (
        "prerelease"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"format_version": True},
        {"format_version": 2},
        {"request_id": "not-a-uuid"},
        {"channel": "dev"},
        {"channel": False},
        {"url": "https://evil.test"},
    ],
)
def test_request_rejects_untrusted_fields(change):
    with pytest.raises(ValueError):
        parse_request(json.dumps({**REQUEST, **change}).encode())


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b"null",
        b"\xff",
        b" " * 4097,
        b'{"format_version":1,"format_version":1}',
        b'{"x":NaN}',
    ],
    ids=["empty", "array", "null", "utf8", "oversized", "duplicate", "nan"],
)
def test_request_rejects_malformed_or_oversized_json(raw):
    with pytest.raises(ValueError):
        parse_request(raw)


@pytest.mark.parametrize(
    "change",
    [
        {"updater_protocol": 2},
        {"config_copy_protocol": True},
        {"runtime_backward_compatible": False},
        {"runtime_backward_compatible": 1},
        {"accepted_input_schema_versions": [True]},
        {"accepted_input_schema_versions": []},
        {"accepted_input_schema_versions": [0, 0]},
        {"output_schema_version": -1},
        {"output_schema_version": 2**31},
        {"unexpected": 1},
    ],
)
def test_contract_rejects_unsupported_or_ambiguous_values(change):
    with pytest.raises(ValueError):
        parse_contract(json.dumps({**CONTRACT, **change}).encode())


def test_contract_requires_explicit_runtime_compatibility():
    contract = dict(CONTRACT)
    del contract["runtime_backward_compatible"]
    with pytest.raises(ValueError):
        parse_contract(json.dumps(contract).encode())


def test_config_copy_preserves_all_existing_sibling_trees():
    original = {"general": {"port": 8085}, "custom": [{"nested": [1, True, None]}]}
    migrated = {**copy.deepcopy(original), "schema_version": 1, "new_default": 0}
    validate_config_copy(original, migrated, parse_contract(json.dumps(CONTRACT).encode()))
    assert original == {"general": {"port": 8085}, "custom": [{"nested": [1, True, None]}]}


@pytest.mark.parametrize(
    "migrated",
    [
        {"general": {"port": 8086}, "schema_version": 1},
        {"general": {}, "schema_version": 1},
        {"schema_version": 1},
        {"general": {"port": 8085, "new": 1}, "schema_version": 1},
        {"general": {"port": 8085}, "schema_version": True},
        {"general": {"port": 8085}, "schema_version": 0},
    ],
)
def test_config_copy_rejects_sibling_mutation_or_wrong_schema(migrated):
    with pytest.raises(ValueError):
        validate_config_copy(
            {"general": {"port": 8085}},
            migrated,
            parse_contract(json.dumps(CONTRACT).encode()),
        )


@pytest.mark.parametrize("current", ["1.2.3", "1.2.3+other", "2.0.0"])
def test_no_equal_precedence_reinstall_or_downgrade(current):
    assert select_release(release("1.2.3+build"), "stable", current) is None


def test_prerelease_semver_sorting_and_page_bound():
    pages = [[release("2.0.0-rc.2", prerelease=True)], [release("2.0.0-rc.10", prerelease=True)]]
    selected = select_release(pages, "prerelease", "1.0.0")
    assert selected.version == "2.0.0-rc.10"
    assert selected.archive_name == "knx_to_openhab-2.0.0-rc.10.tar.gz"
    with pytest.raises(ValueError):
        select_release([[]] * 11, "prerelease", "1.0.0")


def test_stable_excludes_drafts_and_prereleases():
    assert select_release(release("2.0.0", draft=True), "stable", "1.0.0") is None
    assert select_release(release("2.0.0-rc.1", prerelease=True), "stable", "1.0.0") is None
    assert select_release(release("2.0.0-rc.1"), "stable", "1.0.0") is None
    assert select_release(release("2.0.0"), "stable", "1.0.0").version == "2.0.0"


@pytest.mark.parametrize("version", ["01.2.3", "1.2.3-01", "1.2.3\n", "1.٢.3"])
def test_release_rejects_non_strict_semver(version):
    with pytest.raises(ValueError):
        select_release(release(version), "stable", "1.0.0")


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/diddip21/knx_to_openhab/releases/download/v2.0.0/a",
        "https://evil.test/a",
        "https://github.com.evil.test/a",
        "https://user@github.com/diddip21/knx_to_openhab/releases/download/v2.0.0/a",
        "https://github.com/other/repo/releases/download/v2.0.0/a",
        "https://github.com:443/diddip21/knx_to_openhab/releases/download/v2.0.0/a",
    ],
)
def test_release_rejects_unsafe_asset_urls(url):
    metadata = release("2.0.0")
    metadata["assets"][0]["browser_download_url"] = url
    with pytest.raises(ValueError):
        select_release(metadata, "stable", "1.0.0")


@pytest.mark.parametrize("assets", [[], [0], None])
def test_release_requires_well_formed_assets(assets):
    metadata = release("2.0.0")
    metadata["assets"] = assets
    with pytest.raises(ValueError):
        select_release(metadata, "stable", "1.0.0")


def test_release_rejects_duplicate_asset():
    metadata = release("2.0.0")
    metadata["assets"].append(dict(metadata["assets"][0]))
    with pytest.raises(ValueError):
        select_release(metadata, "stable", "1.0.0")


def test_metadata_limit_is_enforced():
    metadata = release("2.0.0")
    metadata["body"] = "x" * (1024 * 1024)
    with pytest.raises(ValueError):
        select_release(metadata, "stable", "1.0.0")


@pytest.mark.parametrize("old,new", [(1, True), ([1], [True]), ({"value": 1}, {"value": True})])
def test_config_copy_does_not_confuse_boolean_and_numeric_values(old, new):
    with pytest.raises(ValueError):
        validate_config_copy(
            {"general": old},
            {"general": new, "schema_version": 1},
            parse_contract(json.dumps(CONTRACT).encode()),
        )


@pytest.mark.parametrize(
    "versions,want",
    [
        (["2.0.0-alpha", "2.0.0-1"], "2.0.0-alpha"),
        (["2.0.0-rc.10", "2.0.0"], "2.0.0"),
        (["2.0.0-alpha.1", "2.0.0-alpha"], "2.0.0-alpha.1"),
    ],
)
def test_semver_precedence_rules(versions, want):
    metadata = [release(version, prerelease="-" in version) for version in versions]
    assert select_release(metadata, "prerelease", "1.0.0").version == want
