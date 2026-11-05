# 006-yt-dlp

## 本地测试

所有单元测试集中放在 `tests/`，不需要启动 Modal 云端容器：

```powershell
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

测试文件分别覆盖下载器配置、下载协议、NVIDIA 视频理解、NVIDIA 密钥读取。
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
- `vision_app.py`、`video_vision.py`：保留旧版 NVIDIA 视频分析入口，兼容原有调用。
  分析入口使用独立的 FFmpeg 轻量镜像，不再复用包含 Deno、yt-dlp、aria2 的下载镜像。
  新的独立视频分析架构位于同仓库 `007-video-understanding/`；
  007 的 Cloudflare 全流程尚未完成端到端验证，因此此处暂不删除旧入口。

根目录的 `.env` 和 `cookies.txt` 均属于本地敏感配置、已被 Git 忽略；
`.venv/`、`__pycache__/` 属于运行缓存，不需要移动进业务目录。

## NVIDIA 视频抽帧分析（独立入口）

指定模型：`nvidia/nemotron-3.5-super-vl-120b-a12b`。
使用现有 Modal Volume 中已下载的视频，通过 FFmpeg 每隔 5 秒提取一帧，
默认最多 24 帧，每 4 帧附带时间戳一起发送给 NVIDIA API。
分析结果以 `nvidia_vision.json` 保存在对应视频任务目录，不修改下载器。

先在 NVIDIA Build 创建 API Key。可以复制 `.env.example` 为 `.env`，
填入 `NVIDIA_API_KEY=你的密钥`；该文件已被 Git 忽略。
然后运行以下命令，把密钥安全写入 Modal Secret（不会把 .env 打包进镜像）：

```powershell
# 自动读取 .env 的 NVIDIA_API_KEY；没有配置时才隐藏输入
uv run python scripts/setup_nvidia_secret.py

# 先使用下载任务 manifest.json 里的 job_id
uv run python -m modal run vision_app.py --job-id "JOB_ID" --interval 5 --max-frames 24 --batch-size 4
```

Secret 名称必须是 `nvidia-api`，字段名是 `NVIDIA_API_KEY`。
请注意接口每批包含多张图，调用次数约为 `ceil(帧数 / batch_size)`。
此流程需要对 NVIDIA API 的访问权限，可能产生用量费用。

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
