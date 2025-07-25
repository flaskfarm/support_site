from http.cookies import SimpleCookie

from . import SiteUtil
from .entity_base import (EntityActor, EntityExtra, EntityExtra2, EntityMovie,
                          EntityMovie2, EntityRatings, EntityReview,
                          EntitySearchItemFtv, EntitySearchItemMovie,
                          EntitySearchItemTv, EntityShow, EntityThumb)
from .setup import *


class SiteWatcha(object):
    site_name = 'watcha'
    site_base_url = 'https://thetvdb.com'

    """
    default_headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'x-watchaplay-client': 'WatchaPlay-WebApp',
        'x-watchaplay-client-language': 'ko',
        'x-watchaplay-client-region' : 'KR',
        'x-watchaplay-client-version' : '1.0.0',
        'referer': 'https://pedia.watcha.com/',
        'origin': 'https://pedia.watcha.com',
        'x-watcha-client': 'watcha-WebApp',
        'x-watcha-client-language': 'ko',
        'x-watcha-client-region': 'KR',
        'x-watcha-client-version': '2.0.0',
    }
    """
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0',
        'X-Watcha-Client-Language': 'ko',
        'X-Watcha-Client-Region': 'KR',
        'X-Frograms-Client-Version': '2.1.0',
        'X-Frograms-Client': 'Galaxy-Web-App',
        'X-Frograms-App-Code': 'Galaxy',
        'X-Frograms-Galaxy-Language': 'ko',
        'X-Frograms-Galaxy-Region': 'KR',
        'X-Frograms-Version': '2.1.0',
    }

    IMAGE_QUALITIES = ['xlarge', 'large', 'medium', 'small']
    POSTER_QUALITIES = ['hd', *IMAGE_QUALITIES]
    STILLCUT_QUALITIES = ['original', 'fullhd', *IMAGE_QUALITIES]

    @classmethod
    def initialize(cls, watcha_cookie: str, use_proxy: bool = False, proxy_url: str = None) -> None:
        cookies = SimpleCookie()
        try:
            cookies.load(watcha_cookie)
        except:
            logger.error(traceback.format_exc())
            logger.error('입력한 쿠키 값을 확인해 주세요.')
        cls._watcha_cookie = {key:morsel.value for key, morsel in cookies.items()}
        cls._use_proxy = use_proxy
        cls._proxy_url = proxy_url if cls._use_proxy else None

    @classmethod
    def _search_api(cls, keyword, content_type='movies'):
        try:
            url = 'https://pedia.watcha.com/api/searches?query=%s' % keyword
            data = cls.get_json(url)
            if content_type == 'movies':
                return data['result']['movies']
            elif content_type == 'tv_seasons':
                return data['result']['tv_seasons']
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            logger.debug(f'keyword: {keyword}, content_type: {content_type}, data: {data}')

    @classmethod
    def info_basic(cls, code, entity, api_return=False):
        try:
            url = 'https://pedia.watcha.com/api/contents/%s' % code
            data = cls.get_json(url).get('result')
            if api_return:
                return data
            entity.title = data['title']
            entity.year = data['year']
            for item in data['credits']['result']:
                try:
                    actor = EntityActor('', site=cls.site_name)
                    actor.name = item['person']['name']
                    if item['person']['photo']:
                        actor.thumb = item['person']['photo']['medium']
                    credit_types = item.get('type', '').split('::')
                    credit_type = credit_types[-1]
                    if credit_type == 'Director' and type(entity) != EntityShow:
                        entity.director.append(item['person']['name'])
                    else:
                        entity.actor.append(actor)
                except Exception as e:
                    logger.error(f"Exception:{str(e)}")
                    logger.error(traceback.format_exc())
                    logger.debug(item)
            try: entity.runtime = int(data['duration']/60)
            except: pass
            try:
                entity.extra_info['title_en'] = data.get('eng_title', '')
                if not entity.extra_info['title_en']:
                    data['original_title'].encode('ascii')
                    entity.extra_info['title_en'] = data.get('original_title', '')
            except: pass
            entity.mpaa = data.get('film_rating_long') or data.get('age_rating_long') or data.get('age_rating_short', '')
            for item in data['genres']:
                entity.genre.append(item)
            try: entity.country.append(data['nations'][0]['name'])
            except: pass
            entity.originaltitle = data['original_title']
            images = {
                'posters': [data['poster'][q] for q in cls.POSTER_QUALITIES if q in (data.get('poster') or {})],
                'stillcuts': [data['stillcut'][q] for q in cls.STILLCUT_QUALITIES if q in (data.get('stillcut') or {})]
            }
            for key in images:
                if not images[key]: continue
                thumb_entity = EntityThumb(aspect='poster' if key == 'posters' else 'landscape', value=images[key][0], thumb=images[key][-1], site=cls.site_name, score=60)
                entity.thumb.append(thumb_entity) if type(entity) is EntityShow else entity.art.append(thumb_entity)
            entity.plot = data['description'] if data['description'] else ''
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            logger.error(f'code={code}')


    @classmethod
    def info_review(cls, code, entity, api_return=False):
        try:
            url = 'https://pedia.watcha.com/api/contents/%s/comments?filter=all&order=popular' % code
            data = cls.get_json(url)
            if api_return:
                return data
            for item in data['result']['result']:
                review = EntityReview(cls.site_name)
                review.text = u'[좋아요 : %s' % item['likes_count']
                review.source = ''
                review.author = item['user']['name']
                if item['user_content_action']['rating'] is not None:
                    review.text += ' / 평점 : %s' % (item['user_content_action']['rating']/2.0)
                    review.rating = item['user_content_action']['rating']
                review.link = ''
                tmp = item['text'].replace('\n', '\r\n')
                tmp = re.sub(r'[^ %s-=+,#/\?:^$.@*\"~&%%!\\|\(\)\[\]\<\>`\'A-Za-z0-9]' % u'ㄱ-ㅣ가-힣', ' ', tmp)
                review.text += ']   ' + tmp
                entity.review.append(review)
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())



    @classmethod
    def info_collection(cls, code, entity, api_return=False, like_count=100):
        try:
            url = 'https://pedia.watcha.com/api/contents/%s/decks' % code
            data = cls.get_json(url)
            if api_return:
                return data
            for item in data['result']['result']:
                if item['likes_count'] > like_count:
                    entity.tag.append(item['title'])
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def get_json(cls, url: str) -> dict | None:
        try:
            data = SiteUtil.get_response(
                url,
                headers=cls.default_headers,
                proxy_url=cls._proxy_url,
                cookies=cls._watcha_cookie,
            ).json()
            return data
        except:
            logger.error(traceback.format_exc())




