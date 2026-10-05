# 369 Attendance

> Employee-facing attendance and leave app for Odoo 19 — check in and out, watch the month
> take shape, and apply for leave from the phone.

369 Attendance is an [Expo](https://expo.dev) React Native app for the
[`hr_attendance_369`](odoo_modules/hr_attendance_369/) Odoo suite that ships beside it. An
employee picks a server, signs in, and lands on a home screen that shows today's state and the
month so far; one button handles check-in and check-out. A second screen covers leave — paid
balance, request history and a range-picker apply sheet.

The app talks to a **live Odoo server** over JSON-RPC. It is not tied to any particular
deployment: the server address and database are chosen on first launch and remembered.

## Features

**Connect and sign in** — enter a server address, pick a database from the list the server
returns, then log in. Authentication is a session cookie, captured and persisted so later calls
survive an app restart.

**Home** — an attendance card whose single button flips between Check In and Check Out based on
the employee's live `attendance_state`; month stat tiles graded Present / Late / Half Day /
Absent; recent activity; and quick-action tiles.

**Leave** — paid-leave balance card, request list with state chips and a server-side state
filter, cancel with a state-aware confirmation, and an apply sheet built on a hand-rolled
month-grid range calendar ([src/components/DateRangeCalendar.js](src/components/DateRangeCalendar.js)) —
no extra dependency.

**Theme** — slate and amber with sharp corners, deliberately distinct from the house style.
Always opens light.

## Tech stack

| | |
|---|---|
| Framework | Expo SDK ~54, React Native 0.81.5, React 19.1 |
| Navigation | React Navigation 7 (native stack) |
| State | React context — [src/state/SessionContext.js](src/state/) |
| Styling | Custom token theme in [src/theme/](src/theme/), Inter via `@expo-google-fonts` |
| Storage | AsyncStorage (session id, server, database) |
| Transport | `fetch` against Odoo JSON-RPC — no HTTP client dependency |

Fifteen runtime dependencies in total; the app deliberately adds none it can hand-roll.

## Odoo backend

Both modules are in [odoo_modules/](odoo_modules/) and target **Odoo 19**.

| Module | Purpose |
|---|---|
| `hr_attendance_369` | Attendance Suite — late tracking & deductions, leave requests, work-from-home, monthly employee reports and device registration in one module. Depends on `base`, `web`, `hr`, `hr_attendance`. |
| `kra_kpi_attendance_bridge` | Starting a KRA/KPI workday records an HR attendance check-in, and ending it writes the check-out. Every KRA user is linked to an HR employee (matched by work email, or created) on install and on their first Start Workday. Depends on `hr_attendance_369` + `kra_kpi_module`; auto-installs only where both are present. |

The bridge is optional — install it only alongside the
[KRA_KPI](https://github.com/Sri-balakumar/kra_kpi) app's module.

### Two things to know about the transport

Both are documented at the top of [src/services/odoo.js](src/services/odoo.js):

1. **A failed Odoo call still returns HTTP 200.** The failure arrives as an `error` key in the
   JSON body, so checking `response.ok` proves nothing — every body is inspected.
2. **Auth is a cookie.** `/web/session/authenticate` replies with `session_id`. React Native's
   native cookie jar is opaque and clears with the app, so the id is captured and persisted and
   also sent explicitly on later calls.

## Getting started

**Prerequisites** — Node.js 18+, npm, and the [Expo Go](https://expo.dev/go) app. A reachable
Odoo 19 server with `hr_attendance_369` installed.

```bash
npm install
npx expo start
```

Press `a` for Android, `w` for the browser, or scan the QR code with Expo Go.

On first launch the app asks for a server address. **A phone needs the server's LAN address, not
`localhost`** — `localhost` on the phone means the phone. The app supplies `http://` automatically
for private address ranges. Pick the database from the list, then sign in with Odoo credentials.

After changing [metro.config.js](metro.config.js), restart Metro fully rather than reloading:

```bash
npx expo start -c
```

## Verifying a build

`expo export` compiles modules but never *evaluates* them, so a module-scope `ReferenceError`
passes the build and then crashes at launch — which has happened here twice, both times a theme
value used inside a module-level `StyleSheet.create`. [tools/verify-bundle.js](tools/verify-bundle.js)
closes that gap by parsing everything, then actually running it against stubbed native modules,
and only then exporting.

```bash
npm run verify
```

## Project structure

```
App.js              entry point
src/
  screens/          SplashScreen, auth/ (AuthScreen: server + sign-in steps),
                    home/ (HomeScreen, AttendanceCard, StatTiles, RecentActivity, QuickActions),
                    leave/ (LeaveScreen, LeaveApplySheet, LeaveBalanceStrip, LeaveRequestCard)
  services/         odoo.js — the live JSON-RPC client (auth, attendance, leave)
                    mockOdoo.js — retired; only its DAY_STATUS map is still used
  components/       AppTextInput, Card, Chip, ConfirmDialog, DateRangeCalendar,
                    PrimaryButton, SelectSheet, Skeleton, Toast
  navigation/       RootNavigator.js
  state/            SessionContext.js
  theme/            ThemeProvider, colors, tokens
  utils/            time.js (Odoo's naive-UTC datetimes), url.js
tools/              verify-bundle.js — the three-part bundle check
odoo_modules/       hr_attendance_369, kra_kpi_attendance_bridge
```

## Status and roadmap

Home and Leave both run on live server data.

| Phase | State |
|---|---|
| 1 — Attendance (check in/out, month tiles, recent activity) | Done |
| 2 — Leave (balance, list, filter, cancel, apply) | Done |
| 3 — Work From Home (`/wfh/request/*`, `/wfh/today_status`) | Planned |
| 4 — Attendance history, and a My Details tile in place of Reports | Planned |

Not yet exercised on a physical device: the Leave screen's appearance, the dark-mode pass, and
Android hardware back.

## Documentation

- [SESSION.md](SESSION.md) — engineering notes: what the addon added, API behaviour verified
  against a live server, and the open items behind the roadmap above.
- [docs/legacy-README.md](docs/legacy-README.md) — the previous README, written while the app
  still ran on mock data. Kept for reference; its description of the app is out of date.
