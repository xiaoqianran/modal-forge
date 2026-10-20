# 独立原始项目测试

本目录仅测试上游 Hunyuan3D-2.1 实现，不修改正式部署 `../app.py`。

## Modal PBR GLB 转换对比

```powershell
uv run --no-sync modal run tests/modal_compare_glb.py
```

- 使用独立 CPU Modal 镜像，拉取固定 Fork Commit `b4c57ab`；不下载模型权重。
- 合成相同的 OBJ/MTL、UV、Albedo、Metallic、Roughness，对比 #215 的 `_convert_obj_to_glb_trimesh` 与 #163 将使用的 `create_glb_with_pbr_materials`。
- 云端转换成功（2026-10-19）：#215 为 2,104 B，#163 为 3,148 B；均有 1 Mesh、1 Material、2 Images，UV 和 PBR 引用存在。
- Metallic-Roughness 像素：#215 `[0,80,190]`，#163 `[255,80,190]`；G/B 相同，R 不用于标准 metallic-roughness 通道。
- 限制：尚未验证多材质、复杂 MTL、并发及真实 Paint 生成的 GLB，也没有逐帧可视化渲染对比。

手动保留生成的测试 GLB，可在本地装齐依赖后运行：

```powershell
uv run --with trimesh --with pygltflib --with pillow --with numpy --with opencv-python python tests/compare_glb.py --output tests/out-glb
```

## 2026-10-19 云端异常输入回归（已运行）

命令：`uv run --no-sync modal run tests/modal_compare_glb.py`

运行记录：https://modal.com/apps/shuhuaqaq/main/ap-bOoekuwIhmIiXhyOgd95l7

| 情况 | 结果 |
| --- | --- |
| 普通单网格 | 两种导出器均有 UV、Albedo、MR 引用；MR G/B 正确 |
| JPEG MIME | pygltflib 路径声明 `data:image/png`，实际首字节 `ffd8ff` (JPEG)，**已复现** |
| 固定中间文件 | 实际生成 `temp.glb` 和 `mr_combined.png`，**已复现固定路径**，尚未证明并发污染 |
| 缺失 roughness | 导出抛出 `AttributeError: 'NoneType' object has no attribute 'read'`，**已复现** |
| 两个 OBJ object | 本次转换成一个 glTF mesh，**尚未验证多个 glTF mesh 材质分配** |

`modal_real_paint.py` 用官方自带 Paint `assets/case_1/mesh.glb` + `image.png` 在 L40S 上生成真实 OBJ / MTL / 贴图并比较两条导出路径；该测试需完整 CUDA 构建，只有得到成功报告后才算完成。

## 真实 Paint L40S 测试状态

入口：`uv run --no-sync modal run tests/modal_real_paint.py`

Modal 记录：https://modal.com/apps/shuhuaqaq/main/ap-VKEX9OuccqhvN9PcIiWo7X

本次完整镜像构建时会话超时：仍处于 `pip install -r requirements.txt` 依赖构建阶段，**没有生成真实 Paint OBJ/MTL/纹理，也没有产生真实样本转换对比结果**。此脚本保留以便单独重试；不得将它标记为成功。正式 `app.py` 及 Fork 没有修改。

## 背景去除回归测试（2026-10-19）

命令：uv run --no-sync modal run tests/modal_test_rembg.py

结果：Modal CPU 6/6 PASS。RGB、不透明 RGBA、透明 RGBA、部分透明、强制去背景、灰度图片。
测试使用 GitHub b4c57ab + 本地修复版 rembg.py，不推送 Fork。使用模拟 BackgroundRemover，尚未运行真实模型。
运行记录：https://modal.com/apps/shuhuaqaq/main/ap-w3bFxODHOYwRAddTLK82Aw


## RMBG 2.0 背景分割 A/B（2026-10-19）

运行（Windows PowerShell）：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
uv run --no-sync modal run tests/modal_compare_rmbg2.py
```

- 独立 Modal L40S 镜像，不修改 Fork 或正式 `app.py`；使用 `assets/demo.png`。
- 现有 `rembg` 与 `briaai/RMBG-2.0` 处理同一 RGB 图片。
- 复用 Modal Secret `huggingface-secret`；需要账号具有 RMBG-2.0 权重访问权限，并提供 `HF_TOKEN`（或 `HUGGINGFACE_HUB_TOKEN`）。
- 输出到 Modal Volume `modal-forge/001-Hunyuan3D-2.1/tests/rmbg2-ab/`：`source.png`、`original.png`、`rmbg2.png`、`report.json`。
- 本脚本只对比分割结果、时间、显存，**不代表 Shape 地面伪影已被解决**；要在相同种子下完成 Mesh 对比后才能决定生产集成。
- PR #155 原始描述已核实，但完整 GitHub 文件 diff 获取失败；逐行比对尚未完成。

## 多样本 RMBG 2.0 对比（2026-10-19）

- 脚本：`modal_compare_rmbg2_multi.py`（分割），`modal_shape_ab_multi.py`（Shape）。独立测试，不更改生产 `app.py` 或 Fork。
- 样本：`assets/example_images/{004,052,073}.png`；原图含 Alpha，先合成白底，再由 U2Net / RMBG 2.0 分别分割。因此不构成真实复杂地面/阴影测试。
- Modal 分割：https://modal.com/apps/shuhuaqaq/main/ap-DNe5qjyvAd8K7JlI97UpV6
- Modal Shape：https://modal.com/apps/shuhuaqaq/main/ap-GzfhYsJziy7pUiQPwfHgr5
- 统一 L40S、Seed 42、50 步；3 个样本全部完成两份 GLB，合计 6 份。输出目录：Volume `001-Hunyuan3D-2.1/tests/shape-ab-multi/`。
- Mask IoU 分别为 0.9967、0.9873、0.9782。RMBG 2.0 面数相对 U2Net：004 -0.99%、052 -3.72%、073 -9.03%。所有 6 个导出 GLB 的 `watertight` 为 false；未诊断具体拓扑缺陷，不能声称 RMBG 2.0 有更优几何质量。
- 尚未按真实地面/阴影类别采集样本，也未进行多种子稳健性测试。不得直接据此将 RMBG 2.0 设为默认。