class SiteWatchaMovie(SiteWatcha):
    module_char = 'M'
    site_char = 'X'

    @classmethod
    def info_api(cls, code):
        try:
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]
            ret = {}
            ret['basic'] = cls.info_basic(code, None, api_return=True)
            ret['review'] = cls.info_review(code, None, api_return=True)
            ret['collection'] = cls.info_collection(code, None, api_return=True)
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def search_api(cls, keyword):
        return cls._search_api(keyword, 'movies')

    @classmethod
    def search(cls, keyword, year=1900):
        try:
            ret = {}
            data = cls.search_api(keyword)
            result_list = []
            if data is not None:
                for idx, item in enumerate(data):
                    entity = EntitySearchItemMovie(cls.site_name)
                    entity.code = cls.module_char + cls.site_char + item['code']
                    '''
                    https://pedia.watcha.com/ko-KR/contents/mWz3mPV
                    잭 화이트\x1d: 닐링 앳 더 앤썸 D.C.
                    '''
                    pritable_chars = [char for char in item['title'] if char.isprintable()]
                    entity.title = ''.join(pritable_chars)
                    if 'poster' in item and item['poster'] is not None and 'hd' in item['poster']:
                        entity.image_url = item['poster']['hd']
                    entity.year = item.get('year') or 1900
                    try: entity.desc = f"{item['nations'][0]['name']} - {item['director_names'][0]}"
                    except: pass
                    if SiteUtil.compare(keyword, entity.title):
                        if year != 1900:
                            if abs(entity.year-year) <= 1:
                                entity.score = 100
                            else:
                                entity.score = 80
                        else:
                            entity.score = 95
                    else:
                        entity.score = 80 - (idx*5)
                    result_list.append(entity.as_dict())
            if result_list:
                ret['ret'] = 'success'
                ret['data'] = result_list
            else:
                ret['ret'] = 'empty'
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def info(cls, code, like_count=100):
        try:
            ret = {}
            entity = EntityMovie2(cls.site_name, code)
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]
            entity.code_list.append(['watcha_id', code])
            cls.info_basic(code, entity)
            cls.info_review(code, entity)
            cls.info_collection(code, entity, like_count=like_count)
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret





































