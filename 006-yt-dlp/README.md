# 006-yt-dlp

下载完成后默认调用已部署的 007 `process_video`，云端执行抽帧、
Cloudflare 排队及 NVIDIA 分析。本地只发送启动指令，不中转媒体数据。
先部署 007，再部署 006；只下载不分析时添加 `--no-analyze`。
返回值中的 `analysis.status=scheduled` 表示已提交云端分析任务，
不表示所有截图已经完成分析。如果触发失败，视频仍会保存在共享 Volume，
可使用 `modal run app.py::start_analysis --job-id <job_id>` 重新触发，
无需重新下载。

## 本地测试

所有单元测试集中放在 `tests/`，不需要启动 Modal 云端容器：

```powershell
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

测试文件分别覆盖下载器配置、认证、存储路径与下载协议。
FFmpeg 相关测试仅在本机安装 FFmpeg 时运行；下载协议探测测试需要安装
`yt-dlp`（未安装时自动跳过）。本地需要验证该项时执行：

```powershell
uv run --with yt-dlp python -m unittest discover -s tests -p "test_*.py" -v
```

## 性能基准测试

性能脚本集中放在 `benchmarks/`，与 `tests/` 单元测试分开。
从项目根目录运行（会调用 Modal 云端资源）：

```powershell
uv run python -m modal run benchmarks/benchmark_1fps.py --help
uv run python -m modal run benchmarks/benchmark_ffmpeg.py --help
```

## 项目分工

- `app.py`：Modal 下载入口；`yt_downloader/`：下载、认证与 Volume 存储的业务代码。
- `tests/`：离线测试；`benchmarks/`：可选、可能产生 Modal 费用的云端性能测试。
- `scripts/`：本地 Secret 配置工具与 **仅在明确需要时执行** 的一次性 Volume 迁移脚本。
- 视频理解统一由同仓库 `007-video-understanding/` 负责；006 仅下载并保存
  视频及 `manifest.json`，不再调用 NVIDIA。两个模块通过 Modal Volume 中
  的 `job_id` 衔接，不依赖相互导入源码。

根目录可能仍有历史遗留的 `.env` 和 `cookies.txt`，均已被 Git 忽略；
`.venv/`、`__pycache__/` 属于运行缓存，不需要移动进业务目录。

## 下载完成后如何分析视频

下载命令返回 `job_id` 后，在 `../007-video-understanding/` 中运行新入口：

```powershell
cd ../007-video-understanding
uv run python -m modal run smoke.py --job-id "JOB_ID"
# 完成 Cloudflare R2、Queues、Worker 和 Modal Secret 配置并验收后：
uv run python -m modal run app.py --job-id "JOB_ID" --start-second 0 --max-batches 25 --batch-size 4
```

007 将窗口内帧上传 R2 并写入队列，由 Worker 请求 NVIDIA，分析 JSON 保存在
R2 `results/<job_id>/<batch_id>.json`；成功写入后删除临时 JPEG。
它目前是分窗口运行，不会在下载完成时自动调用；Cloudflare 生产端到端流程尚未验收。
详细配置与限制见 `../007-video-understanding/README.md`。

Download YouTube media **inside Modal cloud containers** into a persistent Modal Volume. Nothing is downloaded to the Windows workstation by default.

Three selectable transfer strategies:
- `aria2` (opt-in): yt-dlp extracts the video; aria2c handles ordinary HTTP(S) media with up to 4 simultaneous connections. DASH/HLS stays on yt-dlp's own fragment downloader. In the 2026-11-04 test its audio transfer was unusually slow, so it is not the default.
- `chunked`: yt-dlp's built-in HTTP downloader uses 8 MiB requests (sequential), useful when the server throttles large Range responses.
- `native` (default; fastest in the 2026-11-04 same-video comparison): keep yt-dlp's original HTTP behaviour without forcing a custom HTTP chunk size, with one concurrent fragment. Note that yt-dlp / the extractor may still apply its own internal chunking.

The default fragment concurrency is 1 (original behaviour). Optional aria2 connection concurrency defaults to 4. Both are capped at 8. More connections can trigger server limits; higher throughput is not guaranteed. The selected stream protocols and timestamped progress are logged without exposing media URLs or Cookie values.

### Measured selection of the default

Same YouTube video `og3AR_xu6U8`, formats 137 (135.36 MiB video) + 251 (6.86 MiB audio), two sequential Modal runs for each strategy:

| Worker total time (including extraction, remux, and Volume commit) | Run 1 | Run 2 | Average |
| --- | ---: | ---: | ---: |
| `native` **(default)** | 16.487 s | 24.954 s | **20.721 s** |
| `chunked` (forced 8 MiB) | 36.688 s | 25.678 s | 31.183 s |

Across these limited observations, `native` reduced average Worker time by 33.6% versus forced 8 MiB chunks. The first-party yt-dlp/extractor may already use bounded requests; we do not override it by default. Network/CDN conditions vary, so this ranking is not a universal speed guarantee. See `results/2026-11-04-og3AR_xu6U8-native-vs-8mib.md`.

## Names and cloud layout

- Modal application: `modal-forge-006-yt-dlp`
- Modal Volume: `modal-forge`
- Required Secret for authenticated downloads and inspection fallback: **`youtube-cookies`**
- Mount point: `/data`
- Directory inside the Volume: `006-yt-dlp-downloads/videos/<job_id>/`
- Final media files and `manifest.json` are kept in the Volume.

The Modal Volume is named **`modal-forge`**. The project directory within that Volume is **`006-yt-dlp-downloads/`**. The worker mounts the Volume at `/data`, so its final output starts with `/data/006-yt-dlp-downloads/`.

## Setup on PC2

```powershell
cd D:\a_programming_list\Ai-application\A-modal\modal-forge\006-yt-dlp
uv sync --locked
uv run python -m unittest discover -s tests -p "test_*.py" -v
uv run python -m modal run app.py --help
```

To configure authenticated downloads, export your *own* valid Netscape Cookie file locally to `cookies.txt` in this folder. The file is ignored by Git, and never included in the Modal image.

After reviewing cookie/session safety, create the named Secret from this file:

```powershell
uv run python scripts/setup_secret.py
```

This helper uses a temporary local JSON file and the Modal CLI's `--from-json` option. It removes the temporary file after creation. The actual cookies are still sensitive: Base64 is just encoding and should never be logged or committed.

## Remote commands

The following commands **run on Modal and can incur charges**. Supply a real media URL you have permission to download.

```powershell
# Public metadata; anonymous first, automatically retries using Secret on a login challenge
uv run python -m modal run app.py --url "VIDEO_URL"

