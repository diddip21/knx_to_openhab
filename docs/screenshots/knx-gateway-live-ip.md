# KNX Things format and live gateway IP

These screenshots show the Devices settings and the result of applying the documentation-only sample address `192.0.2.42`; `198.51.100.10` is the sample ETS source address. Both are reserved for documentation. The live target is the Things file from the last successful deployment, shown relative to the OpenHAB root; pending format/path selections do not relabel it. The success state confirms only that the managed file was updated, not that OpenHAB reloaded it or that the bridge is online.

## Devices settings

The format selector keeps DSL as the default and offers YAML for OpenHAB 5.0+. The gateway controls include a dedicated Undo action and apply only to the last deployed generator-owned file. YAML destinations must be provisioned before deployment, and YAML live actions require a known OpenHAB 5.0+ installation.

![Devices settings showing the KNX Things format and gateway controls](knx-gateway-live-ip-settings.png)

## Live IP applied

The status confirms the file-only update, shows that Undo is available, and explicitly leaves runtime status unchecked. Undo is guarded against changes to the deployed target or managed file.

![Devices settings after applying the sample KNX gateway IP](knx-gateway-live-ip-applied.png)
