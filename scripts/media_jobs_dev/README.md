# 集群图片与视频一次性作业（开发脚本）

远端项目目录：`/data/home/tg100044/dfcs-bak/dspawagent/liyicheng/Video`。
入口为 `generate_image.sh` 和 `generate_video.sh`；两者调用同目录的 `media_job.py`。

## MiniMax-H3-Image W4A8（手动对比）

系统短剧立绘使用脚本默认的 Qwen-Image-2.1-Turbo。MiniMax 仅在手动传递 `--image-model minimax-h3-w4a8` 或 `--image-model minimax-h3-int8` 时使用。
W4A8 作业固定申请 1 张 4090、10 CPU、90000M 内存。ComfyUI 在作业内临时启动，生成后退出释放 GPU。

独立源码目录：`ComfyUI-h3-image-dev`，固定上游提交 `989d93d0d968e704c589ce0146bb18c77f6b50cc`。
独立环境：`.venv-h3-image`，只读复用 `.venv-comfy` 的 PyTorch 2.11.0+cu128 等依赖，单独安装 `comfy-kitchen==0.2.41`。
保持原有 `.venv-comfy` 目录，因为新环境通过 `.pth` 搜索其包目录。新增版本不会安装到原环境。
CUDA 12.8 下明确启用 Comfy Kitchen Triton 后端；不使用要求 CUDA 13 的优化 CUDA 后端。
工作流通过原生 `ModelAttentionBackend` 节点明确指定 `pytorch attention`，覆盖权重自带的 Comfy Kitchen INT8 attention 配置；后者会直接调用 CUDA 13 内核，不受 Triton 量化后端设置控制。

权重文件：

```text
models/MiniMax-H3-Image-W4A8/diffusion_models/minimax_h3_image_pruned_w4a8.safetensors
models/MiniMax-H3-Image-W4A8/vae/minimax_h3_image_vae_fp16.safetensors
models/Comfy-Org-MiniMax-H3/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
```

主模型 SHA256：`517cc19b85348386f4df7c806dce80d839d0899e7cdaa3e1dbb09de964381dbb`。
VAE SHA256：`d80e9c2e5cfc9844869961ff5a58c9a9e52182df6bfb30b26018dd7f348721af`。
二者已与 ModelScope 仓库校验值核对一致。编码器直接复用现有文件。

用户执行首次真实验收：

```bash
cd /data/home/tg100044/dfcs-bak/dspawagent/liyicheng/Video
bash media_jobs_dev/generate_image.sh \
  --image-model minimax-h3-w4a8 \
  --prompt '电影写实风格角色立绘，一位二十五岁的成年女性，椭圆脸，黑色长发，蓝色棉布上衣，正面全身站姿，完整双手与双脚，自然柔光，朴素浅灰色背景，面部细节清晰。' \
  --width 768 --height 1024 --seed 42 \
  --output outputs/h3_image_w4a8_portrait_check.png --wait
```

可先附加 `--dry-run` 只检查权重路径和参数，不申请 GPU。
运行返回 `result_file`、`log_file`；同目录额外保留 `comfy-image.log` 和完整的 `workflow.json`。
使用 `--wait` 时，已启动但执行失败的作业也返回任务路径和真实错误，并以非零退出码结束；Slurm 提交被拒绝仍直接报错。
工作流固定官方 6 步、CFG 1、Euler/simple，使用 W4A8 图像模型专用 VAE。
生成画布至少约 4MP，宽高向上取 32 倍数，再用 Lanczos 缩放为请求尺寸；不会因显存不足更换模型或降低生成画布。
参考图通过 `--reference-images` 按顺序传入，最多 16 张，提示词用 `<Picture 1>` 等引用。
完整提示词按原文进入 ComfyUI，不截断、不扩写；原生编码器对无法处理的长度直接报错。
作业独立保存模型搜索路径、输入、输出和用户目录，临时文件在退出时清理，原始参考图保留。

当前已完成 CPU 导入/工作流契约与自动化测试；单卡峰值显存、推理耗时和实际立绘质量需以上真实作业验收。

