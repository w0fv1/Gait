import json
import os
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts.toolchain import gait_command
from tests.support import GaitFixture


def reply(text):
    return [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}]


def call(name, arguments=None, identifier='call_1'):
    return [{'type': 'function_call', 'call_id': identifier, 'name': name, 'arguments': json.dumps(arguments or {})}]


@contextmanager
def agent_server(outputs):
    requests = []
    queue = list(outputs)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            is_probe = 'JSON schema connection_probe:' in body.get('instructions', '')
            output = reply('{"ok":true}') if is_probe else (queue.pop(0) if queue else reply('done'))
            if callable(output):
                output = output(body)
            response = dict(id='response_' + str(len(requests)), status='completed', output=output)
            if body.get('stream'):
                events = []
                for item in output:
                    if item['type'] == 'message':
                        for part in item['content']:
                            if part['type'] == 'output_text':
                                events.append(dict(type='response.output_text.delta', delta=part['text']))
                events.append(dict(type='response.completed', response=response))
                data = ''.join('data: ' + json.dumps(item) + '\n\n' for item in events).encode()
            else:
                data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if body.get('stream') else 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield dict(GAIT_AI_API_KEY='test-key', GAIT_AI_MODEL='test-model', GAIT_AI_ENDPOINT=f'http://127.0.0.1:{server.server_port}/responses'), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class Agent(GaitFixture):
    def chat(self, connection, *args, stdin='', directory=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GAIT_AI_')}
        env.update(connection)
        env['APPDATA'] = str(self.repo / 'settings')
        return subprocess.run([*gait_command(), *args], cwd=directory or self.repo, input=stdin,
                              capture_output=True, encoding='utf-8', env=env, timeout=120)

    def test_direct_reply_outside_repository(self):
        outside = self.repo / 'outside'
        outside.mkdir()
        with agent_server([reply('ok')]) as (env, requests):
            env['GIT_CEILING_DIRECTORIES'] = str(self.repo)
            result = self.chat(env, '回复ok', directory=outside)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('ok\n', result.stdout)
            self.assertNotIn('text', requests[0])

    def test_each_invocation_is_independent_and_exits_after_one_reply(self):
        with agent_server([reply('ok'), reply('不知道')]) as (env, requests):
            result = self.chat(env, '我的口令 orchid-42，回复ok', stdin='这条不应读取\n')
            self.assertEqual('ok\n', result.stdout)
            restarted = self.chat(env, '我的口令是什么')
            self.assertEqual('不知道\n', restarted.stdout)
            self.assertEqual(1, len(requests[1]['input']))
            self.assertNotIn('orchid-42', json.dumps(requests[1]))
            self.assertFalse((self.repo / 'settings/gait/sessions.json').exists())
            self.assertNotIn('你>', result.stderr)

    def test_streamed_tool_preamble_is_not_reprinted_on_completion(self):
        with agent_server([reply('我先查看') + call('git_status'), reply('状态已确认')]) as (env, requests):
            result = self.chat(env, '查看状态')
            self.assertEqual('我先查看\n状态已确认\n', result.stdout)

    def test_stdin_is_one_complete_message_and_empty_input_exits(self):
        with agent_server([reply('收到')]) as (env, requests):
            result = self.chat(env, '--stdin', stdin='第一行\n第二行\n')
            self.assertEqual('收到\n', result.stdout)
            self.assertEqual('第一行\n第二行\n', requests[0]['input'][0]['content'].replace('\r\n', '\n'))
            empty = self.chat(env)
            self.assertEqual(2, empty.returncode)
            self.assertEqual(1, len(requests))

    def test_multiple_tools_then_natural_answer(self):
        (self.repo / 'tracked.txt').write_text('changed\n', encoding='utf-8')
        with agent_server([call('git_status'), call('git_diff', dict(paths=[], staged=False), 'call_2'), reply('tracked.txt 已修改。')]) as (env, requests):
            result = self.chat(env, '看看改了什么并总结')
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('tracked.txt 已修改。\n', result.stdout)
            self.assertIn('+changed', json.dumps(requests[2]['input']))
            self.assertEqual('function_call_output', requests[1]['input'][-1]['type'])
            changes = json.loads(requests[1]['input'][-1]['output'])['result']['data']['changes']
            self.assertTrue(any(item['path'] == 'tracked.txt' for item in changes))

    def test_invalid_tool_arguments_return_error_without_writing(self):
        with agent_server([call('git_stage', dict(paths=['../escape'])), reply('路径无效')]) as (env, requests):
            result = self.chat(env, '暂存修改')
            self.assertEqual('路径无效\n', result.stdout)
            self.assertIn('INVALID_ARGUMENT', requests[1]['input'][-1]['output'])
            self.assertEqual('', self.git('diff', '--cached', '--name-only'))

    def test_stage_and_commit_preserves_unstaged_changes(self):
        (self.repo / 'tracked.txt').write_text('staged\n', encoding='utf-8')
        (self.repo / 'other.txt').write_text('untracked\n', encoding='utf-8')
        with agent_server([call('git_stage', dict(paths=['tracked.txt'])), call('git_commit', dict(message='change tracked'), 'call_2'), reply('已提交')]) as (env, requests):
            result = self.chat(env, '暂存 tracked.txt 并提交，消息 change tracked')
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual('change tracked', self.git('log', '-1', '--format=%s'))
            self.assertIn('?? other.txt', self.git('status', '--porcelain'))

    def test_read_untracked_files_and_commit_separate_batches(self):
        (self.repo / 'feature.txt').write_text('new feature\n', encoding='utf-8')
        (self.repo / 'guide.txt').write_text('usage guide\n', encoding='utf-8')
        with agent_server([
            call('git_status'),
            call('git_read_files', dict(paths=['feature.txt', 'guide.txt']), 'read'),
            call('git_stage', dict(paths=['feature.txt']), 'stage_feature'),
            call('git_commit', dict(message='feat: add feature'), 'commit_feature'),
            call('git_stage', dict(paths=['guide.txt']), 'stage_guide'),
            call('git_commit', dict(message='docs: add usage guide'), 'commit_guide'),
            call('git_status', identifier='verify'), reply('已分两批提交')
        ]) as (env, requests):
            result = self.chat(env, '提交代码')
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            files = json.loads(requests[2]['input'][-1]['output'])['result']['data']['files']
            self.assertIn('+new feature', files[0]['diff'])
            self.assertIn('+usage guide', files[1]['diff'])
            self.assertEqual('feature.txt', self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD~1'))
            self.assertEqual('guide.txt', self.git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD'))
            self.assertEqual('', self.git('status', '--porcelain'))

    def test_read_files_rejects_outside_metadata_ignored_and_directory_paths(self):
        (self.repo / '.gitignore').write_text('ignored.txt\n', encoding='utf-8')
        (self.repo / 'ignored.txt').write_text('ignored\n', encoding='utf-8')
        outputs = [call('git_read_files', dict(paths=[path]), str(i)) for i, path in enumerate(['../escape', '.git/config', 'ignored.txt', '.'])]
        with agent_server(outputs + [reply('无法读取')]) as (env, requests):
            result = self.chat(env, '检查文件')
            self.assertEqual(0, result.returncode)
            for request in requests[1:]:
                self.assertEqual('failed', json.loads(request['input'][-1]['output'])['result']['status'])

    def test_branch_tools_and_unknown_tool(self):
        with agent_server([call('git_create_branch', dict(branch='feature')), call('git_switch_branch', dict(branch='feature'), 'call_2'), call('shell', dict(command='echo no'), 'call_3'), reply('已切换')]) as (env, requests):
            result = self.chat(env, '创建并切换 feature')
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual('feature', self.git('branch', '--show-current'))
            self.assertIn('UNKNOWN_TOOL', requests[-1]['input'][-1]['output'])

    def test_tool_error_outside_repository_is_returned_to_model(self):
        outside = self.repo / 'outside'
        outside.mkdir()
        with agent_server([call('git_status'), reply('这里不是 Git 仓库')]) as (env, requests):
            env['GIT_CEILING_DIRECTORIES'] = str(self.repo)
            result = self.chat(env, '查看状态', directory=outside)
            self.assertIn('NOT_REPOSITORY', requests[1]['input'][-1]['output'])
            self.assertEqual('这里不是 Git 仓库\n', result.stdout)

    def test_configuration_tool_saves_and_tests(self):
        with agent_server([call('configure', dict(apiKey='', model='', endpoint='')), reply('配置完成')]) as (env, requests):
            result = self.chat(env, '帮我配置')
            self.assertEqual('配置完成\n', result.stdout)
            saved = json.loads((self.repo / 'settings/gait/config.json').read_text(encoding='utf-8'))
            self.assertEqual(env['GAIT_AI_API_KEY'], saved['apiKey'])
            self.assertTrue(json.loads(requests[-1]['input'][-1]['output'])['result']['data']['connection_tested'])

    def test_strict_arguments_reject_wrong_types(self):
        with agent_server([call('git_stage', dict(paths='tracked.txt')), reply('参数错误')]) as (env, requests):
            result = self.chat(env, '暂存')
            self.assertIn('INVALID_ARGUMENT', requests[1]['input'][-1]['output'])
            self.assertEqual(0, result.returncode)

    def test_external_change_between_observation_and_write_is_rejected(self):
        def mutate(body):
            (self.repo / 'tracked.txt').write_text('external change\n', encoding='utf-8')
            return call('git_stage', dict(paths=['tracked.txt']), 'call_2')
        with agent_server([call('git_status'), mutate, reply('仓库发生变化')]) as (env, requests):
            self.chat(env, '查看并暂存 tracked.txt')
            self.assertIn('STATE_CHANGED', requests[-1]['input'][-1]['output'])
            self.assertEqual('', self.git('diff', '--cached', '--name-only'))

    def test_unknown_fields_and_duplicate_calls_never_write(self):
        with agent_server([call('git_stage', dict(paths=['tracked.txt'], extra=True)), reply('字段错误')]) as (env, requests):
            self.chat(env, '暂存')
            self.assertIn('INVALID_ARGUMENT', requests[-1]['input'][-1]['output'])
        with agent_server([call('git_stage', dict(paths=['tracked.txt'])) * 2]) as (env, requests):
            result = self.chat(env, '暂存')
            self.assertNotEqual(0, result.returncode)
            self.assertEqual('', self.git('diff', '--cached', '--name-only'))

    def test_loop_budget_and_json_events(self):
        with agent_server([call('git_status', identifier='call_' + str(i)) for i in range(64)]) as (env, requests):
            result = self.chat(env, '--format', 'json', '循环')
            self.assertEqual(64, len(requests))
            self.assertIn('TOOL_LIMIT', result.stdout)
            self.assertEqual('error', json.loads(result.stdout)['type'])

    def test_old_session_file_is_not_read_or_changed(self):
        path = self.repo / 'settings/gait/sessions.json'
        path.parent.mkdir(parents=True)
        path.write_text('invalid old session data', encoding='utf-8')
        with agent_server([reply('ok')]) as (env, requests):
            result = self.chat(env, '回复ok')
            self.assertEqual('ok\n', result.stdout)
            self.assertEqual(1, len(requests[0]['input']))
            self.assertEqual('invalid old session data', path.read_text(encoding='utf-8'))

    def test_json_contains_one_answer_and_tool_results(self):
        with agent_server([reply('我先查看') + call('git_status'), reply('完成')]) as (env, requests):
            result = self.chat(env, '--format', 'json', '查看状态')
            value = json.loads(result.stdout)
            self.assertEqual('完成', value['text'])
            self.assertEqual(1, len(value['tools']))
            self.assertEqual('git_status', value['tools'][0]['name'])
