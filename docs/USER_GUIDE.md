# User Guide — KNX to OpenHAB Generator

This guide explains the everyday workflow first. Mapping rules and advanced settings follow below. This integration branch is not approved for upgrades of existing productive installations; see the [current status](FEATURE_UPGRADE.md#status-für-bestehende-installationen).

For a complete overview of the integrated changes, usage notes, and before/after screenshots, see the [Feature Upgrade Guide](FEATURE_UPGRADE.md).

## First project: review before deploy

1. **Select** a `.knxproj`, `.knxprojarchive` or supported JSON dump. Add its project password if needed. Use **Preview structure** to check floors and rooms without processing.
2. Choose **Process project**. This stages the generated result; it does not deploy to the running openHAB configuration.
3. In **Review results and changes**, open the job. Check the generated files, the **Diff**, and reports of unrecognized or incomplete addresses. Correct ETS naming and process again if needed. Auto-place is optional and off by default.
4. Choose **Deploy** only after the result makes sense. The review dialog lists every affected file; open the file names for the diff, tick the acknowledgement, then press **Deploy now**. The service makes a backup before writing managed output.
5. If the result is wrong, choose **Rollback**, select the backup and check the restored output. Manually maintained files outside the managed output are not part of this rollback.

![Authenticated dashboard with project upload and job history](screenshots/feature-upgrade/after-authenticated-dashboard.png)

## Table of Contents

1. [Command Line Usage (CLI)](#command-line-usage)
2. [Web UI vs CLI](#web-ui-vs-cli)
3. [Configuration (`config.json`)](#configuration-configjson)
4. [openHAB 5.2 YAML Output](#openhab-52-yaml-output)
5. [ETS Project Preparation](#ets-project-preparation)
6. [Logic & Mappings](#logic--mappings)
7. [Troubleshooting](#troubleshooting)

---

## Command Line Usage

You can run the generator directly from the command line without the Web UI:

```bash
python knxproject_to_openhab.py --file_path "MyHouse.knxproj"
```

**Parameters:**

- `--file_path`: Path to your `.knxproj` file (or `.json` dump). If omitted, a file picker opens.
- `--knxPW`: Password for protected KNX project files.
- `--readDump`: Read from JSON dump instead of `.knxproj`.

**Example with password:**

```bash
python knxproject_to_openhab.py --file_path "project.knxproj" --knxPW "password"
```

The CLI uses the same `config.json` and generates the same output as the Web UI.

## Web UI vs CLI

- **Web UI**: Best for interactive uploads, quick config edits, and report review (unknown/partial/completeness).
- **CLI**: Best for automation or headless environments.

The Web UI exposes **reports** in the *Expert* panel (View / Download / Copy):
- `unknown_report.json` (generated even when `addMissingItems` is disabled)
- `partial_report.json`
- `completeness_report.json` (checks for missing required channels and recommended feedback)

**Expert Reports panel:** enable **Expert** in the *Generated Files Statistics* section to see the reports list and open the full, human‑readable recommendations via **View**.

**Completeness rules (summary):**
- **Required:** dimmer → `position`; rollershutter → `upDown`; switch/number/string/datetime → `ga`
- **Recommended:**
  - dimmer → one of `switch` or `increaseDecrease`
  - rollershutter → one of `stopMove` or `position`
  - switch/number → status feedback (`ga` with `+<` status binding)
  - number with HVAC DPT 20.102 → status feedback if missing

## Configuration (`config.json`)

The `config.json` file controls global settings for the generator.

### Key Settings

- **`output_format`**: Selects the model format.
  - `legacy` (default during the migration period): separate `.things`, `.items`, and `.sitemap` files.
  - `yaml`: one native openHAB 5.2 `version: 1` model.

- **`yaml_path`**: Target for the native YAML model.
  - Default: `openhab/yaml/knx.yaml` (or `$OPENHAB_CONF/yaml/knx.yaml` when openHAB is detected).

- **`drop_words`**: A list of words to remove from item labels to keep them short.
  - _Example_: If you have a group address "Kitchen Light Right", and "Light" is in `drop_words`, the label becomes "Kitchen Right" (assuming the icon already indicates it's a light).
  - _Note_: Words are NOT dropped if doing so would result in an empty label.

- **`openhab_path`**: The output directory for generated files.
  - Default is `openhab`.
  - If running on the OpenHAB server, this might point to `/etc/openhab`.

- **`general.auto_place_unknown`**: Automatically creates missing floors/rooms for unknown group addresses.
  - `false` (default): Unknowns remain in the report so you can fix naming/structure in ETS.
  - `true`: Unknowns get auto-placed into newly created floor/room nodes.

- **`dimmer`**: Configuration for dimmer detection.
  - `absolut_suffix`: Suffixes in the GA name identifying the absolute dimming value (e.g., "Dimmen absolut", "Helligkeitswert").
  - `status_suffix`: Suffixes identifying the status GA (e.g., "Status Dimmwert", "Rückmeldung Dimmen").

- **`switch`**: Configuration for switch detection.
  - `status_suffix`: Suffixes identifying the status GA (e.g., "Status", "Rückmeldung").

## openHAB 5.2 YAML Output

Set `output_format` to `yaml` in the Web UI or `config.json` to generate a native openHAB 5.2 file:

```json
{
  "output_format": "yaml",
  "yaml_path": "openhab/yaml/knx.yaml"
}
```

The resulting document contains `version: 1` and the `things`, `items`, and `sitemaps` sections. The generator validates Item names, parent Groups, Bridge references, Item-channel links, and Sitemap Item references before replacing the target file.

Migration is intentionally explicit: never load the generated legacy model files and `knx.yaml` at the same time, because they define the same entity IDs. A Web UI deployment backs up the live configuration and then retires the generated files from the other format. Rollback restores the backed-up configuration.

`influxdb.persist` remains in the persistence directory. The existing stateful `fenster.rules` also remains textual; wrapping its body in a YAML Script action would reset its counters and change the 15-minute notification behavior.

Official format reference: [openHAB YAML Configuration](https://www.openhab.org/docs/configuration/yaml/).

## KNX Gateway Address

The **Devices** settings allow an optional gateway IP override. Enter a valid IPv4 or IPv6
address, save the configuration, and reprocess the project. Leave the field empty to keep
ETS-based gateway detection. Invalid addresses are rejected before generated files change.
Saving the address preserves the other device settings.

## openHAB and evcc Package Updates

The **Services** section can check APT package lists and update openHAB or evcc one at a time.
The update uses the candidate version shown in the confirmation and stops if that candidate
changes before installation. Only an already installed package managed by APT is updated;
Docker and manually installed copies are left alone. Review upstream release notes before
major upgrades. A package update does not replace generated KNX configuration.

## Login and Remote Access

Sign in with the Web UI username and the password configured during installation. Sessions
expire and can be revoked with **Log out**. The service listens on `127.0.0.1` by default.
From another computer, use an SSH tunnel:

```bash
ssh -L 8085:127.0.0.1:8085 <benutzer>@<geraete-ip>
```

Then open `http://127.0.0.1:8085` in the local browser. Direct LAN access must be explicitly
configured by an administrator; use HTTPS through a trusted reverse proxy on untrusted
networks.

---

## ETS Project Preparation

The generator relies partly on your ETS project structure and naming conventions. You can also use the **Description** field of Group Addresses (GAs) in ETS to pass special instructions.

### Description Field Tags

You can add multiple tags to a GA's description field, separated by semicolons (`;`).

| Tag            | Effect                                                                                                                                                                | Example               |
| :------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------- |
| `influx`       | Automatically persist this item to InfluxDB.                                                                                                                          | `influx`              |
| `debug`        | Adds a visibility tag. Item is hidden unless `extended_view` is enabled.                                                                                              | `debug;influx`        |
| `semantic=...` | Overrides the default Semantic Model tag. [See options](https://github.com/openhab/openhab-core/blob/main/bundles/org.openhab.core.semantics/model/SemanticTags.csv). | `semantic=Projector`  |
| `icon=...`     | Sets a specific icon.                                                                                                                                                 | `icon=pump`           |
| `location`     | Adds location tags to the first two layers of the GA structure.                                                                                                       | `location`            |
| `ignore`       | Completely skips importing this GA.                                                                                                                                   | `ignore`              |
| Scene Mapping  | Maps raw scene numbers to text labels.                                                                                                                                | `1='Cooking', 2='TV'` |

**Example Description**:
`semantic=Pump;icon=pump;debug;influx`

---

## Logic & Mappings

The generator automatically determines the OpenHAB Item type based on the **Data Point Type (DPT)** assigned in ETS.

### 1. Automatic Type Mapping (Based on DPT)

| ETS DPT                    | OpenHAB Item           | Unit/Note                                     | Semantic                 |
| :------------------------- | :--------------------- | :-------------------------------------------- | :----------------------- |
| **DPST-1-1**               | Switch                 | On/Off                                        | Control                  |
| **DPST-1-5**               | Switch                 | Alarm                                         | Alarm                    |
| **DPST-1-11**              | Switch                 | Status                                        | Measurement, Status      |
| **DPST-1-19**              | Contact                | Window/Door Contact                           | OpenState, Opening       |
| **DPST-1-24**              | Switch                 | Window Day/Night                              | Control                  |
| **DPST-1-100**             | Switch                 | Heating/Cooling Status                        | Measurement, Status      |
| **DPST-5-1**               | Dimmer                 | Percentage (0-100%)                           | Measurement              |
| **DPST-5-010**             | Number:Dimensionless   | HVAC Mode (Komfort/Standby/Nacht/Frostschutz) | HVAC                     |
| **DPST-7-12**              | Number:ElectricCurrent | Ampere (A)                                    | Measurement, Current     |
| **DPST-9-1**               | Number:Temperature     | Temperature (°C)                              | Measurement, Temperature |
| **DPST-9-4**               | Number:Illuminance     | Brightness (Lux)                              | Measurement, Light       |
| **DPST-9-5**               | Number:Speed           | Wind Speed (m/s)                              | Measurement, Wind        |
| **DPST-9-7**               | Number:Dimensionless   | Humidity (%)                                  | Measurement, Humidity    |
| **DPST-9-8**               | Number:Dimensionless   | Air Quality (ppm)                             | Measurement              |
| **DPST-12-1200**           | Number:Volume          | Volume (L)                                    | Measurement, Volume      |
| **DPST-13-10**             | Number:Energy          | Energy (Wh)                                   | Measurement, Energy      |
| **DPST-13-100**            | Number:Time            | Duration/Time                                 | Measurement, Duration    |
| **DPST-14-56**             | Number:Power           | Power (W)                                     | Measurement, Power       |
| **DPST-16-0** / **DPT-16** | String                 | Text/String                                   | -                        |
| **DPST-17-1**              | Number                 | Scene Number                                  | -                        |
| **DPST-19-1**              | DateTime               | Date and Time                                 | -                        |
| **DPST-20-102**            | Number:Dimensionless   | HVAC Mode (with Alexa/HomeKit)                | HVAC                     |

**Notes:**

- DPTs with "Number:X" use OpenHAB's Unit of Measurement (UoM) system
- Some DPTs have specific Alexa/HomeKit integrations configured (e.g., Temperature, Humidity, Window Contact)
- HVAC modes (DPST-5-010, DPST-20-102) include predefined state options (Komfort=1, Standby=2, Nacht=3, Frostschutz=4)

### 2. Name-Based Detection

Some complex items require specific naming conventions to be detected correctly, as the DPT alone is not sufficient to group them properly.

#### Rollershutters

- Detects Rollershutters based on common naming patterns in the GA name.
- Combines multiple GAs:
  - **Up/Down**: "Auf/Ab", "Jalousie Auf/Ab", "Rollladen Auf/Ab" (DPST-1-8)
  - **Stop**: "Stop", "Stopp", "Lamellenverstellung / Stopp" (DPST-1-10, DPST-1-9, DPST-1-7)
  - **Absolute Position**: "absolute Position" (DPST-5-1)
  - **Status**: "Status", "Rückmeldung", "Status aktuelle Position" (DPST-5-1)

#### Dimmers

- Looks for a pair or trio of GAs:
  1. **Control GA**: Name ends with configured `absolut_suffix` (e.g., "Dimmen absolut", "Helligkeitswert").
  2. **Status GA**: Name ends with `status_suffix` (e.g., "Status Dimmwert", "Rückmeldung Dimmen").
  3. **Switch GA** (optional): Name ends with switch suffix (e.g., "Schalten", "Ein/Aus").
  4. **Switch Status GA** (optional): Name ends with switch status suffix (e.g., "Status Ein/Aus", "Rückmeldung").
- The generator merges these into a single OpenHAB `Dimmer` item.
- **Special metadata override** for specific dimmer types:
  - **Farbtemperatur**: Color temperature control (no Alexa/HomeKit)
  - **Lamellenposition**: Blind slat position (with Alexa TiltAngle & HomeKit support)
  - **Stellwert**: HVAC actuator value

#### Switches (Status Pairing)

- Looks for a Status GA with the same base name + `status_suffix`.
- _Example_: "Licht Küche" (Cmd) + "Licht Küche Status" (Status) → Single Switch Item with status feedback.
- **Metadata override** based on switch name:
  - **Licht**: Mapped to Light equipment with Alexa/HomeKit integration
  - **Steckdose**: Mapped to PowerOutlet
  - **Heizen**: Mapped to HVAC/Heating
  - **Audio**: Mapped to Speaker

#### Heating

- Combines heating mode GAs:
  - **Mode Control**: "Betriebsmodus", "Betriebsartvorwahl" (DPST-5-010, DPST-20-102)
  - **Mode Status**: "Status Betriebsmodus", "DPT_HVAC Mode: Reglerstatus senden" (DPST-5-010, DPST-20-102)

---

## UI Reports & Auto-Placement

The Web UI shows **reports** for unknown, partial, and completeness checks so you can quickly fix ETS naming or structure. If you prefer automatic placement, enable it in **Settings → Auto-place unknown addresses** (or set `general.auto_place_unknown = true` in `config.json`).

---

## Troubleshooting

### "Login/401 in Web UI"

- The Web UI uses a sign-in form and a protected browser session by default.
- Use the Web UI password you set during installation. Existing user-chosen
  passwords are preserved during migration; the shipped default is replaced.
- For new installs, open `http://127.0.0.1:8085` locally or connect through an SSH
  tunnel; LAN-wide listening requires an explicit configuration choice.
- Local development and browser tests can disable authentication with `FLASK_ENV=testing`.
  Production authentication is configured during installation.

### "My device shows as a generic Number"

- **Cause**: DPT is missing or not specific enough in ETS.
- **Fix**: Open ETS, select the Group Address, and ensure the correct "Data Type" is selected (e.g., set to "temperature (℃)" instead of just "2-byte float").

### "Dimmer not working"

- **Cause**: Naming mismatch between Control and Status GAs.
- **Fix**: Check `config.json` for `dimmer.absolut_suffix` and `dimmer.status_suffix`, and ensure your ETS names match exactly with one of the configured suffixes.

### "Rollershutter not detected"

- **Cause**: GA names don't match the expected patterns.
- **Fix**: Ensure your GAs follow common naming conventions like "Auf/Ab", "Stop", "absolute Position" or add custom suffixes to the `rollershutter` section in `config.json`.

### "Item names are too long"

- **Fix**: Add common words (like "Licht", "Steckdose", "Fensterkontakt") to the `drop_words` list in `config.json`.

### "HVAC mode not showing correct options"

- **Cause**: Wrong DPT selected in ETS.
- **Fix**: Use DPST-5-010 or DPST-20-102 for heating modes. These DPTs have predefined options (1=Komfort, 2=Standby, 3=Nacht, 4=Frostschutz).

### "Units not displaying correctly"

- **Cause**: Unit of Measurement (UoM) not configured or DPT doesn't specify units.
- **Fix**: Use specific DPTs like DPST-9-1 for temperature, DPST-14-56 for power, etc. Generic DPTs (like 9.xxx without subtype) may not include units.
