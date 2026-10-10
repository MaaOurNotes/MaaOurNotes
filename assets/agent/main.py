import sys
import logging

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

# 导入模块以注册 PlayChart 动作。
import chart_player
import pipeline_assist


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    Toolkit.init_option("./")

    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        sys.exit(1)

    socket_id = sys.argv[-1]

    if not AgentServer.start_up(socket_id):
        raise RuntimeError("AgentServer 启动失败")
    try:
        AgentServer.join()
    finally:
        AgentServer.shut_down()


if __name__ == "__main__":
    main()
