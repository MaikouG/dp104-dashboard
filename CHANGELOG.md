# Changelog

## 2.4.0

- Added tray-based weather-location configuration.
- Added Open-Meteo place-name search with selectable results.
- Added manual latitude/longitude input and editable display label.
- Search results can auto-fill the location timezone.
- Weather configuration applies without restarting the tray app.
- Added a clear-location action.
- Universal Release EXE no longer requires build-time location data.
- Location remains local-only under `%APPDATA%\DP104Dashboard\config.json`.
- Preserved guarded application-controlled auto sleep from v2.3.

## 2.2.0

- Public-repository privacy cleanup.
- Removed all embedded geographic coordinates and location names.
- Added local-only weather configuration.
- Added bilingual README.
- Added `.gitignore` rules for auth/config/secrets/build outputs.
- Preserved tray mode switching and Windows auto-start support.
- Preserved 5-second hybrid typing-to-scroll idle timeout.
- Added Windows GitHub Actions build workflow.
