# Battery Monitor iOS wrapper — automation entry points.
# Requires macOS with Xcode command-line tools. XcodeGen is installed on demand.
SIM ?= iPhone 15
PROJECT = BatteryMonitor.xcodeproj
SCHEME = BatteryMonitor

.PHONY: help bootstrap icon generate open build run clean

help:
	@echo "make run       Build + launch in the iOS Simulator (no Apple account needed)"
	@echo "make open      Generate the project and open it in Xcode"
	@echo "make generate  Generate $(PROJECT) from project.yml"
	@echo "make build     Build for the Simulator (unsigned)"
	@echo "make icon      Regenerate the app icon from the dashboard icon"
	@echo "make clean     Remove generated project + build output"
	@echo "Override the simulator with: make run SIM='iPhone 15 Pro'"

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

clean:
	rm -rf build $(PROJECT)
