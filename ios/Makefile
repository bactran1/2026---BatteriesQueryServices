# Battery Monitor iOS wrapper — automation entry points.
# Requires macOS with Xcode installed. XcodeGen is installed on demand.
# SIM is optional; empty means "auto-pick an available iPhone simulator".
SIM ?=
DEVELOPMENT_TEAM ?=
PROJECT = BatteryMonitor.xcodeproj
SCHEME = BatteryMonitor

.PHONY: help bootstrap icon generate open build run archive ipa clean

help:
	@echo "make run       Build + launch in the iOS Simulator (no Apple account needed)"
	@echo "make open      Generate the project and open it in Xcode"
	@echo "make generate  Generate $(PROJECT) from project.yml"
	@echo "make build     Build for the Simulator (unsigned)"
	@echo "make icon      Regenerate the app icon from the dashboard icon"
	@echo "make archive   Signed Release archive (App Store). Needs DEVELOPMENT_TEAM=XXXX"
	@echo "make ipa       Export an App Store .ipa from the archive"
	@echo "make clean     Remove generated project + build output"
	@echo "Pick a specific simulator with: make run SIM='iPhone 16 Pro'"

bootstrap:
	./scripts/bootstrap.sh

icon:
	python3 scripts/make-appicon.py

generate: bootstrap
	xcodegen generate

open: generate
	open $(PROJECT)

build: generate
	xcodebuild -project $(PROJECT) -scheme $(SCHEME) -configuration Debug \
		-sdk iphonesimulator -derivedDataPath build CODE_SIGNING_ALLOWED=NO build

run:
	./scripts/run-simulator.sh "$(SIM)"

archive: generate
	@test -n "$(DEVELOPMENT_TEAM)" || { echo "Set your team: make archive DEVELOPMENT_TEAM=XXXXXXXXXX"; exit 1; }
	xcodebuild -project $(PROJECT) -scheme $(SCHEME) -configuration Release \
		-destination 'generic/platform=iOS' -archivePath build/BatteryMonitor.xcarchive \
		-allowProvisioningUpdates DEVELOPMENT_TEAM=$(DEVELOPMENT_TEAM) archive

ipa: archive
	xcodebuild -exportArchive -archivePath build/BatteryMonitor.xcarchive \
		-exportOptionsPlist ExportOptions.plist -exportPath build/ipa -allowProvisioningUpdates
	@echo "App Store .ipa written to build/ipa/"

clean:
	rm -rf build $(PROJECT)
