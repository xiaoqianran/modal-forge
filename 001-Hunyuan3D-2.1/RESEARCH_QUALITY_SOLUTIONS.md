# Hunyuan3D-2.1 几何退化、抠图缺失：社区方案核查

研究日期：2026-10-19。仅使用 GitHub 作者仓库、源码、Issue 与 PR 等一手材料。本次没有修改生产代码或运行云端推理。

## 结论与证据等级

**有人处理过其中几类问题，也公开了代码；没有找到足以证明“一个 PR 普遍修好 NVIDIA L40S 上任意照片变长方体”的证据。** 最值得先验证的是 ComfyUI 的 2.1 原生实现中已经存在的 FP16 数值稳定处理，同时为输入分割补上明确主体和预览机制。不要把更换抠图器写成 t009 的已证实修复。

本文区分：**源码证实**（已阅读相应实现）；**作者实测声明**（作者提供效果或实验，但本次未复现）；**本地已有证据**（本会话此前测量，非本研究重新运行）；**待验证推断**（建议试验，不承诺有效）。

本地已有证据：t009 在 Paint 前的原始 Shape 就是方盒，约 98.2% 面积为轴向平面；回退 sigma 和普通/meta 加载得到逐顶点相同结果；关闭抠图仍为方盒；企鹅官方样例正常。t011 自动抠图前景仅约 0.214%。这些证据意味着至少有两条失败路径，不能归成同一个 rembg 问题。

## 1. 优先候选：采用别人已经实施的 FP16 稳定处理，做同 seed 对照

**源码证实**：Comfy-Org 当前原生 Hunyuan3D-2.1 实现，在 `use_fp16` 时将 attention 的 Q/K norm、Transformer block 多处 norm 和 final norm 的 epsilon 设为 `1 / 65504`，其他精度保留 `1e-6`。源码注释明确指出 FP16 下 `1e-6` 有数值稳定问题。

来源：[ComfyUI 原生 2.1 hunyuandit.py](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/ldm/hunyuan3dv2_1/hunyuandit.py)，尤其约 304、381、450、530 行。

**本地源码对照证实**：本 Fork 的 `modal-forge-Hunyuan3D-2.1/hy3dshape/hy3dshape/models/denoisers/hunyuandit.py` 在 165、268 行还保留“FP16 应改 epsilon”的 TODO，Q/K norm 和其余 norm 目前固定 `1e-6`。

**建议**：保持 t009 输入、seed、步数、权重和解码器完全一致，对比原始 FP16 与 dtype-aware epsilon；记录 latents、norm 输出和解码场的 finite 比例、极值，以及实际多角度 mesh。必要时先将少数 norm/attention 提升到 FP32，另做 BF16 对照（注意 epsilon 策略随精度分别处理）。

**边界**：这证明别人确实做过相关数值稳定改造，尚不证明它就是 t009 根因；企鹅正常也不能单独排除输入依赖的数值异常。不要只改一个 attention norm 就宣称已复刻整个 ComfyUI 实现。

## 2. 真实精度修复案例：AMD 上 FP16 attention 破坏 SDF

