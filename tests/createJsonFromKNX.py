import json

from xknxproject import XKNXProj

file_names = [
    ("Charne.knxprojarchive", None, "de-DE"),
]

for file_name, password, language in file_names:
    print(f"Parsing {file_name}")
    knxproj = XKNXProj(
        path=f"tests/{file_name}",
        password=password,
        language=language,
    )
    project = knxproj.parse()

    with open(f"tests/{file_name}.json", "w", encoding="utf8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)