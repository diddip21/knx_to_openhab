from pathlib import Path

from completeness import check_completeness

TESTS_DIR = Path(__file__).parent
PROJECTS = [
    TESTS_DIR / "fixtures" / "mini_project.json",
    TESTS_DIR / "Charne.knxproj.json",
    TESTS_DIR / "upload.knxprojarchive.json",
]


def _rule_checks_for_project(project_path: Path, tmp_path: Path, generate_output_from_json):
    output_dir = generate_output_from_json(project_path, tmp_path)
    things_text = (output_dir / "knx.things").read_text(encoding="utf-8")
    return check_completeness(things_text)


def test_things_completeness_matrix_all_projects(tmp_path, generate_output_from_json):
    missing_required = []
    recommended_missing = []

    for project_path in PROJECTS:
        project_missing, project_recommended = _rule_checks_for_project(
            project_path, tmp_path, generate_output_from_json
        )
        missing_required.extend(project_missing)
        recommended_missing.extend(project_recommended)

    if recommended_missing:
        print("Recommended (not required) feedback missing:")
        for kind, reason, line in recommended_missing:
            print(f" - {kind}: {reason} :: {line}")

    assert missing_required == []
