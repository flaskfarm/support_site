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
import traceback
import sys
from unittest.mock import patch
import datetime

import redis

from framework.init_main import Framework

from .setup import P as PLUGIN

FRAMEWORK = Framework.get_instance()
LIST_LIMIT = 10
RECENT_DAYS = 7
DEFAULT_QUERY = {
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
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.20',
    'Wavve-Credential': PLUGIN.ModelSetting.get('site_wavve_credential'),
}
REDIS_CONN = redis.Redis(host='localhost', port=6379, decode_responses=True)
REDIS_KEY_WAVVE_BLACKLIST_CONTENTS = 'flaskfarm:wavve:blacklist:contents'
REDIS_CONN.delete(REDIS_KEY_WAVVE_BLACKLIST_CONTENTS)


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


def vod_programs_landing(query: dict) -> dict:
    url = urlunparse(('https', 'apis.wavve.com', '/fz/vod/programs/landing', '', urlencode(query, doseq=True), ''))
    return SupportWavve.session.request('GET', url, headers=DEFAULT_HEADERS).json()


def vod_contents_detail(content_id: str, query: dict) -> dict:
    url = urlunparse(('https', 'apis.wavve.com', f'/fz/vod/contents-detail/{content_id}', '', urlencode(query, doseq=True), ''))
    return SupportWavve.session.request('GET', url, headers=DEFAULT_HEADERS).json()


def vod_newcontents(query: dict) -> dict:
    url = urlunparse(('https', 'apis.wavve.com', '/cf/vod/newcontents', '', urlencode(query, doseq=True), ''))
    return SupportWavve.session.request('GET', url, headers=DEFAULT_HEADERS).json()

def vod_programs_contents(program_id: str, query: dict) -> dict:
    url = urlunparse(('https', 'apis.wavve.com', f'/fz/vod/programs/{program_id}/contents', '', urlencode(query, doseq=True), ''))
    return SupportWavve.session.request('GET', url, headers=DEFAULT_HEADERS).json()


def search_list(keyword: str, query: dict) -> dict:
    query['keyword'] = keyword
    url = urlunparse(('https', 'apis.wavve.com', f'/fz/search/list.js', '', urlencode(query, doseq=True), ''))
    return SupportWavve.session.request('GET', url, headers=DEFAULT_HEADERS).json()


def vod_program_contents_programid(code: str, page: int = 1) -> dict:
    '''
    프로그램 정보 api 오류 대응
    '''
    try:
        query = dict(DEFAULT_QUERY)
        query['offset'] = (page - 1) * 10
        data = vod_programs_contents(code, query)
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


def wrapper_vod_programs_programid(f: callable) -> callable:
    @functools.wraps(f)
    def wrap(*args, **kwds):
        '''
        /vod/programs API로 데이터를 가져오지 못할 경우 대응
        증상:
            플렉스에서 일부 프로그램을 웨이브 메타 적용시 오류 발생
        '''
        data = f(*args, **kwds)
        if not data:
            try:
                query = dict(DEFAULT_QUERY)
                query.pop('limit')
                query.pop('offset')
                query['programid'] = args[0]
                query['history'] = 'season'
                content_id = vod_programs_landing(query).get('content_id')
                contents = SupportWavve.vod_contents_contentid(content_id)
                data['tags'] = contents.get('tags', {})
                data['programactors'] = contents.get('actors', {})
                data['image'] = contents.get('image', contents.get('programimage', ''))
                data['cirlceimage'] = contents.get('programcircleimage', '')
                data['posterimage'] = contents.get('programposterimage', '')
                data['programsynopsis'] = contents.get('programsynopsis', '')
                data['closedate'] = contents.get('closedate', '')
                data['onair'] = contents.get('onair', '')
                data['cpid'] = contents.get('cpid', '')
                data['endtime'] = contents.get('programendtime', '')
                data['releaseweekday'] = contents.get('releaseweekday', '')
                data['starttime'] = contents.get('programstarttime', '')
                data['channelname'] = contents['channelname']
                data['programtitle'] = contents.get('seasontitle') or contents.get('programtitle')
                data['cpname'] = contents.pop('cpname', '')
                data['livechannelid'] = contents.pop('channelid', '')
                data['alarm'] = contents.get('alarm', '')
                data['zzim'] = contents.get('zzim', '')
                data['programid'] = contents.get('programid', '')
                data['channelid'] = contents.get('channelid', '')
                data['firstreleasedate'] = contents.get('firstreleasedate', '')
                data['playtimetext'] = contents.get('playtimetext', '')
            except Exception as e:
                PLUGIN.logger.error(e)
                PLUGIN.logger.error(traceback.format_exc())
        return data
    return wrap
