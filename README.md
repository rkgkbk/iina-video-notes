# IINA Video Notes

把正在播放的视频，变成可以回看的文字笔记。

为 IINA 提供极简侧边栏：本地 Qwen-ASR 转录音轨，手动调用 Codex CLI 生成深度总结。**转录完成后不会自动调用 Codex。**

## 功能

- 本地转录，每段默认 3 分钟，保存进度并支持断点续跑。
- 转录完成后，手动点击「生成总结」。
- 先用费曼方法检验概念、机制与边界，再借鉴《如何阅读一本书》的分析阅读框架审视论证，用金字塔结构表达。
- 总结与全文切换；复制按钮复制当前标签页的全部内容。
- 点击时间戳跳转播放；时间戳为分段起点，不是逐字对齐。
- 提示词修改后重新生成总结，同时保留已有转录。

## 环境要求

当前在 macOS、IINA 1.5.0、Apple Silicon / MLX 环境下验证。

- 启用 JavaScript 插件功能的 IINA。
- FFmpeg。
- 已登录并配置好模型的 Codex CLI。
- 本地 Qwen-ASR 环境，目录结构如下：

```text
qwen-asr/
  .venv/bin/python
  model/
```

Python 环境需要 `numpy`、`mlx-audio` 及其依赖，并支持 `mlx_audio.stt.utils.load_model`。已验证模型为 Qwen3-ASR-0.6B 的 MLX 4-bit 版本。模型及 Python 环境不包含在此仓库中；这不是一键安装模型的工具。

## 安装

1. 克隆仓库：

```sh
git clone https://github.com/rkgkbk/iina-video-notes.git
cd iina-video-notes
```

2. 修改 `AI-Video.iinaplugin/config.json`，填写本机的绝对路径：

```json
{
  "asrDirectory": "/absolute/path/to/qwen-asr",
  "ffmpeg": "/opt/homebrew/bin/ffmpeg",
  "codex": "/opt/homebrew/bin/codex",
  "chunkSeconds": 180
}
```

使用 `command -v ffmpeg` 和 `command -v codex` 确认路径。`asrDirectory` 必须包含上述 Python 环境和模型目录，不要直接填模型目录。

3. 安装插件：

```sh
mkdir -p "$HOME/Library/Application Support/com.colliderli.iina/plugins"
cp -R AI-Video.iinaplugin "$HOME/Library/Application Support/com.colliderli.iina/plugins/local.video.ai-summary.iinaplugin"
```

首次安装时目标目录应不存在；更新已有安装时，请将源目录中的文件复制到已有插件目录内，避免嵌套一层目录。保留本机配置。

4. 在 IINA 的插件设置中启用插件，重启 IINA 或重新加载所有插件。安装目录名称必须为 `local.video.ai-summary.iinaplugin`，当前入口通过该路径定位后台程序。

## 使用

1. 打开本地音视频。
2. 菜单「插件 → 打开 AI 总结」，或使用 `Control + Option + S`。
3. 点击「开始转录」。已有部分进度时显示「继续转录」。
4. 转录结束后可在「全文」中阅读、复制或跳转播放。
5. 需要总结时，手动点击「生成总结」。已有总结会直接显示。

转录使用本地模型。**只有手动生成总结时，转录文字才会提交给 Codex 所配置的模型服务。**调用沿用本机 Codex 的模型与登录配置，使用只读沙箱，并禁用已配置的 MCP 服务及 hooks。

## 自定义提示词与缓存

编辑已安装插件目录中的 `summary-prompt.txt`，然后重新打开面板或重新加载插件。提示词变化只使总结缓存失效，不会要求重新转录。

缓存目录：

```text
~/Library/Application Support/com.colliderli.iina/plugins/.data/local.video.ai-summary/
```

视频路径、文件大小、修改时间及配置参与转录缓存标识。更改分段长度后会重新转录，旧缓存仍保留。点击文件夹按钮可以打开总结结果目录，其中包含 `总结.md`、`转写.txt` 和诊断日志。

## 限制

- 只读取本地文件的第一条内嵌音轨，不分析画面、OCR、在线流或外置音轨。
- 同时只处理一个转录/总结任务。
- 停止 ASR 时需等待当前片段完成；提取音轨和 Codex 子进程可以取消。
- 长视频会分批总结后合并；ASR 仍可能误识别，总结也可能遗漏或推断错误。
- 3 分钟为默认分段设置，实际速度和内存取决于设备、音频及模型。

## 开发与验证

```sh
python3 tests/test_worker.py
python3 tests/test_manual_summary.py
node tests/test_plugin.js
```

以上测试覆盖缓存、分组、取消、界面状态，以及「仅转录不会自动调用 Codex」的行为；使用模拟调用，不下载模型、不运行真实 ASR 或请求总结服务。实际使用需要另外配置上述依赖。

代码结构：`main.js` 连接 IINA；`worker.py` 负责转录、缓存和 Codex；`sidebar.html`、`style.css`、`ui.js` 负责侧边栏；`summary-prompt.txt` 管理总结提示词。
