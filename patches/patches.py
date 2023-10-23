import datetime
import functools
import re
import sys
import traceback
import pathlib
import shutil
from unittest.mock import patch
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

import redis
import yaml

from framework.init_main import Framework
from support_site import SupportWavve
from support_site.setup import P as PLUGIN

FRAMEWORK = Framework.get_instance()
CONFIG_FILE = pathlib.Path(f"{FRAMEWORK.config['path_data']}/db/patches.support_site.yaml")
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.20',
    'Wavve-Credential': PLUGIN.ModelSetting.get('site_wavve_credential'),
}
PTN_WAVVE_BANDWIDTH = re.compile(r'.*?BANDWIDTH=(\d+)')
PTN_WAVVE_LAST_URL = re.compile(r'^(.*?)/')
PTN_WAVVE_URL_LIST = re.compile(r'list.js')
PTN_WAVVE_URL_BAND = re.compile(r'band.js')
REDIS_EXPIRE = 86400 # in seconds
# REDIS_KEY_WAVVE_CONTENTS:{content_id} = {'releasedate': 'date', 'recent': 'true', ...}
REDIS_KEY_WAVVE_CONTENTS = 'flaskfarm:support_site:wavve:contents'

try:
    REDIS_CONN = redis.Redis(host='localhost', port=6379, decode_responses=True)
    cursor = '0'
    while cursor != 0:
        cursor, keys = REDIS_CONN.scan(cusor=cursor, match=f'{REDIS_KEY_WAVVE_CONTENTS}:*', count=5000)
        if keys:
            REDIS_CONN.delete(*keys)
except:
    PLUGIN.logger.error(traceback.format_exc())
    REDIS_CONN = None


def get_config() -> dict:
    '''
    /data/db/patches.support_site.yaml
    변경사항은 플러그인 로딩시 적용
    '''
    default = pathlib.Path(__file__).parent / 'files' / 'patches.support_site.yaml'
    try:
        if not CONFIG_FILE.exists():
            shutil.copyfile(default, CONFIG_FILE)
        with CONFIG_FILE.open(encoding='utf-8', newline='\n') as file:
            return yaml.safe_load(file)
    except Exception as e:
        PLUGIN.logger.warning(e)
        with default.open(encoding='utf-8', newline='\n') as file:
            return yaml.safe_load(file)
CONFIG = get_config()


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
                args[0]['episodenumber'] = parse_episode_number(args[0]['episodenumber'])
            releasedate = args[0].get('releasedate')
            if not releasedate and args[0].get('contentid'):
                releasedate = hget(f'{REDIS_KEY_WAVVE_CONTENTS}:{args[0]["contentid"]}', 'releasedate')
                args[0]['releasedate'] = releasedate or args[0]['releasedate']
        except:
            PLUGIN.logger.debug(args)
            PLUGIN.logger.debug(kwargs)
            PLUGIN.logger.error(traceback.format_exc())
        return f(*args, **kwargs)
    return wrap
SupportWavve.get_filename = get_filename_warpper(SupportWavve.get_filename)


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
            match = PTN_WAVVE_BANDWIDTH.match(l)
            if match:
                bandwidth = int(match.group(1))
                if bandwidth > max_bandwidth:
                    max_bandwidth = bandwidth
                    last_url = next(iterator)
        if last_url is not None and last_url != '':
            match = PTN_WAVVE_LAST_URL.match(last_url)
            if match:
                url_type = match.group(1)
                if url.find('chunklist') != -1:
                    url_type = f'chunklist{url_type}'
                last_url = f'{url.split(url_type)[0]}{last_url}'
                return last_url
        PLUGIN.logger.debug(f'function: {sys._getframe().f_code.co_name}, url: {url}, data: {data}')
        return url
    except:
        PLUGIN.logger.error(traceback.format_exc())
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


def wrapper_vod_program_contents_programid(f: callable) -> callable:
    @functools.wraps(f)
    def wrap(code: str, page: int = 1) -> dict:
        '''
        기존 API에서 정보를 가져오지 못 할 경우 새로운 API로 시도
        '''
        data = f(code, page)
        if data.get('list'):
            return data
        else:
            PLUGIN.logger.debug(f'No episode list of {code} on page {page}: {data}')
            query = dict(parse_qsl(CONFIG['patches']['wavve']['query']))
            query['offset'] = (page - 1) * 10
            try:
                data = vod_programs_contents(code, query)
                data = data.pop('cell_toplist')
                data['list'] = data['celllist']
                for ep in data['list']:
                    ep['image'] = ep.pop('thumbnail')
                    ep['programtitle'] = ep.pop('alt')
                    ep['episodeactors'] = ep.pop('actors')
                    ep['episodetitle'] = ep.get('episodetitle') or ep.get('title_list', [{}])[0].get('text') or ep.get('contentid')
                    ep['targetage'] = ep.get('targetage') or '0'
                    check_date(ep.get('releasedate'), ep.get('contentid'))
            except:
                PLUGIN.logger.error(traceback.format_exc())
                PLUGIN.logger.debug(f'{code}: {data}')
            finally:
                return data
    return wrap
