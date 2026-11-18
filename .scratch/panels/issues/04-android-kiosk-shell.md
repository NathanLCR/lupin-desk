# P04 - Android kiosk shell for old devices

Status: done (RG406H verified 2026-11-18; Moto G5 and boot/USB trigger test pending)
Blocked by: P01

## Scope

- Extend the existing WebView shell (`android/src/com/nathanlucio/deskassistant/MainActivity.java`, built by `scripts/build_android_apk.py`, no Gradle). One APK for the RG406H and old phones/tablets.
- Lower minSdk from 26 to 24 (Moto G5, Android 7). Keep targetSdk.
- First run: enter or discover the Brain's address (Wi-Fi or `adb reverse` over USB). The role is set on the Mac (P01), not on the device.
- Keep screen on, fullscreen/immersive, start on boot or on USB power if the user enables it, reconnect with backoff.
- Keep RG406H features working (Gamepad API, microphone permission, current Body behaviour).

## Acceptance criteria

- [ ] The APK installs and runs on the Moto G5 (Android 7) and the RG406H (Android 13).
- [ ] After a reboot or Wi-Fi drop, the shell reconnects by itself.
- [ ] The screen stays on while a Panel is shown.
