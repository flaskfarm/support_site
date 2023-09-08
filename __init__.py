import os

try:
    import xmltodict
except:
    os.system("pip install xmltodict")

try:
    import lxml
except:
    os.system("pip install lxml")

from support import SupportSC

from .site_util import SiteUtil

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'wavve.py')):
        import wavve
        SupportWavve = wavve.SupportWavve
    else:
        wavve = SupportSC.load_module_f(__file__, 'wavve')
        SupportWavve = wavve.SupportWavve
except:
    pass

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'kakaotv.py')):
        from .kakaotv import SupportKakaotv
    else:
        SupportKakaotv = SupportSC.load_module_f(__file__, 'kakaotv').SupportKakaotv
except:
    pass

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'seezn.py')):
        from .seezn import SupportSeezn
    else:
        SupportSeezn = SupportSC.load_module_f(__file__, 'seezn').SupportSeezn
except:
    pass

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'tving.py')):
        from .tving import SupportTving
    else:
        SupportTving = SupportSC.load_module_f(__file__, 'tving').SupportTving
except:
    pass


try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'cppl.py')):
        from .cppl import SupportCppl
    else:
        SupportCppl = SupportSC.load_module_f(__file__, 'cppl').SupportCppl
except:
    pass


try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'dl_watcha.py')):
        from .dl_watcha import DL_Watcha
    else:
        DL_Watcha = SupportSC.load_module_f(__file__, 'dl_watcha').DL_Watcha
except:
    pass


from .server_util import MetadataServerUtil
from .site_daum import SiteDaum
from .site_daum_movie import SiteDaumMovie
from .site_daum_tv import SiteDaumTv
from .site_lastfm import SiteLastfm
from .site_melon import SiteMelon
from .site_naver import SiteNaver, SiteNaverMovie
from .site_naver_book import SiteNaverBook
from .site_tmdb import SiteTmdbFtv, SiteTmdbMovie, SiteTmdbTv
from .site_tvdb import SiteTvdbTv
from .site_tving import SiteTvingMovie, SiteTvingTv
from .site_vibe import SiteVibe
from .site_watcha import SiteWatchaMovie, SiteWatchaTv
from .site_wavve import SiteWavveMovie, SiteWavveTv

"""

from .site_fc2.site_7mmtv import Site7mmTv
from .site_fc2.site_bp4x import SiteBp4x
from .site_fc2.site_fc2cm import SiteFc2Cm
from .site_fc2.site_fc2com import SiteFc2Com
from .site_fc2.site_fc2hub import SiteFc2Hub
from .site_fc2.site_msin import SiteMsin

from .site_dmm import SiteDmm
from .site_jav321 import SiteJav321
from .site_javbus import SiteJavbus

from .site_mgstage import SiteMgstageAma, SiteMgstageDvd


from .site_uncensored.site_1pondotv import Site1PondoTv
from .site_uncensored.site_10musume import Site10Musume
from .site_uncensored.site_carib import SiteCarib
from .site_uncensored.site_heyzo import SiteHeyzo




"""

import functools
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import re
import json
import traceback
import sys
from unittest.mock import patch

from .setup import P as PLUGIN


def get_filename_warpper(f):
    '''
    파일 이름을 생성할 때 "programtitle"이 공백일 경우 "seasontitle"로 대체
    ssokka:
        드라마의 경우 파일 이름에 시즌 표시가 안됨
        "seasontitle"로 1차적으로 적용하고 공백일 경우 "programtitle"로 대체
    '''
    @functools.wraps(f)
    def wrap(*args, **kwargs):
        try:
            if 'programtitle' in args[0] and 'seasontitle' in args[0]:
                programtitle = args[0].get('programtitle')
                args[0]['programtitle'] = args[0]['seasontitle']
                if not args[0]['programtitle']:
                    args[0]['programtitle'] = programtitle
        except Exception:
            PLUGIN.logger.debug(args)
            PLUGIN.logger.debug(kwargs)
            PLUGIN.logger.error(traceback.format_exc())
        return f(*args, **kwargs)
    return wrap
SupportWavve.get_filename = get_filename_warpper(SupportWavve.get_filename)


