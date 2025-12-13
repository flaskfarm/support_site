import json
import sqlite3

from .setup import *


class ModuleSite(PluginModuleBase):
    db_default = {
        f'db_version' : '1.2',
        f"site_wavve_credential": "",
        "site_wavve_credentials": "",
        f"site_wavve_use_proxy": "False",
        f"site_wavve_proxy_url": "",
        f"site_wavve_profile":'{"id": "", "password": "", "profile": "0", "device_id": ""}',
        'site_wavve_patterns_episode': '^(?!.*(티저|예고|특집)).*?(?P<episode>\d+)$',
        'site_wavve_patterns_title': '^(?P<title>.*)$',
        'site_wavve_headers': '',
        'site_wavve_use_cache' : 'False',
        'site_wavve_cache_expiry' : '60',
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
        'site_watcha_headers': '{"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36","X-Frograms-Client-Version":"2.1.0","X-Frograms-Client":"Galaxy-Web-App","X-Frograms-App-Code":"Galaxy","X-Frograms-Galaxy-Language":"ko","X-Frograms-Galaxy-Region":"KR","X-Frograms-Version":"2.1.0","X-Frograms-Device-Name":"Chrome:142.0.0.0 Windows:NT 10.0"}',
        'site_watcha_use_cache' : 'False',
        'site_watcha_cache_expiry' : '60',
        'site_naver_login_client_id' : '',
        'site_naver_login_client_secret' : '',
        'site_naver_login_refresh_token' : '',
        'site_naver_login_refresh_token_time' : '',
        'site_naver_login_access_token' : '',
        'site_naver_login_access_token_time' : '',
        'site_common_loose_match_shows' : '',
        'site_common_headers' : '{"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8","Accept-Language":"ko,en-US;q=0.9,en;q=0.8,de;q=0.7,zh-CN;q=0.6,zh;q=0.5,lb;q=0.4","User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"}',
    }

    def __init__(self, P):
        super(ModuleSite, self).__init__(P, name='site', first_menu='setting')

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret':'success'}
        if command == 'tving_login':
            from . import SupportTving
            login_ret = SupportTving.do_login(arg1, arg2, arg3)
            if login_ret == None:
                ret['ret'] = 'warning'
                ret['msg'] = f"로그인에 실패하였습니다."
            else:
                if login_ret['status_code'] == 200:
                    ret['token'] = login_ret['token']
                    ret['msg'] = "토큰값을 가져왔습니다.<br>저장버튼을 눌러야 값을 저장합니다."
                else:
                    ret['ret'] = 'warning'
                    ret['msg'] = f"로그인에 실패하였습니다.<br>응답코드: {login_ret['status_code']}"
        elif command == 'tving_deviceid':
            from . import SupportTving
            device_list = SupportTving.get_device_list(token=arg1)
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
        self.__util_init()

    def plugin_load(self):
        self.__wavve_init()
        self.__daum_init()
        self.__tving_init()
        self.__naver_init()
        self.__watcha_init()
        self.__util_init()

    def plugin_load_celery(self):
        '''
        셀러리로 플러그인 로딩시 사이트 정보 초기화
        '''
        self.plugin_load()

    def __wavve_init(self):
        from . import SupportWavve
        SupportWavve.initialize(
            P.ModelSetting.get('site_wavve_credentials'),
            P.ModelSetting.get_list('site_wavve_patterns_episode'),
            P.ModelSetting.get_list('site_wavve_patterns_title'),
            P.ModelSetting.get('site_wavve_headers'),
            P.ModelSetting.get('site_common_headers')
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
