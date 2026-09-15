import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


class AutoDeployContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.watcher = (DEPLOY / "auto-deploy.sh").read_text(encoding="utf-8")
        cls.launcher = (DEPLOY / "auto-deploy-launcher.sh").read_text(
            encoding="utf-8"
        )
        cls.installer = (DEPLOY / "install-auto-deploy.sh").read_text(
            encoding="utf-8"
        )
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_watcher_tracks_master_safely_and_uses_existing_deployers(self) -> None:
        self.assertIn('REMOTE="origin"', self.watcher)
        self.assertIn('BRANCH="master"', self.watcher)
        self.assertIn("fetch --quiet --prune", self.watcher)
        self.assertIn('merge --quiet --ff-only "${target}"', self.watcher)
        self.assertIn('flock -n 9', self.watcher)
        self.assertIn('monitor/deploy-monitor.sh', self.watcher)
        self.assertIn('DEPLOY_SCRIPT="${REPO_ROOT}/deploy-collector.sh"', self.watcher)
        self.assertIn('"${DEPLOY_ARGUMENTS[@]}" --skip-git-update', self.watcher)

    def test_watcher_verifies_health_and_the_running_image_revision(self) -> None:
        self.assertIn('org.opencontainers.image.revision', self.watcher)
        self.assertIn('container_is_healthy', self.watcher)
        self.assertIn('${SERVICE}.seen', self.watcher)
        self.assertIn('${SERVICE}.deployed', self.watcher)
        self.assertIn('Deployment returned successfully', self.watcher)
        self.assertIn('--follow-logs cannot be used', self.watcher)

    def test_watcher_filters_services_and_preserves_collector_config(self) -> None:
        self.assertIn('monitor/*|docker-compose.monitor.yml', self.watcher)
        self.assertIn('src/*|Dockerfile|docker-compose.yml', self.watcher)
        self.assertIn('" M config.toml"', self.watcher)
        self.assertIn('also changes config.toml', self.watcher)
        self.assertIn('status --porcelain --untracked-files=normal', self.watcher)

    def test_installer_creates_persistent_systemd_timers(self) -> None:
        self.assertIn('battery-monitor-auto-deploy', self.installer)
        self.assertIn('battery-collector-auto-deploy', self.installer)
        self.assertIn('OnBootSec=2min', self.installer)
        self.assertIn('OnUnitActiveSec=${INTERVAL}', self.installer)
        self.assertIn('RandomizedDelaySec=${RANDOM_DELAY}', self.installer)
        self.assertIn('Persistent=true', self.installer)
        self.assertIn('StateDirectory=battery-auto-deploy', self.installer)
        self.assertIn('systemctl enable --now', self.installer)
        self.assertIn('EnvironmentFile=-${CONFIG_DIR}/${SERVICE}.env', self.installer)

    def test_launcher_uses_the_live_checkout_so_the_watcher_updates_itself(self) -> None:
        self.assertIn('${repo}/deploy/auto-deploy.sh', self.launcher)
        self.assertIn('--arguments-file "${arguments_file}"', self.launcher)
        self.assertIn('BATTERY_AUTO_DEPLOY_SNAPSHOT', self.watcher)

    def test_readme_has_commands_for_both_hosts(self) -> None:
        self.assertIn('## Automatic deployment from master', self.readme)
        self.assertIn('install-auto-deploy.sh monitor', self.readme)
        self.assertIn('install-auto-deploy.sh collector', self.readme)
        self.assertIn('battery-monitor-auto-deploy.timer', self.readme)
        self.assertIn('battery-collector-auto-deploy.timer', self.readme)

    def test_deployment_defaults_match_the_installed_hosts(self) -> None:
        monitor_compose = (ROOT / "docker-compose.monitor.yml").read_text(
            encoding="utf-8"
        )
        collector_compose = (ROOT / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        monitor_deploy = (ROOT / "monitor" / "deploy-monitor.sh").read_text(
            encoding="utf-8"
        )
        collector_deploy = (ROOT / "deploy-collector.sh").read_text(
            encoding="utf-8"
        )
        collector_url = "http://192.168.10.194:8000"
        inverter_host = "192.168.20.138"
        logger_serial = "3503566593"
        serial_device = (
            "/dev/serial/by-id/"
            "usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0"
        )

        self.assertIn(collector_url, monitor_compose)
        self.assertIn(collector_url, monitor_deploy)
        self.assertIn(serial_device, collector_compose)
        self.assertIn(serial_device, collector_deploy)
        self.assertIn(inverter_host, collector_compose)
        self.assertIn(inverter_host, collector_deploy)
        self.assertIn(logger_serial, collector_compose)
        self.assertIn(logger_serial, collector_deploy)


if __name__ == "__main__":
    unittest.main()
