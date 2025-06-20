import requests
from datetime import datetime, timedelta
import urllib
from .setup import *

class ToolNaverCafe(object):

    @classmethod
    def write_post(cls, cafe_id, menu_id, subject, content):
        access_token = cls.get_naver_access_token()
        if access_token is None:
            logger.error("Naver access token is None")
            return None
        url = "https://openapi.naver.com/v1/cafe/" + cafe_id + "/menu/" + menu_id + "/articles"
        data = {'subject': urllib.parse.quote(subject), 'content': urllib.parse.quote(content)}
        header = "Bearer " + access_token 
        res = requests.post(url, data=data, headers={'Authorization': header})
        data = res.json()
        logger.debug(data)
        return data


    @classmethod
    def get_naver_access_token(cls):
        time_str = P.ModelSetting.get('site_naver_login_access_token_time')
        if time_str == '':
            return None
        access_time = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
        if access_time + timedelta(minutes=55) > datetime.now():
            return P.ModelSetting.get('site_naver_login_access_token')
        
        ret = cls.do_refresh()
        if ret['ret'] == 'success':
            return P.ModelSetting.get('site_naver_login_access_token')
        else:
            logger.error(f"Naver access token refresh failed: {ret['msg']}")
            return None


    @classmethod
    def do_refresh(cls):
        code = 'refresh_token'
        url = f"https://nid.naver.com/oauth2.0/token?grant_type=refresh_token&client_id={P.ModelSetting.get('site_naver_login_client_id')}&client_secret={P.ModelSetting.get('site_naver_login_client_secret')}&refresh_token={P.ModelSetting.get('site_naver_login_refresh_token')}"
        res = requests.get(url)
        data = res.json()
        logger.debug(data)
        if 'error' in data:
            ret = {
                'ret': 'error',
                'msg': data['error_description'],
            }
        else:
            ret = {
                'ret': 'success',
                'msg': data['access_token']
            }
            P.ModelSetting.set('site_naver_login_access_token', data['access_token'])
            P.ModelSetting.set('site_naver_login_access_token_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return ret


    @classmethod
    def do_login(cls, code, state):
        url = f"https://nid.naver.com/oauth2.0/token?grant_type=authorization_code&client_id={P.ModelSetting.get('site_naver_login_client_id')}&client_secret={P.ModelSetting.get('site_naver_login_client_secret')}&redirect_uri=&code={code}&state={state}"
        res = requests.get(url)
        data = res.json()
        logger.debug(data)
        if 'error' in data:
            ret = {
                'ret': 'error',
                'msg': data['error_description'],
            }
        else:
            ret = {
                'ret': 'success',
                'msg': '토큰을 저장하였습니다'
            }
            P.ModelSetting.set('site_naver_login_refresh_token', data['refresh_token'])
            P.ModelSetting.set('site_naver_login_access_token', data['access_token'])
            P.ModelSetting.set('site_naver_login_refresh_token_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            P.ModelSetting.set('site_naver_login_access_token_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return ret
