# User Guide — KNX to OpenHAB Generator

This guide explains how to prepare your ETS project, configure the generator, and understand how KNX data types are mapped to OpenHAB items.

## Table of Contents

1. [Command Line Usage (CLI)](#command-line-usage)
1. [Configuration (`config.json`)](#configuration-configjson)
1. [ETS Project Preparation](#ets-project-preparation)
1. [Logic & Mappings](#logic--mappings)
1. [Troubleshooting](#troubleshooting)

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

The Web UI exposes **reports** in the *Generated Files* table (Preview / Download / Copy):
- `unknown_report.json` (generated even when `addMissingItems` is disabled)
- `partial_report.json`
- `completeness_report.json` (checks for missing required channels and recommended feedback)

**Completeness rules (summary):**
- **Required:** dimmer → `position`; rollershutter → `upDown`; switch/number/string/datetime → `ga`
- **Recommended:**
  - dimmer → one of `switch` or `increaseDecrease`
  - rollershutter → one of `stopMove` or `position`
  - switch/number → status feedback (`ga` with `+<` status binding)
  - number with HVAC DPT 20.102 → status feedback if missing

## First-Run (Recommended Flow)

1. **Upload** your `.knxproj` (or JSON dump)
2. **Preview Structure** to verify floors/rooms
3. **Process** and check **Generated Files** + **Reports**
4. **Fix ETS naming** or **enable Auto‑Place** if you want quick placement
5. **Deploy** when you’re happy with the output

## Configuration (`config.json`)

The `config.json` file controls global settings for the generator.

### Key Settings

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

- The Web UI uses **Basic Auth** by default.
- Default credentials: **admin / logihome** (change in Settings).
- If you disabled auth in `web_ui/backend/config.json`, restart the UI service.

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
