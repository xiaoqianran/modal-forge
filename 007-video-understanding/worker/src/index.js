// Private ingest endpoint and rate-limited NVIDIA queue consumer.
// Bind R2, Queue, NVIDIA_API_KEY and INGEST_TOKEN via Wrangler.

const NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions";
const ID = /^[a-zA-Z0-9_-]{8,80}$/;
const BATCH = /^[0-9]{8}$/;

function resultKey(jobId, batchId) {
  return `results/${jobId}/${batchId}.json`;
}

function validMessage(message) {
  if (!message || typeof message !== "object" ||
      !ID.test(message.job_id || "") || !BATCH.test(message.batch_id || "") ||
      !Array.isArray(message.keys) || !Array.isArray(message.timestamps_s) ||
      message.keys.length < 1 || message.keys.length > 8 ||
      message.keys.length !== message.timestamps_s.length) {
    return false;
  }
  const offset = Number(message.batch_id);
  return message.keys.every((key, index) =>
    key === `temp/${message.job_id}/${String(offset + index).padStart(8, "0")}.jpg` &&
    message.timestamps_s[index] === offset + index
  );
}

function base64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

async function handleBatch(message, env, fetcher = fetch, sleep = delay) {
  if (!validMessage(message)) throw new Error("Invalid queue message");
  const output = resultKey(message.job_id, message.batch_id);
  // Idempotency: results are written before input cleanup. Retries skip inference.
  if (await env.FRAMES.head(output)) {
    await env.FRAMES.delete(message.keys);
    return "already-done";
  }
  const content = [{
    type: "text",
    text: "请按时间顺序用简体中文分析每张图片的场景、人物、动作、字幕、镜头变化，再给出可能的AI视频生成提示词。区分真实观察与推测，不要声称恢复了原始提示词。",
  }];
  for (let i = 0; i < message.keys.length; i++) {
    const object = await env.FRAMES.get(message.keys[i]);
    if (!object) throw new Error("Missing source frame; check R2 TTL and retry policy");
    const bytes = new Uint8Array(await object.arrayBuffer());
    content.push({ type: "text", text: `视频时间：${message.timestamps_s[i]} 秒` });
    content.push({
      type: "image_url",
      image_url: { url: "data:image/jpeg;base64," + base64(bytes) },
    });
  }
  const start = Date.now();
  let response;
  try {
    response = await fetcher(NVIDIA_URL, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.NVIDIA_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: env.NVIDIA_MODEL || "nvidia/nemotron-3.5-super-vl-120b-a12b",
        messages: [{ role: "user", content }],
        max_tokens: 1800,
        reasoning_effort: "none",
        stream: false,
      }),
    });
    if (!response.ok) {
      const code = response.status;
      // Do not log response body: providers sometimes echo request metadata.
      if (code === 401 || code === 403) {
        throw new Error(`NVIDIA authorization failed HTTP ${code}; stop/inspect queue`);
      }
      throw new Error(`NVIDIA request failed HTTP ${code}`);
    }
    const result = await response.json();
    const description = result?.choices?.[0]?.message?.content;
    if (typeof description !== "string" || !description.trim()) {
      throw new Error("NVIDIA response has no usable message.content");
    }
    await env.FRAMES.put(output, JSON.stringify({
      job_id: message.job_id,
      batch_id: message.batch_id,
      timestamps_s: message.timestamps_s,
      model: env.NVIDIA_MODEL || "nvidia/nemotron-3.5-super-vl-120b-a12b",
      description,
      analyzed_at: new Date().toISOString(),
    }), { httpMetadata: { contentType: "application/json" } });
    await env.FRAMES.delete(message.keys);
    return "completed";
  } finally {
    // One consumer at a time, one message per invocation. Enforce spacing
    // between request starts, not just queue throughput; no fixed sleep after slow API calls.
    const minimum = Number(env.MIN_REQUEST_INTERVAL_MS || 5000);
    const elapsed = Date.now() - start;
    if (Number.isFinite(minimum) && minimum > elapsed) {
      await sleep(Math.min(60000, minimum - elapsed));
    }
  }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return new Response("ok", { status: 200 });
    }
    if (url.pathname !== "/enqueue" || request.method !== "POST") {
      return new Response("not found", { status: 404 });
    }
    if (!env.INGEST_TOKEN ||
        request.headers.get("authorization") !== `Bearer ${env.INGEST_TOKEN}`) {
      return new Response("unauthorized", { status: 401 });
    }
    let message;
    try {
      message = await request.json();
    } catch {
      return new Response("invalid json", { status: 400 });
    }
    if (!validMessage(message)) return new Response("invalid batch", { status: 400 });
    if (await env.FRAMES.head(resultKey(message.job_id, message.batch_id))) {
      await env.FRAMES.delete(message.keys);
      return new Response("already processed", { status: 202 });
    }
    // Producer has uploaded all frames before sending the batch.
    for (const key of message.keys) {
      if (!(await env.FRAMES.head(key))) return new Response("missing frame", { status: 409 });
    }
    await env.VIDEO_QUEUE.send(message);
    return new Response("queued", { status: 202 });
  },

  async queue(batch, env) {
    for (const item of batch.messages) {
      try {
        await handleBatch(item.body, env);
        item.ack();
      } catch (error) {
        // Failed messages are retried with delay and eventually sent to DLQ.
        console.error("Video batch failed:", String(error.message || error));
        item.retry({ delaySeconds: 60 });
      }
    }
  },
};

export { validMessage, resultKey, handleBatch };
