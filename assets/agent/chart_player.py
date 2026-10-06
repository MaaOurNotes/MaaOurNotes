"""谱面回放：单点、分段缓动长条、Trace 与滑键。"""

import json
import logging
import time
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction

logger = logging.getLogger(__name__)

# 统一校准参数：坐标使用控制器缩放后的坐标，时间单位为毫秒。
LANE_LEFT = 125  # 整个判定区域的左边界 X，单位为像素，并非单条轨道的边界
LANE_RIGHT = 1150  # 整个判定区域的右边界 X，单位为像素；音符位置在左右边界间换算
JUDGE_Y = 570  # 判定线的 Y 坐标，单位为像素；所有触摸在此高度执行
MUSIC_START_OFFSET_MS = 0  #  音乐起点相对动作内记录 origin 时刻的偏移：正数推迟，负数提前，单位为毫秒
INPUT_LEAD_MS = 0  # 触摸发送提前量：正数提前发送，负数延后发送，单位为毫秒

FLICK_DISTANCE_PX = 100  # 滑键移动距离（控制器坐标像素）；普通滑键向上，定向滑键向左/右

TAP_MS = 30  # 普通单点从按下到抬起的时长，单位为毫秒；长条时长由谱面决定

chart_files = {
                ("unravel", "easy"): "unravel_easy.json",
                ("unravel", "hard"): "unravel_hard.json",
                ("ave mujica", "easy"): "ave_mujica_easy.json",
                ("六兆年と一夜物語", "easy"): "six_trillion_easy.json",
                ("六兆年と一夜物語", "hard"): "six_trillion_hard.json",
                ("ave mujica", "expert"): "ave_mujica_expert.json",
                ("春日影(mygo!!!!! ver.)", "hard"): "haruhikage_mygo_hard.json",
                ("homie’s tie!!", "hard"): "homies_tie_hard.json",
}


def line_ease(t, kind):
    # 与网站/游戏枚举一致，名称与常见缓动库的命名方向不同。
    if kind == "Linear":
        return t
    if kind == "EaseIn":
        return (2 - t) * t
    if kind == "EaseOut":
        return t * t
    raise ValueError(f"未知长条缓动类型：{kind}")


def note_center(note, lanes):
    return (note["laneStartFloat"] + note["laneEndFloat"] + 1) / (2 * lanes)


def line_center(first, last, t, lanes):
    # 左右边缘分别插值；宽度变化或两侧缓动不同时也能跟随中心。
    left_t = line_ease(t, first.get("lineEase", "Linear"))
    right_t = line_ease(t, first.get("lineEaseR", "Linear"))
    left = first["laneStartFloat"] + (last["laneStartFloat"] - first["laneStartFloat"]) * left_t
    right = first["laneEndFloat"] + (last["laneEndFloat"] - first["laneEndFloat"]) * right_t
    return max(0, min(1, (left + right + 1) / (2 * lanes)))


