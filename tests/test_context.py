import json

from tests.test_agent import agent_server, call, reply
from tests.support import GaitFixture
from tests import test_agent


class Context(GaitFixture):
    chat = test_agent.Agent.chat

    def test_file_summary_uses_focus_and_hides_raw_content_from_main_context(self):
        (self.repo / 'feature.txt').write_text('FEATURE_SOURCE_MARKER\n' + 'implementation detail\n' * 100, encoding='utf-8')
        def summarize(body):
            self.assertNotIn('tools', body)
            serialized = json.dumps(body, ensure_ascii=False)
            self.assertIn('按提交主题归类', serialized)
            self.assertIn('FEATURE_SOURCE_MARKER', serialized)
            return reply('实现新功能，建议与相关测试归为同一提交。')
        with agent_server([
            call('git_summarize_file', dict(path='feature.txt', focus='按提交主题归类')),
            summarize, reply('已了解文件')
        ]) as (env, requests):
            result = self.chat(env, '了解新文件')
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(3, len(requests))
            source = json.dumps(requests[-1]['input'], ensure_ascii=False)
            self.assertNotIn('FEATURE_SOURCE_MARKER', source)
            self.assertIn('建议与相关测试', source)
    def test_paged_reads_advance_without_repeating_file_prefix(self):
        (self.repo / 'large.txt').write_text(''.join(f'line-{i:04}\n' for i in range(1, 401)), encoding='utf-8')
        with agent_server([
            call('git_read_files', dict(paths=['large.txt'], startLine=1, lineCount=30)),
            call('git_read_files', dict(paths=['large.txt'], startLine=31, lineCount=30), 'second'),
            reply('已检查')
        ]) as (env, requests):
            result = self.chat(env, '检查文件')
            self.assertEqual(0, result.returncode, result.stderr)
            first = json.loads(requests[1]['input'][-1]['output'])['result']['data']['files'][0]
            second = json.loads(requests[2]['input'][-1]['output'])['result']['data']['files'][0]
            self.assertIn('+line-0001', first['diff'])
            self.assertNotIn('+line-0031', first['diff'])
            self.assertEqual(31, first['next_line'])
            self.assertIn('+line-0031', second['diff'])
            self.assertNotIn('+line-0001', second['diff'])
            self.assertIn('large.txt', result.stderr)

    def test_summary_rejects_multiple_files(self):
        with agent_server([call('git_summarize_file', dict(paths=['one.txt', 'two.txt'])), reply('需要单个文件')]) as (env, requests):
            result = self.chat(env, '总结文件')
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(2, len(requests))
            self.assertIn('INVALID_ARGUMENT', requests[-1]['input'][-1]['output'])

    def test_large_file_summary_merges_chunks_without_source_in_main_context(self):
        (self.repo / 'large.txt').write_text('BEGIN_MARKER\n' + 'x' * 25000 + '\nEND_MARKER\n', encoding='utf-8')
        def first(body):
            source = json.dumps(body['input'])
            self.assertIn('BEGIN_MARKER', source)
            self.assertNotIn('END_MARKER', source)
            return reply('已发现开头标记。')
        def second(body):
            source = json.dumps(body['input'], ensure_ascii=False)
            self.assertIn('END_MARKER', source)
            self.assertIn('已发现开头标记', source)
            return reply('文件包含开头和结尾标记。')
        with agent_server([call('git_summarize_file', dict(path='large.txt')), first, second, reply('已总结')]) as (env, requests):
            result = self.chat(env, '总结文件')
            self.assertEqual(0, result.returncode, result.stderr)
            source = json.dumps(requests[-1]['input'], ensure_ascii=False)
            self.assertIn('文件包含开头和结尾标记', source)
            self.assertNotIn('BEGIN_MARKER', source)
            self.assertNotIn('END_MARKER', source)

    def test_context_compaction_preserves_goal_and_verified_write(self):
        (self.repo / 'large.txt').write_text(''.join(f'{i}: ' + 'x' * 160 + '\n' for i in range(600)), encoding='utf-8')
        def check_summary(body):
            self.assertNotIn('tools', body)
            return reply('已检查 large.txt 的前 400 行；已创建 feature 分支，尚未切换。下一步继续原目标，无需重读已检查部分。')
        def check_resumed(body):
            source = json.dumps(body['input'], ensure_ascii=False)
            self.assertIn('创建 feature 分支并检查大文件', source)
            self.assertIn('git_create_branch', source)
            self.assertIn('created_branch', source)
            self.assertLess(len(source), 20000)
            return reply('已完成')
        with agent_server([
            call('git_create_branch', dict(branch='feature')),
            call('git_read_files', dict(paths=['large.txt'], startLine=1, lineCount=200), 'read_1'),
            call('git_read_files', dict(paths=['large.txt'], startLine=201, lineCount=200), 'read_2'),
            check_summary, check_resumed
        ]) as (env, requests):
            result = self.chat(env, '创建 feature 分支并检查大文件')
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(5, len(requests))
            self.assertNotIn('CONTEXT_FULL', result.stdout + result.stderr)
            self.assertIn('feature', self.git('branch', '--list'))
