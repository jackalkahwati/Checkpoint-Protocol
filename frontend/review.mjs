// Drives the Checkpoint review UI across every page, capturing console errors,
// failed network calls, mock-mode fallbacks, and a screenshot per page.
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "http://localhost:3000";
const API = "http://localhost:8800";
const TOKEN = fs.readFileSync("/tmp/checkpoint-live/token.txt", "utf8").trim();
const SID = process.env.SID || "cs_20260622_082350_rename_parser_tokenizer_drop_blanks";
const SHOTS = "/tmp/ckpt-shots";
fs.mkdirSync(SHOTS, { recursive: true });

const routes = [
  ["01-repos", "/repos"],
  ["02-repo", "/repos/jack/demo"],
  ["03-session", `/repos/jack/demo/sessions/${SID}`],
  ["04-policy", "/repos/jack/demo/policy"],
  ["05-identities", "/repos/jack/demo/identities"],
  ["06-integrity", "/repos/jack/demo/integrity"],
  ["07-audit", "/repos/jack/demo/audit"],
];

async function launch() {
  try { return await chromium.launch(); }
  catch { return await chromium.launch({ channel: "chrome" }); }
}

const report = [];

const browser = await launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
// authenticate before any app code runs
await ctx.addInitScript(([t, b]) => {
  localStorage.setItem("checkpoint_token", t);
  localStorage.setItem("checkpoint_base_url", b);
}, [TOKEN, API]);

async function visit(name, path) {
  const page = await ctx.newPage();
  const errors = [], failures = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("response", (r) => { if (r.status() >= 400) failures.push(`${r.status()} ${r.url()}`); });
  let httpStatus = null;
  const resp = await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 20000 }).catch((e) => { errors.push("goto: " + e.message); return null; });
  if (resp) httpStatus = resp.status();
  await page.waitForTimeout(800); // let client fetches settle
  const body = await page.evaluate(() => document.body.innerText).catch(() => "");
  const mock = /mock data/i.test(body);
  const emptyish = body.trim().length < 40;
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
  report.push({ name, path, httpStatus, mock, emptyish,
    errors: errors.slice(0, 8), apiFailures: failures.filter(f => f.includes("/ui/")).slice(0, 8),
    textLen: body.trim().length });
  await page.close();
}

// 1) login page (fresh, unauthenticated context) to verify the form renders
const anon = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
{
  const page = await anon.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  await page.goto(BASE + "/login", { waitUntil: "networkidle" }).catch(() => {});
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/00-login.png`, fullPage: true });
  const body = await page.evaluate(() => document.body.innerText).catch(() => "");
  report.push({ name: "00-login", path: "/login", httpStatus: 200, mock: false,
    emptyish: body.trim().length < 40, errors, apiFailures: [], textLen: body.trim().length });
  await page.close(); await anon.close();
}

for (const [name, path] of routes) await visit(name, path);

await browser.close();
fs.writeFileSync(`${SHOTS}/report.json`, JSON.stringify(report, null, 2));
for (const r of report) {
  const flag = r.errors.length || r.apiFailures.length ? "  ⚠" : (r.mock ? "  MOCK" : (r.emptyish ? "  EMPTY?" : "  ok"));
  console.log(`${r.name.padEnd(14)} http=${r.httpStatus} len=${r.textLen}${flag}`);
  r.errors.forEach((e) => console.log("      console: " + e.slice(0, 160)));
  r.apiFailures.forEach((f) => console.log("      api:     " + f.slice(0, 160)));
}
console.log("\nscreenshots in " + SHOTS);