def chart_events(score, tap_ms=TAP_MS):
    lanes = score["laneCount"]
    if lanes <= 0 or tap_ms <= 0:
        raise ValueError("轨道数和单点时长必须为正数")
    notes = {n["id"]: n for n in score["notes"]}
    events = []
    intervals = []
    hold_ids = set()
    begins, connections, ends = {20, 41, 61, 80}, {21, 63}, {22, 42, 62, 82}
    for line in score["lines"]:
        if line["type"] == "guide":
            continue  # 导引线仅用于显示，不占用触点
        if line["type"] != "long":
            raise ValueError(f"未知线类型：{line['type']}")
        nodes = [notes[i] for i in line["noteIds"]]
        # Combo 和 slideAlong 音符不是塑造轨迹的连接节点。
        nodes = [n for n in nodes if n["op"] in begins | connections | ends and not n.get("slideAlong", False)]
        if len(nodes) < 2 or nodes[0]["op"] not in begins or nodes[-1]["op"] not in ends:
            raise ValueError("长条缺少有效起点或终点")
        if any(n["op"] not in connections for n in nodes[1:-1]):
            raise ValueError("长条内部节点类型无效")
        for first, last in zip(nodes, nodes[1:]):
            if last["timeMs"] <= first["timeMs"]:
                raise ValueError("长条节点时间必须递增")
            line_ease(0, first.get("lineEase", "Linear"))
            line_ease(0, first.get("lineEaseR", "Linear"))
        hold_ids.update(n["id"] for n in nodes)
        # 长条上的沿线连接判定由持续接触覆盖，不塑造轨迹，也不单独点击。
        hold_ids.update(
            i for i in line["noteIds"]
            if notes[i]["op"] in connections and notes[i].get("slideAlong", False)
        )
        end = nodes[-1]["timeMs"] + (tap_ms if nodes[-1]["op"] == 42 else 0)
        intervals.append((nodes[0]["timeMs"], end, nodes))
    for note in score["notes"]:
        if note["id"] in hold_ids or note["op"] in {120, 121, 122, 100, 103}:
            continue
        # 导引线上的 SlideConnectionTrace 需要触摸；长条连接点已由 hold_ids 排除。
        if note["op"] in {1, 40, 60, 63, 101, 102, 104, 105}:
            intervals.append((note["timeMs"], note["timeMs"] + tap_ms, [note]))
        else:
            raise ValueError(f"不支持音符类型 {note['op']}")

    def flick(ms, note, contact):
        # 手势距离/时长属于输入校准参数，不是谱面规定的判定窗口。
        fraction = note_center(note, lanes)
        direction = note.get("direction", "Normal")
        if direction not in {"Left", "Right", "Normal"}:
            raise ValueError(f"未知滑键方向：{direction}")
        distance = FLICK_DISTANCE_PX / (LANE_RIGHT - LANE_LEFT)
        for elapsed in sorted(set(range(8, tap_ms, 8)) | {tap_ms}):
            progress = elapsed / tap_ms
            x = fraction
            y_offset = 0
            if direction == "Normal":
                y_offset = -FLICK_DISTANCE_PX * progress
            else:
                x = max(0, min(1, fraction + distance * progress * (-1 if direction == "Left" else 1)))
            events.append((ms + elapsed, "move", contact, (x, y_offset)))

    # 在整个长条期间保留触点；同时间的音符使用不同触点。
    free_at = [float("-inf")] * 10
    for start, end, nodes in sorted(intervals, key=lambda item: item[0]):
        contact = next((i for i, available in enumerate(free_at) if available <= start), None)
        if contact is None:
            raise ValueError("同时触点超过 10 个")
        free_at[contact] = end
        first, last = nodes[0], nodes[-1]
        events.append((start, "down", contact, note_center(first, lanes)))
        events.append((end, "up", contact, note_center(last, lanes)))
        if first["op"] in {40, 41, 102}:
            if len(nodes) > 1 and nodes[1]["timeMs"] - start <= tap_ms:
                raise ValueError("起点滑键与下一连接点间隔不足手势时长")
            flick(start, first, contact)
        for a, b in zip(nodes, nodes[1:]):
            segment_start, segment_end = a["timeMs"], b["timeMs"]
            # 起点滑键完成后回到长条，再继续跟随轨迹。
            times = set(range(segment_start + 16, segment_end, 16)) | {segment_end}
            if a is first and first["op"] == 41:
                times = {ms for ms in times if ms > start + tap_ms} | {start + tap_ms + 1}
            for ms in sorted(times):
                position = line_center(a, b, (ms - segment_start) / (segment_end - segment_start), lanes)
                # 保留原有静止直条不发送 move 的行为。
                edges_change = (a["laneStartFloat"], a["laneEndFloat"]) != (b["laneStartFloat"], b["laneEndFloat"])
                if edges_change or a is first and first["op"] == 41:
                    events.append((ms, "move", contact, position))
        if len(nodes) > 1 and last["op"] == 42:
            flick(last["timeMs"], last, contact)
    priority = {"move": 0, "up": 1, "down": 2}
    return sorted(events, key=lambda e: (e[0], priority[e[1]], e[2]))


