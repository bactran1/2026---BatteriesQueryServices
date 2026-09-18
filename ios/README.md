# Battery Monitor for iPhone and iPad

This directory contains the native SwiftUI companion app for the existing
`battery-monitor` service. The app is a read-only client: it connects to the
monitor API on the home network and does not contact the Raspberry Pi collector
or the battery RS485 bus directly.

## Included

- Universal iPhone and iPad interface
- iPhone tab navigation and iPad sidebar navigation
- Animated live flow for solar, grid, inverter, batteries, Home load, and Backup load
- Direct rack and individual battery telemetry, including cells and temperatures
- Interactive Swift Charts power and SOC history
- PSE savings views
- Weather, irradiance, and sun-position details
- Five-second foreground refresh with pull-to-refresh
- Last-known dashboard cache for temporary network outages
- System, light, and dark appearance modes
- English and Vietnamese localization
- Local-network privacy description and HTTP local-network support
- Small and medium Home Screen widgets for rack SOC, power, and pack status
- One-command Simulator launch, unsigned CI builds, and App Store archive targets

## Requirements

- macOS with Xcode 16 or newer
- XcodeGen (`brew install xcodegen`)
- iOS or iPadOS 17 or newer
- Network access from the Apple device to the x86 monitor host

## Build and run

```bash
cd ios
make run
```

Use `make open` to generate the project and open it in Xcode instead. Both
commands install XcodeGen through Homebrew when it is not already available.

In Xcode, select the `BatteryMonitor` target, choose your Apple development
team, then run on an iPhone/iPad simulator or a connected device. The target is
configured as a universal iOS app (`TARGETED_DEVICE_FAMILY = 1,2`).

On first launch, open **Settings** and enter the x86 monitor address, including
port `8080`, for example:

```text
http://192.168.10.50:8080
```

Use the monitor host address, not the collector URL at port `8000`. iOS will ask
for permission to access devices on the local network the first time the app
connects.

The app and widget share this address through the
`group.com.trant.batterymonitor` App Group. After running the app once and
granting local-network permission, add the widget from the iPhone or iPad Home
Screen. WidgetKit refreshes it on the system-managed schedule, generally around
every 15 minutes rather than every five seconds.

Useful automation commands:

```bash
make build
make test
make run SIM='iPhone 16 Pro'
make archive DEVELOPMENT_TEAM=XXXXXXXXXX
make ipa DEVELOPMENT_TEAM=XXXXXXXXXX
```

## Distribution

For household-only installation, run from Xcode using a personal or paid Apple
Developer team. TestFlight or App Store distribution requires a paid Apple
Developer Program membership, a unique bundle identifier, signing certificates,
and App Store Connect configuration.