**作者声明 + 源码证实**：[kroqueta-s/hunyuan3d-strix-halo](https://github.com/kroqueta-s/hunyuan3d-strix-halo) 针对 gfx1151 / Windows ROCm：作者观察到 math attention 的 FP16 中间乘积溢出，解码场变噪声；启动时实际探测 flash/memory-efficient backend，支持时直接用，否则采用按 head 分块的 FP32 attention。

实现：[shape.py 的 fast_attention_available 与 _install_sdpa_shim](https://github.com/kroqueta-s/hunyuan3d-strix-halo/blob/main/runners/hunyuan3d/shape.py)。这是有效的诊断思路：验证真正运行的 backend 与中间数值，而不只看默认配置。

**边界**：L40S 是 NVIDIA CUDA，不能直接搬 ROCm 环境变量或断言同因；作者报告的是噪声 SDF，也不是我们已确认的同一方盒案例。借鉴数值探针和保守精度 A/B，不直接安装全局 monkey patch。

另见 [ComfyUI PR #12772](https://github.com/Comfy-Org/ComfyUI/pull/12772)，2026-03-17 已合并：作者记录 SageAttention 使 2.1 DiT 输出全 NaN，导致空网格；通过两处 `low_precision_attention=False` 回退 PyTorch attention。我们的现有路径没有使用 SageAttention，不能把“关 Sage”当作已命中修复，也不能把空网格证据等同于方盒证据。

## 3. 确实有人通过修正 RGBA/去背景顺序缓解地板，但明确不是全解

[官方 Issue #48 的首次修复评论](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/48#issuecomment-3030332133) 指出 demo 先转 RGBA，再判断 RGB，导致去背景永远跳过。作者调整顺序并给出前后效果。

但 [同帖作者后续回复](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/48#issuecomment-3032467184) 明确表示：修顺序后仍不能稳定去掉底板。该问题还有后续 rembg 无效报告。官方 [#88](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/88) 与 [#191](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/191) 也仍有地面生成投诉；#88 最初预期交付是训练代码和权重，不是一个已发布的通用参数解。

**意义**：顺序 bug 必须修，但本 Fork 已处理这条路径；t009 关闭去背景仍退化，不能再次用它解释全部问题。

## 4. RMBG-2.0：有现成 PR，但证据仅覆盖作者样例

[官方 PR #155](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/pull/155) 在研究时为 open、未合并。已逐项查看 diff：新增一个 demo3 图片和 RMBG 类，在 1024×1024 输入上预测 mask，缩回原尺寸作为 alpha，minimal_demo 改为先分割再送 Shape。作者表示原 rembg 对其示例质量不高，改 RMBG-2.0 后不再生成地面。

**已证实**：代码方案和作者效果声明存在。**未证实**：多种真实照片上的成功率、t008–t016 是否改善，以及对 t009 方盒是否有效。该 PR 不是训练后消除模型地板先验的权重。

**建议**：可加为可选分割器，保留 alpha/条件图供人工确认；不要直接全量替换默认并宣布根因解决。模型部署资格和权重来源应按它自己的模型说明处理。

## 5. 更切题的工程先例：指定主体，而不是自动猜前景

[Hasasasaki/photo-to-mesh](https://github.com/Hasasasaki/photo-to-mesh) 把真实物体照片接到 Hunyuan：单图使用 2.1，多图使用另外的 2mv 权重；通过 SAM 3 文本提示决定保留哪个物体，并显示分割预览。作者声明真实照片的 Shape 已验证，但 PBR 和 VGGT/2DGS 路径仍为实验、未完成端到端验证。

源码：[app.py](https://github.com/Hasasasaki/photo-to-mesh/blob/main/app.py)、[mask_sam3.py](https://github.com/Hasasasaki/photo-to-mesh/blob/main/src/mask_sam3.py)。它是 GUI 内文本提示分割，**不是已实现的点击/画笔交互遮罩工具**。

值得借鉴：SAM 3 精确指定目标 → RGBA → 掩膜预览 → Shape → 环绕预览。需要改进：它的 GUI 在无置信匹配时返回全白 mask，并在异常时退回 rembg；对于我们当前失败案例，这种自动降级会再次把整张照片送入模型。CLI 反而把无匹配写成空 mask 供下游过滤。我们应让失败显式可见，并允许上传人工 mask 或重新选择目标。

SAM 3 权重有独立获取要求；若只想快速验证几何根因，先用人工制作的高质量 alpha，无需一开始引入一个大分割系统。

## 6. 仍会保留地板的真实失败例

[VladimirTalyzin/hunyuan3d-2.1-mac-rocm README](https://github.com/VladimirTalyzin/hunyuan3d-2.1-mac-rocm#what-makes-a-good-input) 特意保留 owl 失败样例：可见地板与柔和阴影被去背景保留下来，最终得到小猫头鹰坐在大圆板上的模型。作者建议去掉地面，或用无地平线的背景拍摄。

**作者实测声明**，并非通用 bug 修复：它同时说明“用了去背景工具”不代表条件图合格。适用于 t008 等复杂场景的输入审查，不足以解释掩膜已好的 t009。

## 7. 切底板的代码有公开，但只能作最后手段

[#48 中公开的 Blender strip_bottom_plane](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/48#issuecomment-3220233692) 根据网格底部与整体 XY 包围盒的接近程度估计底板，再做布尔差集。作者承认会稍微裁伤主体。

它可以救“已有合格主体，只多一块水平底座”，不能把没有头部几何的 t009 盒子还原成人头。不能默认对所有模型切底，否则车轮、脚、合法底座都会有风险。

## 8. 多视角需要换正确权重，不能给默认 2.1 硬塞四张图

[官方 #143](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/143) 记录默认 2.1 多视图接口不可用；[visualbruno #15 作者回复](https://github.com/visualbruno/ComfyUI-Hunyuan3d-2-1/issues/15#issuecomment-3060707057) 与 [#17](https://github.com/visualbruno/ComfyUI-Hunyuan3d-2-1/issues/17#issuecomment-3056671218) 明确当时要用 2.0 路径。

photo-to-mesh 实际采用 `tencent/Hunyuan3D-2mv` 的 DiT 和 2.0 VAE，且是前/左/后/右规范视角，不是默认 2.1 权重新增了多图能力。[Comfy-Org 官方工作流文档](https://github.com/Comfy-Org/docs/blob/main/tutorials/3d/hunyuan3D-2.mdx) 同样区分 2mv 多图与 2.1 单图。

**建议**：用户有同一物体多视图时，可以开独立 2mv Shape 后端，再单独验证是否能接当前 Paint；不要将多图拼图喂给默认 2.1 并当成多视角融合。

## 9. 照片改成清洁物体参考图：有生产流程先例，保持身份尚未证实

[NVlabs/GRAIL 资产生成文档](https://github.com/NVlabs/GRAIL/blob/main/docs/source/gen_3d_assets.md) 公开了生成 1024×1024 参考图、检查图文匹配并重试、去背景并缩到 512、Shape、Paint 的工作流；还列出裸 cube/pedestal 等描述易引入额外底板，建议明确自然支撑/接触面。

这是“先得到规范物体图，再交给 Hunyuan”的真实工程先例；它针对文本生成物体，不是证明能把真人照片稳定改成保真三维头像。t009 可尝试透明背景、完整头肩轮廓的正面或轻侧面雕塑参考图，但 AI 补全缺失区域、改视角会改变脸和几何，必须让原图与参考图可对照。这应排在原始输入的数值稳定 A/B 后，不能先改图掩盖 pipeline 缺陷。

## 10. 没有找到现成修复的相似报告

[ComfyUI #7424](https://github.com/Comfy-Org/ComfyUI/issues/7424) 在 2025-03-29 报告默认 Hunyuan 工作流生成 Minecraft 样块状物，研究时仍 open。这发生在 2.1 发布前，只能证明相似现象早已存在，不能证明同因或已经有 patch。

[visualbruno #53](https://github.com/visualbruno/ComfyUI-Hunyuan3d-2-1/issues/53) 报告 Paint 后有洞，但没有找到确认原因或修复回复。它不构成我们物理破碎的根因证据；UV 接缝引起的顶点复制也不能等同于物理碎裂。

## 11. 多 seed 选 Shape：有现成工程先例，适合放在几何验收阶段

[lpalbou/abstract3d 的 Quality presets](https://github.com/lpalbou/abstract3d#quality-presets-best-of-n-shape-selection) 公开 `--shape-candidates N`：使用间隔 seed 多次生成 Shape，根据输入轮廓、凹部细节和拓扑评分选优，只对选中的几何运行一次贴图，并保存各候选指标。作者提供 Apple MPS 上三候选汽车的端到端计时和同设置不同抽样质量差异；本次核实其文档，未复现或审计完整评分实现。

**值得借鉴**：几何不合格时，不继续花 Paint 成本；一次失败不直接交付；保存所有候选便于追查。建议先测 3 个 Shape 候选，全部不合格就显式失败，而不是强行选一个。

**边界**：该仓库明确 NVIDIA/CUDA 尚无已发布验证记录，且聚焦单个居中物体；其 MPS 速度和成功率不能外推 Modal L40S。多 seed 也不能救所有候选都退化的确定性错误；拓扑健康与轮廓相似不代表背面正确。合法盒状物/薄板必须结合主体语义判断。

另一个人像前例是作者 [Creating a mini 3d version of myself](https://mengascini.dev/blog/3dme/)：先用 img2img 把照片转成 Mii 风格人物，再送 ComfyUI Hunyuan3D-2.1；这是主动改变参考图风格的成功工作流，不能当作照片保真重建或原始方盒 bug 修复。

## 对当前项目的落地顺序（待执行验证）

1. **先诊断 t009 方盒**：原输入同 seed，对比当前 FP16、Comfy 风格 dtype-aware epsilon、必要时 FP32 norm / BF16；保持 sigma 和权重不变，保存中间统计与原始 Shape，排除已无效的重复回退。只在几何肉眼合格后花费 Paint。
2. **再修 t008/t011 输入损伤**：显示完整 alpha 和模型收到的 512×512 条件图；允许明确目标与手工 mask；前景几乎消失时中止，避免把错误结果当成功。对复杂场景，先选其中物体。如果目标是整张街景，则另行选择场景重建后端。
3. **增强稳健性**：在模型仍有随机失败时，最多小批多 seed 生成 Shape，按轮廓匹配、退化几何检测和多角度视觉选择结果；检测应考虑目标可能本来就是薄板或盒子，不能按尺寸一刀切删掉合法物体。
4. **仍不合格才换参考/后端**：同一主体有多视角时测 2mv；单图可测清洁参考图，单独标记 AI 补全及身份变化。不要以“换模型可跑通”冒充当前 2.1 bug 已修。
5. 验收用原九张图加正常企鹅对照，保留失败率、轮廓与多角度几何；只有 JSON/GLB 格式检查通过，不足以宣布质量修好。