@AgentServer.custom_action("PlayChart")
class PlayChart(CustomAction):
    def run(self, context, argv):

        controller = context.tasker.controller
        active = set()
        try:
            params = json.loads(argv.custom_action_param or "{}")
            if not isinstance(params, dict):
                raise ValueError("custom_action_param 必须是对象")
            song = params.get("song")
            difficulty = params.get("difficulty")
            if not isinstance(song, str) or not song.strip():
                raise ValueError("song 必须是非空歌曲名")
            if not isinstance(difficulty, str):
                raise ValueError("difficulty 必须是难度名称")

            chart_file = chart_files.get((song.strip().lower(), difficulty.strip().lower()))
            if chart_file is None:
                supported = "、".join(f"{name} / {level}" for name, level in chart_files)
                raise ValueError(f"不支持的歌曲或难度：{song} / {difficulty}；当前支持 {supported}")
            chart_path = Path(__file__).resolve().parent.parent / "charts" / chart_file
            score = json.loads(chart_path.read_text(encoding="utf-8-sig"))
            events = chart_events(score, TAP_MS)
            logger.info("谱面已读取：歌曲=%s，难度=%s", song, difficulty)
            left, right, y = LANE_LEFT, LANE_RIGHT, JUDGE_Y
            if not 0 <= left < right or y < 0:
                raise ValueError("判定线坐标无效")
            # 以动作启动为零点；此偏移由用户校准，不是自动音乐同步。
            print("歌曲初始识别开始")
            origin = time.perf_counter() + MUSIC_START_OFFSET_MS / 1000

            dynamic_latency = 0  # 用于修正APP掉帧导致的游戏画面不同步，正数表示延后发送，负数提前发送，单位为毫秒。

            for ms, kind, contact, fraction in events:
                offset = dynamic_latency - INPUT_LEAD_MS
                target = origin + (ms + offset) / 1000
                print(f"target ms {target - origin} kind {kind} contact {contact} fraction {fraction} latency {dynamic_latency}")

                ocr_times = 0

                while time.perf_counter() < target:

                    # 当下一个判定点比较充裕时，截图获取刚刚的分数，对Good和Bad进行修正，参考数据：
                    # _assistLevel = 0
                    # Perfect ≤ 50 ms
                    # Great > 50 ～ 83 ms
                    # Good > 83 ～ 100 ms
                    # Bad > 100 ～ 125 ms
                    # 如果游戏内谱面因为掉帧延迟落后，MISS出现的时机将比按键时晚很多，此时有必要进行多次OCR。
                    if time.perf_counter() + 0.8 < target and ocr_times < 15:
                        # print(f"pre screen shot time {time.perf_counter()-origin}")
                        controller = context.tasker.controller
                        job = controller.post_screencap()
                        job.wait()
                        if not job.succeeded:
                            return False

                        ocr_times += 1
                        # print(f"postreen shot time {time.perf_counter()-origin}")
                        image = controller.cached_image
                        result = context.run_recognition("ReadTouchResult", image)
                        if result and result.hit:
                            print(f"OCR 结果：{result.best_result.text}")
                            postpone_ms = 0
                            if result.best_result.text == "GOOD":
                                postpone_ms = 30
                                ocr_times = 15
                            if result.best_result.text == "BAD":
                                postpone_ms = 60
                                ocr_times = 15
                            if result.best_result.text == "MISS":
                                postpone_ms = 120
                                ocr_times = 15
                            if result.best_result.text == "GREAT":
                                ocr_times = 15
                            if result.best_result.text == "ERFEC" :   
                                ocr_times = 15
                            dynamic_latency += postpone_ms
                            target += postpone_ms / 1000
                        else:
                            print("没有识别到文字")

                    if context.tasker.stopping:
                        return False
                    time.sleep(min(0.005, max(0, target - time.perf_counter())))
                if context.tasker.stopping:
                    return False
                if time.perf_counter() - target > 0.25:
                    # 放弃迟到事件，并立即释放该触点，避免漏掉抬手后持续按住。
                    print("回放迟到超过 250 ms，请调整起点或检查输入性能")
                    if contact in active:
                        job = controller.post_touch_up(contact=contact)
                        job.wait()
                        if not job.succeeded:
                            raise RuntimeError(f"释放迟到触点失败：contact={contact}")
                        active.discard(contact)
                    continue
                # 按下被跳过或触点已提前释放时，不再发送对应的移动和抬手。
                if kind != "down" and contact not in active:
                    continue
                touch_fraction, y_offset = fraction if isinstance(fraction, tuple) else (fraction, 0)
                touch_x = round(left + touch_fraction * (right - left))
                touch_y = max(0, round(y + y_offset))
                if kind == "down":
                    active.add(contact)
                    job = controller.post_touch_down(touch_x, touch_y, contact=contact)
                elif kind == "move":
                    job = controller.post_touch_move(touch_x, touch_y, contact=contact)
                else:
                    job = controller.post_touch_up(contact=contact)
                job.wait()
                if not job.succeeded:
                    raise RuntimeError(f"触摸失败：{kind} contact={contact}")
                if kind == "up":
                    active.discard(contact)
            return True
        except Exception as e:
            logger.exception("谱面回放失败 {e}")
            return False
        finally:
            for contact in active:
                try:
                    controller.post_touch_up(contact=contact).wait()
                except Exception:
                    logger.exception("释放触点失败：%s", contact)