### INT8 对比出图

`--image-model minimax-h3-int8` 加载 `models/MiniMax-H3-Image-INT8/diffusion_models/minimax_h3_image_pruned_int8_convrot.safetensors`。
复用 W4A8 目录中的图片 VAE 和原有 NVFP4 AWQ 文本编码器；工作流仍使用 PyTorch attention、Triton 量化后端、单张 4090 和 6 步采样。
开发版网页默认使用 Qwen；INT8 作为手动对比选项保留。

```bash
bash media_jobs_dev/generate_image.sh \
  --image-model minimax-h3-int8 \
  --prompt '电影写实风格角色立绘，一位二十五岁的成年女性，黑色长发，蓝色棉布上衣，正面全身站姿，完整双手与双脚，自然柔光，浅灰色背景，面部细节清晰。' \
  --width 768 --height 1024 --seed 42 \
  --output outputs/h3_image_int8_portrait_check.png --wait
```

首次保持 W4A8 的提示词、seed 和尺寸，只改变图像模型，便于比较量化差异。
INT8 文件大小 `20979314802` 字节，SHA256 `83eb140f1ff95c068f8a6886e6d3f3d0d4ab2e07bb2fe6d2ef992a51146ee622`。
INT8 的 GPU 运行、速度和显存需用户执行以上命令验收。
仅新增 `media_jobs_dev/`，不修改现有 H3 服务及 ComfyUI 代码。

每次执行默认提交一个 Slurm 作业，申请 `tx4090` 的 1 张 GPU、10 CPU、90000M 内存，最长 4 小时。
提交后立即返回作业号；`--wait` 等待作业结束。等待期间 GPU 日志写入文件，不在终端流式显示。
任务结束后进程退出，Slurm 释放 GPU。视频任务仅临时启动计算节点本机 ComfyUI，不启动 H3 常驻 API。

## 图片依赖安装（用户执行一次）

现有 `.venv-comfy` 已有 PyTorch 2.11.0+cu128 和 Transformers 5.22.1，但没有 Diffusers 与 Accelerate。
下面创建独立的图片虚拟环境，通过只读搜索路径复用现有 PyTorch/CUDA 包；新安装的包写入 `.venv-image`，不修改 `.venv-comfy`。
因此不要删除或移动 `.venv-comfy`。依赖从阿里云 PyPI 镜像安装；权重直接读取已下载的 ModelScope 目录。

```bash
ssh hzwCloud44
cd /data/home/tg100044/dfcs-bak/dspawagent/liyicheng/Video

.venv-comfy/bin/python -m venv .venv-image
IMAGE_JOB_SITE=$(.venv-image/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
H3_SHARED_SITE=$(.venv-comfy/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')
printf '%s\n' "$H3_SHARED_SITE" > "$IMAGE_JOB_SITE/h3_shared_packages.pth"

.venv-image/bin/python -m pip install \
  --index-url https://mirrors.aliyun.com/pypi/simple \
  'diffusers==0.42.1' 'accelerate>=1.12,<2' 'transformers>=5.17,<6' pillow

# 只检查导入，不运行生成，也不申请 GPU。
.venv-image/bin/python -c 'import torch, diffusers, accelerate; from diffusers import QwenImage21Pipeline; print(torch.__version__, diffusers.__version__, accelerate.__version__)'
```

如果虚拟环境已存在，不需要重新创建；后续推理不执行任何安装。

## 图片生成、参考图与编辑

文生图，默认 1024×1024、seed=42，使用模型保存的官方 8 步采样配置：

```bash
bash media_jobs_dev/generate_image.sh \
  --prompt '电影写实风格，一位成年女性，蓝色棉布上衣，黑色长发，正面半身角色定妆照，朴素灰色背景，自然柔光。' \
  --output outputs/character_01.png
```

参考图和指令编辑采用相同入口。参考图片顺序与提示词中的“图1、图2”等对应：