SupportWavve.vod_program_contents_programid = wrapper_vod_program_contents_programid(SupportWavve.vod_program_contents_programid)


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
        #PLUGIN.logger.error(traceback.format_exc())
        pass
    finally:
        return response


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
    return check_empty_json(response, query.get("keyword", [None])[0], r'{"cell_toplist": {}}', PTN_WAVVE_URL_LIST.search(url_parts[2]))
SupportWavve.search_movie = patch_wrapper(SupportWavve.search_movie, 'support_site.SupportWavve.session.get', patch_session_get)


def patch_search_session_get(*args, **kwds):
    '''
    웨이브 band.js api 검색 응답이 '{}'일 경우:
        band.js api: KeyError: 'band'
    '''
    response = SupportWavve.session.request('GET', *args, **kwds)
    url_parts = urlparse(args[0])
    query = parse_qs(url_parts.query)
    return check_empty_json(response, query.get("keyword", [None])[0], r'{"band": {}}', PTN_WAVVE_URL_BAND.search(url_parts.path))
SupportWavve._SupportWavve__search = patch_wrapper(SupportWavve._SupportWavve__search, 'support_site.SupportWavve.session.get', patch_search_session_get)


def wrapper_vod_programs_programid(f: callable) -> callable:
    @functools.wraps(f)
    def wrap(*args, **kwds):
        '''
        /vod/programs API로 데이터를 가져오지 못할 경우 대응
        증상:
            플렉스에서 일부 프로그램을 웨이브 메타 적용시 오류 발생
        '''
        data = f(*args, **kwds) or {}
        if not data:
            PLUGIN.logger.debug(f'No data of {args[0]}')
            query = dict(parse_qsl(CONFIG['patches']['wavve']['query']))
            query.pop('limit')
            query.pop('offset')
            query['programid'] = args[0]
            query['history'] = 'season'
            try:
                content_id = vod_programs_landing(query).get('content_id')
                contents = SupportWavve.vod_contents_contentid(content_id)
            except:
                PLUGIN.logger.error(traceback.format_exc())
                contents = None
            if contents:
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
        return data
    return wrap
SupportWavve.vod_programs_programid = wrapper_vod_programs_programid(SupportWavve.vod_programs_programid)


def get_vod_ids(celllist: list) -> set:
    contents_ids = set()
    for vod in celllist:
        try:
            _id = parse_qs(vod['event_list'][1]['url'].split('?')[1]).get('contentid')[0]
            contents_ids.add(_id)
            # 방송 날짜 파싱 후 레디스에 임시 저장
            title_list = vod.get('title_list')
            if title_list:
                date_text = title_list[-1].get('text')
                for match in re.findall(CONFIG['patches']['wavve']['patterns_airdate'], date_text):
                    redis_key = f'{REDIS_KEY_WAVVE_CONTENTS}:{_id}'
                    hset(redis_key, 'releasedate', match)
                    break
        except:
            PLUGIN.logger.error(traceback.format_exc())
            continue
    return contents_ids


def get_vod_ids_from_newcontents(page: int) -> set:
    '''
    새로운 API 에서 content id 수집
    '''
    query = dict(parse_qsl(CONFIG['patches']['wavve']['query']))
    query['subgenre'] = 'all'
    query['channel'] = 'all'
    query['weekday'] = 'all'
    query['genre'] = 'all'
    #query['limit'] = CONFIG['patches']['wavve']['list_limit']
    # 기존 API와 동일하게 기본 20개씩 로딩.
    query['limit'] = 20
    query['offset'] = (page - 1) * query['limit']
    try:
        celllist = vod_newcontents(query).get('cell_toplist', {}).get('celllist', [])
        return get_vod_ids(celllist)
    except:
        PLUGIN.logger.error(traceback.format_exc())
        return set()


