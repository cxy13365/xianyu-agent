import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(new Request("http://localhost/", { headers: { accept: "text/html" } }), {
    ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
  }, { waitUntil() {}, passThroughOnException() {} });
}

test("renders the Xianyu Agent Desk shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /Xianyu Agent Desk/);
  assert.match(html, /智能值守工作台/);
  assert.match(html, /连接闲鱼账号/);
  assert.match(html, /知识库命中/);
  assert.doesNotMatch(html, /Agent 决策轨迹|Trace #XY-094124/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/);
});
