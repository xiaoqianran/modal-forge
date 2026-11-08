# 007-moss-image

独立 Modal 生图服务：使用 vLLM-Omni 官方版本镜像；原有 007-video-understanding 不变。

## 模型及后端
MOSS-Image **同时支持 vLLM-Omni、SGLang 和 ComfyUI**。此模块实际实现 vLLM-Omni，因为官方有明确的 MOSS Docker 镜像、单 GPU 服务命令和兼容 OpenAI 的图像生成 API。SGLang 暂未加入部署实现，必须在相同环境实测后才能选择更快者。

默认模型 `OpenMOSS-Team/MOSS-Image-SFT`，可替换 `OpenMOSS-Team/MOSS-Image-Base`。默认 GPU `RTX-PRO-6000`。镜像 `vllm/vllm-omni:v0.32.0`，运行 `vllm serve MODEL --omni --enforce-eager`。已在 RTX PRO 6000 上成功加载模型并完成 50 步推理。使用 Modal Image Builder 2026.10 和 SDK 1.6.3，直接保留官方镜像的 Python 依赖；无需手动安装兼容包。

## 部署

```powershell
cd 007-moss-image
uv sync
$env:MOSS_MODEL = "OpenMOSS-Team/MOSS-Image-SFT"
$env:MOSS_GPU = "RTX-PRO-6000"
uv run modal deploy app.py
```

Modal App 名称：`modal-forge-007-moss-image`。使用现有 Modal Volume `modal-forge` 的 `007-moss-image` 子目录缓存模型（每 60 秒尝试提交）；首次请求需要下载模型。默认 `min_containers=0`、`max_containers=2`、每容器并发 1 个请求。空闲时不常驻 GPU。API 启用 Modal Proxy Auth；需要在 Workspace 创建 Proxy Token。

## 请求

服务路径 `POST /v1/images/generations`。使用 `Modal-Key` 和 `Modal-Secret` 请求头。示例 JSON：

```json
{
  "prompt": "A red fox in a snowy forest",
  "size": "1024x1024",
  "n": 1,
  "num_inference_steps": 50,
  "guidance_scale": 3.0,
  "flow_shift": 5.0,
  "seed": 0,
  "response_format": "b64_json",
  "extra_params": {
    "uncond_skip_layers": [22],
    "slg_start": 0.01,
    "slg_stop": 1.0
  }
}
```

## 性能问题

**vLLM-Omni 和 SGLang 不保证比 ComfyUI 快。** 同一模型、精度、分辨率、步数、CFG/SLG 和 GPU 才能比较。分别记录单张 warm 延迟、并发吞吐、显存峰值、冷启动与费用。Modal 多容器并行不等于同卡动态批处理。ComfyUI 如使用低步数 LoRA 或量化，不能和原版 BF16 50 步直接比较。

官方资料：
- https://github.com/OpenMOSS/MOSS-Image
- https://recipes.vllm.ai/OpenMOSS-Team/MOSS-Image-Base
- https://docs.vllm.ai/projects/vllm-omni/en/latest/models/supported_models/
- https://github.com/sgl-project/sglang

## Image Builder 2026.10 实测（2026-11-08）

- 已在 Modal 工作区启用 Image Builder 2026.10，PC2 Modal SDK 为 1.6.3。
- 删除了 app.py 和 benchmark.py 中旧版 Builder 所需的 4 项依赖强制安装补丁；只使用官方镜像 `vllm/vllm-omni:v0.32.0`。
- 真实 GPU 测试通过：RTX PRO 6000、MOSS-Image-SFT、1024×1024、50 步、HTTP 200。
- 本轮启动至服务就绪 40.03 秒；单张请求 14.88 秒；双请求分别 14.82 秒和 29.67 秒（请求排队而非同卡并行）。
- 测试运行：https://modal.com/apps/yuqueaaa/main/ap-EDds39wS99PEai8GvLWMA6
- 不再为了 Modal 本身修改 `typing_extensions`、`protobuf`、`aiohttp`、`idna`。如上游镜像后续升级，需重新验证。

## 已完成的实测（2026-11-08）

- 设备：Modal RTX PRO 6000（Blackwell）；模型：MOSS-Image-SFT；引擎：vLLM-Omni 0.32.0。
- 生成设置：1024×1024、50 步、CFG 3、flow shift 5、固定 seed、SLG skip layer 22。
- vLLM 日志中模型加载：14.90 秒、25.34 GiB（不是生成时间）。
- 50 步单图请求：引擎记录约 14.66 秒，HTTP 200；去噪吞吐约 3.46 step/s。
- 两个 HTTP 请求已完成（各返回 200）；引擎当前 max_num_seqs=1，请求排队，尚不能说明单卡支持双任务真正同步推理。
- 这是 vLLM 的单独基线，**尚无同条件 SGLang、ComfyUI 结果，不能排名**。
- Modal 任务：https://modal.com/apps/yuqueaaa/main/ap-GrhBxvVEt2tCGV9BbSq5lo

在本目录启动独立的 GPU 端到端测试（使用 GPU 容器 localhost API，不需要公开 HTTP API）：

```powershell
uv run modal run benchmark.py
```

脚本输出完整的请求级耗时和显存信息；实测过程中模型权重缓存复用 `modal-forge` Volume。
