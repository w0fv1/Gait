import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from scripts.toolchain import gait_command, prepare


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def probe_server(probe_ok=True, probe_status=200, probe_error=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            body['_authorization'] = self.headers.get('Authorization')
            requests.append(body)
            payload = {'ok': probe_ok}
            response = {'id': 'resp_test', 'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(payload)}]}]}
            if probe_status >= 400:
                response = {'error': probe_error or {'code': 'unauthorized', 'message': 'Invalid credentials'}}
            data = json.dumps(response).encode()
            self.send_response(probe_status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *arguments):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield {'GAIT_AI_API_KEY': 'local-test-key', 'GAIT_AI_MODEL': 'test-model', 'GAIT_AI_ENDPOINT': f'http://127.0.0.1:{server.server_port}/responses'}, requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


class GaitFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('GAIT_EXECUTABLE'):
            (ROOT / '.tmp').mkdir(exist_ok=True)
        else:
            prepare()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Gait Test')
        self.git('config', 'user.email', 'gait@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        (self.repo / 'tracked.txt').write_text('original\n', encoding='utf-8')
        self.git('add', '--', 'tracked.txt')
        self.git('commit', '-m', 'initial')

    def git(self, *arguments, check=True):
        return subprocess.run(['git', '-C', str(self.repo), *arguments], check=check, capture_output=True, encoding='utf-8').stdout.strip()

    def start(self, connection, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GAIT_AI_')}
        env.update(connection)
        env['APPDATA'] = str(self.repo / 'settings')
        return subprocess.Popen([*gait_command(), *args, '执行请求'], cwd=self.repo, env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