def get_vod_ids_from_search(keyword: str, page: int) -> set:
    '''
    검색 키워드에서 content ID 수집
    '''
    query = dict(parse_qsl(CONFIG['patches']['wavve']['query']))
    query['limit'] = CONFIG['patches']['wavve']['list_limit']
    query['offset'] = (page - 1) * query['limit']
    query['type'] = 'vod'
    query['version'] = '2'
    query['mtype'] = ''
    try:
        celllist = search_list(keyword, query).get('cell_toplist', {}).get('celllist', [])
        return get_vod_ids(celllist)
    except:
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
        model = wavve.logic.get_module('recent').web_list_model
        page = kwds.get('page', 1)
        # 1. 취합 목록
        more_recents = set()
        # 2. 기존의 SupportWavve.vod_newcontents() 에서 수집한 목록
        data: dict = f(*args, **kwds)
        recents = data.get('list', [])
        recents_ids = {epi['contentid'] for epi in recents}
        PLUGIN.logger.debug(f'current page: {kwds.get("page", -1)}')
        # 3. 새로운 API 에서 수집한 목록
        more_newcontents = get_vod_ids_from_newcontents(page)
        PLUGIN.logger.debug(f'newcontents: {len(more_newcontents - recents_ids)} more items')
        more_recents.update(more_newcontents)
        # 4. 키워드 검색으로 수집한 목록
        for keyword in CONFIG['patches']['wavve']['keywords'].split('|'):
            if keyword:
                ids = get_vod_ids_from_search(keyword, page)
                PLUGIN.logger.debug(f'{keyword}: {len(ids - (recents_ids | more_recents))} more items')
                more_recents.update(ids)
        PLUGIN.logger.debug(f'more_recents: before={len(more_recents)} after={len(more_recents - recents_ids)}')
        # 5. 2번 목록과 비교후 중복 제거
        more_recents.difference_update(recents_ids)
        if more_recents:
            PLUGIN.logger.debug(f'found more vods: {len(more_recents)}')
            # 6. VOD 정보 가져오기
            for contentid in more_recents:
                try:
                    # DB 및 redis에서 skip 대상인지 확인
                    redis_key = f'{REDIS_KEY_WAVVE_CONTENTS}:{contentid}'
                    if hget(redis_key, 'recent') == 'false' or model.get_episode_by_recent(contentid):
                        continue
                    # VOD 정보 수집
                    contents = SupportWavve.vod_contents_contentid(contentid)
                    # 방송날짜 우선 순위 1. /fz/vod/contents의 releasedate 2. /cf/vod/newcontents 목록의 타이틀 3. /fz/vod/contents의 firstreleasedate
                    releasedate_redis = hget(redis_key, 'releasedate')
                    releasedate = contents.get('releasedate') or releasedate_redis or contents.get('firstreleasedate', '')
                    if not check_date(releasedate, contentid):
                        continue
                    programtitle = contents.get('seasontitle') or contents.get('programtitle')
                    episodenumber = parse_episode_number(contents.get('episodenumber', 0))
                    content_type = contents.get('type', '')
                    # 기존 /vod/contents API 형식에 맞춰 VOD 정보 입력
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
                    recents.append(info)
                except:
                    PLUGIN.logger.warning(traceback.format_exc())
                    continue
        return data
    return wrap
SupportWavve.vod_newcontents = wrapper_vod_newcontents(SupportWavve.vod_newcontents)


def parse_episode_number(epno: str) -> str:
    '''
    episodenumber 정보에 "Part1 10" 패턴이 있을 경우 대응
    다른 소스에서 len()을 사용하기 때문에 str로 리턴
    '''
    if not epno.isdigit():
        for ptn in CONFIG['patches']['wavve']['patterns_episode'].splitlines():
            for match in re.findall(ptn, epno):
                if match.isdigit():
                    PLUGIN.logger.debug(f'episode number: [{epno}] -> [{match}]')
                    epno = match
    return epno


def check_date(releasedate: str, contentid: str) -> bool:
    # 방송일자 형식이 1900-01-01 이 아니거나 오래됐으면 False
    confirm = True
    if CONFIG['patches']['wavve']['check_date']:
        date_limit = datetime.datetime.today() - datetime.timedelta(days=CONFIG['patches']['wavve']['recent_days'])
        redis_key = f'{REDIS_KEY_WAVVE_CONTENTS}:{contentid}'
        try:
            rel_datetime = datetime.datetime.strptime(releasedate, '%Y-%m-%d')
            if rel_datetime > date_limit and rel_datetime < datetime.datetime.today() + datetime.timedelta(days=2):
                hset(redis_key, 'releasedate', releasedate)
                hset(redis_key, 'recent', 'true')
            else:
                confirm = False
        except:
            confirm = False
        finally:
            if not confirm:
                hset(redis_key, 'recent', 'false')
    return confirm


def check_redis(func: callable) -> callable:
    @functools.wraps(func)
    def wrap(*args, **kwds) -> str | int | None:
        if REDIS_CONN:
            return func(*args, **kwds)
    return wrap


@check_redis
def hset(key: str, field: str = None, value: str = None, mapping: dict = None, items: list = None) -> None:
    REDIS_CONN.hset(key, field, value, mapping, items)
    if REDIS_CONN.ttl(key) < 0:
        REDIS_CONN.expire(key, time=REDIS_EXPIRE)


@check_redis
def hget(key: str, field: str) -> str | None:
    return REDIS_CONN.hget(key, field)


@check_redis
def hgetall(key: str) -> dict:
    return REDIS_CONN.hgetall(key)
