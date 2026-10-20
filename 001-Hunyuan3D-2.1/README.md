# Hunyuan3D-2.1 on Modal

`app.py` 从 GitHub 拉取固定版本的修复版 Fork，在 Modal L40S 上执行图片 → Shape → Paint → PBR GLB。
模型缓存和结果保存在 `modal-forge` Volume；生成后自动下载报告、条件图、遮罩、全部原始 Shape 和多角度预览到本地 `outputs/`，通过几何检查才生成最终 GLB。

## 运行

在本目录执行。Windows PowerShell 建议先设置 UTF-8，避免 Modal CLI 输出触发 GBK 编码错误：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
uv sync
uv run --no-sync modal run app.py --run-gpu --image-path .\input.png
```

也可使用 HTTPS 图片地址：

```powershell
uv run --no-sync modal run app.py --run-gpu --image-url "https://example.com/input.png" --name my-model --seed 42 --steps 50
```

仅生成形状：

```powershell
uv run --no-sync modal run app.py --run-gpu --image-path .\input.png --no-paint
```

可选参数：`--views 6`（6–9）、`--resolution 512`（512 或 768）、`--output-dir outputs`。
必须已有 Modal 登录配置；未指定 `--run-gpu` 时只打印用法，不调用生成方法。
首次镜像构建、CUDA 编译及模型下载较慢，后续运行复用镜像与模型缓存。

## 质量模式

建议先跑三个 Shape 候选；只有通过几何检查且轮廓得分最高的一份进入 Paint：

```powershell
uv run --no-sync modal run app.py --run-gpu --image-path .\input.png --shape-candidates 3
```

默认一个候选，可设置 1–4 个。每个候选增加一次 Shape 推理，Paint 只运行一次。输入前景几乎消失、网格含非有限值、疑似纯方盒或薄板时会返回 `status="rejected"`，保存诊断文件并停止 Paint。`completed` 仅表示通过当前启发式检查；仍需查看 `candidate-N/shape-preview.png`，它不能保证人物完整、身份准确或背面正确。

默认最高轮廓 IoU 至少 0.75，可用 `--min-silhouette-iou` 调整。摄影视角不在当前四个比较方向时可能误拒；降低阈值不会改善几何。旋转方盒/薄板也会检测，不仅检查坐标轴对齐的面。

如果主体本来就是盒子或薄板，分别使用 `--allow-box-like`、`--allow-flat`。自动抠图保留面积默认至少 1%，特殊细小主体可用 `--min-foreground 0.001` 调整，但完全空白仍拒绝。

指定人工 mask（白色保留、黑色去除，尺寸与 EXIF 校正后的原图一致）：

```powershell
uv run --no-sync modal run app.py --run-gpu --image-path .\input.jpg --mask-path .\mask.png --shape-candidates 3
```

可选 `--background rmbg2` 使用 RMBG-2.0，`--background none` 保留整图。RMBG-2.0 需要模型访问权限；CLI 自动将现有 `HF_TOKEN` 作为 Modal Secret 传入，也可指定 `--hf-secret your-secret-name`。失败会明确报错，不自动换回 rembg。已有透明背景的输入保持原 alpha。

## SAM3 指定主体

SAM3 使用独立 Python 3.12 / PyTorch 2.7 / CUDA 12.6 镜像，避免改坏 Shape/Paint 的依赖。先获得 `facebook/sam3` 权限，并通过 `HF_TOKEN` 或 `--hf-secret` 提供凭证：

```powershell
uv run --no-sync modal run segment.py --run-gpu --image-path .\photo.jpg --subject "glass of orange juice" --output-dir masks
uv run --no-sync modal run app.py --run-gpu --image-path .\photo.jpg --mask-path .\masks\mask.png --shape-candidates 3
```

先检查 `masks/foreground.png` 是否选对目标。无匹配会停止，不会返回全白遮罩。复杂房间、街景中选择单一物体；此功能不把单物体模型变成完整场景重建模型。

## 多视角与精度诊断

同一物体的规范前/左/后/右照片使用独立的 2mv 权重，默认 2.1 单图权重不接受额外视图：

```powershell
uv run --no-sync modal run app.py --run-gpu --shape-backend 2mv --image-path front.png --left-path left.png --back-path back.png --right-path right.png --no-paint
```

2mv 支持 1–4 张规范视图；只有正面也可以作为不同 Shape 权重的对照，此时没有额外视角约束。每张图都须有合格主体，透明 PNG 最容易核查。合成或镜像视图不能冒充真实拍摄。2mv 与 2.1 的几何质量需分别验收，接口可用不代表效果更好。

默认使用 FP16 与按 dtype 调整的归一化 epsilon。`--precision bf16` 做整条 Shape 精度对照；`--attention-precision fp32` 仅将 2.1 attention 按 head 提升为 FP32 计算，速度更慢，属于诊断选项。t009 已测的 epsilon/BF16 对照仍是方盒，不应据此宣称已修好。

## 输出与版本

- GLB 内含 Albedo 与 Metallic-Roughness 材质纹理。
- 每次运行保存独立目录：`source.png`、`foreground.png`、`mask.png`、棋盘格前景预览、实际 `condition.png` / `condition-mask.png`、候选网格与四视图、`report.json`。成功时增加 `output.glb`。
- 报告包含所有候选 seed、采样极值、几何指标、轮廓评分、选择结果、拒绝原因、精度与 Fork commit。
- SDK 返回 `status` 为 `completed` / `rejected` / `failed`，失败或拒绝时 `path=None`，可根据 `artifacts` 下载诊断。旧调用方需要处理这一返回约定。
- GPU 容器闲置 60 秒后释放；模型缓存保留在 Volume。
- 当前 Fork 固定版本以 `app.py` 的 `FORK_COMMIT` 为准，更新 Fork 后需显式更新该值。
- `BUILD_COMMIT` 固定原生依赖的构建版本；运行版在编译后检出。原生代码或依赖变化时 diff 检查会拒绝复用旧构建，须更新 `BUILD_COMMIT` 重建。

运行证据与已知限制见 `MODAL_VALIDATION.md`；审查来源见 `UPSTREAM_AUDIT.md`。
本轮社区方案移植、九图回归及未解决项见 [QUALITY_IMPLEMENTATION.md](QUALITY_IMPLEMENTATION.md)。

## 调用已部署的服务

服务已部署到当前 Modal workspace，名称为 `modal-forge-hunyuan3d-2-1`。
CLI 的 `modal run` 会创建独立运行；需要复用已部署服务时使用 Python SDK：

```python
import modal

service = modal.Cls.from_name("modal-forge-hunyuan3d-2-1", "Hunyuan3D")()
result = service.generate.remote(
    image_url="https://example.com/input.png",
    paint=True, steps=50, seed=42, views=6, resolution=512,
)
print(result)  # 包含 Volume 结果路径
```

也可传 `image_bytes=Path("input.png").read_bytes()` 上传本地图片，此时不传 `image_url`。
人工 mask 对应 `mask_bytes`；多视图对应 `shape_backend="2mv"`、`view_bytes={"left": ..., "back": ...}`。
SDK 使用受限 RMBG-2.0 权重时，应通过 `service` 类的 `with_options(secrets=[...])` 配置 `HF_TOKEN`。
