# 007 - Video Understanding

与 `006-yt-dlp` **分离**，复用同一个 Modal Volume `modal-forge` 中已经下载的视频。
**本项目是唯一保留的视频理解入口**：006 的旧版 `vision_app.py`、
`video_vision.py` 及 NVIDIA Secret 配置脚本已删除。下载仍使用 006 的
`app.py`；从下载结果获取 `job_id` 后，在本目录运行 `smoke.py` 检查
抽帧，再运行 `app.py` 上传并排队。
此迁移不自动删除此前部署的 Modal App/Secret 或历史 Volume 数据，
也不自动把旧的 `nvidia_vision.json` 转换为新格式。
这是首版**按窗口运行**的低成本工作流：Modal CPU 抽帧、临时上传 R2，
Cloudflare Queues 独立限速消费、NVIDIA 视觉理解、结果保存后立即清理 JPEG。
无需把视频或图片下载到 PC2。

## 架构

1. `006-yt-dlp` 下载到 `/data/006-yt-dlp-downloads/videos/<job_id>/`。
2. `app.py` 对指定窗口按 **1 FPS** 连续抽帧，默认每次最多 100 秒、100 张图。
3. `producer.py` 将 JPEG 上传 R2 的 `temp/<job_id>/...`；每四张通过鉴权的 Worker `/enqueue` 写入 Queues。
4. Worker 串行消费每条消息、从 R2 读取四张图，调用
   `nvidia/nemotron-3.5-super-vl-120b-a12b`，保存到 `results/<job_id>/<batch_id>.json`。
5. **结果保存后立即删除**对应临时 JPEG。失败保留供重试（最多 3 次，之后进入 DLQ）。
6. Modal 完成上传后退出，不等待 NVIDIA 推理。

**边界：** 一次生产最多 50 批（200 张图）；默认 25 批（100 张图）。
这只是单次上传限制，**不是全局并发生产者的 R2 空间硬上限**；
当前需逐窗口提交下一段，防止大量未处理图片积压。
尚未实现无人值守的跨窗口自动调度或全局容量锁。

## 配置

1. 在 Cloudflare 创建 **R2 Standard** 私有 Bucket `modal-video-frames`
   （名称不同则同步更新 `worker/wrangler.jsonc` 和 `.env`）。
2. 创建两个队列：
   `modal-video-analysis` 和 `modal-video-analysis-dlq`。
3. 在 R2 Bucket 上给 `temp/` 前缀设置 **1 天后删除**生命周期规则作为兜底，
   正常消费成功时立即删除。注意：1 天规则可能在到期后约 24 小时才执行；
   如果你的队列可能积压超过一天，不要启用该规则，先解决队列积压。
4. 在 `worker` 目录执行 `npm install`，通过 `npx wrangler login` 登录，
   将 Worker Secret `NVIDIA_API_KEY` 和 `INGEST_TOKEN` 用
   `npx wrangler secret put <NAME>` 设置；两个值不能写入 `wrangler.jsonc`。
5. 执行 `npx wrangler deploy`，确认 `/health` 返回 200。
6. 从 R2 创建仅限该 Bucket 的对象读写 API Token。
   复制 `.env.example` 为 `.env`，填写 R2 凭据、Worker URL，以及与
   Worker 的 `INGEST_TOKEN` **相同**的随机长密钥。
7. 在 007 根目录执行 `uv sync`、`uv run python setup_secret.py`。
   Modal Secret 名称是 `cf-video-pipeline`；源 `.env` 已忽略于 Git。

### 首次只测试抽帧（无 R2 / NVIDIA 请求）

```powershell
uv run python -m modal run smoke.py --job-id 3631d8c342d94847a2ba4ba140cdfc28
```

### 正式产生第一小段队列任务

```powershell
uv run python -m modal run app.py --job-id 3631d8c342d94847a2ba4ba140cdfc28 --start-second 0 --max-batches 25 --batch-size 4
```

返回 `next_second` 为下次的 `--start-second`，如 `100`。
先确认 R2 JSON 已产生、临时图片被删除，再继续下一段。

### 测试

```powershell
uv run python -m unittest discover -s tests -p "test_*.py" -v
cd worker
npm test
```

Python 单元测试统一放在根目录的 `tests/` 中；Cloudflare Worker 的
JavaScript 测试保留在 `worker/test/`，分别使用对应运行时验证。

## 限速与成本

队列配置最大并发消费者 **1**、单次交付 **1** 条消息。
单条消息中请求 NVIDIA 最少间隔约 5 秒；如模型本身更慢，则下一次请求自然后移。
该方式适用于**只有此队列消费 NVIDIA** 的初版部署，不是跨账号/跨 Worker 的严格全局限速器。
后续如存在多个队列或外部调用，应引入 Durable Object 进行全局令牌控制。

Cloudflare Workers Free 的单次调用 CPU 时间限制通常为 10ms。
四张 JPEG Base64 编码可能超限，必须先以真实 Worker 进行一批端到端测试；
不能仅凭本地测试认定免费额度可用。API 调用额度、Queues 积压、
Worker CPU 时间和 R2 存储需分别监控。

NVIDIA 401/403、429、5xx 均不会触发无限重试。
出现鉴权故障时应暂停消费、修复密钥后再重放 DLQ，避免重复失败。
请勿开启 R2 对象公开访问；Consumer 直接通过绑定读取私有 R2。
