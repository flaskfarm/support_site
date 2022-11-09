import urllib.request

from . import SiteUtil
from .setup import *


class SiteVibe(object):
    site_name = 'vibe'
    
    default_headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'Accept' : 'application/json',
    }

    module_char = 'S'
    site_char = 'V'

    @classmethod
    def search_api(cls, keyword, mode='all'):
        try:
            url = f"https://apis.naver.com/vibeWeb/musicapiweb/v4/searchall?query={urllib.request.quote(keyword)}&sort=RELEVANCE&vidDisplay=25"
            data = SiteUtil.get_response(url, headers=cls.default_headers).json()
            if mode == 'artist':
                data = data['response']['result']['artistResult']['artists']
            elif mode == 'album':
                data = data['response']['result']['albumResult']['albums']
            return data
        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())


    @classmethod
    def search_artist(cls, keyword, return_format='normal'):
        try:
            data = cls.search_api(keyword, 'artist')
            if return_format == 'api':
                return data
            ret = []
            for idx, item in enumerate(data):
                ret.append({
                    'code': f"{cls.module_char}{cls.site_char}{item['artistId']}",
                    'name': item['artistName'],
                    'thumb' : item['imageUrl'],
                    'desc' : f"{item['gender']} {item['genreNames']}",
                    'score': 100 - (idx*5),
                })
            return ret
        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())


    @classmethod
    def info_artist(cls, code, return_format='normal'):
        try:
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]
            url = f"https://apis.naver.com/vibeWeb/musicapiweb/v1/artist/{code}"
            data = SiteUtil.get_response(url, headers=cls.default_headers).json()
            if return_format == 'api':
                return data
            return data
        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())

