// LuCI functional acceptance suite for the TR3000 Full firmware.
//
// This is a manual device tool, not part of the CI unit-test run. It drives a
// real browser against a flashed router and asserts the documented Full
// behaviour with an explicit PASS/FAIL result and evidence for every case.
//
//   npm i playwright            # once, anywhere on the PATH
//   TR3000_FULL_DEVICE=192.168.10.1 \
//   TR3000_FULL_LUCI_USER=root TR3000_FULL_LUCI_PASS=<password> \
//   node tests/device/luci-functional.mjs
//
// The router must use a self-signed certificate, so HTTPS errors are ignored
// on purpose. The password is only needed when the router enforces one.
import { chromium } from 'playwright';

const DEVICE = process.env.TR3000_FULL_DEVICE || '192.168.10.1';
const HOST = `https://${DEVICE}`;
const USER = process.env.TR3000_FULL_LUCI_USER || 'root';
const PASS = process.env.TR3000_FULL_LUCI_PASS || '';
const SHOTS = process.env.TR3000_FULL_SHOTS || '/tmp/tr3000-full-luci';

const results = [];
let failures = 0;

function assert(id, title, ok, evidence) {
  const status = ok ? 'PASS' : 'FAIL';
  if (!ok) failures += 1;
  results.push({ id, title, status, evidence: String(evidence ?? '') });
  console.log(`[${status}] ${id} ${title}`);
  if (evidence) console.log(`       ${String(evidence).replace(/\n/g, '\n       ').slice(0, 900)}`);
}

