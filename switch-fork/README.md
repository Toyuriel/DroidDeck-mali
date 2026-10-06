# CloversNX Mali v0.1 build overlay

This branch is an isolated build overlay for Strato aimed at recent ARM Mali-G720 Android devices.

Base: strato-emu/strato commit `ae1566a48285816a87e81d4aeb40bd2f4e56e60b`.

v0.1 changes:
- Separate Android application id: `com.cloversgamers.cloversnx.mali`
- App label: `CloversNX Mali`
- Mali-G720 runtime detection
- Conservative Vulkan compatibility path on Mali-G720
- Single-threaded pipeline compilation on Mali-G720 to reduce proprietary-driver race/crash risk
- Slightly smaller GPU executor queue defaults (32 slots instead of 64)
- Lower default flush threshold (192 instead of 256)
- Existing Strato Mali fixes remain intact

The build does not bundle keys, firmware, games, copyrighted Nintendo files, or proprietary GPU drivers.
