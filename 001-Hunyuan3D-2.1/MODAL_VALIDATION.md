# Modal 实测记录

日期：2026-10-19。

**后续版本：** 社区方案移植版 `1112a61` 已部署，33 项回归和新的端到端验证通过。
当前生成质量、原九图的拒绝结果及未解决项以 [QUALITY_IMPLEMENTATION.md](QUALITY_IMPLEMENTATION.md) 为准；下面保留 `e1ee20d` 的历史链路记录。

**质量复核更正：** 以下“通过”仅指构建、执行、文件结构和材质有效性，不能代表生成外观合格。
后续实际渲染 `outputs/t008-t016` 的 9 个模型，已确认矩形板、长方体及大量场景缺失。
这些结果不能作为生成质量已验收的证据；详见 `outputs/t008-t016/inspection/QUALITY_REVIEW.md`。

## 已完成

- Fork 修复已推送：[`e1ee20d`](https://github.com/xiaoqianran/modal-forge-Hunyuan3D-2.1/commit/e1ee20d1a543e8bbea7af237a8d97b65f2ca91f2)。包含此前的 #209 sigma 修复。
- 本地 Windows Python 3.12 CPU：19 项回归全部通过。
- Modal Linux Python 3.10：同一组 19 项回归全部通过。
- CUDA 光栅化扩展与 C++ 补洞扩展构建成功，Shape/Paint 推理导入检查成功。
- L40S 上真实图片 → Shape → Paint → PBR GLB 完成，结果持久化到 Volume 并自动下载。
- 下载后的 GLB 通过独立网格、UV、材质引用与贴图解码检查。
- 已部署：[modal-forge-hunyuan3d-2-1](https://modal.com/apps/shuhuaqaq/main/deployed/modal-forge-hunyuan3d-2-1)。这是 Modal Python 类服务，通过 CLI / Python SDK 调用。
- 部署后通过 `modal.Cls.from_name` 调用 HTTPS 图片 URL → Shape-only，50 步成功，GLB 和 JSON 下载成功。

## 完整 PBR 运行

[成功运行日志](https://modal.com/apps/shuhuaqaq/main/ap-IgCrRv5Vg3CosJQgIAHvWI)

```powershell
uv run --no-sync modal run app.py --run-gpu --image-path modal-forge-Hunyuan3D-2.1/assets/demo.png --name modal-validation --steps 50
```

参数：L40S、seed=42、Shape 50 步、Paint 6 视角、512 分辨率。

| 项目 | 实测 |
| --- | --- |
| Shape（含网格解码） | 29.59 秒 |
| Paint + PBR 导出（不含 Paint 加载） | 50.40 秒 |
| generate 方法总耗时 | 195.77 秒，含首次 Paint 下载/加载；不含镜像构建及 Shape 容器初始化 |
| Shape 原始网格 | 354,457 顶点 / 708,930 面 |
| 最终 PBR 网格 | 23,536 顶点 / 40,000 面 |
| 最终 GLB | 4,187,332 字节 |
| Albedo | 内嵌 JPEG，2048×2048 RGB |
| Metallic-Roughness | 内嵌 PNG，2048×2048 RGB，G/B 通道有有效数据 |

本地输出：

- `outputs/modal-validation_20261019-141443_42_23c6bc70.glb`
- `outputs/modal-validation_20261019-141443_42_23c6bc70.json`：运行元数据，vertices/faces 对应 Shape 原始网格。
- `outputs/modal-validation_20261019-141443_42_23c6bc70.validation.json`：独立检查，vertices/faces 对应最终 GLB。

Volume 路径：`modal-forge/001-Hunyuan3D-2.1/outputs/`。

GLB SHA256：`82c46a91a4b3e4709e87556c35f2a0ad791b7558212894fe8dd3c1722ac86acd`。

独立检查命令：

```powershell
uv run --no-project --with trimesh==4.4.7 --with numpy --with pillow --with pygltflib python tests/validate_output.py outputs/modal-validation_20261019-141443_42_23c6bc70.glb
```

## Modal 构建与运行修复

- 依赖安装禁用构建隔离，复用固定的 torch=2.5.1 / torchvision=0.20.1，避免 BasicSR 额外安装后端依赖。
- 显式配置 CC=gcc、CXX=g++、LDSHARED，解决 standalone Python 使用不存在的 clang++ 链接扩展的问题。
- 持久化缓存环境变量在构建检查后设置，避免提前创建 Volume 挂载目录导致 `cannot mount volume on non-empty path`。
- 入口固定已实测 Fork commit；接入共享前景预处理；任务文件名加入 UUID，防止重名覆盖。
- 支持本地图片、HTTPS URL、Shape-only、参数设置、Volume 保存及本地自动下载。

## 部署后的 Shape-only 验证

服务 App ID：`ap-eR8oeGPn6ZvoBZKuaebIjv`。从固定 Fork commit 的 `assets/demo.png` HTTPS 地址读取图片。
seed=42，50 步，Shape 耗时 30.93 秒，generate 总耗时 31.22 秒（容器初始化另计）。
输出 354,457 顶点 / 708,930 面，与完整流程的 Shape 阶段一致。

- `outputs/modal-shape-validation_20261019-141812_42_fcad6b1b.glb`
- `outputs/modal-shape-validation_20261019-141812_42_fcad6b1b.json`

## 验证边界

本记录证明一张官方示例图片的完整 Modal 流程可以运行，不能证明任意输入的生成质量或长时间负载稳定性。
Windows CUDA 编译、MPS/ROCm、RMBG-2.0 的地板伪影改善，以及时间嵌入参数改动的权重兼容性尚未验证。
保留预训练权重的时间嵌入行为，保留原有默认补洞算法；本次样本的整个 Paint 和导出耗时 50.40 秒，不等于 #139 的所有慢样本已被修复。
GLB 未知 chunk 兼容仅影响内存中的解析视图，不改写原始输入文件；导出的新模型不会自动保留或验证原输入的来源凭证。
