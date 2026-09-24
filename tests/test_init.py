import json
import os
import subprocess

from tests.support import GaitFixture, gait_command, probe_server


class Initialization(GaitFixture):
    def initialize(self, text, extra=()):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('GAIT_AI_')}
        environment['APPDATA'] = str(self.repo / 'settings')
        result = subprocess.run([*gait_command(), '--init', '--format', 'json', *extra], input=text,
                                encoding='utf-8', capture_output=True, env=environment, timeout=90)
        self.assertTrue(result.stdout, result.stderr)
        return result, json.loads(result.stdout)

    def test_initializes_without_existing_configuration(self):
        with probe_server() as (environment, requests):
            result, value = self.initialize('wizard-key\nwizard-model\n' + environment['GAIT_AI_ENDPOINT'] + '\n')
            self.assertEqual(0, result.returncode, value)
            self.assertTrue(value['result']['data']['config_saved'])
            self.assertIn('API 密钥', result.stderr)
            self.assertIn('模型名称', result.stderr)
            self.assertIn('接口地址', result.stderr)
            self.assertNotIn('wizard-key', result.stdout + result.stderr)
            self.assertEqual(1, len(requests))
            self.assertEqual({'type': 'json_object'}, requests[0]['text']['format'])
            saved = json.loads((self.repo / 'settings/gait/config.json').read_text(encoding='utf-8'))
            self.assertEqual('wizard-key', saved['apiKey'])

    def test_enter_retains_existing_values(self):
        with probe_server() as (environment, requests):
            path = self.repo / 'settings/gait/config.json'
            path.parent.mkdir(parents=True)
            existing = dict(apiKey='existing-secret', model='existing-model', endpoint=environment['GAIT_AI_ENDPOINT'])
            path.write_text(json.dumps(existing), encoding='utf-8')
            result, value = self.initialize('\r\n\r\n\r\n')
            self.assertEqual(0, result.returncode, value)
            self.assertEqual(existing, json.loads(path.read_text(encoding='utf-8')))
            self.assertNotIn('existing-secret', result.stdout + result.stderr)
            self.assertIn('API 密钥 [******]: ', result.stderr)
            self.assertIn('模型名称 [existing-model]: ', result.stderr)
            self.assertIn('接口地址 [' + existing['endpoint'] + ']: ', result.stderr)

    def test_eof_and_conflicting_arguments_do_not_write(self):
        result, value = self.initialize('')
        self.assertEqual(2, result.returncode, value)
        self.assertEqual('CONFIG_CANCELLED', value['issues'][0]['code'])
        self.assertFalse((self.repo / 'settings/gait/config.json').exists())
        result, value = self.initialize('', ('--stdin',))
        self.assertEqual(2, result.returncode, value)
        self.assertEqual('INVALID_ARGUMENT', value['issues'][0]['code'])

    def test_blank_required_value_reprompts_and_large_field_is_rejected(self):
        with probe_server() as (environment, requests):
            result, value = self.initialize('\nkey\nmodel\n' + environment['GAIT_AI_ENDPOINT'] + '\n')
            self.assertEqual(0, result.returncode, value)
            self.assertIn('此项不能为空', result.stderr)
        result, value = self.initialize('x' * 4097 + '\n')
        self.assertEqual(2, result.returncode, value)
        self.assertEqual('INVALID_ARGUMENT', value['issues'][0]['code'])

    def test_failed_test_does_not_save(self):
        with probe_server(probe_status=401) as (environment, requests):
            result, value = self.initialize('key\nmodel\n' + environment['GAIT_AI_ENDPOINT'] + '\n')
            self.assertEqual(2, result.returncode, value)
            self.assertEqual('CONFIG_TEST_FAILED', value['issues'][0]['code'])
            self.assertFalse((self.repo / 'settings/gait/config.json').exists())

    def test_provider_error_is_explained_without_exposing_key(self):
        error = dict(code='responses_feature_not_supported', message="text.format type 'json_schema' is not supported; secret-test-key")
        with probe_server(probe_status=400, probe_error=error) as (environment, requests):
            result, value = self.initialize('secret-test-key\nmodel\n' + environment['GAIT_AI_ENDPOINT'] + '\n')
            self.assertEqual(2, result.returncode, value)
            self.assertIn('HTTP 400', value['issues'][0]['message'])
            self.assertIn('json_schema', value['issues'][0]['message'])
            self.assertNotIn('secret-test-key', result.stdout + result.stderr)
            self.assertFalse((self.repo / 'settings/gait/config.json').exists())

    def test_base_url_is_saved_as_responses_endpoint(self):
        with probe_server() as (environment, requests):
            endpoint = environment['GAIT_AI_ENDPOINT'].replace('/responses', '/v1/responses')
            result, value = self.initialize('key\nmodel\n' + endpoint.removesuffix('/responses') + '/\n')
            self.assertEqual(0, result.returncode, value)
            saved = json.loads((self.repo / 'settings/gait/config.json').read_text(encoding='utf-8'))
            self.assertEqual(endpoint, saved['endpoint'])