SupportWavve.vod_programs_programid = wrapper_vod_programs_programid(SupportWavve.vod_programs_programid)


def get_vod_ids(celllist: list) -> set:
    contents_ids = set()
    for vod in celllist:
        try:
            _id = parse_qs(vod['event_list'][1]['url'].split('?')[1]).get('contentid')[0]
            contents_ids.add(_id)
            #PLUGIN.logger.debug(f"{vod['alt']} - {_id}")
        except Exception as e:
            PLUGIN.logger.error(e)
            PLUGIN.logger.error(traceback.format_exc())
            continue
    return contents_ids


def get_vod_ids_from_newcontents(page: int) -> set:
    '''
    새로운 API 에서 content id 수집
    '''
    query = dict(DEFAULT_QUERY)
    query['subgenre'] = 'all'
    query['channel'] = 'all'
    query['weekday'] = 'all'
    query['genre'] = 'all'
    query['limit'] = LIST_LIMIT
    query['offset'] = (page - 1) * LIST_LIMIT
    try:
        celllist = vod_newcontents(query).get('cell_toplist', {}).get('celllist', [])
        return get_vod_ids(celllist)
    except Exception as e:
        PLUGIN.logger.error(e)
        PLUGIN.logger.error(traceback.format_exc())
        return set()


def get_vod_ids_from_search(keyword: str, page: int) -> set:
    '''
    검색 키워드에서 content ID 수집
    '''
    query = dict(DEFAULT_QUERY)
    query['limit'] = LIST_LIMIT
    query['offset'] = (page - 1) * LIST_LIMIT
    query['type'] = 'vod'
    query['version'] = '2'
    query['mtype'] = ''
    try:
        celllist = search_list(keyword, query).get('cell_toplist', {}).get('celllist', [])
        return get_vod_ids(celllist)
    except Exception as e:
        PLUGIN.logger.error(e)
        PLUGIN.logger.error(traceback.format_exc())
        return set()


