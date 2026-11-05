import test from "node:test";
import assert from "node:assert/strict";
import handler, { validMessage, handleBatch } from "../src/index.js";

const message = {
  job_id: "8748ecf7da644a1884d7cd8fae692b41",
  batch_id: "00000000",
  keys: ["temp/8748ecf7da644a1884d7cd8fae692b41/00000000.jpg"],
  timestamps_s: [0],
};

test("rejects unsafe object keys", () => {
  assert.equal(validMessage(message), true);
  assert.equal(validMessage({ ...message, keys: ["../secret"] }), false);
  assert.equal(validMessage({ ...message, batch_id: "../abc" }), false);
});

function store() {
  const data = new Map([[message.keys[0], Uint8Array.from([255, 216, 255])]]);
  const state = {
    FRAMES: {
      head: async (key) => data.has(key) ? {} : null,
      get: async (key) => data.has(key) ? {
        arrayBuffer: async () => Uint8Array.from(data.get(key)).buffer,
      } : null,
      put: async (key, value) => { data.set(key, value); },
      delete: async (keys) => {
        for (const key of Array.isArray(keys) ? keys : [keys]) data.delete(key);
      },
    },
    VIDEO_QUEUE: { send: async () => {} },
    NVIDIA_MODEL: "nvidia/nemotron-3.5-super-vl-120b-a12b",
    NVIDIA_API_KEY: "fake-test-key",
    INGEST_TOKEN: "dummy",
    MIN_REQUEST_INTERVAL_MS: "0",
  };
  return { data, state };
}

test("completed batch saves JSON then deletes JPEG; retry skips NVIDIA", async () => {
  const { data, state } = store();
  let calls = 0;
  const fakeFetch = async (_url, opts) => {
    calls++;
    const payload = JSON.parse(opts.body);
    assert.equal(payload.messages[0].content[2].type, "image_url");
    return { ok: true, json: async () => ({ choices: [{ message: { content: "描述" } }] }) };
  };
  assert.equal(await handleBatch(message, state, fakeFetch), "completed");
  assert.equal(data.has(message.keys[0]), false);
  assert.equal(data.has("results/" + message.job_id + "/00000000.json"), true);
  assert.equal(await handleBatch(message, state, fakeFetch), "already-done");
  assert.equal(calls, 1);
});

test("API failure leaves JPEG for retry", async () => {
  const { data, state } = store();
  await assert.rejects(handleBatch(message, state, async () => ({ ok: false, status: 429 })));
  assert.equal(data.has(message.keys[0]), true);
});

test("ingest endpoint requires token", async () => {
  const { state } = store();
  const req = new Request("https://worker.example/enqueue", {
    method: "POST", body: JSON.stringify(message),
  });
  const res = await handler.fetch(req, state);
  assert.equal(res.status, 401);
});
