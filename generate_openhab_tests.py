import os
import subprocess


def generate_openhab_tests(project_json, test_output_py):
    base = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(base, ".venv", "Scripts", "python.exe")
    script = os.path.join(base, "knxproject_to_openhab.py")
    subprocess.run([venv_python, script, "--file_path", project_json, "--readDump"], check=True)

    files = {
        "items": os.path.join(base, "openhab", "items", "knx.items"),
        "things": os.path.join(base, "openhab", "things", "knx.things"),
        "sitemap": os.path.join(base, "openhab", "sitemaps", "knx.sitemap"),
        "persist": os.path.join(base, "openhab", "persistence", "influxdb.persist"),
        "rules": os.path.join(base, "openhab", "rules", "fenster.rules"),
    }

    with open(test_output_py, "w", encoding="utf-8") as out:
        out.write("import unittest\nimport os\n\n")
        out.write("class TestKNXProjectToOpenHAB_Auto(unittest.TestCase):\n")
        out.write("    @classmethod\n    def setUpClass(cls):\n")
        out.write(f"        # Automatisch generiert für {os.path.basename(project_json)}\n")
        out.write("        pass  # Output-Dateien müssen vorab generiert sein\n\n")
        for key, path in files.items():
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            out.write(f"    def test_{key}_file_exists_and_content(self):\n")
            out.write(f"        self.assertTrue(os.path.isfile(r'{path}'))\n")
            out.write(f"        with open(r'{path}', encoding='utf-8') as f:\n")
            out.write("            content = f.read()\n")
            for line in lines:
                if line.startswith(
                    (
                        "Group",
                        "Number",
                        "Dimmer",
                        "Switch",
                        "Type",
                        "Default",
                        "Frame",
                        "Strategies",
                        "rule",
                    )
                ):
                    safe_line = line.replace('"', '\\"')
                    out.write(f'            self.assertIn("{safe_line}", content)\n')
            out.write("\n")
        out.write("if __name__ == '__main__':\n    unittest.main()\n")


# Beispiel-Aufruf:
# generate_openhab_tests('tests/Mayer.knxprojarchive.json', 'tests/unit/test_knxproject_to_openhab_output_auto.py')
generate_openhab_tests(
    "tests/Mayer.knxprojarchive.json", "tests/unit/test_knxproject_to_openhab_Mayer.py"
)