```bash
bash media_jobs_dev/generate_image.sh \
  --prompt '保持图1女性的五官、发型和蓝色棉布上衣，改为侧面全身站姿，站在清晨乡村木门旁，电影写实风格。' \
  --reference-images outputs/character_01.png \
  --width 1024 --height 1024 \
  --output outputs/character_01_side.png
```

支持最多 10 张本地参考图，均须位于项目目录内。不额外提供遮罩重绘参数；此版本提供文本指令与参考图片编辑。
默认用 BF16 + `enable_model_cpu_offload()` 分组件调度，并启用 VAE tiling；没有量化转换、自动降分辨率或失败后切换其他模型。
24GB GPU 上的实际显存占用和出图质量需首个真实作业确认。

## 视频生成

```bash
bash media_jobs_dev/generate_video.sh \
  --prompt '电影写实风格，清晨乡村庭院，一位穿蓝色棉布上衣的成年女性站在木门旁，缓慢转头，固定中景，微风与鸟鸣。' \
  --duration 5 --width 960 --height 544 --seed 19341109 \
  --output outputs/shot_01.mp4
```

参考图生视频：

```bash
bash media_jobs_dev/generate_video.sh \
  --prompt '图1中的女性穿着相同衣服，站在乡村庭院中缓慢转头，固定中景，自然光。' \
  --reference-images outputs/character_01.png \
  --duration 5 --output outputs/shot_02.mp4
```

首帧模式：

```bash
bash media_jobs_dev/generate_video.sh \
  --prompt '镜头缓慢推进，女性轻轻抬头，微风吹动头发。' \
  --first-frame outputs/character_01_side.png \
  --duration 5 --output outputs/shot_03.mp4
```

默认 Turbo 8 步；`--mode base --steps 20` 使用基础模式。工作流直接复用现有 `h3_video_service/service.py` 的校验与渲染函数。
支持 `--last-frame`，与现有服务一致：首帧参数若为视频取最后一帧，尾帧参数若为视频取第一帧。
参考图不能与首尾帧混用。时长 1–15 秒，帧数仍按现有 `17k+5` 对齐，实际时长可能略有不同。

## 完整提示词、预检查与任务查看

长提示词建议保存成 UTF-8 文本，使用 `--prompt-file`。内容完整读取、完整保存，不做截断或自动扩写。
`--prompt` 和 `--prompt-file` 只能选一个。相对路径均相对于项目根目录。

```bash
bash media_jobs_dev/generate_image.sh \
  --prompt-file prompts/character.txt \
  --output outputs/character_02.png --dry-run
```

`--dry-run` 只检查请求，不加载模型、不联网、不提交 Slurm 作业，也不创建推理结果。
正式提交会返回 `slurm_job_id`、`request_file`、`result_file`、`log_file`。
输入文件、输出文件及视频状态目录均位于项目内；已有目标文件会直接报错。

```bash
squeue -j <作业号>
tail -f <返回的log_file路径>
cat <返回的result_file路径>
scancel <作业号>
```

`result_file` 从执行开始记录状态，成功时包含完整执行耗时、输出路径和分项耗时；失败记录错误并以非零状态退出。
总耗时包含 Python 内依赖导入、模型加载、推理、结果保存与视频子进程清理，不包含 Slurm 排队及 Python 解释器启动。
排队时间可通过 `sacct -j <作业号> -X --format=JobID,State,Submit,Start,End,Elapsed` 查看。

所有推理均设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`、`DIFFUSERS_OFFLINE=1`；图片管线另外使用 `local_files_only=True`。
下载或依赖缺失直接报错，任务不会尝试从 Hugging Face 下载权重。

## 验证范围

已做参数校验、提交参数传递、离线模型加载契约、8 步采样配置保留、失败记录和 ComfyUI 子进程清理的单元测试，及 Shell 语法检查。
这些测试不启动 GPU 或执行真实推理。H3 同工作流已在此前基准测试中真实生成成功；新脚本本身及 Qwen 图片推理尚待用户执行验收。

```bash
python3 -m unittest discover -s media_jobs_dev/tests -v
```
