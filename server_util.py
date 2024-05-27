import urllib.parse

import requests

from .setup import *
from .site_util import SiteUtil

SERVER_PLUGIN_DDNS = 'https://meta.sjva.me'
WEB_DIRECT_URL = 'http://52.78.103.230:49734'
try:
    if F.SystemModelSetting.get('ddns') == SERVER_PLUGIN_DDNS:
        SERVER_PLUGIN_DDNS = 'http://127.0.0.1:19999'
except:
    pass

class MetadataServerUtil(object):
    @classmethod
    def get_metadata(cls, code):
        try:
            url = f"{WEB_DIRECT_URL}/meta/get_meta.php?"
            url += urllib.parse.urlencode({'type':'meta', 'code':code})
            logger.warning(url)
            data = requests.get(url).json()
            if data['ret'] == 'success':
                return data['data']
        except Exception as exception:
            logger.error('metaserver connection fail.. get_metadata')
    

    @classmethod
    def set_metadata(cls, code, data, keyword):
        try:
            url = f'{SERVER_PLUGIN_DDNS}/server/normal/metadata/set'
            upload_id = F.PluginManager.get_plugin_instance('sjva').ModelSetting.get('sjva_id')
            param = {'code':code, 'data':json.dumps(data), 'user':upload_id, 'keyword':keyword}
            data = requests.post(url, data=param).json()
            if data['ret'] == 'success':
                logger.info('%s Data save success. Thanks!!!!', code)
        except Exception as exception: 
            logger.error('metaserver connection fail.. set_metadata')


    @classmethod
    def set_metadata_jav_censored(cls, code, data, keyword):
        try:
            if data['thumb'] is None or (code.startswith('C') and len(data['thumb']) < 2) or (code.startswith('D') and len(data['thumb']) < 1):
                return
            for tmp in data['thumb']:
                if tmp['value'] is None or tmp['value'].find('.discordapp.') == -1:
                    return
                if requests.get(tmp['value']).status_code != 200:
                    return
            if SiteUtil.is_include_hangul(data['plot']) == False:
                return
            cls.set_metadata(code, data, keyword)   
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def set_metadata_jav_uncensored(cls, code, data, keyword):
        try:
            if data['thumb'] is None:
                return
            for tmp in data['thumb']:
                if tmp['value'] is None or tmp['value'].find('.discordapp.') == -1:
                    return
                if requests.get(tmp['value']).status_code != 200:
                    return
            if SiteUtil.is_include_hangul(data['tagline']) == False:
                return
            if data['plot'] is not None and SiteUtil.is_include_hangul(data['plot']) == False:
                return
            cls.set_metadata(code, data, keyword)
            logger.debug(f'set metadata uncensored complete, {code}')
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    
    @classmethod
    def get_meta_extra(cls, code):
        try:
            url = f"{WEB_DIRECT_URL}/meta/get_meta.php?"
            url += urllib.parse.urlencode({'type':'extra', 'code':code})
            data = requests.get(url).json()
            if data['ret'] == 'success':
                return data['data']
        except Exception as exception: 
            logger.error('metaserver connection fail.. get_meta_extra')
