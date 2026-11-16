"""按模型轮次记录完整回复、工具参数与结果；内容使用普通文本列。"""
import json
import uuid
import database
from models.short_drama import DramaMessage, DramaSession
from services import short_drama_store as store


class StoryboardConversation:
    def __init__(self, session_id, turn_id):
        self.session_id, self.turn_id = session_id, turn_id
        self.assistant = None
        self.tools = {}

    def create(self, role, content='', **fields):
        with database.SessionLocal() as db:
            session = db.get(DramaSession, self.session_id)
            row = store.add_message(db, session, role, content, turn_id=self.turn_id, **fields)
            db.commit()
            return store.message_data(row)

    def save(self, rows):
        with database.SessionLocal() as db:
            for data in rows:
                row = db.get(DramaMessage, data['id'])
                for field in ('content', 'reasoning', 'arguments', 'status', 'tool_call_id', 'tool_name'):
                    setattr(row, field, data[field])
            db.commit()
        return [dict(row) for row in rows]

    def tool(self, index, name, call_id):
        if index not in self.tools:
            self.tools[index] = self.create('tool_call', name, llm_call_id=self.assistant['id'],
                tool_call_id=call_id, tool_name=name, status='running')
        row = self.tools[index]
        if name:
            row['tool_name'] = name
            row['content'] = name
        if call_id:
            row['tool_call_id'] = call_id
        return row

    def handle(self, event, data):
        """返回已提交的消息快照；增量事件携带所属消息 ID。"""
        if event == 'stage_start':
            call_id = str(uuid.uuid4())
            self.assistant = self.create('assistant', status='running', id=call_id, llm_call_id=call_id)
            self.tools = {}
            return [dict(self.assistant)]
        if event == 'storyboard_stream':
            phase = data['phase']
            if phase in ('reasoning', 'content'):
                self.assistant[phase] += data['chunk']
                data['message_id'] = self.assistant['id']
                return []
            if phase == 'tool_args':
                index = data.get('tool_index', 0)
                first = index not in self.tools
                row = self.tool(index, data.get('tool', ''), data.get('tool_call_id', ''))
                data['message_id'] = row['id']
                snapshots = []
                if first:
                    self.assistant['status'] = 'done'
                    snapshots = self.save([self.assistant]) + [dict(row)]
                row['arguments'] += data['chunk']
                return snapshots
        if event == 'llm_end':
            self.assistant['status'] = 'done'
            return self.save([self.assistant, *self.tools.values()])
        if event == 'tool_start':
            row = self.tool(data.get('tool_index', 0), data['tool'], data['tool_call_id'])
            if not row['arguments']:
                row['arguments'] = json.dumps(data['arguments'], ensure_ascii=False)
            return self.save([row])
        if event in ('tool_end', 'tool_error'):
            row = next(row for row in self.tools.values() if row['tool_call_id'] == data['tool_call_id'])
            row['status'] = 'failed' if event == 'tool_error' else 'done'
            result = data['detail'] if event == 'tool_error' else json.dumps(data['result'], ensure_ascii=False)
            snapshots = self.save([row])
            snapshots.append(self.create('tool_result', result, llm_call_id=row['llm_call_id'],
                tool_call_id=row['tool_call_id'], tool_name=row['tool_name'], status=row['status']))
            return snapshots
        if event == 'stage_progress':
            content = data['label'] + ('\n' + data['detail'] if data.get('detail') else '')
            return [self.create('process', content)]
        return []

    def finish(self, message):
        if self.assistant is None or self.assistant['content'] not in ('', message):
            self.assistant = self.create('assistant', message)
        else:
            self.assistant['content'] = message
        self.assistant['status'] = 'done'
        return self.save([self.assistant])

    def fail(self):
        if self.assistant is None:
            return []
        if self.assistant['status'] == 'running':
            self.assistant['status'] = 'failed'
        for row in self.tools.values():
            if row['status'] == 'running':
                row['status'] = 'failed'
        return self.save([self.assistant, *self.tools.values()])
