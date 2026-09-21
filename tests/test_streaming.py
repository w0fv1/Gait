import json
import queue
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.support import GaitFixture
from tests.test_agent import reply, call


def event(kind, **fields):
    return ('event: ' + kind + '\r\ndata: ' + json.dumps(dict(type=kind, **fields), ensure_ascii=False) + '\r\n\r\n').encode('utf-8')


@contextmanager
def streaming_server(mode='text'):
    requests = []
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                if mode == 'reclassified' and len(requests) == 1:
                    self.wfile.write(event('response.output_text.delta', delta='<tool_call>'))
                    output = call('git_status', {})
                    output[0]['arguments'] = '\n'
                elif mode == 'tool' and len(requests) == 1:
                    self.wfile.write(event('response.function_call_arguments.delta', delta='{"paths":['))
                    self.wfile.flush()
                    release.wait(10)
                    output = call('git_stage', dict(paths=['tracked.txt']))
                elif mode == 'truncated':
                    self.wfile.write(event('response.function_call_arguments.delta', delta='{"paths":["tracked.txt"]}'))
                    self.wfile.flush()
                    return
                elif mode == 'error':
                    self.wfile.write(event('error', code='provider_failure', message='stream failed'))
                    self.wfile.flush()
                    return
                else:
                    first = event('response.output_text.delta', delta='你好')
                    split = first.index('你'.encode()) + 1
                    self.wfile.write(b': keepalive\r\n\r\n' + first[:split])
                    self.wfile.flush()
                    self.wfile.write(first[split:])
                    self.wfile.flush()
                    release.wait(10)
                    self.wfile.write(event('response.output_text.delta', delta='，世界🌍'))
                    output = reply('你好，世界🌍')
                self.wfile.write(event('response.completed', response=dict(id='response_test', status='completed', output=output)))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield dict(GAIT_AI_API_KEY='test-key', GAIT_AI_MODEL='test-model', GAIT_AI_ENDPOINT=f'http://127.0.0.1:{server.server_port}/responses'), requests, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join()


class Streaming(GaitFixture):
    def test_completed_tool_is_authoritative_when_provider_reclassifies_text(self):
        with streaming_server('reclassified') as (env, requests, release):
            release.set()
            process = self.start(env)
            output, error = process.communicate(timeout=30)
            self.assertEqual(0, process.returncode, error.decode('utf-8'))
            self.assertEqual('<tool_call>\n你好，世界🌍\n', output.decode('utf-8').replace('\r\n', '\n'))
            self.assertEqual(2, len(requests))
            result = json.loads(requests[1]['input'][-1]['output'])
            self.assertEqual('ok', result['result']['status'])

    def test_text_arrives_before_server_sends_completion(self):
        with streaming_server() as (env, requests, release):
            process = self.start(env)
            first = queue.Queue()
            reader = threading.Thread(target=lambda: first.put(process.stdout.read(6)), daemon=True)
            reader.start()
            try:
                self.assertEqual('你好', first.get(timeout=8).decode('utf-8'))
                self.assertIsNone(process.poll())
                self.assertTrue(requests[0]['stream'])
                release.set()
                reader.join()
                rest, error = process.communicate(timeout=30)
                self.assertEqual(0, process.returncode, error.decode('utf-8'))
                self.assertEqual('，世界🌍\n', rest.decode('utf-8').replace('\r\n', '\n'))
            finally:
                release.set()
                if process.poll() is None:
                    process.kill()
                    process.wait()
                reader.join(timeout=2)
                process.stdout.close()
                process.stderr.close()

    def test_truncated_tool_stream_never_executes(self):
        (self.repo / 'tracked.txt').write_text('changed\n', encoding='utf-8')
        with streaming_server('truncated') as (env, requests, release):
            process = self.start(env)
            output, error = process.communicate(timeout=30)
            self.assertNotEqual(0, process.returncode)
            self.assertEqual('', self.git('diff', '--cached', '--name-only'))

    def test_stream_error_is_reported(self):
        with streaming_server('error') as (env, requests, release):
            process = self.start(env)
            output, error = process.communicate(timeout=30)
            self.assertNotEqual(0, process.returncode)
            self.assertIn('stream failed', error.decode('utf-8'))

    def test_tool_arguments_are_not_executed_until_completion(self):
        (self.repo / 'tracked.txt').write_text('changed\n', encoding='utf-8')
        with streaming_server('tool') as (env, requests, release):
            process = self.start(env)
            try:
                deadline = time.monotonic() + 8
                while not requests and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(requests)
                self.assertEqual('', self.git('diff', '--cached', '--name-only'))
                self.assertIsNone(process.poll())
                release.set()
                output, error = process.communicate(timeout=30)
                self.assertEqual(0, process.returncode, error.decode('utf-8'))
                self.assertEqual('tracked.txt', self.git('diff', '--cached', '--name-only'))
                self.assertEqual(2, len(requests))
            finally:
                release.set()
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_json_waits_for_completion_and_remains_one_document(self):
        with streaming_server() as (env, requests, release):
            process = self.start(env, '--format', 'json')
            first = queue.Queue()
            reader = threading.Thread(target=lambda: first.put(process.stdout.read(1)), daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + 8
                while not requests and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(requests)
                with self.assertRaises(queue.Empty):
                    first.get(timeout=0.2)
                release.set()
                prefix = first.get(timeout=10)
                reader.join()
                rest, error = process.communicate(timeout=30)
                self.assertEqual(0, process.returncode, error.decode('utf-8'))
                self.assertEqual('你好，世界🌍', json.loads(prefix + rest)['text'])
                self.assertTrue(requests[0]['stream'])
            finally:
                release.set()
                if process.poll() is None:
                    process.kill()
                    process.wait()
                reader.join(timeout=2)
