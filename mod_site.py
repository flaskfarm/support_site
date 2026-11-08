import json
import secrets
import sqlite3
import time

from flask import session

from .setup import *


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
        'site_melon_headers': '',
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
                P.ModelSetting.set('site_wavve_credentials', arg1)
                success = []
                failed = []
                for name in SupportWavve.api.accounts:
                    if SupportWavve.do_login(name):
                        success.append(name)
                    else:
                        failed.append(name)
                ret['credentials'] = P.ModelSetting.get('site_wavve_credentials')
                msg = f"성공: {','.join(success)}<br>실패: {','.join(failed)}"
                ret['ret'] = 'success'
                ret['msg'] = msg
            except Exception as e:
                logger.error(f'Exception:{str(e)}')
                logger.error(traceback.format_exc())
                ret['ret'] = 'error'
                ret['msg'] = f"에러: {str(e)}"
        elif command == 'imgur_auth_start':
            if req.method != 'POST':
                return jsonify({'ret': 'error', 'error_code': 'invalid_request', 'error_origin': 'ff', 'msg': 'POST 요청이 필요합니다.'}), 405
            state = secrets.token_urlsafe(32)
            session['imgur_oauth'] = {'state': state, 'issued_at': time.time()}
            return jsonify({'ret': 'success', 'state': state})
        elif command == 'imgur_auth_complete':
            if req.method != 'POST':
                return jsonify({'ret': 'error', 'error_code': 'invalid_request', 'error_origin': 'ff', 'msg': 'POST 요청이 필요합니다.'}), 405
            pending = session.get('imgur_oauth') or {}
            supplied_state = req.form.get('state', '')
            issued_at = pending.get('issued_at')
            expected_state = pending.get('state')
            if (not isinstance(issued_at, (int, float)) or
                    not 0 <= time.time() - issued_at <= 600):
                session.pop('imgur_oauth', None)
                return jsonify({'ret': 'error', 'error_code': 'invalid_request', 'error_origin': 'ff', 'msg': '인증 요청이 없거나 만료되었습니다.'}), 400
            if (not isinstance(expected_state, str) or not expected_state or
                    not supplied_state or not secrets.compare_digest(
                        expected_state.encode('utf-8'), supplied_state.encode('utf-8'))):
                return jsonify({'ret': 'error', 'error_code': 'invalid_request', 'error_origin': 'ff', 'msg': '인증 요청이 일치하지 않습니다.'}), 400
            fields = ('access_token', 'refresh_token', 'account_username', 'account_id')
            values = {key: req.form.get(key, '').strip() for key in fields}
            if any(not value or any(ord(char) < 32 or ord(char) == 127 for char in value)
                   for value in values.values()):
                return jsonify({'ret': 'error', 'error_code': 'invalid_request', 'error_origin': 'ff', 'msg': '인증 정보가 누락되었거나 올바르지 않습니다.'}), 400
            # 토큰은 본문에서만 수신하며 응답·예외 로그에 포함하지 않는다.
            session.pop('imgur_oauth', None)
            try:
                from .tool_imgur import ToolImgur
                for key, value in values.items():
                    P.ModelSetting.set(f'site_imgur_{key}', value)
                ToolImgur.reset_client()
            except Exception:
                return jsonify({'ret': 'error', 'error_code': 'ff_internal_error', 'error_origin': 'ff', 'msg': '인증 정보 저장에 실패했습니다. 다시 인증하세요.'}), 500
            return jsonify({'ret': 'success', 'msg': 'Imgur 인증 정보를 저장했습니다.'})
        elif command == 'imgur_upload':
            image = req.form.get('url', '')
            if not image.startswith('data:image/') or 'base64,' not in image or not image.split('base64,', 1)[1]:
                return jsonify(ret='error', error_code='invalid_request', error_origin='ff', msg='클립보드 이미지가 올바르지 않습니다.'), 400
            try:
                from .tool_imgur import ToolImgur
                tmp = ToolImgur.upload_from_paste(image)
                if tmp:
                    return jsonify(ret='success', url=tmp)
                return jsonify(ret='error', error_code='upstream_unavailable', error_origin='unknown', msg='Imgur 업로드 결과를 확인하지 못했습니다.'), 502
            except Exception as exc:
                import requests
                status, origin, code = 500, 'ff', 'ff_internal_error'
                remote = None
                response = getattr(exc, 'response', None)
                if isinstance(exc, requests.exceptions.HTTPError) and response is not None:
                    remote = response.status_code
                elif type(exc).__module__.startswith('imgurpython.'):
                    remote = getattr(exc, 'status_code', None)
                if type(remote) is int:
                    status, origin, code = (503 if remote == 429 else 504 if remote == 504 else 502), 'external', 'upstream_http_error'
                elif isinstance(exc, requests.exceptions.Timeout):
                    status, origin, code = 504, 'external', 'upstream_timeout'
                elif isinstance(exc, requests.exceptions.ConnectionError):
                    status, origin, code = 502, 'external', 'upstream_unavailable'
                body = dict(ret='error', error_code=code, error_origin=origin, msg='Imgur 이미지 업로드에 실패했습니다. 상태를 확인하세요.')
                if origin == 'external':
                    body['upstream'] = dict(site='imgur', http_status=remote, reason='timeout' if code == 'upstream_timeout' else 'request_failed')
                # SDK 예외 원문에는 OAuth 정보가 포함될 수 있다.
                logger.error('Imgur 업로드 실패: code=%s origin=%s status=%s', code, origin, remote)
                return jsonify(body), status
        elif command == 'naverlogin_callback_process':
            from . import ToolNaverCafe
            ret = ToolNaverCafe.do_login(arg1, arg2)
        return jsonify(ret)

    def process_normal(self, sub, req):
        return '', 404

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
        self.__melon_init()

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
        SupportWavve.initialize(
            P.ModelSetting.get('site_wavve_credentials'),
            P.ModelSetting.get_list('site_wavve_patterns_episode'),
            P.ModelSetting.get_list('site_wavve_patterns_title'),
            P.ModelSetting.get_list('site_wavve_patterns_season'),
            P.ModelSetting.get('site_wavve_headers'),
            P.ModelSetting.get('site_common_headers'),
            P.ModelSetting.get_bool('site_wavve_credential_auto_refresh'),
            P.ModelSetting.get_int('site_wavve_credential_ttl'),
            P.ModelSetting.get_int('site_wavve_credential_cooldown'),
            P.ModelSetting.get_bool('site_wavve_use_cache'),
            P.ModelSetting.get_int('site_wavve_cache_expiry')
        )
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

    def __melon_init(self):
        from .site_melon import SiteMelon
        SiteMelon.initialize(
            P.ModelSetting.get('site_melon_headers'),
            P.ModelSetting.get('site_common_headers'),
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
