// Optional integration test: Playwright + Chromium/Edge, with synthetic telemetry only.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const staticDir = path.resolve(__dirname, "../monitor/src/battery_monitor/static");
const artifacts = path.resolve(__dirname, "../data/chart-browser-tests");
const day = new Date().toISOString().slice(0, 10);
const start = Date.parse(`${day}T00:00:00Z`) / 1000;
const selectedSavingsDay = new Date((start - 86400) * 1000).toISOString().slice(0, 10);
const power = Array.from({length:49}, (_, index) => ({
  unix:start + index * 1800, timestamp:new Date((start + index * 1800) * 1000).toISOString(),
  grid_power_w:900 * Math.cos(index / 7), battery_power_w:2500 * Math.sin(index / 9),
  solar_power_w:Math.max(0, 4200 * Math.sin((index - 12) * Math.PI / 24)),
  home_load_power_w:1500 + 350 * Math.cos(index / 3), load_power_w:400,
  battery_soc_percent:30 + index * 1.35,
}));
const energy = Array.from({length:24}, (_, index) => ({
  unix:start + index * 3600, timestamp:new Date((start + index * 3600) * 1000).toISOString(),
  period:`${day} ${String(index).padStart(2,"0")}:00`, consumption_kwh:1.8,
  solar_generation_kwh:Math.max(0, 3 * Math.sin((index-6) * Math.PI / 12)), grid_import_kwh:0.4,
}));
const live = {
  collector_status:"online", collector_error:null, monitor:{last_success_at:new Date().toISOString()},
  snapshot:{batteries:[]}, summary:{}, rack:{expected_battery_count:3,batteries:[]}, storage:{},
};
const weather = {
  status:"ok",source:"Open-Meteo",location:"King County, WA",
  observed_at:new Date().toISOString(),temperature_c:18.2,apparent_temperature_c:17.4,
  relative_humidity_percent:71,precipitation_mm:0.2,weather_code:61,
  cloud_cover_percent:83,wind_speed_kmh:8.6,is_day:true,
  solar_irradiance_w_m2:482.4,direct_normal_irradiance_w_m2:621.7,
  solar_elevation_degrees:42.4,solar_azimuth_degrees:188.2,
};
const savings = {
  currency:"USD", default_period:"month", selected_date:day,
  periods:{
    date:{solar_generation_kwh:6.4,grid_import_kwh:3.1,observed_days:1,
      estimated_savings_usd_low:1.2,estimated_savings_usd_high:1.32,
      estimated_grid_cost_usd_low:0.58,estimated_grid_cost_usd_high:0.64,
      solar_share_percent:67.4,average_savings_per_observed_day_usd_low:1.2,
      average_savings_per_observed_day_usd_high:1.32},
    today:{solar_generation_kwh:6.4,grid_import_kwh:3.1,observed_days:1,
      estimated_savings_usd_low:1.2,estimated_savings_usd_high:1.32,
      estimated_grid_cost_usd_low:0.58,estimated_grid_cost_usd_high:0.64,
      solar_share_percent:67.4,average_savings_per_observed_day_usd_low:1.2,
      average_savings_per_observed_day_usd_high:1.32},
    month:{solar_generation_kwh:642.8,grid_import_kwh:184.2,observed_days:13,
      estimated_savings_usd_low:120.5,estimated_savings_usd_high:133,
      estimated_grid_cost_usd_low:34.53,estimated_grid_cost_usd_high:38.11,
      solar_share_percent:77.7,average_savings_per_observed_day_usd_low:9.27,
      average_savings_per_observed_day_usd_high:10.23},
    year:{solar_generation_kwh:6240,grid_import_kwh:2810,observed_days:255,
      estimated_savings_usd_low:1169.78,estimated_savings_usd_high:1290.94,
      estimated_grid_cost_usd_low:526.78,estimated_grid_cost_usd_high:581.39,
      solar_share_percent:69,average_savings_per_observed_day_usd_low:4.59,
      average_savings_per_observed_day_usd_high:5.06},
    retained:{solar_generation_kwh:16240,grid_import_kwh:7210,observed_days:730,
      estimated_savings_usd_low:3044.03,estimated_savings_usd_high:3359.77,
      estimated_grid_cost_usd_low:1351.62,estimated_grid_cost_usd_high:1491.62,
      solar_share_percent:69.3,average_savings_per_observed_day_usd_low:4.17,
      average_savings_per_observed_day_usd_high:4.6},
  },
  tariff:{provider:"Puget Sound Energy",schedule:"Residential Schedule 7",region:"King County, WA",
    effective_date:"2026-05-01",tier_1_limit_kwh:600,basic_charge_usd:7.49,
    municipal_tax_percent:0,effective_rate_low_usd_per_kwh:0.187465,
    effective_rate_high_usd_per_kwh:0.206882},
};
const types = {".html":"text/html", ".js":"text/javascript", ".css":"text/css", ".svg":"image/svg+xml", ".png":"image/png"};
const server = http.createServer((request, response) => {
  const url = new URL(request.url, "http://localhost");
  let body;
  let type = "application/json";
  if (url.pathname === "/api/live") body = JSON.stringify(live);
  else if (url.pathname === "/api/weather") body = JSON.stringify(weather);
  else if (url.pathname === "/api/power-history") body = JSON.stringify({points:power,
    selected_date:day,window_start_unix:start,window_end_unix:start+86400,bucket_seconds:1800});
  else if (url.pathname === "/api/energy") body = JSON.stringify({points:energy,
    selected_date:day,selected_period:day,window_start_unix:start,window_end_unix:start+86400});
  else if (url.pathname === "/api/savings") body = JSON.stringify({
    ...savings,
    selected_date:url.searchParams.get("date") || day,
  });
  else if (url.pathname.startsWith("/api/")) body = "{}";
  else {
    const relative = url.pathname === "/" ? "index.html" : url.pathname.replace(/^\/static\//, "");
    const file = path.resolve(staticDir, relative);
    if (!file.startsWith(staticDir + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      response.writeHead(404); response.end(); return;
    }
    body = fs.readFileSync(file);
    if (file.endsWith("index.html")) body = body.toString().replaceAll("__BUILD_COMMIT__", "chart-test");
    type = types[path.extname(file)] || "application/octet-stream";
  }
  response.writeHead(200, {"Content-Type":type,"Cache-Control":"no-store"});
  response.end(body);
});

async function tapChart(page, id) {
  const canvas = page.locator(`#${id}`);
  await canvas.scrollIntoViewIfNeeded();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const box = await canvas.boundingBox();
  const clip = id === "energyHistoryChart" ? await page.locator("#energyChartScroll").boundingBox() : box;
  const left = Math.max(box.x, clip.x, 0);
  const right = Math.min(box.x + box.width, clip.x + clip.width, page.viewportSize().width);
  await page.touchscreen.tap(left + (right - left) * 0.6, box.y + box.height - 48);
}

async function closeReadout(page, id) {
  const button = page.locator(`#${id} [data-dismiss-chart]`);
  const box = await button.boundingBox();
  const center = {x:box.x + box.width / 2, y:box.y + box.height / 2};
  assert.ok(await button.evaluate(el => {
    const rect = el.getBoundingClientRect();
    return document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2)?.closest("[data-dismiss-chart]");
  }),
    `${id}: close button must be reachable`);
  await page.touchscreen.tap(center.x, center.y);
}

(async () => {
  fs.mkdirSync(artifacts, {recursive:true});
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({headless:true, ...(process.env.BROWSER_CHANNEL ? {channel:process.env.BROWSER_CHANNEL} : {})});
  try {
    for (const width of [320, 390, 480, 600, 768, 1024, 1440]) {
      for (const theme of ["light", "dark"]) {
        for (const language of ["en", "vi"]) {
          const mobile = width <= 480;
          const context = await browser.newContext({viewport:{width,height:900}, hasTouch:mobile,
            isMobile:mobile, deviceScaleFactor:2, timezoneId:"UTC", reducedMotion:"reduce"});
          const page = await context.newPage();
          const errors = [];
          page.on("pageerror", error => errors.push(error.message));
          await page.addInitScript(({theme,language}) => {
            localStorage.setItem("battery-monitor-theme", theme);
            localStorage.setItem("battery-monitor-language", language);
          }, {theme,language});
          await page.goto(`http://127.0.0.1:${server.address().port}/`);
          await page.waitForFunction(() => document.querySelector('#historyChart').dataset.socScale === '0-100');
          await page.waitForFunction(() => document.querySelector('#savingsEstimate').textContent !== '--');
          await page.waitForFunction(() => document.querySelector('#energyWeatherTemperature').textContent !== '--');
          const energyFlowLayout = await page.locator("#energyFlowLeaders").evaluate(svg => {
              const sectionRect = svg.closest("#energyFlowSection").getBoundingClientRect();
              const copyRect = svg.closest("#energyFlowSection")
                .querySelector(".energy-flow__copy").getBoundingClientRect();
              const callouts = [...svg.closest("#energyFlowSection").querySelectorAll(".energy-flow__callout")]
                .map(element => {
                  const rect = element.getBoundingClientRect();
                  return {
                    name:[...element.classList].find(name => name.startsWith("energy-flow__callout--")
                      && name !== "energy-flow__callout--bottom").replace("energy-flow__callout--", ""),
                    left:rect.left - sectionRect.left,
                    right:rect.right - sectionRect.left,
                    top:rect.top - sectionRect.top,
                    bottom:rect.bottom - sectionRect.top,
                  };
                });
              const leaders = [...svg.querySelectorAll("line")].map(line => {
                const x1 = Number(line.getAttribute("x1"));
                const y1 = Number(line.getAttribute("y1"));
                const x2 = Number(line.getAttribute("x2"));
                const y2 = Number(line.getAttribute("y2"));
                return {
                  name:line.dataset.target,
                  length:Math.hypot(x2 - x1, y2 - y1),
                };
              });
              return {
                width:sectionRect.width,
                height:sectionRect.height,
                dividerBottom:copyRect.bottom - sectionRect.top,
                callouts,
                leaders,
              };
          });
          for (const callout of energyFlowLayout.callouts) {
            assert.ok(callout.left >= -1 && callout.right <= energyFlowLayout.width + 1
                && callout.top >= -1 && callout.bottom <= energyFlowLayout.height + 1,
              `${width} ${theme} ${language}: ${callout.name} callout is outside the scene`);
          }
          for (let index = 0; index < energyFlowLayout.callouts.length; index += 1) {
            for (let other = index + 1; other < energyFlowLayout.callouts.length; other += 1) {
              const a = energyFlowLayout.callouts[index];
              const b = energyFlowLayout.callouts[other];
              const overlap = a.left < b.right - 1 && a.right > b.left + 1
                && a.top < b.bottom - 1 && a.bottom > b.top + 1;
              assert.equal(overlap, false,
                `${width} ${theme} ${language}: ${a.name} and ${b.name} callouts overlap`);
            }
          }
          const topCallouts = energyFlowLayout.callouts
            .filter(callout => ["inverter", "solar", "grid"].includes(callout.name));
          const dividerClearance = Math.min(...topCallouts.map(callout => callout.top))
            - energyFlowLayout.dividerBottom;
          assert.ok(dividerClearance >= 12,
            `${width} ${theme} ${language}: title divider crosses the top callouts (${Math.round(dividerClearance)}px)`);
          if (width <= 480) {
            const lengths = energyFlowLayout.leaders.map(leader => leader.length);
            assert.equal(lengths.length, 6, `${width} ${theme} ${language}: missing energy leader`);
            assert.ok(Math.max(...lengths) <= 175,
              `${width} ${theme} ${language}: energy leader is too long (${energyFlowLayout.leaders
                .map(leader => `${leader.name}:${Math.round(leader.length)}`).join(", ")})`);
            assert.ok(Math.max(...lengths) / Math.min(...lengths) <= 2.6,
              `${width} ${theme} ${language}: energy leaders are visually unbalanced (${energyFlowLayout.leaders
                .map(leader => `${leader.name}:${Math.round(leader.length)}`).join(", ")})`);
            const bottomGap = energyFlowLayout.height
              - Math.max(...energyFlowLayout.callouts.map(callout => callout.bottom));
            assert.ok(bottomGap >= 16 && bottomGap <= 80,
              `${width} ${theme} ${language}: mobile energy footer gap is ${Math.round(bottomGap)}px`);
          }
          assert.equal(await page.locator("#energyWeather").getAttribute("data-kind"), "rain");
          assert.notEqual(await page.locator("#energyWeatherDetails").innerText(), "");
          assert.match(await page.locator("#energyWeatherSolar").innerText(), /W\/m²/);
          const weatherBounds = await page.locator("#energyWeather").evaluate(element => {
            const weatherRect = element.getBoundingClientRect();
            const sectionRect = element.closest("#energyFlowSection").getBoundingClientRect();
            const topCallouts = [
              ".energy-flow__callout--inverter",
              ".energy-flow__callout--solar",
              ".energy-flow__callout--grid",
            ].map(selector => sectionRect.top
              + element.closest("#energyFlowSection").querySelector(selector).offsetTop);
            return {
              inside: weatherRect.left >= sectionRect.left - 1
                && weatherRect.right <= sectionRect.right + 1
                && weatherRect.top >= sectionRect.top - 1
                && weatherRect.bottom <= sectionRect.bottom + 1,
              overflow: element.scrollWidth > element.clientWidth + 1,
              height: weatherRect.height,
              paddingLeft: getComputedStyle(element).paddingLeft,
              paddingRight: getComputedStyle(element).paddingRight,
              calloutClearance: Math.min(...topCallouts) - weatherRect.bottom,
              background: getComputedStyle(element).backgroundColor,
            };
          });
          assert.equal(weatherBounds.inside, true, `${width} ${theme} ${language}: weather outside scene`);
          assert.equal(weatherBounds.overflow, false, `${width} ${theme} ${language}: weather overflow`);
          assert.ok(weatherBounds.calloutClearance >= 12,
            `${width} ${theme} ${language}: weather too close to power callouts`);
          if (width <= 390) {
            assert.equal(weatherBounds.background, "rgba(0, 0, 0, 0)",
              `${width} ${theme} ${language}: mobile weather should blend into scene`);
            assert.ok(weatherBounds.height <= 90,
              `${width} ${theme} ${language}: mobile weather is too tall (${Math.round(weatherBounds.height)}px)`);
            assert.equal(weatherBounds.paddingLeft, "0px",
              `${width} ${theme} ${language}: mobile weather left padding`);
            assert.equal(weatherBounds.paddingRight, "0px",
              `${width} ${theme} ${language}: mobile weather right padding`);
          }
          if ([320, 390, 480, 600, 1440].includes(width) && theme === "light" && language === "en") {
            await page.locator("#energyFlowSection").screenshot({
              path:path.join(artifacts,`weather-${width}-${theme}-${language}.png`),
            });
          }
          const chart = page.locator("#historyChart");
          await chart.scrollIntoViewIfNeeded();
          await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
          assert.match(await page.locator("#savingsEstimate").innerText(), /\$/);
          await page.locator('[data-savings-period="year"]').click();
          assert.match(await page.locator("#savingsEstimate").innerText(), /1[,.]1|1[,.]2/);
          await page.locator('[data-savings-period="date"]').click();
          const selectedSavingsResponse = page.waitForResponse(response => {
            const responseUrl = new URL(response.url());
            return responseUrl.pathname === "/api/savings"
              && responseUrl.searchParams.get("date") === selectedSavingsDay;
          });
          await page.locator("#savingsDateInput").fill(selectedSavingsDay);
          await selectedSavingsResponse;
          assert.equal(await page.locator("#savingsDateControl").isVisible(), true);
          assert.equal(await page.locator("#savingsDateInput").inputValue(), selectedSavingsDay);
          assert.notEqual(await page.locator("#savingsPeriodLabel").innerText(), "");
          const savingsLayout = await page.locator("#energySavingsSection").evaluate(section => {
            const sectionRect = section.getBoundingClientRect();
            const clipped = [...section.querySelectorAll("*")]
              .filter(element => {
                const style = getComputedStyle(element);
                if (style.display === "none" || style.visibility === "hidden") return false;
                const rect = element.getBoundingClientRect();
                return rect.width > 0 && (
                  rect.left < sectionRect.left - 1 || rect.right > sectionRect.right + 1
                );
              })
              .map(element => element.id || element.className || element.tagName);
            return {
              clipped,
              horizontalOverflow: section.scrollWidth > section.clientWidth + 1,
            };
          });
          assert.deepEqual(savingsLayout.clipped, [], `${width} ${theme} ${language}: savings content clipped`);
          assert.equal(savingsLayout.horizontalOverflow, false, `${width} ${theme} ${language}: savings overflow`);
          await page.locator("#energySavingsSection").screenshot({path:path.join(artifacts,`savings-${width}-${theme}-${language}.png`)});
          assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
          assert.equal(await chart.evaluate(canvas => {
            const data = canvas.getContext("2d").getImageData(0,0,canvas.width,canvas.height).data;
            return data.some((value,index) => index % 4 === 3 && value > 0);
          }), true);
          if (mobile) {
            await tapChart(page, "historyChart");
          } else {
            await chart.scrollIntoViewIfNeeded();
            await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
            const box = await chart.boundingBox();
            await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
          }
          await page.locator("#chartTooltip").waitFor({state:"visible"});
          assert.match(await page.locator("#chartTooltipContent").innerText(), /%/);
          // Element screenshots can scroll a tall section, intentionally dismissing the readout.
          await page.screenshot({path:path.join(artifacts,`power-${width}-${theme}-${language}.png`)});
          const tooltipBox = await page.locator("#chartTooltip").boundingBox();
          assert.ok(tooltipBox.x >= 0 && tooltipBox.x + tooltipBox.width <= width);
          const overflow = await page.locator("#chartTooltip").evaluate(element => element.scrollWidth > element.clientWidth);
          assert.equal(overflow, false, `${width} ${theme} ${language}: readout overflow`);
          if (mobile) {
            await closeReadout(page, "chartTooltip");
            await page.locator("#chartTooltip").waitFor({state:"hidden"});
            await tapChart(page, "historyChart");
            await page.locator("#chartTooltip").waitFor({state:"visible"});
            await tapChart(page, "historyChart");
            await page.locator("#chartTooltip").waitFor({state:"hidden"});
            await tapChart(page, "historyChart");
            await page.locator("#chartTooltip").waitFor({state:"visible"});
            await page.locator("#chartTitle").tap();
            await page.locator("#chartTooltip").waitFor({state:"hidden"});
            await tapChart(page, "historyChart");
            await page.evaluate(() => window.scrollBy(0, 80));
            await page.locator("#chartTooltip").waitFor({state:"hidden"});
            await page.locator('[data-energy-view="date"]').click();
            await page.waitForFunction(() => state.energyView === "date" && state.energyChartGeometry?.points.length > 0);
            await tapChart(page, "energyHistoryChart");
            await page.locator("#energyHistoryTooltip").waitFor({state:"visible"});
            await closeReadout(page, "energyHistoryTooltip");
            await page.locator("#energyHistoryTooltip").waitFor({state:"hidden"});
            // Run the native swipe last so momentum doesn't affect later tap assertions.
            await chart.scrollIntoViewIfNeeded();
            const box = await chart.boundingBox();
            const cdp = await context.newCDPSession(page);
            await cdp.send("Input.dispatchTouchEvent", {type:"touchStart",touchPoints:[{x:box.x+120,y:box.y+240}]});
            await cdp.send("Input.dispatchTouchEvent", {type:"touchMove",touchPoints:[{x:box.x+120,y:box.y+160}]});
            await cdp.send("Input.dispatchTouchEvent", {type:"touchEnd",touchPoints:[]});
            await cdp.detach();
            await page.locator("#chartTooltip").waitFor({state:"hidden"});
          } else {
            await page.keyboard.press("Escape");
            await page.locator("#chartTooltip").waitFor({state:"hidden"});
            await chart.focus();
            await page.keyboard.press("ArrowRight");
            await page.locator("#chartTooltip").waitFor({state:"visible"});
            await page.keyboard.press("Tab");
            assert.equal(await page.locator("#chartTooltip [data-dismiss-chart]").evaluate(el => el === document.activeElement), true);
            await page.keyboard.press("Enter");
            await page.locator("#chartTooltip").waitFor({state:"hidden"});
          }
          assert.deepEqual(errors, []);
          console.log(`PASS ${width}px ${theme} ${language}`);
          await context.close();
        }
      }
    }
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
