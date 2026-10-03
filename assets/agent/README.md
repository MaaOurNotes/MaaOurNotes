# 演出 Agent 入口

`LoopLivePerform` 识别起点标记后，调用 Python Agent 的 `PlayChart` 动作。
动作从 `custom_action_param` 读取歌曲、难度，使用 `chart_player.py` 中的校准常量，再加载
`charts/unravel_easy.json`，由 MAA 控制器执行按下、移动、抬起。
已支持 unravel Easy 的 36 个单点、17 条长条，内部 Combo 标记不额外点击。
支持多连接点长条，左右边缘分别按 Linear、EaseIn、EaseOut 插值；支持 Trace、普通/定向滑键及长条起点/终点滑键。导引线只显示，不占用长条触点。
滑键以连续触摸移动实现，普通滑键向上，定向滑键向左/右；距离由 `FLICK_DISTANCE_PX` 控制，时长沿用 `TAP_MS`，需在设备上校准。未知音符和缓动类型会明确报错。

```json
"custom_action_param": {
    "song": "unravel",
    "difficulty": "easy"
}
```

参数无效或谱面读取失败时动作返回失败，并在日志里打印原因。
歌曲选项已同步传入歌曲名，当前仅实现 `unravel / easy`；此参数不负责切换游戏内难度。
在 UI 选择“自动演出(alpha)”及 unravel，并手动保证游戏内难度为 Easy。

`chart_player.py` 文件顶部的校准常量（修改后需重启 Agent）：

- `LANE_LEFT` / `LANE_RIGHT`：判定线有效区域左右边界，控制器缩放后的坐标。
- `JUDGE_Y`：判定线纵坐标。当前左右边界为 125/1150，纵坐标为 570，需实测校准。
- `MUSIC_START_OFFSET_MS`：音乐起点相对于动作启动的偏移，音乐晚 2 秒填 2000，早 1 秒填 -1000。
- `INPUT_LEAD_MS`：正数表示提前发送触摸，默认 0。
- `TAP_MS`：单点按住时长，默认 30 毫秒。

没有自动起点同步，先用第一条长条（10.666–12.000 秒）校准。
使用单调时钟绝对计时，停止/异常会释放触点，回放后接回等待结算流程。
发布时 charts 会一并复制到包中。

谱面来源：https://assets.bdon.moe/chart-site/assets/4db2aedbcafec0ff39e25da98ab734ef261930848b7a96265b28c83617445bd0.json

本地开发需要 Python 和与框架版本匹配的 MaaFw 包。
Windows x64 发布包自带 `python/` 便携环境及 MaaFw 依赖，解压后无需额外安装 Python。
打包时启动路径自动改为 `./python/python.exe`；其他平台暂时仍使用系统 Python。
`interface.json` 的 `child_args` 相对于该文件所在目录。
Agent 源码统一放在 `assets/agent`；谱面读取和回放动作都在 `chart_player.py`。
本地 `assets/interface.json` 直接启动 `assets/agent/main.py`。
打包脚本将 `assets/agent` 复制到发布目录的 `agent`，不包含 Python 缓存文件。

已注册的动作/识别实例由 AgentServer 复用。本入口不保存每次调用的上下文与参数。