# Authenticated media download, entirely in the Modal container
uv run python -m modal run app.py --url "VIDEO_URL" --download

# Optional HTTP acceleration: 4 aria2 connections + 4 DASH/HLS fragments
uv run python -m modal run app.py --url "VIDEO_URL" --download --strategy aria2 --connections 4 --fragments 4

# Optional bounded 8 MiB HTTP Range requests
uv run python -m modal run app.py --url "VIDEO_URL" --download --strategy chunked --fragments 4

# Explicitly use default (yt-dlp decides its own HTTP transfer details)
uv run python -m modal run app.py --url "VIDEO_URL" --download --strategy native --fragments 1

# Download with English subtitle availability
uv run python -m modal run app.py --url "VIDEO_URL" --download --subtitles

# View the Volume contents, no transfer to Windows
uv run python -m modal volume ls modal-forge /006-yt-dlp-downloads
```

The download response includes `job_id`, `cloud_directory`, `files`, and `volume`. Other Modal jobs can mount the same Volume to consume downloaded media.

## Operational caveats

- Cookie authentication does **not** guarantee that YouTube accepts Modal's data center IP address. A restricted site can still reject downloads.
- For the tested video, forced 8 MiB HTTP chunks were slower than the original yt-dlp behavior. aria2c multi-connection HTTP also performed poorly on the audio stream. Do not enable either by default without reproducing the benchmark.
- No GPU is requested. Container CPU, Volume usage, cloud networking, and image builds may cost money.
- No playlist download: requests use `noplaylist=True`, deliberately bounding each job to a single media item.
- Each task downloads into `.incomplete/<job_id>`, moves completed results into `videos/<job_id>`, writes `manifest.json`, and calls `volume.commit()`.
- The Volume is not a transactional database. Avoid concurrent edits to a given file and rely on unique job IDs and completion manifests.
- Cookie files should be re-exported when expired or revoked. Never publish logs with authentication content.