def wrapper_vod_newcontents(f: callable) -> callable:
    @functools.wraps(f)
    def wrap(*args, **kwds):
        '''
        기존 최신 콘텐츠 API 목록에 다른 API에서 가져온 콘텐츠를 추가
        wavve 플러그인 mod_recent.ModuleRecent.scheduler_function() 이 암호화 되어 있어서 여기서 작업
            - scheduler_function() 은 wavve.SupportWavve.vod_newcontents() 을 호출함.
            - api 중복 조회를 감안해야 함.

        "최신"의 기준을 지난 1주일로 상정하고 방송 일자 정보가 없거나 오래된 방송은 제외:
            - 제외된 content_id는 redis에 저장되고 플러그인 재시작시 삭제됨
        '''
        wavve = FRAMEWORK.PluginManager.get_plugin_instance('wavve')
        recent_quality = wavve.ModelSetting.get('recent_quality')
        model = wavve.logic.get_module('recent').web_list_model
        # 기존의 SupportWavve.vod_newcontents() 에서 return 할 데이터
        data: dict = f(*args, **kwds)
        page = kwds.get('page', 1)
        recents = data.get('list', [])
        recents_ids = {epi['contentid'] for epi in recents}
        more_recents = set()

        PLUGIN.logger.debug(f'current page: {kwds.get("page", -1)}')

        more_newcontents = get_vod_ids_from_newcontents(page)
        PLUGIN.logger.debug(f'newcontents: {len(more_newcontents - recents_ids)} more items')
        more_recents.update(more_newcontents)

        for keyword in ['드라마', '예능', '시사', '교양', '시리즈', '애니메이션', '스포츠']:
            ids = get_vod_ids_from_search(keyword, page)
            PLUGIN.logger.debug(f'{keyword}: {len(ids - (recents_ids | more_recents))} more items')
            more_recents.update(ids)

        PLUGIN.logger.debug(f'more_recents: before={len(more_recents)} after={len(more_recents - recents_ids)}')
        more_recents.difference_update(recents_ids)
        if more_recents:
            PLUGIN.logger.debug(f'found more vods: {len(more_recents)}')
            date_limit = datetime.datetime.today() - datetime.timedelta(days=RECENT_DAYS)
            for contentid in more_recents:
                try:
                    blacklist = REDIS_CONN.lrange(REDIS_KEY_WAVVE_BLACKLIST_CONTENTS, 0, REDIS_CONN.llen(REDIS_KEY_WAVVE_BLACKLIST_CONTENTS))
                    if contentid in blacklist:
                        continue
                    if model.get_episode_by_recent(contentid):
                        continue
                    contents = SupportWavve.vod_contents_contentid(contentid)
                    programtitle = contents.get('seasontitle') or contents.get('programtitle')
                    episodenumber = contents.get('episodenumber', -1)
                    releasedate = contents.get('releasedate', '')
                    content_type = contents.get('type', '')
                    # 방송일자 형식이 1900-01-01 이 아니거나 오래됐으면 건너뛰기
                    try:
                        rel_date = datetime.datetime.strptime(releasedate, '%Y-%m-%d')
                        if rel_date < date_limit or \
                        rel_date - datetime.timedelta(days=1) > datetime.datetime.today():
                            REDIS_CONN.rpush(REDIS_KEY_WAVVE_BLACKLIST_CONTENTS, contentid)
                            continue
                    except Exception as e:
                        PLUGIN.logger.warning(f'{contentid} - releasedate={releasedate}')
                        REDIS_CONN.rpush(REDIS_KEY_WAVVE_BLACKLIST_CONTENTS, contentid)
                        continue

                    PLUGIN.logger.debug(f'add [{programtitle}] [{episodenumber}] [{releasedate}]')
                    info = {
                        'episodenumber': episodenumber,
                        'image': contents.get('image') or contents.get('programimage', ''),
                        'programtitle': programtitle,
                        'price': contents.get('price', -1),
                        'contentid': contentid,
                        'releasedate': releasedate,
                        'releaseweekday': contents.get('releaseweekday', ''),
                        'channelname': contents.get('channelname', ''),
                        'type': content_type,
                        'episodetitle': contents.get('episodetitle', ''),
                        'targetage': contents.get('targetage', 0),
                        'programid': contents.get('programid', ''),
                        'update': contents.get('update', '')
                    }
                    '''
                    # API 중복 조회를 회피하기 위해 직접 DB에 저장해 봤지만
                    # scheduler_function()에서 필터링 처리가 안 되는 상황이 발생
                    streaming = SupportWavve.streaming(content_type, contentid, recent_quality)
                    new_item = model('recent', info=info, streaming=streaming, contents=contents)
                    new_item.set_info(info)
                    new_item.set_streaming(streaming)
                    new_item.save()
                    '''
                    recents.append(info)
                except Exception as e:
                    PLUGIN.logger.warning(e)
                    PLUGIN.logger.warning(traceback.format_exc())
                    continue
        return data
    return wrap
SupportWavve.vod_newcontents = wrapper_vod_newcontents(SupportWavve.vod_newcontents)
