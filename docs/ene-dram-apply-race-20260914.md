# ENE DRAM profile-application race — 2026-09-14

## Symptom

The wallpaper hook reported that `tori-blue.json` was applied, but both ENE
DRAM modules remained in their default rainbow state. Earlier repeated attempts
left the controller at address `0x73` dark until standby power was removed.

## Evidence

After a cold boot, both modules were visibly running the default rainbow. Their
hardware registers contained mode `255`, Direct disabled, and only six of the
eight requested Direct colors. The saved profile correctly contained eight
Tori Blue values for both modules.

OpenRGB 1.0's CLI calls `SetActiveMode()`, which queues `DeviceUpdateMode()` on
the controller worker thread, and then immediately calls `DeviceUpdateLEDs()`
on the CLI thread. An ENE logical register write is itself a register-selection
SMBus transaction followed by a separate data transaction. Those two logical
operations can interleave on the same controller, explaining the partial color
buffer and missing Direct-mode commit.

OpenRGB also reports unknown hardware mode `255` as its default internal mode
index zero, named Direct. SDK/controller readback therefore cannot prove that
the physical mode was applied.

## Fix design

The active adapter uses the persistent OpenRGB SDK server and serializes mode,
zone, color, and controller operations with a settle interval. After OpenRGB
state validation, it pauses the idle server and reads the ENE mode and color
registers directly. The wallpaper success marker is written only after this
hardware verification passes.