async function open(page, path) {
  await page.goto(`${HOST}${path}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  // LuCI renders the view asynchronously.
  await page.waitForFunction(
    () => {
      const main = document.querySelector('#maincontent') || document.body;
      return main && !/Loading view|Loading\.\.\./.test(main.innerText);
    },
    { timeout: 20000 },
  ).catch(() => {});
  await page.waitForTimeout(600);
}

async function text(page) {
  return page.evaluate(() => document.body.innerText);
}

const browser = await chromium.launch({
  headless: true,
  // Some sandboxes ship the full chromium build but not chrome-headless-shell.
  ...(process.env.CHROME_BIN ? { executablePath: process.env.CHROME_BIN } : {}),
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
  ignoreHTTPSErrors: true,
});
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();

try {
  await page.goto(`${HOST}/cgi-bin/luci/`, { waitUntil: 'domcontentloaded' });
  if (await page.locator('input[name="luci_username"]').count()) {
    await page.fill('input[name="luci_username"]', USER);
    if (PASS) await page.fill('input[name="luci_password"]', PASS);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }).catch(() => {}),
      page.click('button[type="submit"], input[type="submit"]'),
    ]);
  }
  await page.waitForTimeout(1500);

  // -------------------------------------------------------------- dashboard
  await open(page, '/cgi-bin/luci/admin/status/overview');
  let body = await text(page);
  assert('T1.1', 'LuCI dashboard loads for the administrator',
    /ImmortalWrt/.test(body) && !/Authorization Required/.test(body), body.split('\n').slice(0, 4).join(' | '));
  assert('T1.2', 'Argon theme is active',
    (await page.locator('link[href*="argon"]').count()) > 0,
    `${await page.locator('link[href*="argon"]').count()} argon stylesheet links`);
  assert('T1.3', 'the router reports a configured root password',
    !/No password set/i.test(body), body.match(/No password set[^\n]*/i)?.[0] || 'warning absent');

  // ------------------------------------------------- TR3000 Full own pages
  await open(page, '/cgi-bin/luci/admin/services/tr3000-full/services');
  body = await text(page);
  assert('T2.1', 'the TR3000 Full remote services page renders',
    /TR3000 Full remote services/i.test(body), body.split('\n').slice(0, 3).join(' | '));
  for (const service of ['WireGuard', 'Tailscale', 'HomeProxy', 'Cloudflare Tunnel']) {
    assert(`T2.2.${service}`, `service row present: ${service}`, body.includes(service), service);
  }
  assert('T2.3', 'services outside this build are marked as not included',
    /Not included in this build/.test(body), (body.match(/Not included in this build/g) || []).length + ' rows');
  assert('T2.4', 'the default-off warning is shown',
    /All remote services are disabled by default/i.test(body),
    body.match(/All remote services[^\n]*/i)?.[0] || 'missing');
  assert('T2.5', 'no legacy industrial configuration is reported',
    !/Legacy industrial configuration detected/i.test(body), 'no legacy banner');
  const buttons = await page.evaluate(() => Array.from(document.querySelectorAll('table button')).map((b) => ({
    text: b.innerText.trim(),
    disabled: b.disabled,
    attribute: b.getAttribute('disabled'),
  })));
  const actionable = buttons.filter((b) => b.disabled === false);
  assert('T2.6', 'installed services expose an actionable Enable button',
    actionable.length >= 2,
    buttons.map((b) => `${b.text}:disabled=${b.disabled}`).join(', '));
  assert('T2.7', 'services outside this build keep their button disabled',
    buttons.filter((b) => b.disabled === true).length >= 2,
    buttons.map((b) => `${b.text}:disabled=${b.disabled}`).join(', '));

  await open(page, '/cgi-bin/luci/admin/services/tr3000-full/uplinks');
  body = await text(page);
  assert('T3.1', 'the multi-uplink status page renders',
    /Multi-uplink status/i.test(body), body.split('\n').slice(0, 3).join(' | '));
  for (const name of ['wan', 'wwan', 'usbwan']) {
    assert(`T3.2.${name}`, `uplink row present: ${name}`, body.includes(name), name);
  }
  assert('T3.3', 'the management AP section is rendered',
    /Management AP/i.test(body), body.match(/Management AP[^\n]*/i)?.[0] || 'missing');

  // ------------------------------------------------------- upstream pages
  await open(page, '/cgi-bin/luci/admin/services/homeproxy');
  body = await text(page);
  assert('T4.1', 'the HomeProxy page is available',
    !/Not Found|404/i.test(body) && /HomeProxy/i.test(body), body.split('\n').slice(0, 3).join(' | '));

  await open(page, '/cgi-bin/luci/admin/services/ddns');
  body = await text(page);
  assert('T5.1', 'the Dynamic DNS page is available',
    /Dynamic DNS/i.test(body) && !/Not Found/i.test(body), body.split('\n').slice(0, 3).join(' | '));
  assert('T5.2', 'the Cloudflare provider template is listed',
    /cloudflare/i.test(body), body.match(/[^\n]*cloudflare[^\n]*/i)?.[0] || 'missing');

  await open(page, '/cgi-bin/luci/admin/vpn/cloudflared/config');
  body = await text(page);
  assert('T6.1', 'the Cloudflare Zero Trust Tunnel page is available',
    !/Not Found/i.test(body) && /cloudflare|tunnel/i.test(body), body.split('\n').slice(0, 3).join(' | '));

  await open(page, '/cgi-bin/luci/admin/status/wireguard');
  body = await text(page);
  assert('T7.1', 'the WireGuard status page is available',
    /wireguard/i.test(body) && !/Not Found/i.test(body), body.split('\n').slice(0, 3).join(' | '));

  // --------------------------------------------------------- wireless state
  await open(page, '/cgi-bin/luci/admin/network/wireless');
  body = await text(page);
  assert('T8.1', 'the wireless page is available', !/Not Found/i.test(body), body.split('\n').slice(0, 3).join(' | '));
  assert('T8.2', 'the managed TR3000-Full access point is listed',
    /TR3000-Full-[0-9A-F]{6}/.test(body), (body.match(/TR3000-Full-[0-9A-F]{6}/g) || []).join(',') || 'missing');
  assert('T8.3', 'the managed access point uses WPA2',
    /Encryption: WPA2/i.test(body), body.match(/Encryption:[^\n]*/i)?.[0] || 'missing');
  // The radio driver keeps its open default access point in the
  // configuration, but it must stay disabled.
  const openDefaults = body.match(/ImmortalWrt-[0-9.]+G/g) || [];
  const disabledMarkers = (body.match(/Wireless is disabled/g) || []).length;
  assert('T8.4', 'every open default access point is disabled',
    openDefaults.length === 0 || disabledMarkers >= openDefaults.length,
    `${openDefaults.length} default SSIDs, ${disabledMarkers} disabled markers`);

  // ------------------------------------------------------------- firewall
  await open(page, '/cgi-bin/luci/admin/network/firewall/zones');
  body = await text(page);
  assert('T9.1', 'the firewall zone page renders', !/Not Found/i.test(body), body.split('\n').slice(0, 3).join(' | '));
  assert('T9.2', 'the wg zone is visible', /\bwg\b/.test(body), body.match(/[^\n]*\bwg\b[^\n]*/)?.[0] || 'missing');
  assert('T9.3', 'no industrial plant or mgmt zone is present',
    !/\bplant\b/i.test(body), (body.match(/[^\n]*plant[^\n]*/i) || ['none'])[0]);

  // ----------------------------------------------------------------- theme
  await open(page, '/cgi-bin/luci/admin/system/system');
  const clicked = await page.evaluate(() => {
    const tab = Array.from(document.querySelectorAll('.cbi-tabmenu a, .tabs a, li a'))
      .find((a) => /Language and Style/i.test(a.textContent || ''));
    if (tab) { tab.click(); return true; }
    return false;
  });
  await page.waitForTimeout(1200);
  assert('T10.1', 'the Language and Style panel is reachable',
    clicked || /Language and Style/i.test(await text(page)), 'tab clicked: ' + clicked);
  const theme = await page.evaluate(() => {
    const el = document.querySelector('select[id*="_mediaurlbase"]');
    return el ? { value: el.value, options: Array.from(el.options).map((o) => o.value) } : null;
  });
  assert('T10.2', 'Argon is the selected theme',
    theme && theme.value === '/luci-static/argon', JSON.stringify(theme));
  assert('T10.3', 'Bootstrap stays available as a fallback',
    theme && theme.options.some((o) => o.includes('bootstrap')), JSON.stringify(theme && theme.options));

  // ------------------------------------------- theme switch round trip (F13)
  // The LuCI 24.10 system page only offers "Save", which stages the change.
  // It is committed through the "Unsaved Changes" indicator and its
  // "Apply unchecked" action. The test restores Argon afterwards.
  const switchTheme = async (value) => {
    await page.goto(`${HOST}/cgi-bin/luci/admin/system/system`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    await page.click('.cbi-tabmenu a:has-text("Language and Style"), .tabs a:has-text("Language and Style")').catch(() => {});
    await page.waitForTimeout(1000);
    await page.selectOption('select[id*="_mediaurlbase"]', value);
    await page.click('button.cbi-button-save');
    await page.waitForTimeout(5000);
    await page.click('span[data-indicator="uci-changes"]');
    await page.waitForTimeout(2500);
    const action = await page.evaluate(() => {
      const item = Array.from(document.querySelectorAll('.cbi-dropdown li'))
        .find((e) => /Apply unchecked/i.test(e.textContent || ''));
      if (item) { item.click(); return 'Apply unchecked'; }
      return null;
    });
    await page.waitForTimeout(9000);
    await page.goto(`${HOST}/cgi-bin/luci/admin/status/overview`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(2500);
    return page.evaluate(() => Array.from(document.querySelectorAll('link[rel=stylesheet]'))
      .map((l) => l.getAttribute('href')).filter((h) => h && /argon|bootstrap/.test(h)).join(','));
  };
  if (process.env.TR3000_FULL_LUCI_THEME_SWITCH === '1') {
    const bootstrapCss = await switchTheme('/luci-static/bootstrap');
    assert('T10.4', 'the theme can be switched to Bootstrap and applied',
      bootstrapCss.includes('bootstrap'), bootstrapCss);
    const argonCss = await switchTheme('/luci-static/argon');
    assert('T10.5', 'the theme can be switched back to Argon',
      argonCss.includes('argon'), argonCss);
  } else {
    console.log('[SKIP] T10.4/T10.5 theme switch (set TR3000_FULL_LUCI_THEME_SWITCH=1 to run)');
  }
} finally {
  await browser.close();
}

console.log(`\n===== LuCI functional suite: ${results.length - failures}/${results.length} passed =====`);
if (process.env.TR3000_FULL_LUCI_JSON) {
  const { writeFileSync } = await import('node:fs');
  writeFileSync(process.env.TR3000_FULL_LUCI_JSON, JSON.stringify(results, null, 2));
}
process.exit(failures ? 1 : 0);
