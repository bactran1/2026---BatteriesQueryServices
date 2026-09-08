# Battery Monitor — iOS app

A thin native iOS wrapper (SwiftUI + `WKWebView`) that renders the **exact** live
dashboard. It is not a rewrite: the app loads the monitor's web UI over the
network, so every page, chart, and the WebGL energy-flow scene are identical to
the browser. The Xcode project is generated from [`project.yml`](project.yml) by
[XcodeGen](https://github.com/yonaskolb/XcodeGen), so there is no `.xcodeproj` to
hand-edit or keep in sync.

## What's automated

| Step | How |
| --- | --- |
| App icon (1024², opaque) | `scripts/make-appicon.py`, from the dashboard icon |
| Xcode project | `xcodegen generate` (from `project.yml`) |
| Build + run in Simulator | `make run` — one command, **no Apple account** |
| CI build on every push | `.github/workflows/ios.yml` on a macOS runner (unsigned) |

## What still needs a human (and why)

Apple's toolchain cannot be run off a Mac, so these are irreducible:

- **A Mac with Xcode** (or the GitHub Actions macOS runner, already wired up) to
  compile. There is no way to build an iOS app on Windows/Linux.
- **An Apple ID** to run on a *physical device*, and a paid **Apple Developer
  account** to ship via TestFlight / the App Store. The Simulator needs neither.

## Run it (Simulator — the zero-setup path)

On a Mac with **Xcode** installed (the full app, not just the Command Line Tools):

```bash
cd ios
make run            # or: make run SIM='iPhone 15 Pro'
```

This installs XcodeGen if missing, generates the project, builds it unsigned, and
launches it in the Simulator. To work in Xcode instead: `make open`.

> If you see `xcodebuild requires Xcode, but active developer directory is a
> command line tools instance`, point the tools at Xcode once:
> ```bash
> sudo xcode-select -s /Applications/Xcode.app
> ```
> (`make run` now detects this and prints the exact command for your setup.)

## Point it at your server

The default address is `http://192.168.1.114:8080` — the constant
`AppConfig.defaultURLString` in [`Shared/AppConfig.swift`](Shared/AppConfig.swift).
Change the address at runtime in the app: tap the ⚙︎ (top-right) → type it → Save
(there's a clear ✕ and a one-tap "Use default"). The value is stored in an App
Group so the widget uses the same address.

HTTP to `.local`/private-range hosts is allowed via `NSAllowsLocalNetworking`
(App Store–acceptable); no need to disable App Transport Security wholesale.

## Home Screen widget

A WidgetKit extension (`BatteryWidgetExtension`) adds small/medium widgets showing
**rack SOC, live power, and online packs**, refreshed ~every 15 minutes. It fetches
`/api/live` itself (the web view can't drive a widget) and reads the server address
from the shared App Group, so it follows whatever you set in the app.

Add it on device: long-press the Home Screen → **+** → search "Battery Monitor".
Notes:
- The widget needs local-network access, which iOS grants once you've opened the
  app on that device.
- The App Group (`group.com.trant.batterymonitor`) is pre-wired in the
  entitlements; automatic signing registers it when you pick a Team.

## Ship to the App Store

Prerequisites: enrollment in the **Apple Developer Program** ($99/yr) and a Mac.

**One-time setup**
1. `make open`, then for **both** targets (BatteryMonitor and BatteryWidget) →
   *Signing & Capabilities* → select your **Team**. Automatic signing creates the
   certificates, provisioning profiles, and registers the App Group + bundle IDs
   (`com.trant.batterymonitor` and `…​.widget`).
2. In **App Store Connect** → *Apps* → **＋** → create an app for bundle ID
   `com.trant.batterymonitor` (name, primary language, SKU).

**Build & upload** — either:
- *Xcode:* Product → **Archive** → **Distribute App** → *App Store Connect*. Easiest
  for a first submission.
- *Command line (scripted):*
  ```bash
  cd ios
  make ipa DEVELOPMENT_TEAM=XXXXXXXXXX          # -> build/ipa/BatteryMonitor.ipa
  xcrun altool --upload-app -f build/ipa/BatteryMonitor.ipa \
    --apiKey <KEY_ID> --apiIssuer <ISSUER_ID>   # or drag the .ipa into Transporter
  ```
  (Find your 10-char Team ID in the Apple Developer portal → *Membership*.)

Then in App Store Connect add screenshots + a privacy label (this app collects no
data), attach the build, and **Submit for Review**. TestFlight builds are available
to testers within minutes of upload without full review.

**Fully automated releases (optional):** create an App Store Connect **API key**
(.p8), store `ASC_KEY_ID` / `ASC_ISSUER_ID` / the key as GitHub secrets, and add a
`workflow_dispatch` job that runs `make ipa` + `xcrun altool --upload-app` (or a
`fastlane` lane). The default CI stays at an unsigned Simulator build so it needs
no secrets.

## Requirements

- iOS **16.4+** (WKWebView gained import-map support there, which the dashboard's
  three.js loader uses; older iOS still runs the app but falls back to the CSS
  energy-flow scene).
- iPhone and iPad (`TARGETED_DEVICE_FAMILY = 1,2`).

## Layout

```
ios/
  project.yml                     XcodeGen spec (source of truth)
  App/Sources/*.swift             @main app, WKWebView, settings, error view
  App/Resources/                  Info.plist (ATS/launch), Assets, App.entitlements
  Widget/Sources/BatteryWidget.swift   WidgetKit extension (SOC / power / packs)
  Widget/Resources/Info.plist          widget extension point + ATS
  Widget/Widget.entitlements           App Group
  Shared/                         AppConfig + MonitorSummary (app + widget)
  ExportOptions.plist             App Store export settings for `make ipa`
  scripts/                        bootstrap, run-simulator, icon generator
  Makefile                        run / open / build / icon / archive / ipa / clean
.github/workflows/ios.yml         CI build on macOS
```
