// Regression test for the markdown renderer in web/index.html.
//
// md() walks lines with a manual index. Any branch that can decline a line
// without advancing that index is an infinite loop on the main thread, which
// locks the browser tab: Chrome offers "wait or exit" and the tab has to be
// killed. That happened on 2026-08-20. A line starting with a pipe whose next
// line is not a table separator fell past the table branch, matched nothing
// else, and was then refused by the paragraph branch on its first test, so the
// index never moved. Streaming made it near certain, because every table is a
// header row with no separator row yet for as long as the next line takes to
// arrive.
//
// The renderer is lifted out of the page and run here rather than reimplemented,
// so this tests the shipping code and not a copy of it. Every case must return;
// a hang shows up as this process never exiting, so run it under a timeout.
//
// Usage:
//   node tools/md_hang_test.mjs
//
// The server selftest carries a cheaper text-level version of this check, for
// the case where node is not installed. This is the one that actually executes.

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const page = path.join(here, "..", "hiveframe", "web", "index.html");
const html = fs.readFileSync(page, "utf8");

// Pull a named function out of the page by matching braces from its opening.
function grab(name) {
    const at = html.indexOf("function " + name + "(");
    if (at < 0) throw new Error("not found in index.html: " + name);
    let depth = 0, started = false, i = at;
    for (; i < html.length; i++) {
        if (html[i] === "{") { depth++; started = true; }
        else if (html[i] === "}") { depth--; if (started && depth === 0) { i++; break; } }
    }
    return html.slice(at, i);
}

const esc = s => String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const md = new Function("esc", grab("md") + "; return md;")(esc);

// Each case is text that must render and return. The pipe cases are the ones
// that hung; the rest are here so a fix that stops the hang by breaking normal
// rendering still fails.
const cases = [
    ["bare pipe line, no separator", "hello\n| Project | Score\nworld", null],
    ["streaming: header only", "| Project | Score |", null],
    ["streaming: header and partial rule", "| Project | Score |\n| ---", null],
    ["complete table still renders", "| A | B |\n|---|---|\n| 1 | 2 |", "<table>"],
    ["pipe inside prose", "use a | b to pipe", null],
    ["trailing pipe at end of input", "text\n|", null],
    ["heading, paragraph, list", "# Head\n\npara one\n\n- a\n- b", "<li>a</li>"],
    ["fenced code", "```\n| not a table |\n```", "<pre><code>"],
];

let failed = 0;
for (const [name, src, expect] of cases) {
    const t0 = Date.now();
    const out = md(src);
    const ms = Date.now() - t0;
    const bad = expect && !out.includes(expect);
    if (bad) failed++;
    console.log(`${String(ms).padStart(5)}ms  ${bad ? "FAIL" : "ok  "}  ${name}`);
    if (bad) console.log(`         expected to contain ${expect}\n         got ${out.slice(0, 120)}`);
}

if (failed) {
    console.log(`FAIL: ${failed} case(s) rendered wrongly`);
    process.exit(1);
}
console.log(`all ${cases.length} cases returned; md() cannot hang on these inputs`);
