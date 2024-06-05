from .setup import *


class ModuleSite(PluginModuleBase):
    db_default = {
        f'db_version' : '1',
        f"site_wavve_credential": "",
        f"site_wavve_use_proxy": "False",
        f"site_wavve_proxy_url": "",
        f"site_wavve_profile":'{"id": "", "password": "", "profile": "0"}',
        'site_daum_cookie' : 'TIARA=2KF1ajSnpkcUMt_AybEXcWY4pblBYRevTpfe177Yr-Z4As9lEoe5RS1i4nDhXbJiy2e.l5weR5Qq38qWoaUNFU7gxRChQhkpe5DL.Aex4vM0',
        'site_daum_use_proxy' : 'False',
        'site_daum_proxy_url' : '',
        'site_daum_test' : '오버 더 레인보우',
        'site_tving_id' : '',
        'site_tving_pw' : '',
        'site_tving_login_type' : 'cjone',
        'site_tving_token' : '',
        'site_tving_deviceid' : '',
        'site_tving_use_proxy' : 'False',
        'site_tving_proxy_url' : '',
        'site_naver_key': '',
        'site_imgur_client_id': '',
        'site_imgur_client_secret': '',
        'site_imgur_access_token': '',
        'site_imgur_refresh_token': '',
        'site_imgur_account_username': '',
        'site_imgur_account_id': '',
    }

    def __init__(self, P):
        super(ModuleSite, self).__init__(P, name='site', first_menu='setting')

    def process_command(self, command, arg1, arg2, arg3, req):
        ret = {'ret':'success'}
        if command == 'tving_login':
            from . import SupportTving
            token = SupportTving.do_login(arg1, arg2, arg3)
            if token is None:
                ret['ret'] = 'warning'
                ret['msg'] = "로그인에 실패하였습니다."
            else:
                ret['token'] = token
                ret['msg'] = "토큰값을 가져왔습니다.<br>저장버튼을 눌러야 값을 저장합니다."
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
                ret['ret'] = 'warning'
                ret['msg'] = "로그인에 실패하였습니다."
                from . import SupportWavve
                account = json.loads(arg1)
                P.ModelSetting.set('site_wavve_profile', arg1)
                result = SupportWavve.do_login(account['id'], account['password'], account['profile'])
                if result[0]:
                    P.ModelSetting.set('site_wavve_credential', result[1]['credential'])
                    ret['msg'] = "로그인 성공<br>Credential을 갱신하였습니다."
                    ret['credential'] = result[1]['credential']
                else:
                    ret['ret'] = 'warning'
                    ret['msg'] = "로그인에 실패하였습니다."
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

        """
        elif command == 'imgur_auth':
            P.ModelSetting.set('site_imgur_client_id', arg1)
            P.ModelSetting.set('site_imgur_client_secret', arg2)
            from .tool_imgur import ToolImgur
            tmp = ToolImgur.request_auth(arg1, arg2)
            if tmp[0]:
                ret['html'] = tmp[1]
            else:
                ret['ret'] = 'error'
                ret['msg'] = f"실패: 응답코드 - {tmp[1]}"
            return jsonify(ret)
        """
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
        for item in change_list:
            if item.startswith('site_wavve_'):
                flag_wavve = True
            if item != 'site_daum_test' and item.startswith('site_daum_'):
                flag_daum = True
            if item.startswith('site_tving_'):
                flag_tving = True
            if item.startswith('site_naver_key'):
                flag_naver = True

        if flag_wavve:
            self.__wavve_init()
        if flag_daum:
            self.__daum_init()
        if flag_tving:
            self.__tving_init()
        if flag_naver:
            self.__naver_init()

    def plugin_load(self):
        self.__wavve_init()
        self.__daum_init()
        self.__tving_init()
        self.__naver_init()

    def plugin_load_celery(self):
        '''
        셀러리로 플러그인 로딩시 사이트 정보 초기화
        '''
        self.plugin_load()

    def __wavve_init(self):
        from . import SupportWavve
        SupportWavve.initialize(
            P.ModelSetting.get('site_wavve_credential'),
            P.ModelSetting.get_bool('site_wavve_use_proxy'),
            P.ModelSetting.get('site_wavve_proxy_url'),
        )
        '''
        ssokka:
            Fix Proxy
            국내 IP가 적용되는 Proxy 주소 사용, warproxy/wgcf 불가
        '''
        if P.ModelSetting.get_bool('site_wavve_use_proxy'):
            SupportWavve.session.proxies = SupportWavve._SupportWavve__get_proxies()
        else:
            SupportWavve.session.proxies = {}

    def __daum_init(self):
        from . import SiteDaum
        SiteDaum.initialize(
            P.ModelSetting.get('site_daum_cookie'),
            P.ModelSetting.get_bool('site_daum_use_proxy'),
            P.ModelSetting.get('site_daum_proxy_url'),
        )

    def __tving_init(self):
        from . import SupportTving
        SupportTving.initialize(
            P.ModelSetting.get('site_tving_token'),
            P.ModelSetting.get_bool('site_tving_use_proxy'),
            P.ModelSetting.get('site_tving_proxy_url'),
            P.ModelSetting.get('site_tving_deviceid'),
        )

    def __naver_init(self):
        from . import SiteNaver
        SiteNaver.initialize(
            P.ModelSetting.get('site_naver_key'),
        )
