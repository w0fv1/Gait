import json
import os
import queue
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.support import GaitFixture
from scripts.toolchain import gait_command


@contextmanager
def chat_server(truncated=False, text_only=False):
    requests = []
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            self.send_response(200)
            if not body.get('stream'):
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(dict(id='probe', choices=[dict(message=dict(content='{"ok":true}'), finish_reason='stop')])).encode())
                return
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            if text_only:
                self.wfile.write(('data: ' + json.dumps(dict(id='chat_test', choices=[dict(index=0, delta=dict(content='你好'), finish_reason=None)]), ensure_ascii=False) + '\n\n').encode())
                self.wfile.flush()
                release.wait(10)
                chunks = [(dict(content='，世界'), None), ({}, 'stop')]
            elif len(requests) == 1:
                chunks = [
                    (dict(role='assistant', reasoning_content='Inspect the repository.'), None),
                    (dict(tool_calls=[dict(index=0, id='call_status', type='function', function=dict(name='git_status', arguments=''))]), None),
                    (dict(tool_calls=[dict(index=0, function=dict(arguments='{'))]), None),
                    (dict(tool_calls=[dict(index=0, function=dict(arguments='}'))]), None),
                ]
                if not truncated:
                    chunks.append(({}, 'tool_calls'))
            else:
                chunks = [(dict(content='仓库'), None), (dict(content='已检查'), None), ({}, 'stop')]
            for delta, finish in chunks:
                item = dict(id='chat_test', choices=[dict(index=0, delta=delta, finish_reason=finish)])
                self.wfile.write(('data: ' + json.dumps(item, ensure_ascii=False) + '\n\n').encode())
                self.wfile.flush()
            if not truncated:
                self.wfile.write(b'data: [DONE]\n\n')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield dict(GAIT_AI_API_KEY='test-key', GAIT_AI_MODEL='test-model', GAIT_AI_ENDPOINT=f'http://127.0.0.1:{server.server_port}/chat/completions'), requests, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join()


class ChatStreaming(GaitFixture):
    def test_chat_configuration_probe_and_save(self):
        with chat_server() as (connection, requests, release):
            env = {k: v for k, v in os.environ.items() if not k.startswith('GAIT_AI_')}
            env.update(connection, APPDATA=str(self.repo / 'settings'))
            result = subprocess.run([*gait_command(), '--init'], cwd=self.repo, env=env, input='\n\n\n', capture_output=True, encoding='utf-8', timeout=30)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            config = json.loads((self.repo / 'settings/gait/config.json').read_text(encoding='utf-8'))
            self.assertEqual(connection['GAIT_AI_ENDPOINT'], config['endpoint'])
            self.assertEqual({'type': 'json_object'}, requests[0]['response_format'])

    def test_native_tool_deltas_execute_and_reasoning_is_returned(self):
        with chat_server() as (env, requests, release):
            process = self.start(env)
            output, error = process.communicate(timeout=30)
            self.assertEqual(0, process.returncode, error.decode('utf-8'))
            self.assertEqual('仓库已检查\n', output.decode('utf-8').replace('\r\n', '\n'))
            self.assertEqual(2, len(requests))
            self.assertTrue(all(request['stream'] for request in requests))
            self.assertIn('function', requests[0]['tools'][0])
            messages = requests[1]['messages']
            assistant = next(m for m in messages if m['role'] == 'assistant')
            self.assertEqual('Inspect the repository.', assistant['reasoning_content'])
            self.assertEqual('{}', assistant['tool_calls'][0]['function']['arguments'])
            self.assertEqual('call_status', messages[-1]['tool_call_id'])
            self.assertEqual('ok', json.loads(messages[-1]['content'])['result']['status'])

    def test_truncated_chat_tool_is_not_executed(self):
        with chat_server(truncated=True) as (env, requests, release):
            process = self.start(env)
            output, error = process.communicate(timeout=30)
            self.assertNotEqual(0, process.returncode)
            self.assertNotIn('工具：', error.decode('utf-8'))
            self.assertEqual(1, len(requests))

    def test_chat_text_is_displayed_before_completion(self):
        with chat_server(text_only=True) as (env, requests, release):
            process = self.start(env)
            first = queue.Queue()
            reader = threading.Thread(target=lambda: first.put(process.stdout.read(6)), daemon=True)
            reader.start()
            try:
                self.assertEqual('你好', first.get(timeout=8).decode('utf-8'))
                self.assertIsNone(process.poll())
                release.set()
                reader.join()
                output, error = process.communicate(timeout=30)
                self.assertEqual(0, process.returncode, error.decode('utf-8'))
                self.assertEqual('，世界\n', output.decode('utf-8').replace('\r\n', '\n'))
            finally:
                release.set()
                if process.poll() is None:
                    process.kill()
                    process.wait()
                reader.join(timeout=2)
                process.stdout.close()
                process.stderr.close()
