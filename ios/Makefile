SIM ?=
DEVELOPMENT_TEAM ?=
PROJECT = BatteryMonitor.xcodeproj
SCHEME = BatteryMonitor

.PHONY: help bootstrap generate open build test run archive ipa clean

help:
	@echo "make run       Build and launch in an iPhone Simulator"
	@echo "make open      Generate the project and open it in Xcode"
	@echo "make build     Build for the Simulator without signing"
	@echo "make test      Run the iOS unit tests"
	@echo "make archive   Create a signed App Store archive"
	@echo "make ipa       Export an App Store IPA"
	@echo "make clean     Remove generated project and build output"

bootstrap:
	bash scripts/bootstrap.sh

generate: bootstrap
	xcodegen generate

open: generate
	open $(PROJECT)

build: generate
	xcodebuild -project $(PROJECT) -scheme $(SCHEME) -configuration Debug \
		-sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
		-derivedDataPath build CODE_SIGNING_ALLOWED=NO build

test:
	bash scripts/test-simulator.sh

run:
	bash scripts/run-simulator.sh "$(SIM)"

archive: generate
	@test -n "$(DEVELOPMENT_TEAM)" || { echo "Set DEVELOPMENT_TEAM to your 10-character Apple Team ID"; exit 1; }
	xcodebuild -project $(PROJECT) -scheme $(SCHEME) -configuration Release \
		-destination 'generic/platform=iOS' -archivePath build/BatteryMonitor.xcarchive \
		-allowProvisioningUpdates DEVELOPMENT_TEAM=$(DEVELOPMENT_TEAM) archive

ipa: archive
	xcodebuild -exportArchive -archivePath build/BatteryMonitor.xcarchive \
		-exportOptionsPlist ExportOptions.plist -exportPath build/ipa -allowProvisioningUpdates

clean:
	rm -rf build $(PROJECT)
