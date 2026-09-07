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

On a Mac with Xcode installed:

```bash
cd ios
make run            # or: make run SIM='iPhone 15 Pro'
```

This installs XcodeGen if missing, generates the project, builds it unsigned, and
launches it in the Simulator. To work in Xcode instead: `make open`.

## Point it at your server

The app defaults to `http://raspberrypi.local:8080` (the monitor's default port).
Change it two ways:

- **In the app:** tap the ⚙︎ (top-right) → enter the address → Save.
- **Build-time default:** edit `MonitorBaseURL` in
  [`App/Resources/Info.plist`](App/Resources/Info.plist).

HTTP to `.local`/private-range hosts is allowed via `NSAllowsLocalNetworking`
(App Store–acceptable); no need to disable App Transport Security wholesale.

## Ship to a device / TestFlight (one-time signing setup)

1. Open the project: `make open`.
2. Select the **BatteryMonitor** target → *Signing & Capabilities* → pick your
   Team. Xcode manages the provisioning profile automatically.
3. Run on a connected device (▶), or *Product → Archive* → *Distribute App*.

To automate a **signed** build in CI later, add repository secrets for an Apple
API key (`APP_STORE_CONNECT_KEY_ID`, `ISSUER_ID`, the `.p8`) and set
`DEVELOPMENT_TEAM` in `project.yml`; a `fastlane` lane or
`xcodebuild -exportArchive` step can then produce and upload an `.ipa`. The
current CI intentionally stops at an unsigned Simulator build so it stays green
with no secrets.

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
  App/Resources/Info.plist        ATS, launch, default server URL
  App/Resources/Assets.xcassets/  app icon + launch color
  scripts/                        bootstrap, run-simulator, icon generator
  Makefile                        make run / open / build / icon / clean
.github/workflows/ios.yml         CI build on macOS
```
