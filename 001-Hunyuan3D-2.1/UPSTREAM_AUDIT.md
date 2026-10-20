# 官方 PR / Issue 与 Fork 对照

核查日期：2026-10-19。Fork 基线：`68fe8e704e9bfdeba7d60b12639c118d9ba81979`。

通过 GitHub API 拉取官方 134 个开放 Issue、23 个开放 PR，以及 28 个关闭 PR 的元数据。
重点检查推理、纹理、安装及模型兼容性相关报告；这不是对所有 Issue 的完整复现。
本次仅调查，未修改 Fork 推理代码、提交合并或启动付费 GPU。

## 优先处理

| 优先级 | 上游来源 | Fork 状态与证据 | 建议 |
| --- | --- | --- | --- |
| 高 | [#195](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/195)、[#121](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/121) | `hy3dpaint/DifferentiableRenderer/MeshRender.py:1182` 对可见深度直接求 max/min。CPU 执行真实源码中的归一化语句：空 mask 触发 RuntimeError；非空但恒定深度得到 NaN。 | 为空视角定义跳过/返回空投影行为，并处理零深度范围；再做真实渲染回归。不能仅捕获异常后继续伪装成功。 |
| 高 | [#214](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/214) | `requirements.txt` 仍固定 `trimesh==4.4.7`。CPU 合成 box GLB 加载正常，追加未知 `TEST` chunk 并修正文件总长度后，报 `ValueError: not binary GLTF!`。 | 修复直接加载用户 GLB 的路径，或评估兼容依赖升级；未知 chunk 兼容不等于可以任意丢弃来源凭证。默认 remesh 路径不是该报告的触发条件。 |
| 高 | [#42](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/42) | `MeshRender.py:36` 吞掉补洞扩展导入异常，`:1408` 仍无条件调用未绑定的 `meshVerticeInpaint`。CPU 执行真实 `uv_inpaint` 方法、模拟扩展不可用，复现 NameError。 | 保留原始导入异常，执行补洞前明确报错；如支持替代补洞算法，应明确选择并验证输出。 |
| 中；Windows 用户高 | [PR #79](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/pull/79)、[PR #99](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/pull/99)、[#55](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/55)、[#12](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/12) | 已读取 PR diff。Fork `grid_neighbor.cpp:397` 仍有 size_t 初始化窄化，`:408` 等仍是 `data_ptr<long>()`；`compile_mesh_painter.sh` 仍依赖 c++/python3-config。未实跑 MSVC/CUDA 编译。 | 优先评审 #79 的定宽整数与跨平台构建改动，再吸收 #99 安装说明。分离已经纳入的 deepspeed 依赖调整，避免整包覆盖。 |
| 中 | [#139](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/139) | Fork 补洞默认仍走 `smooth`；C++ 中存在迭代扫描全部未着色顶点的算法，同时已有 `forward` 实现。报告中的 8521.93 秒是用户实测，不是本次实测。 | 分阶段计时，用同一真实 mesh 比较 smooth/forward 的速度与接缝质量；不能未经验证直接替换默认算法。 |
| 中；兼容性敏感 | [#115](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/115) | 函数签名是 `timestep_embedding(t, dim, max_period=10000, time_factor=1000)`，`:385`/`:390` 却把 `self.time_factor` 作为第三位置参数传入。CPU 执行真实函数，当前调用与显式 `time_factor=1000` 的 embedding 最大绝对差为 1.9738388。 | 参数错位已确认，但预训练权重可能依赖旧行为；先核对训练与推理约定，保留旧权重兼容路径，不能直接全局更改。 |

## 仍需专项验证或属于能力缺口

- [PR #155](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/pull/155)、[#88](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/88)、[#191](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/191)：本次已读完整 #155 文本 diff；新增 ModelScope RMBG-2.0 并替换 minimal_demo 的背景处理。Fork 已修复透明背景判断，但未纳入该分割模型，不能因此宣称地板伪影已解决。需要分割与同 seed 几何生成两层 A/B。
- [PR #206](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/pull/206)、[PR #124](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/pull/124)、[PR #198](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/pull/198)：MPS/CPU/ROCm 支持没有完整纳入。Fork Paint 配置仍固定 CUDA。#206 主要是设备选择、缓存与 UI；#124 包含 CPU rasterizer；#198 仅调整 MeshRender 设备回退。它们不是互相独立、可以任意组合的完整跨平台解决方案；Modal CUDA 优先级较低。
- [#143](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/143)：Fork Gradio 仍通过模型路径是否含 `mv` 激活多视角。存在多视角入口不证明官方默认权重具有多视角条件能力；不能只打开 UI 就宣布支持。
- [#130](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/130)：异常后显存占用需做 OOM 后容器恢复测试。模型常驻显存本身不是内存泄漏证据，本次未复现 GPU 泄漏。
- [#181](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/181)、[#192](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/192)、[#117](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/117)：SDF 标签、采样法线和 watertight 质量报告仍需训练数据专项验证；不能仅根据论文描述或符号约定直接改训练标签。
- [#142](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/142)：报告重点是论文与 libigl winding number 约定的说明差异，不能直接列为确认的运行时缺陷。
- [#67](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/67)、[#92](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/92)：相关 PR #102 已被官方合并，Fork 也存在点数配置调整，不能仅因 Issue 开放就认定完全未修复。仍有严格 `torch.split` 点数前提，应按具体训练配置验证。
- [#177](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/177)、[#175](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/175)：报告堆栈来自 ComfyUI 或其插件，不直接等于本 Fork 的同名缺陷；Fork Paint 构造器实际初始化了 `view_processor`。

## 已处理或已有等效修复，不重复计入

- #209：本 Fork `68fe8e7` 已修复默认重复 sigma。
- PR #207、#217、#201、#159：CHANGELOG 和本地实现已有相应修复。
- PR #215、#180、#158、#167：默认 bpy / Linux 安装问题已有相应或等效调整。并不表示所有平台安装都已通过测试。
- PR #163：Fork 已有 PBR GLB 导出及后续加固；不应直接用旧 PR 覆盖现有导出器。
- PR #38：Fork Dockerfile 当前 CMD 已包含 python，不再是原报告的启动命令问题。

## 部署入口的额外缺口

- `app.py:19` 仍固定 `b4c57ab`，没有包含本 Fork 最近的背景、GLB、sigma 修复。
- Fork 的 `docker/Dockerfile:61` 克隆的是官方仓库，未固定本 Fork 版本；`:72` 扩展安装命令也未使用本 Fork README 建议的 `--no-build-isolation`。
- 因此，Fork 源码已修复并不等于这两个部署入口会运行修复版。Docker 镜像本次未实际构建。

## 本次复现环境和范围

Windows，Python 3.12，PyTorch 2.5.1+cpu，trimesh 4.4.7。CPU 临时依赖环境，不改变项目锁文件。
GLB 测试实际执行 trimesh 加载；其余测试通过 AST 提取真实源码函数/语句，隔离无关模型和 CUDA 扩展依赖。
这验证了确定的代码行为及边界条件，不代表真实 Shape/Paint 全链路或 Windows CUDA 构建已验证。

建议顺序：空视角/恒定深度 → GLB 兼容 → 扩展失败诊断 → Windows 构建 → 补洞性能；时间嵌入单独做权重兼容评估。