p_wavve_bandwidth = re.compile(r'.*?BANDWIDTH=(\d+)')
p_wavve_last_url = re.compile(r'^(.*?)/')
def get_prefer_url(url: str) -> str:
    '''
    ssokka:
        Fix low auido bitrate
        Fix 'SDR_AVC' error log
        Apply auto url type
    '''
    try:
        data = SupportWavve.session.get(url, headers=SupportWavve.config['headers']).text.strip()
        line = data.split('\n')
        max_bandwidth = 0
        last_url = None
        iterator = iter(line)
        for l in iterator:
            match = p_wavve_bandwidth.match(l)
            if match:
                bandwidth = int(match.group(1))
                if bandwidth > max_bandwidth:
                    max_bandwidth = bandwidth
                    last_url = next(iterator)
        if last_url is not None and last_url != '':
            match = p_wavve_last_url.match(last_url)
            if match:
                url_type = match.group(1)
                if url.find('chunklist') != -1:
                    url_type = f'chunklist{url_type}'
                last_url = f'{url.split(url_type)[0]}{last_url}'
                return last_url
        PLUGIN.logger.debug(f'function: {sys._getframe().f_code.co_name}, url: {url}, data: {data}')
        return url
    except Exception as exception:
        PLUGIN.logger.error('Exception:%s', exception)
        PLUGIN.error(traceback.format_exc())
SupportWavve.get_prefer_url = get_prefer_url


default_query = {
    'limit': 10,
    'offset': 0,
    'orderby': 'new',
    'apikey': 'E5F3E0D30947AA5440556471321BB6D9',
    'client_version': '6.0.1',
    'device': 'pc',
    'drm': 'wm',
    'partner': 'pooq',
    'pooqzone': 'none',
    'region': 'kor',
    'targetage': 'all',
}
default_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.20',
    'Wavve-Credential': PLUGIN.ModelSetting.get('site_wavve_credential'),
}
def vod_program_contents_programid(code: str, page: int = 1) -> dict:
    '''
    프로그램 정보 api 오류 대응
    '''
    default_query['offset'] = (page - 1) * 10
    url = urlunparse(('https', 'apis.wavve.com', f'fz/vod/programs/{code}/contents', '', urlencode(default_query, doseq=True), ''))
    try:
        response = SupportWavve.session.get(url, headers=default_headers)
        data = json.loads(response.text)
        data = data.pop('cell_toplist')
        data['list'] = data['celllist']
        for ep in data['list']:
            ep['image'] = ep.pop('thumbnail')
            ep['programtitle'] = ep.pop('alt')
            ep['episodeactors'] = ep.pop('actors')
            ep['episodetitle'] = ep.get('episodetitle') or ep.get('title_list', [{}])[0].get('text') or ep.get('contentid')
        return data
    except:
        PLUGIN.logger.error(traceback.format_exc())
        PLUGIN.logger.debug(response.text)
        return {}
SupportWavve.vod_program_contents_programid = vod_program_contents_programid


def patch_wrapper(f, target, inject):
    @functools.wraps(f)
    def wrap(*args, **kwds):
        with patch(target, inject):
            return f(*args, **kwds)
    return wrap


def check_empty_json(response, keyword, dummy, match):
    try:
        if match:
            result = response.json()
            if not result:
                PLUGIN.logger.debug(f'검색 결과 없음: {keyword}')
                response._content = bytes(dummy, response.encoding or 'utf-8')
    except:
        PLUGIN.logger.error(traceback.format_exc())
    finally:
        return response


p_wavve_url_list = re.compile(r'list.js')
def patch_session_get(*args, **kwds):
    '''
    웨이브 list.js api 검색 응답이 '{}'일 경우:
        search_movie(): list.js api: KeyError: 'cell_toplist'

    mtype:
        all: 전체
        svod: 영화 (인터스텔라)
        ppv: 영화플러스 (타이타닉)
    mtype=ppv일 경우 mtype=all로 변경
    '''
    args = list(args)
    url_parts = list(urlparse(args[0]))
    query = parse_qs(url_parts[4])
    if 'mtype' in query:
        query['mtype'] = 'all'
        url_parts[4] = urlencode(query, doseq=True)
        args = list(args)
        args[0] = urlunparse(url_parts)
    response = SupportWavve.session.request('GET', *args, **kwds)
    return check_empty_json(response, query.get("keyword", [None])[0], r'{"cell_toplist": {}}', p_wavve_url_list.search(url_parts[2]))
SupportWavve.search_movie = patch_wrapper(SupportWavve.search_movie, 'support_site.wavve.SupportWavve.session.get', patch_session_get)


p_wavve_url_band = re.compile(r'band.js')
def patch_search_session_get(*args, **kwds):
    '''
    웨이브 band.js api 검색 응답이 '{}'일 경우:
        band.js api: KeyError: 'band'
    '''
    response = SupportWavve.session.request('GET', *args, **kwds)
    url_parts = urlparse(args[0])
    query = parse_qs(url_parts.query)
    return check_empty_json(response, query.get("keyword", [None])[0], r'{"band": {}}', p_wavve_url_band.search(url_parts.path))
SupportWavve._SupportWavve__search = patch_wrapper(SupportWavve._SupportWavve__search, 'support_site.wavve.SupportWavve.session.get', patch_search_session_get)
