# Changelog

## 2.3.0

- Added tray-configurable application-controlled auto sleep.
- Added 5 / 15 / 30 minute and 1 / 3 / 6 hour idle options.
- Added manual global LED sleep/wake tray actions.
- Uses verified global LED OFF/ON Raw HID packets.
- Only physical keypresses reset the application idle timer.
- Blocks dashboard HID/display refreshes while asleep.
- Added post-sleep key sequence guard to prevent stale events from causing immediate wake.
- Preserved privacy-safe weather configuration; no personal location is embedded.

## 2.2.0

- Public-repository privacy cleanup.
- Removed all embedded geographic coordinates and location names.
- Added local-only weather configuration.
- Added bilingual README.
- Added `.gitignore` rules for auth/config/secrets/build outputs.
- Preserved tray mode switching and Windows auto-start support.
- Preserved 5-second hybrid typing-to-scroll idle timeout.
- Added Windows GitHub Actions build workflow.
