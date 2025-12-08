# User Guide — KNX to OpenHAB Generator

This guide explains how to prepare your ETS project, configure the generator, and understand how KNX data types are mapped to OpenHAB items.

## Table of Contents
1. [Configuration (`config.json`)](#configuration-configjson)
2. [ETS Project Preparation](#ets-project-preparation)
3. [Logic & Mappings](#logic--mappings)
4. [Troubleshooting](#troubleshooting)

---

## Configuration (`config.json`)

The `config.json` file controls global settings for the generator.

### Key Settings

- **`drop_words`**: A list of words to remove from item labels to keep them short.
  - *Example*: If you have a group address "Kitchen Light Right", and "Light" is in `drop_words`, the label becomes "Kitchen Right" (assuming the icon already indicates it's a light).
  - *Note*: Words are NOT dropped if doing so would result in an empty label.

- **`openhab_path`**: The output directory for generated files.
  - Default is `openhab`.
  - If running on the OpenHAB server, this might point to `/etc/openhab`.

- **`dimmer`**: Configuration for dimmer detection.
  - `suffix_absolut`: The suffix in the GA name identifying the absolute dimming value (default: "Dimmen absolut").
  - `status_suffix`: The suffix identifying the status GA (default: "Status Dimmwert").

- **`switch`**: Configuration for switch detection.
  - `status_suffix`: The suffix identifying the status GA (default: "Status").

---

## ETS Project Preparation

The generator relies partly on your ETS project structure and naming conventions. You can also use the **Description** field of Group Addresses (GAs) in ETS to pass special instructions.

### Description Field Tags

You can add multiple tags to a GA's description field, separated by semicolons (`;`).

| Tag | Effect | Example |
| :--- | :--- | :--- |
| `influx` | Automatically persist this item to InfluxDB. | `influx` |
| `debug` | Adds a visibility tag. Item is hidden unless `extended_view` is enabled. | `debug;influx` |
| `semantic=...` | Overrides the default Semantic Model tag. [See options](https://github.com/openhab/openhab-core/blob/main/bundles/org.openhab.core.semantics/model/SemanticTags.csv). | `semantic=Projector` |
| `icon=...` | Sets a specific icon. | `icon=pump` |
| `location` | Adds location tags to the first two layers of the GA structure. | `location` |
| `ignore` | Completely skips importing this GA. | `ignore` |
| Scene Mapping | Maps raw scene numbers to text labels. | `1='Cooking', 2='TV'` |

**Example Description**: 
`semantic=Pump;icon=pump;debug;influx`

---

## Logic & Mappings

The generator automatically determines the OpenHAB Item type based on the **Data Point Type (DPT)** assigned in ETS.

### 1. Automatic Type Mapping (Based on DPT)

| ETS DPT | OpenHAB Item | Note |
| :--- | :--- | :--- |
| **Switch** (1.001) | Switch | |
| **Dimming** | Dimmer | Detected by pairing absolute value + status |
| **Temperature** | Number:Temperature | Uses UoM (Units of Measurement) |
| **Humidity** | Number:Dimensionless | Uses UoM |
| **Window Contact** (1.019)| Contact | |
| **Power** (W) | Number:Power | Uses UoM |
| **Energy** (Wh) | Number:Energy | Uses UoM |
| **Current** (A) | Number:ElectricCurrent | Uses UoM |
| **Lux** | Number:Illuminance | Uses UoM |
| **Alarm** (1.005) | Contact / Switch | Mapped to Alarm type |
| **Scene** (17.001) | Number | Can be mapped to text with description tags |
| **String** (16.000) | String | |
| **Percent** (5.001) | Number:Dimensionless | |

### 2. Name-Based Detection

Some complex items require specific naming conventions to be detected correctly if the DPT is not enough effectively group them.

#### Rollershutters
- Detects Rollershutters based on common naming patterns in the GA name.

#### Dimmers
- Looks for a pair of GAs:
    1. **Control GA**: Name ends with configured `suffix_absolut` (e.g., "Living Room Light Dimming Absolute").
    2. **Status GA**: Name ends with `status_suffix` (e.g., "Living Room Light Dimming Status").
- The generator merges these into a single OpenHAB `Dimmer` item.

#### Switches (Status Pairing)
- Looks for a Status GA with the same base name + `status_suffix`.
- *Example*: "Light Kitchen" (Cmd) + "Light Kitchen Status" (Status) -> Single Switch Item with status feedback.

---

## Troubleshooting

### "My device shows as a generic Number"
- **Cause**: DPT is missing or not specific enough in ETS.
- **Fix**: Open ETS, select the Group Address, and ensure the correct "Data Type" is selected (e.g., set to "temperature (℃)" instead of just "2-byte float").

### "Dimmer not working"
- **Cause**: Naming mismatch between Control and Status GAs.
- **Fix**: Check `config.json` for `dimmer.suffix_absolut` and ensure your ETS names match exactly.

### "Item names are too long"
- **Fix**: Add common words (like "Light", "Switch") to the `drop_words` list in `config.json`.
