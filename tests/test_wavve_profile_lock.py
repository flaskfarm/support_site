"""Framework-free regression tests; all credentials and transport are synthetic."""
import ast
import copy
import json
import sys
import types
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch
from typing import Any

SOURCE = Path(__file__).parents[1] / 'mod_site.py'
PIN = 'synthetic-pin'


class Settings:
    def __init__(self, accounts):
        self.values = {'site_wavve_credentials': json.dumps(accounts)}
        self.writes = 0
        self.reads = 0

    def get(self, key):
        self.reads += 1
        return self.values.get(key, '')

    def set(self, key, value):
        self.values[key] = value
        self.writes += 1

    def get_bool(self, key):
        return key == 'site_wavve_credential_auto_refresh'

    def get_list(self, key):
        return []

    def get_int(self, key):
        return 600

    def accounts(self):
        return json.loads(self.values['site_wavve_credentials'])


def hooks(settings=None):
    tree = ast.parse(SOURCE.read_text())
    nodes: list[ast.stmt] = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name.startswith('_patch_wavve_profile_lock_')]
    namespace: dict[str, Any] = {'urllib': urllib, 'json': json,
                 'P': types.SimpleNamespace(ModelSetting=settings)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace


class Response:
    def __init__(self, status=200):
        self.status_code = status


class Session:
    def __init__(self, pin=None):
        self.pin = pin
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        payload = kwargs.get('json', {})
        rejected = (payload.get('type') == 'credential' and self.pin
                    and payload.get('profile_lock_password') != self.pin)
        return Response(403 if rejected else 200)


class API:
    """Match the installed API's session replacement and callback contract."""
    def __init__(self, pins, callback=None):
        self.accounts = {
            name: types.SimpleNamespace(session=Session(pin), id='synthetic-id',
                                        password='synthetic-password', profile='0',
                                        credential='synthetic-old', device_id='synthetic-device')
            for name, pin in pins.items()
        }
        self.pins = pins
        self.requests = []
        self.raise_error = False
        self._update_account_callback: Any = callback
        self.credential_auto_refresh = False

    def refresh_credential(self, name, run_callback=True):
        account = self.accounts[name]
        if self.raise_error:
            raise RuntimeError('synthetic failure')
        response = account.session.request(
            'POST', 'https://account.example/v1/signin', json={'type': 'credential'})
        self.requests.append(account.session.calls[-1])
        if response.status_code != 200:
            return False
        account.credential = f'synthetic-new-{len(self.requests)}'
        account.device_id = f'synthetic-device-{len(self.requests)}'
        account.session = Session(self.pins[name])
        if run_callback and callable(self._update_account_callback):
            self._update_account_callback(self.accounts)
        return True


def native_callback(settings, fail_after_write=False):
    def update(accounts):
        # The installed SupportWavve.update_account rebuilds this fixed field set.
        values = {name: {key: getattr(account, key)
                         for key in ('id', 'password', 'profile', 'credential', 'device_id')}
                  for name, account in accounts.items()}
        settings.set('site_wavve_credentials', json.dumps(values))
        if fail_after_write:
            raise RuntimeError('synthetic downstream callback error')
        return 'synthetic-callback-result'
    return update


class ProfileLockTest(unittest.TestCase):
    def setUp(self):
        self.settings = Settings({'test': {'lock_password': PIN}})
        self.hooks = hooks(self.settings)

    def configure(self, api, pins, settings_hook=False):
        for name, account in api.accounts.items():
            self.hooks['_patch_wavve_profile_lock_session'](account, pins.get(name))
        self.hooks['_patch_wavve_profile_lock_refresh'](api, pins)
        if settings_hook:
            self.hooks['_patch_wavve_profile_lock_settings'](api, pins)

    def test_second_and_third_refresh_survive_session_replacement(self):
        api = API({'test': PIN})
        self.configure(api, api.pins)
        for _ in range(3):
            self.assertTrue(api.refresh_credential('test'))
        self.assertEqual(3, len(api.requests))
        self.assertTrue(all(call[2]['json']['profile_lock_password'] == PIN for call in api.requests))

    def test_prior_session_only_implementation_reproduces_failure(self):
        api = API({'test': PIN})
        self.hooks['_patch_wavve_profile_lock_session'](api.accounts['test'], PIN)
        self.assertTrue(api.refresh_credential('test'))
        self.assertFalse(api.refresh_credential('test'))

    def test_native_callback_without_fix_drops_pin(self):
        api = API({'test': PIN}, native_callback(self.settings))
        self.configure(api, api.pins)
        self.assertTrue(api.refresh_credential('test'))
        self.assertNotIn('lock_password', self.settings.accounts()['test'])

    def test_callback_keeps_pin_and_new_credential(self):
        api = API({'test': PIN}, native_callback(self.settings))
        self.configure(api, api.pins, settings_hook=True)
        for index in range(1, 4):
            self.assertTrue(api.refresh_credential('test'))
            saved = self.settings.accounts()['test']
            self.assertEqual(PIN, saved['lock_password'])
            self.assertEqual(f'synthetic-new-{index}', saved['credential'])
            self.assertEqual(f'synthetic-device-{index}', saved['device_id'])

    def test_run_callback_false_is_preserved_positional_and_keyword(self):
        api = API({'test': PIN}, native_callback(self.settings))
        self.configure(api, api.pins, settings_hook=True)
        writes = self.settings.writes
        self.assertTrue(api.refresh_credential('test', False))
        self.assertTrue(api.refresh_credential('test', run_callback=False))
        self.assertEqual(writes, self.settings.writes)

    def test_separate_accounts_keep_their_own_pins(self):
        pins = {'a': 'synthetic-pin-a', 'b': 'synthetic-pin-b'}
        self.settings.values['site_wavve_credentials'] = json.dumps(
            {name: {'lock_password': pin} for name, pin in pins.items()})
        api = API(pins, native_callback(self.settings))
        self.configure(api, pins, settings_hook=True)
        for _ in range(2):
            for name, pin in pins.items():
                self.assertTrue(api.refresh_credential(name))
                self.assertEqual(pin, self.settings.accounts()[name]['lock_password'])

    def test_unlocked_account_unchanged(self):
        api = API({'test': None})
        reads = self.settings.reads
        self.configure(api, {}, settings_hook=True)
        for _ in range(2):
            self.assertTrue(api.refresh_credential('test'))
        self.assertNotIn('profile_lock_password', api.requests[-1][2]['json'])
        self.assertEqual(reads, self.settings.reads)

    def test_query_string_path_is_matched(self):
        account = types.SimpleNamespace(session=Session(PIN))
        self.hooks['_patch_wavve_profile_lock_session'](account, PIN)
        response = account.session.request('POST', 'https://account.example/v1/signin?test=1',
                                           json={'type': 'credential'})
        self.assertEqual(200, response.status_code)

    def test_empty_upstream_field_uses_saved_pin_without_mutating_input(self):
        for value in ['', None]:
            account = types.SimpleNamespace(session=Session(PIN))
            self.hooks['_patch_wavve_profile_lock_session'](account, PIN)
            payload = {'type': 'credential', 'profile_lock_password': value}
            response = account.session.request('POST', 'https://account.example/v1/signin', json=payload)
            self.assertEqual(200, response.status_code)
            self.assertEqual(value, payload['profile_lock_password'])

    def test_explicit_payload_pin_is_not_overwritten(self):
        account = types.SimpleNamespace(session=Session())
        self.hooks['_patch_wavve_profile_lock_session'](account, PIN)
        payload = {'type': 'credential', 'profile_lock_password': 'synthetic-explicit-pin'}
        account.session.request('POST', 'https://account.example/v1/signin', json=payload)
        self.assertEqual(payload, account.session.calls[-1][2]['json'])

    def test_other_requests_are_not_modified(self):
        account = types.SimpleNamespace(session=Session())
        self.hooks['_patch_wavve_profile_lock_session'](account, PIN)
        for method, path, payload in [('GET', '/v1/signin', {'type': 'credential'}),
                                     ('POST', '/v1/signin/wavve', {'type': 'wavve'}),
                                     ('POST', '/other', {'type': 'credential'})]:
            account.session.request(method, 'https://account.example' + path, json=payload)
            self.assertNotIn('profile_lock_password', account.session.calls[-1][2]['json'])

    def test_reapplying_hooks_does_not_duplicate_requests_or_callbacks(self):
        api = API({'test': PIN}, native_callback(self.settings))
        self.configure(api, api.pins, settings_hook=True)
        callback = api._update_account_callback
        self.configure(api, api.pins, settings_hook=True)
        self.assertIs(callback, api._update_account_callback)
        self.assertTrue(api.refresh_credential('test'))
        self.assertEqual(1, len(api.requests))

    def test_unknown_account_preserves_native_failure(self):
        api = API({})
        self.configure(api, {})
        with self.assertRaises(KeyError):
            api.refresh_credential('missing')

    def test_error_is_not_converted_to_success(self):
        api = API({'test': PIN})
        self.configure(api, api.pins)
        api.raise_error = True
        with self.assertRaises(RuntimeError):
            api.refresh_credential('test')

    def test_callback_error_does_not_discard_pin_or_hide_error(self):
        api = API({'test': PIN}, native_callback(self.settings, fail_after_write=True))
        self.configure(api, api.pins, settings_hook=True)
        with self.assertRaisesRegex(RuntimeError, 'synthetic downstream'):
            api.refresh_credential('test')
        self.assertEqual(PIN, self.settings.accounts()['test']['lock_password'])

    def test_settings_hook_preserves_callback_return_value(self):
        api = API({'test': PIN}, native_callback(self.settings))
        self.configure(api, api.pins, settings_hook=True)
        self.assertEqual('synthetic-callback-result', api._update_account_callback(api.accounts))

    def test_deleted_account_is_not_resurrected(self):
        api = API({'test': PIN}, native_callback(self.settings))
        self.configure(api, api.pins, settings_hook=True)
        api.accounts.clear()
        api._update_account_callback(api.accounts)
        self.assertEqual({}, self.settings.accounts())

    def test_initialization_callback_pin_loss_is_restored(self):
        self.settings.values['site_wavve_credentials'] = json.dumps({'test': {'credential': 'synthetic-new'}})
        api = API({'test': PIN}, native_callback(self.settings))
        self.hooks['_patch_wavve_profile_lock_settings'](api, {'test': PIN})
        self.assertEqual(PIN, self.settings.accounts()['test']['lock_password'])
        self.assertEqual('synthetic-new', self.settings.accounts()['test']['credential'])

    def test_global_transport_class_is_not_modified(self):
        request = Session.request
        api = API({'test': PIN})
        self.configure(api, api.pins)
        self.assertIs(request, Session.request)

    def test_actual_initializer_restores_settings_and_survives_restart(self):
        tree = ast.parse(SOURCE.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ModuleSite')
        init = copy.deepcopy(next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__wavve_init'))
        init.name = 'initialize_candidate'
        namespace = self.hooks.copy()
        namespace['__package__'] = 'synthetic_support_site'
        exec(compile(ast.Module(body=[init], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        settings = self.settings

        class Support:
            api: Any = None

            @classmethod
            def initialize(support, credentials, *args):
                values = json.loads(credentials)
                self.assertTrue(all('lock_password' not in value for value in values.values()))
                support.api = API({name: PIN for name in values}, native_callback(settings))
                support.api._update_account_callback(support.api.accounts)

        package = types.ModuleType('synthetic_support_site')
        package.__path__ = []
        setattr(package, 'SupportWavve', Support)
        site = types.ModuleType('synthetic_support_site.site_wavve')
        setattr(site, 'SiteWavve', types.SimpleNamespace(initialize=lambda *args: None))
        with patch.dict(sys.modules, {'synthetic_support_site': package,
                                     'synthetic_support_site.site_wavve': site}):
            for _ in range(3):
                # Fresh initialization represents an application restart reading saved JSON.
                namespace['initialize_candidate'](None)
                self.assertTrue(Support.api.credential_auto_refresh)
                self.assertEqual(PIN, settings.accounts()['test']['lock_password'])
                self.assertTrue(Support.api.refresh_credential('test'))
                self.assertTrue(Support.api.refresh_credential('test'))
                self.assertEqual(PIN, settings.accounts()['test']['lock_password'])

    def test_manual_login_keeps_saved_pin(self):
        tree = ast.parse(SOURCE.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ModuleSite')
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'process_command')
        source = ast.unparse(fn)
        self.assertIn("account_config.get('lock_password')", source)
        self.assertNotIn("account_config.pop('lock_password'", source)


if __name__ == '__main__':
    unittest.main()
