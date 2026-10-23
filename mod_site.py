import json
import sqlite3
import urllib.parse

from .setup import *


def _patch_wavve_profile_lock_session(account, lock_password):
    if not lock_password or getattr(account.session, '_profile_lock_patched', False):
        return
    original_request = account.session.request

    def request_with_profile_lock(method, url, **kwargs):
        if method.upper() == 'POST' and urllib.parse.urlsplit(url).path.rstrip('/') == '/v1/signin':
            payload = kwargs.get('json')
            if isinstance(payload, dict) and payload.get('type') == 'credential':
                payload = dict(payload)
                if not payload.get('profile_lock_password'):
                    payload['profile_lock_password'] = lock_password
                kwargs['json'] = payload
        return original_request(method, url, **kwargs)

    account.session.request = request_with_profile_lock
    account.session._profile_lock_patched = True


def _patch_wavve_profile_lock_refresh(api, lock_passwords):
    """Wavve replaces account.session after login; patch each replacement too."""
    if getattr(api, '_profile_lock_refresh_patched', False):
        return
    original_refresh = api.refresh_credential

    def refresh_with_profile_lock(name, *args, **kwargs):
        account = api.accounts.get(name)
        lock_password = lock_passwords.get(name)
        if account is not None:
            _patch_wavve_profile_lock_session(account, lock_password)
        try:
            return original_refresh(name, *args, **kwargs)
        finally:
            account = api.accounts.get(name)
            if account is not None:
                _patch_wavve_profile_lock_session(account, lock_password)

    api.refresh_credential = refresh_with_profile_lock
    api._profile_lock_refresh_patched = True


def _patch_wavve_profile_lock_settings(api, lock_passwords):
    """Keep saved PINs when the native callback rebuilds account JSON."""
    if not any(lock_passwords.values()) or getattr(api, '_profile_lock_settings_patched', False):
        return

    def restore_lock_passwords():
        accounts_config = json.loads(P.ModelSetting.get('site_wavve_credentials') or '{}')
        changed = False
        for name, lock_password in lock_passwords.items():
            account_config = accounts_config.get(name)
            if lock_password and isinstance(account_config, dict) and account_config.get('lock_password') != lock_password:
                account_config['lock_password'] = lock_password
                changed = True
        if changed:
            P.ModelSetting.set(
                'site_wavve_credentials',
                json.dumps(accounts_config, ensure_ascii=False, separators=(',', ':'), indent=2),
            )

    original_update = getattr(api, '_update_account_callback', None)
    if callable(original_update):
        def update_with_profile_lock(*args, **kwargs):
            try:
                return original_update(*args, **kwargs)
            finally:
                restore_lock_passwords()

        api._update_account_callback = update_with_profile_lock
        api._profile_lock_settings_patched = True
    # Initialization itself can invoke the native callback before hooks exist.
    restore_lock_passwords()


