# 社区方案移植与 Modal 验收

日期：2026-10-19。Fork 已推送至 `1112a61026bc6e11a89ea95614e97cba8235b475`，Modal 服务已更新。

**已完成适用代码移植、实际云端测试和视觉检查；没有把原九张照片全部生成合格模型。** 默认 rembg + Shape 路径在这九张图上仍有明显质量问题；新版将其拦截并保留证据，不再上色后当成功模型交付。成功例是官方企鹅、指定主体后的橙汁杯，以及官方 2mv 卡通人物样例。

## 逐项移植

| 来源 | 本项目处理 | 实测结果/限制 |
|---|---|---|
| [ComfyUI FP16 norms](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/ldm/hunyuan3dv2_1/hunyuandit.py) | `StableLayerNorm` / `StableRMSNorm`，输入为 FP16 时使用 `1/65504`；覆盖 Q/K、block、skip、final norm，其他精度保留原 epsilon，checkpoint 键不变 | 已在 L40S 跑旧/新 FP16、BF16 同初始噪声对照；没有消除 t009 方盒 |
| [Strix Halo FP32 attention](https://github.com/kroqueta-s/hunyuan3d-strix-halo/blob/main/runners/hunyuan3d/shape.py) | 独立的按 head FP32 math SDPA，`--attention-precision fp32`；默认保留 CUDA fused SDPA | 真实云端运行成功，但 t009 仍是方盒；没有照搬 ROCm 环境变量 |
| [ComfyUI #12772](https://github.com/Comfy-Org/ComfyUI/pull/12772) | 当前未用 Sage，无需关闭；增加 DiT prediction、采样 latents、VAE features 的 NaN/Inf 检查 | 非有限值立即停止，而不是继续提取空/损坏网格；本次 t009 采样数值均有限 |
| [官方 #48](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/48) | RGB/RGBA 顺序已有修复，本轮延用；增加严格同尺寸人工 mask | 保留原透明背景；支持 `--mask-path`，白色为主体 |
| [官方 #155](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/pull/155) | 可选 `--background rmbg2`，1024px 分割后恢复原尺寸 alpha，模型来自 BRIA 官方 HF 仓库，固定 revision；补装 kornia | 已获当前凭证访问并实际跑通；t009 仍方盒，没有提升成默认抠图器 |
| [photo-to-mesh SAM3](https://github.com/Hasasasaki/photo-to-mesh) | 独立 `segment.py`，Python 3.12 / Torch 2.7 / CUDA 12.6；固定源码与权重 revision；文本选最高分主体，保存 mask/透明图/棋盘格预览/来源哈希 | t011 “glass of orange juice” 得到杯子 mask，分数 0.957；无匹配明确失败，不返回全白 mask |
| [官方 2mv 示例](https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/examples/shape_gen_multiview.py) | 独立 `--shape-backend 2mv`，加载正确 2.0/2mv 组件；兼容官方旧 `hy3dgen.shapegen.*` 配置路径；1–4 个规范视图 | 官方 front/left/back 实际完成，四视图为完整卡通人物；默认 2.1 仍只接单图 |
| [Abstract3D best-of-N](https://github.com/lpalbou/abstract3d#quality-presets-best-of-n-shape-selection) | 1–4 个 seed 的 Shape 候选，独立几何拦截，四视图轮廓评分，选优后只 Paint 一次，全部不合格则拒绝 | t009 的三个候选分别是方盒、圆团、旋转薄板。未照抄其 topology/detail 分数，也未宣称多 seed 能保证质量 |

没有默认移植 Blender 切底板：会裁伤合法主体，也不能从方盒恢复人物。没有自动改成 Mii/雕像参考图或生成伪多视角：这会改变照片内容、身份和任务，需要作为明确的生成选项处理。

## 新的质量流程

原图/人工 mask/可选分割器 → 保存前景与实际 512px condition → 前景检查 → Shape 候选 → 数值检查 → 原始几何检查和四视图 → 轮廓分数 → 选优 → Paint → PBR 检查与带纹理预览。

* 默认前景阈值 1%；t011 原自动 mask 只有 0.214%，在 Shape 前拒绝。
* 检查方盒与薄板，包括相对于世界坐标旋转的退化几何；允许显式声明合法盒体/薄板。
* 默认最高 silhouette IoU 至少 0.75。只比较四个方向，未知相机角度可能造成误拒；这不是任意姿态的配准算法。
* `completed` 只表示通过当前检查；它不证明面部、缺失肢体、隐藏面和完整场景正确。t009 的 SAM3 person 和 2mv 单图对照仍产生不合格浮雕/块状形体，即使轮廓分数通过，人工检查仍判失败。
* 首轮 `020ffd3` 曾漏过 seed 2060 的旋转薄板；亲自看预览后修正为 `1112a61`，最终三个候选全部拒绝。历史目录没有删除，不能把旧 `completed` 报告当最终质量结论。

## 九张原图回归

固定 50 步、seed 42、默认 rembg；t009 另测 seed 1051/2060。下表是工程检查结果，**不是九张图片质量修复成功率**。已实际检查三张联系表中的全部源图与原始几何四视图。

| 原图 | 最终检查 | 观察/最高 IoU |
|---|---|---|
| t008 | 拒绝 | 矩形薄板；0.189 |
| t009 | 三候选全拒绝 | 方盒；圆团 0.707；旋转薄板。轮廓高分不能挽救退化几何 |
| t010 | 拒绝 | 补成不同的全身人物，轮廓 0.365 |
| t011 | Shape 前拒绝 | 前景仅 0.214%，没有继续生成 |
| t012 | 拒绝 | 物品加底板/竖板，不完整场景；0.271 |
| t013 | 拒绝 | 局部盥洗台和截面场景；0.553 |
| t014 | 拒绝 | 方板而非自行车；0.182 |
| t015 | 拒绝 | 局部人物加板；0.382 |
| t016 | 拒绝 | 电车简化成长条；0.576 |

证据：[最终汇总](outputs/quality-fixes/end-to-end/summary.json)、[其余七张](outputs/quality-fixes/end-to-end/summary-remaining.json)、[联系表 1](outputs/quality-fixes/regression-contact-1.png)、[联系表 2](outputs/quality-fixes/regression-contact-2.png)、[联系表 3](outputs/quality-fixes/regression-contact-3.png)。每个目录还包含原始 GLB、条件图、mask、预览和采样统计。

## 正向验收

* 官方企鹅：Shape 32.87 秒，Paint 53.48 秒；PBR GLB 和四视图检查正常。[带纹理预览](outputs/quality-fixes/end-to-end/penguin-pbr_20261019-154135_42_5368ebee/textured-preview/shape-preview.png)
* t011 明确选择橙汁杯：前景 1.183%，Shape 33.10 秒，Paint 61.02 秒，轮廓 IoU 0.931；得到杯形几何。**没有重建整个房间，玻璃仍被生成为偏不透明的橙色材质。** [预览](outputs/quality-fixes/end-to-end/t011-sam3-glass_20261019-154354_42_eed0875e/textured-preview/shape-preview.png)
* 官方 2mv 三张规范图：轮廓 IoU 0.909，完整卡通人物。[原始几何四视图](outputs/quality-fixes/2mv-validation/official-2mv-validation_20261019-153254_42_089534eb/candidate-1/shape-preview.png)

以上阶段计时不含镜像构建与容器冷启动。各测试均在 Modal L40S 上实际执行。

## 明确未解决的部分

1. t009 不能稳定生成合格的人物/头像。旧 FP16、新 epsilon、BF16、FP32 attention、RMBG-2.0、多个 seed、SAM3 person、2mv 单图都没有获得可确认合格的结果。没有据此证明唯一根因，也没有把“几何有限且有轮廓”当作修好。
2. SAM3 文本并不总能选对对象。对 t009 的 “head with hair” 实测主要保留头发、挖掉面部，因此看过 mask 后没有继续花费 Shape。要看预览，不要只信置信度。
3. 完整街景/室内场景没有在当前单物体流程中实现。选择其中物体可以改善输入；不等于完整场景重建。
4. 默认检查偏保守，真实薄板、盒体及未覆盖的拍摄角度可能误拒。透明材质、人物保真与细小缺失部件不在当前指标的保证范围内。

## 部署与检查

* CPU 回归：33 项全部通过，Windows 与 Modal 镜像内均通过。构建也实际导入 Shape/Paint 和已编译 inpaint 扩展。
* 最终端到端：[Modal 运行](https://modal.com/apps/shuhuaqaq/main/ap-uSuN3x04hOV8Psq000rAjo)。四个场景断言通过：坏 mask 拒绝、三个坏 Shape 拒绝、企鹅 PBR 成功、指定杯子 PBR 成功。
* 其余七图：[Modal 运行](https://modal.com/apps/shuhuaqaq/main/ap-XHO85p4gciSUedRZt9LVPF)。没有推理或渲染执行失败，均按质量条件拒绝。
* 已部署：[modal-forge-hunyuan3d-2-1](https://modal.com/apps/shuhuaqaq/main/deployed/modal-forge-hunyuan3d-2-1)。SDK 调用确认返回 `1112a61` 和新拒绝约定，见 [smoke 记录](outputs/quality-fixes/deployed-smoke.json)。

用法见 [README](README.md)。建议先生成/检查主体 mask，再使用 `--shape-candidates 3`；全部候选失败时保留报告并调整任务/输入，不自动把失败候选贴图输出。
