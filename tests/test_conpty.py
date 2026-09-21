import base64
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest


@unittest.skipUnless(os.name == 'nt' and os.environ.get('GAIT_EXECUTABLE'), 'requires Windows Native executable')
class Pseudoterminal(unittest.TestCase):
    def test_stream_delta_reaches_console_before_completion(self):
        from winpty import PTY, WinptyError
        from tests.test_streaming import streaming_server

        with tempfile.TemporaryDirectory() as temporary, streaming_server() as (connection, requests, release):
            environment = {k: v for k, v in os.environ.items() if not k.startswith('GAIT_AI_')}
            environment.update(connection)
            environment['APPDATA'] = temporary
            terminal = PTY(160, 60, backend=0)
            terminal.spawn(str(Path(os.environ['GAIT_EXECUTABLE']).resolve()), cmdline=' 回复测试文本',
                           env='\0'.join(k + '=' + v for k, v in environment.items()) + '\0')
            transcript = ''
            observed_before_completion = False
            deadline = time.monotonic() + 20
            try:
                while time.monotonic() < deadline:
                    try:
                        chunk = terminal.read(blocking=False)
                    except (EOFError, WinptyError):
                        break
                    transcript += chunk
                    if '\x1b[6n' in chunk:
                        terminal.write('\x1b[1;1R')
                    if '你好' in transcript and not release.is_set():
                        observed_before_completion = True
                        self.assertTrue(terminal.isalive())
                        release.set()
                    if '，世界' in transcript:
                        break
                    time.sleep(0.005)
            finally:
                release.set()
                if terminal.isalive():
                    terminal.write('\x03')
                del terminal
            self.assertTrue(observed_before_completion, transcript)
            self.assertIn('你好，世界', transcript)
            self.assertTrue(requests[0]['stream'])

    def test_initializer_waits_for_each_answer(self):
        from winpty import PTY, WinptyError
        from tests.support import probe_server

        with tempfile.TemporaryDirectory() as temporary, probe_server() as (connection, requests):
            environment = {key: value for key, value in os.environ.items() if not key.startswith('GAIT_AI_')}
            environment['APPDATA'] = temporary
            terminal = PTY(160, 60, backend=0)
            terminal.spawn(str(Path(os.environ['GAIT_EXECUTABLE']).resolve()), cmdline=' --init',
                           env='\0'.join(key + '=' + value for key, value in environment.items()) + '\0')
            transcript = ''
            answers = [('API 密钥', 'terminal-key'), ('模型名称', 'test-model'), ('接口地址', connection['GAIT_AI_ENDPOINT'])]
            position = 0
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    chunk = terminal.read(blocking=False)
                except (EOFError, WinptyError):
                    break
                transcript += chunk
                if '\x1b[6n' in chunk:
                    terminal.write('\x1b[1;1R')
                if position < len(answers) and answers[position][0] in transcript:
                    terminal.write(answers[position][1] + '\r')
                    position += 1
                if '配置已保存：是' in transcript:
                    break
                time.sleep(0.02)
            if terminal.isalive():
                terminal.write('\x03')
            del terminal
            self.assertEqual(3, position, transcript)
            self.assertIn('连接测试通过：是', transcript)
            self.assertIn('配置已保存：是', transcript)
            saved = json.loads((Path(temporary) / 'gait/config.json').read_text(encoding='utf-8'))
            self.assertEqual('terminal-key', saved['apiKey'])
            self.assertEqual(1, len(requests))

    def test_interactive_powershell_without_utf8_setup(self):
        from winpty import PTY, WinptyError

        executable = str(Path(os.environ['GAIT_EXECUTABLE']).resolve()).replace("'", "''")
        for shell in ['powershell.exe', 'pwsh.exe']:
            for setup in ['', '[Console]::OutputEncoding=[Text.Encoding]::GetEncoding(936)']:
                with self.subTest(shell=shell, setup=setup):
                    terminal = PTY(160, 60, backend=0)
                    arguments = ' -NoProfile -NoExit'
                    if setup:
                        arguments += ' -EncodedCommand ' + base64.b64encode(setup.encode('utf-16-le')).decode('ascii')
                    terminal.spawn(shutil.which(shell), cmdline=arguments)
                    transcript = ''
                    sent = False
                    deadline = time.monotonic() + 15
                    try:
                        while time.monotonic() < deadline:
                            try:
                                chunk = terminal.read(blocking=False)
                            except (EOFError, WinptyError):
                                break
                            transcript += chunk
                            if '\x1b[6n' in chunk:
                                terminal.write('\x1b[1;1R')
                            if not sent and 'PS ' in transcript and '> ' in transcript:
                                terminal.write("& '" + executable + "' --help\r")
                                sent = True
                            if '问题：无。' in transcript:
                                break
                            time.sleep(0.02)
                        self.assertIn('结果：支持状态', transcript)
                        self.assertIn('用法：gait', transcript)
                        self.assertIn('问题：无。', transcript)
                    finally:
                        terminal.write('exit\r')
                        del terminal
