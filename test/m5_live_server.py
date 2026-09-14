"""Disposable local Web server used by the M5 browser acceptance run."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn

from agent.workflow import WorkflowService
from bus import MessageBus
from channels.web import WebChannel
from session.conversation import ConversationService
from trade_rag.knowledge_repository import KnowledgeRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8876)
    args = parser.parse_args()
    conversations = ConversationService(args.root / "sessions")
    workflows = WorkflowService(args.root / "workflows")
    first = conversations.create("M5 Browser Acceptance")
    asyncio.run(workflows.observe_tool(
        f"web:local:{first.conversation_id}", "extract_rfq",
        json.dumps({"rfq_id": "m5-rfq", "extraction": {"missing_fields": []}}),
    ))
    channel = WebChannel(MessageBus(), host="127.0.0.1", port=args.port,
                         conversation_service=conversations, workflow_service=workflows)
    channel._knowledge_repository = KnowledgeRepository(args.root / "knowledge")
    channel._app = __import__("fastapi").FastAPI(title="NanoClaw M5 Acceptance")
    channel._register_routes()
    uvicorn.run(channel._app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