class SiteWatchaTv(SiteWatcha):
    module_char = 'F'
    site_char = 'X'

    @classmethod
    def info_api(cls, code):
        try:
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]
            ret = {}
            ret['basic'] = cls.info_basic(code, None, api_return=True)
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def search_api(cls, keyword):
        return cls._search_api(keyword, 'tv_seasons')

    # 로마도 검색할 경우 리턴이 Rome이다.
    @classmethod
    def search(cls, keyword, year=None, season_count=None):
        try:
            ret = {}
            data = cls.search_api(keyword)
            #logger.debug(json.dumps(data, indent=4))
            result_list = []
            for idx, item in enumerate(data):
                entity = EntitySearchItemFtv(cls.site_name)
                entity.code = cls.module_char + cls.site_char + item['code']
                entity.studio = item['channel_name']
                if entity.studio == None:
                    entity.studio = ''
                for tmp in item['nations']:
                    entity.country.append(tmp['name'])
                entity.title = item['title']
                entity.year = item['year']
                if 'poster' in item and item['poster'] is not None:
                    for tmp in ['hd', 'xlarge', 'large', 'medium', 'small']:
                        if tmp in item['poster']:
                            entity.image_url = item['poster'][tmp]
                            break
                regexes = [r'\s?%s\s?(?P<season_no>\d+)$' % u'시즌', r'\s(?P<season_no>\d{1,2})\s[$\:]']
                series_insert = False
                for regex in regexes:
                    match = re.search(regex, entity.title)
                    if match:
                        series_name = entity.title.split(match.group(0))[0].strip()
                        entity.extra_info['series_name'] = series_name
                        if series_name != entity.title:
                            series = None
                            for item in result_list:
                                if item['title'] == series_name:
                                    series = item
                                    break
                            if series is None:
                                series = EntitySearchItemFtv(cls.site_name)
                                series.title = series_name
                                series = series.as_dict()
                                result_list.append(series)
                            series['seasons'].append({'season_no':match.group('season_no'), 'year':entity.year, 'info':entity.as_dict()})
                            series['seasons'] = sorted(series['seasons'], key=lambda k: k['year'], reverse=False)
                            series_insert = True
                            break
                if series_insert:
                    continue
                result_list.append(entity.as_dict())

            for idx, item in enumerate(result_list):
                if len(item['seasons']) > 0:
                    item['year'] = item['seasons'][0]['year']
                if (SiteUtil.is_hangul(item['title']) and SiteUtil.is_hangul(keyword)) or (not SiteUtil.is_hangul(item['title']) and not SiteUtil.is_hangul(keyword)):
                    if SiteUtil.compare(item['title'], keyword):
                        if year is not None:
                            if abs(item['year']-year) < 1:
                                item['score'] = 100
                            else:
                                item['score'] = 80
                        else:
                            item['score'] = 95
                    else:
                        item['score'] = 80 - (idx*5)

                else:
                    if year is not None:
                        if abs(item['year']-year) < 1:
                            item['score'] = 100
                        else:
                            item['score'] = 80
                    else:
                        item['score'] = 80 - (idx*5)
                logger.debug('[%s] [%s] [%s] [%s] [%s]', item['title'], item['title_original'], item['year'], year, item['score'])
            result_list = sorted(result_list, key=lambda k: k['score'], reverse=True)

            for item in result_list:
                if len(item['seasons']) > 0:
                    season_data = cls.info_basic(item['seasons'][0]['info']['code'][2:], None, api_return=True)
                else:
                    season_data = cls.info_basic(item['code'][2:], None, api_return=True)
                #logger.debug(season_data['eng_title'])
                try: item['title_en'] = season_data['eng_title']
                except: item['title_en'] = None
                logger.debug('%s %s %s' % (item['title'], 'eng_title' in season_data, item['title_en']))

            if season_count is not None:
                for item in result_list:
                    if len(result_list[0]['seasons']) != season_count:
                        item['score'] += -5
            result_list = sorted(result_list, key=lambda k: k['score'], reverse=True)
            if result_list:
                ret['ret'] = 'success'
                ret['data'] = result_list
            else:
                ret['ret'] = 'empty'
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def info(cls, code):
        try:
            ret = {}
            entity = EntityShow(cls.site_name, code)
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]
            cls.info_basic(code, entity)
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret





class SiteWatchaKTv(SiteWatchaTv):
    module_char = 'K'
