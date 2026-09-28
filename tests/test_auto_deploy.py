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
        cls.workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

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
        self.assertIn('status --porcelain --untracked-files=no', self.watcher)
        self.assertIn('ls-files --others --exclude-standard -z', self.watcher)
        self.assertIn('Untracked files overlap ${SERVICE} build inputs', self.watcher)
        self.assertIn('Ignoring ${untracked_ignored} unrelated untracked file', self.watcher)

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

    def test_ci_runs_the_same_checks_for_both_channels(self) -> None:
        # Every push to master or dev, and every pull request into them, runs
        # the Python suites, the dashboard's Node tests, the deployment
        # scripts' syntax, the dashboard in Chromium and both Docker builds.
        self.assertIn("branches: [master, dev]", self.workflow)
        self.assertIn('python -m unittest discover -s tests -p "test_*.py"', self.workflow)
        self.assertIn("PYTHONPATH: src:monitor/src", self.workflow)
        self.assertIn('node --test "${test}"', self.workflow)
        self.assertIn("*_browser.cjs) continue", self.workflow)
        self.assertIn("node tests/test_frontend_charts_browser.cjs", self.workflow)
        self.assertIn("npx playwright install --with-deps chromium", self.workflow)
        for script in ("deploy-collector.sh", "monitor/deploy-monitor.sh",
                       "deploy/auto-deploy.sh", "deploy/install-auto-deploy.sh"):
            with self.subTest(script=script):
                self.assertIn(script, self.workflow)
        self.assertIn("docker/build-push-action", self.workflow)
        self.assertIn("file: monitor/Dockerfile", self.workflow)
        self.assertIn("COLLECTOR_BRANCH=${{ github.ref_name }}", self.workflow)
        self.assertIn("MONITOR_BRANCH=${{ github.ref_name }}", self.workflow)

    def test_images_and_services_carry_their_channel(self) -> None:
        collector_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        monitor_dockerfile = (ROOT / "monitor" / "Dockerfile").read_text(encoding="utf-8")
        collector_compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        monitor_compose = (ROOT / "docker-compose.monitor.yml").read_text(encoding="utf-8")
        collector_deploy = (ROOT / "deploy-collector.sh").read_text(encoding="utf-8")
        monitor_deploy = (ROOT / "monitor" / "deploy-monitor.sh").read_text(encoding="utf-8")

        # The branch an image was built from is stamped beside its commit.
        self.assertIn('org.opencontainers.image.ref.name="${COLLECTOR_BRANCH}"', collector_dockerfile)
        self.assertIn("BQS_BUILD_BRANCH=${COLLECTOR_BRANCH}", collector_dockerfile)
        self.assertIn('org.opencontainers.image.ref.name="${MONITOR_BRANCH}"', monitor_dockerfile)
        self.assertIn("BQM_BUILD_BRANCH=${MONITOR_BRANCH}", monitor_dockerfile)
        self.assertIn("COLLECTOR_BRANCH: ${COLLECTOR_BRANCH:-unknown}", collector_compose)
        self.assertIn("MONITOR_BRANCH: ${MONITOR_BRANCH:-unknown}", monitor_compose)
        for deploy in (collector_deploy, monitor_deploy):
            self.assertIn('branch="$(git branch --show-current 2>/dev/null || true)"', deploy)
            self.assertIn("Build channel:", deploy)

        # The installer and watcher take any branch; master stays the default.
        self.assertIn('BRANCH="master"', self.installer)
        self.assertIn("install-auto-deploy.sh collector --branch dev", self.installer)
        self.assertIn("follows the %s channel, not the master release channel", self.installer)
        self.assertIn('reason="no trustworthy prior ${BRANCH} commit is available"', self.watcher)
        self.assertNotIn("prior master commit", self.watcher)

    def test_readme_describes_the_dev_test_channel(self) -> None:
        self.assertIn("## Continuous integration", self.readme)
        self.assertIn(".github/workflows/ci.yml", self.readme)
        self.assertIn("### A test channel on a second host", self.readme)
        self.assertIn("git switch dev", self.readme)
        self.assertIn("install-auto-deploy.sh collector --branch dev", self.readme)
        self.assertIn("install-auto-deploy.sh monitor --branch dev", self.readme)
        self.assertIn("/etc/battery-auto-deploy/collector.branch", self.readme)

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
