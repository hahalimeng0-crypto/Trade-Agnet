import json

from session.mysql_session_manager import MySQLSessionManager


class FakeCursor:
    def __init__(self, state):
        self.state = state
        self.rows = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split()).lower()
        self.rowcount = 0
        if normalized.startswith("insert ignore into runtime_conversation"):
            conversation_id, owner_id, channel, title = params
            self.state["conversations"].setdefault(conversation_id, {
                "conversation_id": conversation_id, "owner_id": owner_id,
                "channel": channel, "title": title,
            })
            self.rowcount = 1
        elif normalized.startswith("insert into runtime_message"):
            message_id, conversation_id, role, content_json = params
            self.state["messages"].append({
                "message_id": message_id, "conversation_id": conversation_id,
                "role": role, "content_json": content_json,
                "created_at": len(self.state["messages"]), "archived_at": None,
            })
            self.rowcount = 1
        elif normalized.startswith("select role,content_json"):
            conversation_id = params[0]
            self.rows = [row for row in self.state["messages"]
                         if row["conversation_id"] == conversation_id and row["archived_at"] is None]
        elif normalized.startswith("delete from runtime_message"):
            conversation_id = params[0]
            before = len(self.state["messages"])
            self.state["messages"] = [row for row in self.state["messages"]
                                      if row["conversation_id"] != conversation_id]
            self.rowcount = before - len(self.state["messages"])
        elif normalized.startswith("select conversation_id,channel,owner_id"):
            self.rows = list(self.state["conversations"].values())

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return FakeCursor(self.state)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_internal_agent_history_is_mysql_backed_and_preserves_message_shape(tmp_path):
    state = {"conversations": {}, "messages": []}
    manager = MySQLSessionManager(str(tmp_path), connection_factory=lambda: FakeConnection(state))
    key = "web:local:11111111-1111-4111-8111-111111111111"

    manager.save_message(key, {"role": "tool", "content": "ok", "tool_call_id": "call-1"})

    assert manager.get_history(key) == [
        {"role": "tool", "content": "ok", "tool_call_id": "call-1"}
    ]
    assert not list(tmp_path.glob("*.jsonl"))


def test_customer_agent_does_not_duplicate_portal_owned_messages():
    state = {"conversations": {}, "messages": []}
    conversation_id = "22222222-2222-4222-8222-222222222222"
    state["messages"].extend([
        {"message_id": "1", "conversation_id": conversation_id, "role": "assistant",
         "content_json": json.dumps("previous answer"), "created_at": 1, "archived_at": None},
        {"message_id": "2", "conversation_id": conversation_id, "role": "user",
         "content_json": json.dumps("current question"), "created_at": 2, "archived_at": None},
    ])
    manager = MySQLSessionManager(connection_factory=lambda: FakeConnection(state))
    key = f"customer_portal:account:account-1:{conversation_id}"

    manager.save_message(key, {"role": "user", "content": "current question"})

    assert len(state["messages"]) == 2
    assert manager.get_history(key) == [{"role": "assistant", "content": "previous answer"}]