class ModuleSite(PluginModuleBase):
    db_default = {
        'db_version' : '1.2',
        "site_wavve_credential": "",
        "site_wavve_credentials": "",
        "site_wavve_use_proxy": "False",
        "site_wavve_proxy_url": "",
        "site_wavve_profile":'{"id": "", "password": "", "profile": "0", "device_id": ""}',
        'site_wavve_patterns_episode': '^(?!.*(티저|예고|특집)).*?(?P<episode>\d+)$',
        'site_wavve_patterns_title': '^(?P<title>.*)$',
        'site_wavve_patterns_season': '',
        'site_wavve_headers': '',
        'site_wavve_use_cache' : 'False',
        'site_wavve_cache_expiry' : '60',
        'site_wavve_filename_contentid' : 'False',
        'site_wavve_filename_contentid_list' : '',
        'site_wavve_credential_ttl' : '21600',
        'site_wavve_credential_cooldown' : '600',
        'site_wavve_credential_auto_refresh' : 'True',
        'site_daum_cookie' : '',
        'site_daum_use_proxy' : 'False',
        'site_daum_proxy_url' : '',
        'site_daum_headers': '',
        'site_daum_use_cache' : 'False',
        'site_daum_cache_expiry' : '60',
        'site_daum_test' : '오버 더 레인보우',
        'site_tving_id' : '',
        'site_tving_pw' : '',
        'site_tving_login_type' : 'cjone',
        'site_tving_token' : '',
        'site_tving_deviceid' : '',
        'site_tving_use_proxy' : 'False',
        'site_tving_proxy_url' : '',
        'site_tving_use_cache' : 'False',
        'site_tving_cache_expiry' : '60',
        'site_tving_headers': '',
        'site_naver_key': '',
        'site_imgur_client_id': '',
        'site_imgur_client_secret': '',
        'site_imgur_access_token': '',
        'site_imgur_refresh_token': '',
        'site_imgur_account_username': '',
        'site_imgur_account_id': '',
        'site_watcha_cookie' : '',
        'site_watcha_use_proxy' : 'False',
        'site_watcha_proxy_url' : '',
        'site_watcha_headers': '{"X-Frograms-Client-Version":"2.1.0","X-Frograms-Client":"Galaxy-Web-App","X-Frograms-App-Code":"Galaxy","X-Frograms-Galaxy-Language":"ko","X-Frograms-Version":"2.1.0","X-Frograms-Device-Identifier":""}',
        'site_watcha_use_cache' : 'False',
        'site_watcha_cache_expiry' : '60',
        'site_naver_login_client_id' : '',
        'site_naver_login_client_secret' : '',
        'site_naver_login_refresh_token' : '',
        'site_naver_login_refresh_token_time' : '',
        'site_naver_login_access_token' : '',
        'site_naver_login_access_token_time' : '',
        'site_common_loose_match_shows' : '',
        'site_common_headers' : '{"sec-fetch-user":"?1","sec-fetch-dest":"document","priority":"u=0, i","accept-language":"ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7","accept-encoding":"gzip, br","sec-ch-ua":"\"Chromium\";v=\"124\", \"Google Chrome\";v=\"124\", \"Not-A.Brand\";v=\"99\"","sec-ch-ua-mobile":"?0","sec-ch-ua-platform":"\"macOS\"","upgrade-insecure-requests":"1","user-agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36","accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7","sec-fetch-site":"none","sec-fetch-mode":"navigate"}',
        'site_tmdb_api_key' : '',
        'site_tmdb_image_sizes' : '',
    }

    def __init__(self, P):
        super(ModuleSite, self).__init__(P, name='site', first_menu='setting')

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret':'success'}
        if command == 'tving_login':
            from . import SupportTving
            login_ret = SupportTving.do_login(arg1, arg2, arg3)
            if login_ret is None:
                ret['ret'] = 'warning'
                ret['msg'] = "로그인 실패!"
            elif login_ret.get('code') != '0000' or not login_ret.get('token'):
                ret['ret'] = 'warning'
                msg = login_ret.get('detailMessage') or login_ret.get('message') or login_ret.get('code')
                ret['msg'] = str(msg).replace('\n', '<br>') if msg else "로그인 실패!"
            else:
                ret['token'] = login_ret.get('token')
                ret['deviceid'] = login_ret.get('deviceid')
                P.ModelSetting.set('site_tving_login_type', arg3)
                if ret['token']:
                    P.ModelSetting.set('site_tving_token', ret['token'])
                if ret['deviceid'] and not P.ModelSetting.get('site_tving_deviceid'):
                    P.ModelSetting.set('site_tving_deviceid', ret['deviceid'])
                self.__tving_init()
                ret['msg'] = "로그인 성공!<br>인증 정보를 저장했습니다"
        elif command == 'tving_deviceid':
            from . import SupportTving
            device_list = SupportTving.get_device_list()
            if device_list is None:
                ret['ret'] = False
            else:
                ret['ret'] = True
                ret['json'] = device_list
            return jsonify(ret)
        elif command == 'wavve_login':
            try:
                from . import SupportWavve
                accounts_config = json.loads(arg1)
                lock_passwords = {
                    name: account_config.get('lock_password')
                    for name, account_config in accounts_config.items()
                }
                P.ModelSetting.set(
                    'site_wavve_credentials',
                    json.dumps(accounts_config, ensure_ascii=False, separators=(',', ':'), indent=2),
                )
                self.__wavve_init()

                def login_with_lock(account, lock_password):
                    headers = {}
                    if account.device_id:
                        headers['wavve-device-id'] = account.device_id
                    response = account.session.request(
                        'POST',
                        f'{SupportWavve.api.account_url}/v1/signin/wavve',
                        headers=headers,
                        json={
                            'type': 'wavve',
                            'id': account.id,
                            'password': account.password,
                            'device': 'pc',
                        },
                    )
                    if not 200 <= response.status_code < 300:
                        logger.error('Wavve 1단계 로그인 실패: %s', response.status_code)
                        return False
                    data = response.json()
                    phase1_credential = data.get('credential')
                    if data.get('device_id'):
                        account.device_id = data['device_id']
                    if not all((phase1_credential, account.device_id)):
                        logger.error('Wavve 2단계 로그인에 필요한 정보 부족')
                        return False
                    response = account.session.request(
                        'POST',
                        f'{SupportWavve.api.account_url}/v1/signin',
                        headers={'wavve-device-id': account.device_id},
                        params={'credential': phase1_credential},
                        json={
                            'type': 'credential',
                            'id': phase1_credential,
                            'profile': account.profile or '0',
                            'device': 'pc',
                            'profile_lock_password': lock_password,
                        },
                    )
                    if not 200 <= response.status_code < 300:
                        try:
                            error_data = response.json()
                            detail = error_data.get('data') or {}
                            logger.error(
                                'Wavve 잠금 프로필 로그인 실패: status=%s code=%s detail=%s',
                                response.status_code,
                                detail.get('code') or error_data.get('code'),
                                detail.get('description') or error_data.get('message'),
                            )
                        except Exception:
                            logger.error('Wavve 잠금 프로필 로그인 실패: %s', response.status_code)
                        return False
                    data = response.json()
                    if not data.get('credential'):
                        logger.error('Wavve 잠금 프로필 credential 없음')
                        return False
                    account.credential = data['credential']
                    if data.get('device_id'):
                        account.device_id = data['device_id']
                    return True

                success = []
                failed = []
                for name, account in SupportWavve.api.accounts.items():
                    lock_password = lock_passwords.get(name)
                    logged_in = (
                        login_with_lock(account, lock_password)
                        if lock_password
                        else SupportWavve.do_login(name)
                    )
                    if logged_in:
                        success.append(name)
                        accounts_config[name]['credential'] = account.credential
                        accounts_config[name]['device_id'] = account.device_id
                    else:
                        failed.append(name)
                saved_credentials = json.dumps(
                    accounts_config, ensure_ascii=False, separators=(',', ':'), indent=2
                )
                P.ModelSetting.set('site_wavve_credentials', saved_credentials)
                self.__wavve_init()
                ret['credentials'] = saved_credentials
                msg = f"성공: {','.join(success)}<br>실패: {','.join(failed)}"
                ret['ret'] = 'success'
                ret['msg'] = msg
            except Exception as e:
                logger.error(f'Exception:{str(e)}')
                logger.error(traceback.format_exc())
                ret['ret'] = 'error'
                ret['msg'] = f"에러: {str(e)}"
        elif command == 'imgur_upload':
            from .tool_imgur import ToolImgur
            tmp = ToolImgur.upload_from_paste(req.form['url'])
            if tmp != None:
                ret['url'] = tmp
            else:
                ret['msg'] = '실패'
                ret['ret'] = 'error'
        elif command == 'naverlogin_callback_process':
            from . import ToolNaverCafe
            ret = ToolNaverCafe.do_login(arg1, arg2)
        return jsonify(ret)

    def process_normal(self, sub, req):
        try:
            if sub == 'imgur_callback':
                P.ModelSetting.set('site_imgur_access_token', req.args.get('access_token'))
                P.ModelSetting.set('site_imgur_refresh_token', req.args.get('refresh_token'))
                P.ModelSetting.set('site_imgur_account_username', req.args.get('account_username'))
                P.ModelSetting.set('site_imgur_account_id', req.args.get('account_id'))
                return "토큰을 저장하였습니다.\n설정을 새로고침하세요"
        except Exception as e:
            P.logger.error(f"Exception:{str(e)}")
            P.logger.error(traceback.format_exc())
            return f"{str(e)}"

    def setting_save_after(self, change_list):
        flag_wavve = False
        flag_daum = False
        flag_tving = False
        flag_naver = False
        flag_watcha = False
        flag_tmdb = False
        for item in change_list:
            if item.startswith('site_wavve_'):
                flag_wavve = True
            if item != 'site_daum_test' and item.startswith('site_daum_'):
                flag_daum = True
            if item.startswith('site_tving_'):
                flag_tving = True
            if item.startswith('site_naver_key'):
                flag_naver = True
            if item.startswith('site_watcha_'):
                flag_watcha = True
            if item.startswith('site_tmdb_'):
                flag_tmdb = True

        self.__util_init()

        if flag_wavve:
            self.__wavve_init()
        if flag_daum:
            self.__daum_init()
        if flag_tving:
            self.__tving_init()
        if flag_naver:
            self.__naver_init()
        if flag_watcha:
            self.__watcha_init()
        if flag_tmdb:
            self.__tmdb_init()
        

    def plugin_load(self):
        self.__util_init()
        self.__wavve_init()
        self.__daum_init()
        self.__tving_init()
        self.__naver_init()
        self.__watcha_init()
        self.__tmdb_init()

    def plugin_load_celery(self):
        '''
        셀러리로 플러그인 로딩시 사이트 정보 초기화
        '''
        self.plugin_load()

    def plugin_unload(self):
        """override"""
        from . import SupportWavve
        if api := getattr(SupportWavve, 'api', None):
            api.close_sessions()

    def __wavve_init(self):
        from . import SupportWavve
        accounts_config = json.loads(P.ModelSetting.get('site_wavve_credentials') or '{}')
        lock_passwords = {
            name: account_config.get('lock_password')
            for name, account_config in accounts_config.items()
        }
        runtime_accounts = json.loads(json.dumps(accounts_config))
        for account_config in runtime_accounts.values():
            account_config.pop('lock_password', None)
        credential_auto_refresh = P.ModelSetting.get_bool('site_wavve_credential_auto_refresh')
        SupportWavve.initialize(
            json.dumps(runtime_accounts, ensure_ascii=False, separators=(',', ':')),
            P.ModelSetting.get_list('site_wavve_patterns_episode'),
            P.ModelSetting.get_list('site_wavve_patterns_title'),
            P.ModelSetting.get_list('site_wavve_patterns_season'),
            P.ModelSetting.get('site_wavve_headers'),
            P.ModelSetting.get('site_common_headers'),
            False,
            P.ModelSetting.get_int('site_wavve_credential_ttl'),
            P.ModelSetting.get_int('site_wavve_credential_cooldown'),
            P.ModelSetting.get_bool('site_wavve_use_cache'),
            P.ModelSetting.get_int('site_wavve_cache_expiry')
        )
        for name, account in SupportWavve.api.accounts.items():
            _patch_wavve_profile_lock_session(account, lock_passwords.get(name))
        _patch_wavve_profile_lock_refresh(SupportWavve.api, lock_passwords)
        _patch_wavve_profile_lock_settings(SupportWavve.api, lock_passwords)
        SupportWavve.api.credential_auto_refresh = credential_auto_refresh
        from .site_wavve import SiteWavve
        SiteWavve.initialize(
            P.ModelSetting.get_bool('site_wavve_use_cache'),
            P.ModelSetting.get_int('site_wavve_cache_expiry')
        )

    def __daum_init(self):
        from . import SiteDaum
        SiteDaum.initialize(
            P.ModelSetting.get('site_daum_cookie'),
            P.ModelSetting.get_bool('site_daum_use_proxy'),
            P.ModelSetting.get('site_daum_proxy_url'),
            P.ModelSetting.get_bool('site_daum_use_cache'),
            P.ModelSetting.get_int('site_daum_cache_expiry'),
            P.ModelSetting.get('site_daum_headers'),
            P.ModelSetting.get('site_common_headers')
        )

    def __tving_init(self):
        from . import SupportTving
        SupportTving.initialize(
            P.ModelSetting.get('site_tving_token'),
            P.ModelSetting.get_bool('site_tving_use_proxy'),
            P.ModelSetting.get('site_tving_proxy_url'),
            P.ModelSetting.get('site_tving_deviceid'),
            P.ModelSetting.get('site_tving_headers'),
            P.ModelSetting.get('site_common_headers')
        )
        from .site_tving import SiteTving
        SiteTving.initialize(
            P.ModelSetting.get_bool('site_tving_use_cache'),
            P.ModelSetting.get_int('site_tving_cache_expiry')
        )

    def __naver_init(self):
        from . import SiteNaver
        SiteNaver.initialize(
            P.ModelSetting.get('site_naver_key'),
        )

    def __watcha_init(self):
        from . import SiteWatcha
        SiteWatcha.initialize(
            P.ModelSetting.get('site_watcha_cookie'),
            P.ModelSetting.get_bool('site_watcha_use_proxy'),
            P.ModelSetting.get('site_watcha_proxy_url'),
            P.ModelSetting.get_bool('site_watcha_use_cache'),
            P.ModelSetting.get_int('site_watcha_cache_expiry'),
            P.ModelSetting.get('site_watcha_headers'),
            P.ModelSetting.get('site_common_headers')
        )

    def __tmdb_init(self):
        from .site_tmdb import SiteTmdb
        SiteTmdb.initialize(
            P.ModelSetting.get('site_tmdb_api_key'),
            P.ModelSetting.get('site_tmdb_image_sizes'),
        )

    def __util_init(self):
        from .site_util import SiteUtil
        SiteUtil.initialize(
            P.ModelSetting.get('site_common_headers'),
            P.ModelSetting.get('site_common_loose_match_shows')
        )

    def migration(self) -> None:
        '''override'''
        version = P.ModelSetting.get('db_version')
        P.logger.debug(f'현재 DB 버전: {version}')
        db_file = F.app.config['SQLALCHEMY_BINDS'][P.package_name].replace('sqlite:///', '').split('?')[0]
        if version == '1':
            P.ModelSetting.set('site_wavve_patterns_episode', '^(?!.*(티저|예고|특집)).*?(?P<episode>\d+)$')
            P.ModelSetting.set('site_wavve_patterns_title', '^(?P<title>.*)$')
            version = '1.1'
        if version == '1.1':
            version = '1.2'
        if version == '1.2':
            try:
                accounts = json.loads(P.ModelSetting.get('site_wavve_credentials'))
            except Exception:
                P.logger.exception('Wavve 계정 정보를 가져오지 못했습니다.')
                accounts = None
            if not accounts:
                P.logger.info("Wavve 계정 정보 초기화")
                credential = P.ModelSetting.get('site_wavve_credential')
                use_proxy = P.ModelSetting.get_bool('site_wavve_use_proxy')
                proxy_url = P.ModelSetting.get('site_wavve_proxy_url')
                try:
                    profile = json.loads(P.ModelSetting.get('site_wavve_profile'))
                except Exception:
                    P.logger.exception(f"계정 정보를 가져오지 못했습니다.")
                    profile = {}
                accounts = {
                    'default': {
                        'id': profile.get('id'),
                        'password': profile.get('password'),
                        'profile': profile.get('profile'),
                        'device_id': profile.get('device_id'),
                        'credential': credential,
                        'proxy': proxy_url if use_proxy else None,
                        'headers': None,
                    }
                }
                try:
                    P.ModelSetting.set('site_wavve_credentials', json.dumps(accounts, ensure_ascii=False, separators=(',', ':'), indent=2))
                except Exception:
                    P.logger.exception('Wavve 계정 정보를 초기화하지 못 했습니다.')

            """마이그레이션 보류
            P.logger.debug('DB 버전 1.3 으로 마이그레이션')
            with F.app.app_context():
                with sqlite3.connect(db_file) as conn:
                    try:
                        conn.execute('VACUUM;')
                        conn.row_factory = sqlite3.Row
                        table = 'support_site_setting'
                        for key in ('site_wavve_use_proxy', 'site_wavve_proxy_url', 'site_wavve_profile'):
                            if row := conn.execute(f"SELECT id FROM {table} WHERE key = ?", (key,)).fetchone():
                                conn.execute(f"DELETE FROM {table} WHERE id = ?", (row['id'],))
                        version = '1.2'
                    except Exception:
                        P.logger.exception('DB 마이크레이션 실패')
                F.db.session.flush()
            """
        P.logger.debug(f'최종 DB 버전: {version}')
        P.ModelSetting.set('db_version', version)
