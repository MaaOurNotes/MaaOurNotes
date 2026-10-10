import json
import re
import unicodedata

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition


@AgentServer.custom_recognition("FireAboveThreshold")
class FireAboveThresholdRecognition(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> CustomRecognition.AnalyzeResult:
        try:
            param = json.loads(argv.custom_recognition_param or "{}")
            threshold = param.get("threshold")
            roi = param.get("roi")
            if type(threshold) is not int or threshold < 0:
                raise ValueError("threshold must be a non-negative integer")
            if not isinstance(roi, list) or len(roi) != 4 or any(type(x) is not int for x in roi):
                raise ValueError("roi must contain four integers")
        except (ValueError, TypeError, AttributeError) as error:
            return CustomRecognition.AnalyzeResult(box=None, detail={"error": str(error)})

        result = context.run_recognition(
            "ReadFireAmount",
            argv.image,
            pipeline_override={"ReadFireAmount": {"roi": roi}},
        )
        if result is None or not result.hit or result.best_result is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"error": "Cannot read fire amount"})

        text = unicodedata.normalize("NFKC", str(result.best_result.text)).strip()
        match = re.fullmatch(r"([0-9][0-9]?)(?:\s*/\s*)?", text)
        if match is None:
            return CustomRecognition.AnalyzeResult(box=None, detail={"error": "Invalid fire amount", "text": text})

        fire = int(match.group(1))
        return CustomRecognition.AnalyzeResult(
            box=roi if fire >= threshold else None,
            detail={"fire": fire, "threshold": threshold, "text": text},
        )


@AgentServer.custom_action("ClearLoopLiveCount")
class ClearLoopLiveCountAction(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:
        return context.clear_hit_count("LoopLiveCount")
