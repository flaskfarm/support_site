import json

from support_site import MetadataServerUtil

from .entity_base import (EntityActor, EntityActor2, EntityEpisode2,
                          EntityExtra2, EntityFtv, EntityMovie2, EntityRatings,
                          EntitySearchItemFtv, EntitySearchItemMovie,
                          EntitySeason, EntityThumb)
from .setup import *
from .site_util import SiteUtil

try:
    import tmdbsimple
except Exception:
    os.system("pip install tmdbsimple")
    import tmdbsimple
API_KEY = 'f090bb54758cabf231fb605d3e3e0468'
tmdbsimple.API_KEY = API_KEY

ARTWORK_ITEM_LIMIT = 10
POSTER_SCORE_RATIO = .3 # How much weight to give ratings vs. vote counts when picking best posters. 0 means use only ratings.
BACKDROP_SCORE_RATIO = .3


def _stash_tmdb_extra(entity, key, value):
    """TMDB 원본 구조화 데이터를 extra_info['tmdb']에 보존한다.
    additive 채널 — 기존 소비자(Plex 에이전트/Kodi 규격 필드)에 영향 없음."""
    try:
        if not value:
            return
        if not isinstance(getattr(entity, 'extra_info', None), dict):
            return
        entity.extra_info.setdefault('tmdb', {})[key] = value
    except Exception:
        pass


class SiteTmdb(object):
    site_name = 'tmdb'
    site_char = 'T'

    image_base_url = 'https://image.tmdb.org/t/p/'

    @classmethod
    def initialize(cls, user_api_key: str, user_image_sizes: str) -> None:
        tmdbsimple.API_KEY = user_api_key if user_api_key else API_KEY
        cls.image_sizes = {
            "poster": {"default": "original", "thumb": "w154"}, # "w92", "w154", "w185", "w342", "w500", "w780", "original"
            "backdrop": {"default": "original", "thumb": "w300"}, # "w300", "w780", "w1280", "original"
            "logo": {"default": "original", "thumb": "w45"}, # "w45", "w92", "w154", "w185", "w300", "w500", "original"
            "profile": {"default": "original", "thumb": "w45"}, # "w45", "w185", "h632", "original"
            "still": {"default": "original", "thumb": "w92"}, # "w92", "w185", "w300", "original"
        }
        try:
            user_image_sizes = json.loads(user_image_sizes)
            for key in cls.image_sizes.keys() & user_image_sizes.keys():
                if isinstance(user_image_sizes[key], dict):
                    cls.image_sizes[key].update(user_image_sizes[key])
        except Exception:
            ...
        logger.debug(f"TMDB image sizes: {cls.image_sizes}")

    @classmethod
    def get_image_url(cls, image_path: str, category: str = 'poster', size: str = 'default') -> str:
        if not isinstance(image_path, str):
            return ""
        sizes = cls.image_sizes.get(category) or cls.image_sizes['poster']
        size = sizes.get(size) or sizes.get('default')
        return f"{cls.image_base_url.rstrip('/')}/{size.strip('/')}/{image_path.lstrip('/')}"

    @classmethod
    def get_video_urls(cls, item):
        """
        TMDB videos 결과를 내 서버용 URL 구조로 변환.
        - external_url: YouTube/Vimeo 등 원본 서비스 URL
        - tmdb_url: TMDB 웹의 video play 페이지 주소
        """
        site = item.get('site') or ''
        key = item.get('key') or ''

        external_url = ''
        if site == 'YouTube' and key:
            external_url = f'https://www.youtube.com/watch?v={key}'
        elif site == 'Vimeo' and key:
            external_url = f'https://vimeo.com/{key}'

        tmdb_url = f'https://www.themoviedb.org/video/play?key={key}' if key else ''

        return external_url, tmdb_url

    @classmethod
    def normalize_video_type(cls, video_type):
        if video_type == 'Teaser':
            return 'Trailer'
        if video_type == 'Clip':
            return 'Short'
        if video_type == 'Behind the Scenes':
            return 'BehindTheScenes'
        return video_type

    @classmethod
    def fetch_videos(cls, tmdb):
        """
        tmdbsimple 버전 차이를 감안해서 fallback.
        """
        for kwargs in (
            {'language': 'ko-KR', 'include_video_language': 'ko,en,null'},
            {'language': 'ko-KR'},
            {'language': 'ko'},
            {},
        ):
            try:
                return tmdb.videos(**kwargs)
            except TypeError:
                continue
            except Exception as e:
                logger.warning(f'TMDB videos fetch failed: kwargs={kwargs}, error={str(e)}')
                continue
        return {'results': []}

    @classmethod
    def info_trailers(cls, tmdb, entity):
        """
        use_trailer=True일 때만 호출.
        Plex용으로는 사용하지 않음
        """
        try:
            info = cls.fetch_videos(tmdb)
            results = info.get('results') or []
            trailers = []

            for item in results:
                try:
                    key = item.get('key') or ''
                    site = item.get('site') or ''
                    if not key:
                        continue

                    video_type = cls.normalize_video_type(item.get('type'))

                    if video_type not in ['Trailer', 'Featurette', 'Short', 'BehindTheScenes']:
                        continue

                    external_url, tmdb_url = cls.get_video_urls(item)

                    trailers.append({
                        'source': 'tmdb',
                        'provider': site.lower(),
                        'key': key,
                        'external_url': external_url,
                        'tmdb_url': tmdb_url,
                        'url': external_url or tmdb_url,
                        'title': item.get('name') or '',
                        'type': video_type,
                        'language': item.get('iso_639_1') or '',
                        'country': item.get('iso_3166_1') or '',
                        'official': bool(item.get('official')),
                        'size': item.get('size'),
                        'published_at': item.get('published_at') or '',
                        'tmdb_video_id': item.get('id') or '',
                    })
                except Exception as e:
                    logger.warning(f'TMDB video parse failed: {str(e)}')

            def score(t):
                return (
                    1 if t.get('type') == 'Trailer' else 0,
                    1 if t.get('language') == 'ko' else 0,
                    1 if t.get('official') else 0,
                    1 if t.get('provider') == 'youtube' else 0,
                    1 if t.get('country') == 'KR' else 0,
                    t.get('size') or 0,
                    t.get('published_at') or '',
                )

            trailers = sorted(trailers, key=score, reverse=True)

            _stash_tmdb_extra(entity, 'videos', results)
            _stash_tmdb_extra(entity, 'trailers', trailers)

            if trailers:
                logger.debug(f'TMDB trailers found: {len(trailers)}')

        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def _process_image(cls, tmdb, data):
        try:
            tmdb_images_dict = tmdb.images()

            if 'posters' in tmdb_images_dict and tmdb_images_dict['posters']:
                max_average = max([(lambda p: p['vote_average'] or 5)(p) for p in tmdb_images_dict['posters']])
                max_count = max([(lambda p: p['vote_count'])(p) for p in tmdb_images_dict['posters']]) or 1

                for i, poster in enumerate(tmdb_images_dict['posters']):

                    score = (poster['vote_average'] / max_average) * POSTER_SCORE_RATIO
                    score += (poster['vote_count'] / max_count) * (1 - POSTER_SCORE_RATIO)
                    tmdb_images_dict['posters'][i]['score'] = score

                    # Boost the score for localized posters (according to the preference).
                    if poster['iso_639_1'] == 'ko':
                        tmdb_images_dict['posters'][i]['score'] = poster['score'] + 3

                    # Discount score for foreign posters.
                    if poster['iso_639_1'] != 'ko' and poster['iso_639_1'] is not None and poster['iso_639_1'] != 'en':
                        tmdb_images_dict['posters'][i]['score'] = poster['score'] - 1

                for i, poster in enumerate(sorted(tmdb_images_dict['posters'], key=lambda k: k['score'], reverse=True)):
                    if i > ARTWORK_ITEM_LIMIT:
                        break
                    else:
                        poster_url = cls.get_image_url(poster['file_path'])
                        thumb_url = cls.get_image_url(poster['file_path'], size='thumb')
                        data.append(EntityThumb(aspect='poster', value=poster_url, thumb=thumb_url, site='tmdb', score=poster['score']+100).as_dict())

            if 'backdrops' in tmdb_images_dict and tmdb_images_dict['backdrops']:
                max_average = max([(lambda p: p['vote_average'] or 5)(p) for p in tmdb_images_dict['backdrops']])
                max_count = max([(lambda p: p['vote_count'])(p) for p in tmdb_images_dict['backdrops']]) or 1

                for i, backdrop in enumerate(tmdb_images_dict['backdrops']):
                    score = (backdrop['vote_average'] / max_average) * BACKDROP_SCORE_RATIO
                    score += (backdrop['vote_count'] / max_count) * (1 - BACKDROP_SCORE_RATIO)
                    tmdb_images_dict['backdrops'][i]['score'] = score

                    # For backdrops, we prefer "No Language" since they're intended to sit behind text.
                    if backdrop['iso_639_1'] == 'xx' or backdrop['iso_639_1'] == 'none':
                        tmdb_images_dict['backdrops'][i]['score'] = float(backdrop['score']) + 2

                    # Boost the score for localized art (according to the preference).
                    if backdrop['iso_639_1'] == 'ko':
                        tmdb_images_dict['backdrops'][i]['score'] = float(backdrop['score']) + 3

                    # Discount score for foreign art.
                    if backdrop['iso_639_1'] != 'ko' and backdrop['iso_639_1'] is not None and backdrop['iso_639_1'] != 'en':
                        tmdb_images_dict['backdrops'][i]['score'] = float(backdrop['score']) - 1

                for i, backdrop in enumerate(sorted(tmdb_images_dict['backdrops'], key=lambda k: k['score'], reverse=True)):
                    if i > ARTWORK_ITEM_LIMIT:
                        break
                    else:
                        backdrop_url = cls.get_image_url(backdrop['file_path'], 'backdrop')
                        thumb_url = cls.get_image_url(backdrop['file_path'], 'backdrop', 'thumb')
                        data.append(EntityThumb(aspect='landscape', value=backdrop_url, thumb=thumb_url, site='tmdb', score=backdrop['score']+100).as_dict())
            
            if logos := tmdb_images_dict.get('logos'):
                max_average = max(logo.get("vote_average") or 5 for logo in logos)
                max_count = max(logo.get("vote_count") or 1 for logo in logos)
                for idx, logo in enumerate(logos):
                    try:
                        score = (logo.get('vote_average') or 0) / max_average * POSTER_SCORE_RATIO
                        score += (logo.get('vote_count') or 0) / max_count * (1 - POSTER_SCORE_RATIO)
                        logos[idx]['score'] = score
                        lang = logo.get('iso_639_1')
                        if lang == 'xx' or lang == 'none':
                            logos[idx]['score'] = float(logos[idx]['score']) + 2
                        elif lang == 'ko':
                            logos[idx]['score'] = float(logos[idx]['score']) + 3
                        elif lang == 'en':
                            logos[idx]['score'] = float(logos[idx]['score']) + 1
                        else:
                            logos[idx]['score'] = float(logos[idx]['score']) - 2
                    except Exception as e:
                        logger.error(str(e))
                
                logos = sorted(logos, key=lambda k: k.get('score') or 0, reverse=True)
                for idx, logo in enumerate(logos):
                    if idx > ARTWORK_ITEM_LIMIT:
                        break
                    try:
                        logo_url = cls.get_image_url(logo.get('file_path'), 'logo')
                        thumb_url = cls.get_image_url(logo.get('file_path'), 'logo', 'thumb')
                        data.append(EntityThumb(aspect='logo', value=logo_url, thumb=thumb_url, site='tmdb', score=logo.get('score') or 0).as_dict())
                    except Exception as e:
                        logger.error(str(e))
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def _set_crews(cls, data: dict, mappings: dict, should_translate: bool = False) -> None:
        for item in data.get('crew') or ():
            job = item.get('job')
            if job in mappings:
                mappings[job][0].append(item)
        for job in mappings:
            try:
                mappings[job][0].sort(key=lambda x: ((x.get('popularity') or 0), -(x.get('id') or 0)))
            except Exception as e:
                logger.error(str(e))
        max_crews = 20
        selected_crew_count = 0
        while selected_crew_count < max_crews:
            should_stop = True
            for data_list, entity_list in mappings.values():
                try:
                    if not data_list:
                        continue
                    item = data_list.pop()
                    should_stop = False
                    if crew_name := item.get('name'):
                        if should_translate and not SiteUtil.is_include_hangul(crew_name):
                            try:
                                if translated := SiteUtil.trans(crew_name, source='en', target='ko'):
                                    crew_name = translated.replace(' ', '')
                            except Exception as e:
                                logger.warning(str(e))
                        entity_list.append(crew_name)
                        selected_crew_count += 1
                    if selected_crew_count >= max_crews:
                        return
                except Exception as e:
                    logger.error(str(e))
            if should_stop:
                break
















class SiteTmdbTv(SiteTmdb):

    #site_base_url = 'https://search.daum.net'
    module_char = 'K'



    @classmethod
    def search(cls, title, premiered):
        try:
            tmdb_search = tmdbsimple.Search().tv(query=title, language='ko', include_adult=True)
            for t in tmdb_search['results']:
                if premiered == t['first_air_date']:
                    return t['id']
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
        return

    @classmethod
    def process_image(cls, tmdb, show):
        cls._process_image(tmdb, show['thumb'])


    @classmethod
    def process_actor_image(cls, tmdb, show):
        try:
            tmdb_actor = tmdb.credits(language='en')
            for tmdb_item in tmdb_actor['cast']:
                if tmdb_item['profile_path'] is None:
                    continue
                try:
                    kor_name = SiteUtil.trans(tmdb_item['name'], source='en', target='ko')
                except Exception:
                    kor_name = None
                flag_find = False
                for actor in show['actor']:
                    if actor['name'] == kor_name:
                        flag_find = True
                        actor['thumb'] = cls.get_image_url(tmdb_item['profile_path'], 'profile')
                        break
                if flag_find == False:
                    try:
                        kor_role_name = SiteUtil.trans(tmdb_item['character'], source='en', target='ko')
                    except Exception:
                        kor_role_name = None
                    for actor in show['actor']:
                        if actor['role'] == kor_role_name:
                            flag_find = True
                            actor['thumb'] = cls.get_image_url(tmdb_item['profile_path'], 'profile')
                            break
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def apply(cls, tmdb_id, show, apply_image=True, apply_actor_image=True):
        try:
            tmdb = tmdbsimple.TV(tmdb_id)
            tmdb_dict = tmdb.info()

            votes = tmdb_dict['vote_count']
            rating = tmdb_dict['vote_average']

            if votes > 3:
                show['ratings'].append(EntityRatings(rating, max=10, name='tmdb').as_dict())

            if apply_image:
                cls.process_image(tmdb, show)

            if apply_actor_image:
                cls.process_actor_image(tmdb, show)

            # episodes
            try:
                target_season_no = None
                seasons = tmdb_dict.get('seasons', [])

                # air_date match
                if show.get('premiered'):
                    for s in seasons:
                        if s.get('air_date') == show['premiered'] and s.get('season_number', 0) > 0:
                            target_season_no = s['season_number']
                            break

                # year match
                if target_season_no is None and show.get('premiered'):
                    show_year = show['premiered'].split('-')[0]
                    for s in seasons:
                        if s.get('air_date') and s['air_date'].split('-')[0] == show_year and s.get('season_number', 0) > 0:
                            target_season_no = s['season_number']
                            break

                # show['season'] match
                if target_season_no is None:
                    show_season = show.get('season', 1)
                    for s in seasons:
                        if s.get('season_number') == show_season:
                            target_season_no = show_season
                            break

                # single season
                if target_season_no is None:
                    valid_seasons = [s for s in seasons if s.get('season_number', 0) > 0]
                    if len(valid_seasons) == 1:
                        target_season_no = valid_seasons[0]['season_number']

                if target_season_no is None:
                    target_season_no = 1

                logger.debug(f"TMDB: matching season={target_season_no} for show={show.get('title')}")

                tmdb_season = tmdbsimple.TV_Seasons(tmdb_id, target_season_no)
                try:
                    info_ko = tmdb_season.info(language='ko')
                except Exception:
                    info_ko = {}
                try:
                    info_en = tmdb_season.info(language='en')
                except Exception:
                    info_en = {}

                if 'episodes' in info_ko:
                    if 'extra_info' not in show:
                        show['extra_info'] = {}
                    if 'episodes' not in show['extra_info']:
                        show['extra_info']['episodes'] = {}

                    en_episodes = {e['episode_number']: e for e in info_en.get('episodes', []) if 'episode_number' in e}

                    for tmp in info_ko['episodes']:
                        epi_num = tmp.get('episode_number')
                        if epi_num is None:
                            continue

                        title_text = tmp.get('name') or ''
                        plot_text = tmp.get('overview') or ''

                        en_epi = en_episodes.get(epi_num, {})

                        # fallback to English title
                        if (not title_text or title_text.find(u'에피소드') != -1 or not SiteUtil.is_include_hangul(title_text)) and en_epi.get('name'):
                            title_text = en_epi['name']

                        # fallback to English plot
                        if (not plot_text or not SiteUtil.is_include_hangul(plot_text)) and en_epi.get('overview'):
                            plot_text = en_epi['overview']

                        still_path = tmp.get('still_path')
                        episode_still = cls.get_image_url(still_path, 'still') if still_path else ''
                        episode_thumb = cls.get_image_url(still_path, 'still', size='thumb') if still_path else ''
                        premiered = tmp.get('air_date') or ''

                        if epi_num not in show['extra_info']['episodes']:
                            show['extra_info']['episodes'][epi_num] = {}

                        show['extra_info']['episodes'][epi_num][cls.site_name] = {
                            'code': f"{cls.module_char}{cls.site_char}{tmdb_id}_{target_season_no}_{epi_num}",
                            'value': episode_still,
                            'thumb': episode_thumb,
                            'plot': plot_text,
                            'premiered': premiered,
                            'title': title_text,
                        }
            except Exception:
                try:
                    show_code = show.get('code')
                except Exception:
                    show_code = None
                logger.exception(f"에피소드 적용 중 오류: {tmdb_id=} code={show_code}")
            return True
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
        return False

















class SiteTmdbMovie(SiteTmdb):

    #site_base_url = 'https://search.daum.net'
    module_char = 'M'

    @classmethod
    def search_api(cls, keyword):

        logger.debug(keyword)
        try:
            tmdb_search = tmdbsimple.Search().movie(query=keyword, language='ko', include_adult=True)
            return tmdb_search
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info_api(cls, code):
        try:
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]

            tmdb = tmdbsimple.Movies(code)
            ret = {}
            ret['info'] = tmdb.info(language='ko')
            ret['image'] = tmdb.images()
            ret['credits'] = tmdb.credits(language='ko')
            ret['video'] = cls.fetch_videos(tmdb)
            ret['releases'] = tmdb.releases()

            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def search(cls, keyword, year=1900):
        try:
            ret = {}
            logger.debug('tmdb search : %s', keyword)
            tmdb_search = tmdbsimple.Search().movie(query=keyword, language='ko', include_adult=True)
            logger.debug('TMDB MOVIE SEARCh [%s] [%s]', keyword, year)
            result_list = []
            for idx, item in enumerate(tmdb_search['results']):
                entity = EntitySearchItemMovie(cls.site_name)
                entity.code = '%s%s%s' % (cls.module_char, cls.site_char, item['id'])
                entity.title = item['title'].strip()
                entity.originaltitle = item['original_title'].strip()
                entity.image_url = cls.get_image_url(item['poster_path'])
                try: entity.year = int(item['release_date'].split('-')[0])
                except Exception: entity.year = 1900
                #if item['actor'] != '':
                #    entity.desc += u'배우 : %s\r\n' % ', '.join(item['actor'].rstrip('|').split('|'))
                #if item['director'] != '':
                #    entity.desc += u'감독 : %s\r\n' % ', '.join(item['director'].rstrip('|').split('|'))
                #if item['userRating'] != '0.00':
                #    entity.desc += u'평점 : %s\r\n' % item['userRating']
                entity.desc = item['overview']
                entity.link = f"https://www.themoviedb.org/movie/{item['id']}"

                if SiteUtil.compare(keyword, entity.title) or SiteUtil.compare(keyword, entity.originaltitle):
                    if year != 1900:
                        if abs(entity.year-year) < 2:
                            entity.score = 100
                        else:
                            entity.score = 80
                    else:
                        entity.score = 95
                else:
                    entity.score = 80 - (idx*5)
                result_list.append(entity.as_dict())

            result_list = sorted(result_list, key=lambda k: k['score'], reverse=True)

            if result_list:
                ret['ret'] = 'success'
                ret['data'] = result_list
            else:
                ret['ret'] = 'empty'

            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def info(cls, code, use_trailer=False):
        try:
            ret = {}
            entity = EntityMovie2(cls.site_name, code)
            tmdb = tmdbsimple.Movies(code[2:])
            entity.code_list.append(['tmdb_id', code[2:]])
            cls.info_basic(tmdb, entity)
            cls.info_actor(tmdb, entity)
            if use_trailer:
                cls.info_videos(tmdb, entity)
            cls.info_releases(tmdb, entity)

            entity = entity.as_dict()
            cls._process_image(tmdb, entity['art'])

            ret['ret'] = 'success'
            ret['data'] = entity #entity.as_dict() #tmdb_dict



        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret

    @classmethod
    def info_videos(cls, tmdb, entity):
        try:
            info = tmdb.videos(language='ko-KR', include_video_language='ko,en,null')
            logger.debug(info)

            def normalize_type(video_type):
                if video_type == 'Teaser':
                    return 'Trailer'
                elif video_type == 'Clip':
                    return 'Short'
                elif video_type == 'Behind the Scenes':
                    return 'BehindTheScenes'
                return video_type

            def video_score(item):
                video_type = normalize_type(item.get('type'))
                name = item.get('name') or ''
                lang = item.get('iso_639_1') or ''
                country = item.get('iso_3166_1') or ''

                return (
                    1 if video_type == 'Trailer' else 0,
                    1 if lang == 'ko' else 0,
                    1 if country == 'KR' else 0,
                    1 if item.get('official') else 0,
                    1 if '메인' in name else 0,
                    item.get('size') or 0,
                    item.get('published_at') or '',
                )

            results = info.get('results') or []
            results = sorted(results, key=video_score, reverse=True)

            for tmdb_item in results:
                # 기존 로직처럼 YouTube만 사용
                if tmdb_item.get('site') != 'YouTube':
                    continue

                key = tmdb_item.get('key')
                if not key:
                    continue

                video_type = normalize_type(tmdb_item.get('type'))

                if video_type not in ['Trailer', 'Featurette', 'Short', 'BehindTheScenes']:
                    logger.debug(u'소스 확인 zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz')
                    logger.debug(tmdb_item.get('type'))
                    continue

                lang = tmdb_item.get('iso_639_1') or ''
                country = tmdb_item.get('iso_3166_1') or ''
                size = tmdb_item.get('size') or ''
                official = bool(tmdb_item.get('official'))
                title = tmdb_item.get('name') or ''

                meta_parts = []
                if lang or country:
                    meta_parts.append('/'.join([x for x in [lang, country] if x]))
                if size:
                    meta_parts.append(f'{size}p')
                if official:
                    meta_parts.append('official')

                if meta_parts:
                    title = f"[{' | '.join(meta_parts)}] {title}"

                extra = EntityExtra2()
                extra.content_type = video_type
                extra.mode = 'youtube'
                extra.content_url = key      # 중요: 기존처럼 URL이 아니라 key 그대로 유지
                extra.thumb = ''
                extra.title = title
                extra.premiered = ''
                entity.extras.append(extra)

        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info_actor(cls, tmdb, entity, primary=True, kor_trans=True):
        try:
            info = tmdb.credits(language='ko')
            trans = False
            if kor_trans and ((len(entity.country) > 0 and entity.country[0] in ['South Korea', u'한국', u'대한민국']) or ((entity.extra_info.get('original_language') or '') == 'ko')):
                trans = True
            #trans = True
            # 한국배우는 자동번역
            if primary:
                #logger.debug(len(info['cast']))
                for tmdb_item in info['cast'][:20]:
                    #name = tmdb_item['original_name']
                    name = tmdb_item['name']
                    #logger.debug(tmdb_item)

                    #try:
                    #    if SiteUtil.is_include_hangul(tmdb_item['original_name']) == False:
                    #        people_info = tmdbsimple.People(tmdb_item['id']).info()
                    #        for tmp in people_info['also_known_as']:
                    #            if SiteUtil.is_include_hangul(tmp):
                    #                name = tmp
                    #                break
                    #except: pass

                    actor = EntityActor('', site=cls.site_name)
                    actor.name = name
                    actor.tmdb_id = tmdb_item['id']
                    actor.originalname = tmdb_item.get('original_name') or ''
                    actor.role = tmdb_item['character']
                    try:
                        try:
                            if SiteUtil.is_include_hangul(name) == False:
                                actor.name = SiteUtil.trans(name, source='en', target='ko').replace(' ', '') if trans else name
                            if SiteUtil.is_include_hangul(tmdb_item['character']) == False:
                                actor.role = SiteUtil.trans(tmdb_item['character'], source='en', target='ko').replace(' ', '') if trans else tmdb_item['character']
                        except Exception:
                            pass
                    except Exception:
                        pass
                    if tmdb_item['profile_path'] is not None:
                        actor.thumb = cls.get_image_url(tmdb_item['profile_path'], 'profile')

                    entity.actor.append(actor)
                mappings = {
                    # EntityMovie2: director, producers, credits
                    'Director': ([], entity.director),
                    'Executive Producer': ([], entity.producers),
                    'Producer': ([], entity.producers),
                    'Writer': ([], entity.credits),
                    'Novel': ([], entity.credits),
                    'Book': ([], entity.credits),
                    'Screenplay': ([], entity.credits)
                }
                cls._set_crews(info, mappings, trans)
                _stash_tmdb_extra(entity, 'crews', [
                    {'id': c.get('id'), 'name': c.get('name'), 'original_name': c.get('original_name'),
                     'department': c.get('department'), 'job': c.get('job'),
                     'profile_path': c.get('profile_path'), 'credit_id': c.get('credit_id')}
                    for c in (info.get('crew') or [])
                    if c.get('job') in ('Director', 'Producer', 'Executive Producer', 'Writer', 'Screenplay', 'Novel', 'Book')
                ])
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())



    @classmethod
    def info_basic(cls, tmdb, entity):
        try:
            info = tmdb.info(language='ko')
            info_en = tmdb.info(language='en')



            if 'imdb_id' in info:
                entity.code_list.append(['imdb_id', info['imdb_id']])

            entity.title = info['title']
            entity.originaltitle = info['original_title']
            entity.plot = info['overview']

            if entity.plot == '':
                entity.plot = info_en['overview']

            for tmp in info['genres']:
                entity.genre.append(tmp['name'])

            if len(info['production_companies']) > 0:
                entity.studio = info['production_companies'][0]['name']

            _stash_tmdb_extra(entity, 'companies', [
                {'id': c.get('id'), 'name': c.get('name'), 'origin_country': c.get('origin_country'),
                 'logo_path': c.get('logo_path')}
                for c in (info.get('production_companies') or []) if c.get('name')
            ])
            _stash_tmdb_extra(entity, 'countries', [
                c.get('iso_3166_1')
                for c in ((info.get('production_countries') or info_en.get('production_countries')) or [])
                if c.get('iso_3166_1')
            ])

            #for tmp in info['production_countries']:
            #    entity.country.append(tmp['name'])
            if 'production_countries' in info and len(info['production_countries']) > 0:
                for tmp in info['production_countries']:
                    entity.country.append(SiteUtil.country_code_translate[tmp['iso_3166_1']])
            else:
                if 'production_countries' in info_en:
                    for tmp in info_en['production_countries']:
                        entity.country.append(SiteUtil.country_code_translate[tmp['iso_3166_1']])

            entity.premiered = info['release_date']
            try: entity.year = int(info['release_date'].split('-')[0])
            except Exception: entity.year = 1900

            entity.runtime = info['runtime']
            entity.tagline = info['tagline']

            entity.extra_info['homepage'] = info['homepage']
            entity.extra_info['imdb_id'] = info['imdb_id']
            entity.extra_info['original_language'] = info['original_language']

            entity.extra_info['spoken_languages'] = info['spoken_languages']
            entity.extra_info['status'] = info['status']

            try: entity.ratings.append(EntityRatings(info['vote_average'], name='tmdb', votes=info['vote_count']))
            except Exception: pass
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())




    @classmethod
    def process_actor_image(cls, tmdb, show):
        try:
            tmdb_actor = tmdb.credits(language='en')
            for tmdb_item in tmdb_actor['cast']:
                if tmdb_item['profile_path'] is None:
                    continue
                try:
                    kor_name = SiteUtil.trans(tmdb_item['name'], source='en', target='ko').replace(' ', '')
                except Exception:
                    kor_name = None
                #kor_name = MetadataServerUtil.trans_en_to_ko(tmdb_item['name'])
                flag_find = False

                #logger.debug(tmdb_item)
                for actor in show['actor']:
                    if actor['name'] == kor_name:
                        flag_find = True
                        actor['thumb'] = cls.get_image_url(tmdb_item['profile_path'], 'profile')
                        break
                if flag_find == False:
                    kor_role_name = MetadataServerUtil.trans_en_to_ko(tmdb_item['character'])
                    for actor in show['actor']:
                        if actor['role'] == kor_role_name:
                            flag_find = True
                            actor['thumb'] = cls.get_image_url(tmdb_item['profile_path'], 'profile')
                            break
                if flag_find == False:
                    logger.debug(kor_name)
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def info_releases(cls, tmdb, entity):
        try:
            info = tmdb.releases()
            _stash_tmdb_extra(entity, 'release_dates', [
                {'country': item.get('iso_3166_1'), 'certification': item.get('certification')}
                for item in (info.get('countries') or []) if item.get('certification')
            ])
            datas = []
            for item in info['countries']:
                if item['certification'] == '':
                    continue
                value = f"{item['iso_3166_1'].lower()}/{item['certification']}".replace(' ', '')
                if item['iso_3166_1'] == 'KR':
                    entity.mpaa = value
                    return
                if item['iso_3166_1'] == 'US':
                    datas.insert(0, value)
                else:
                    datas.append(value)
            if len(datas):
                entity.mpaa = datas[0]
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())



























































class SiteTmdbFtv(SiteTmdb):
    module_char = 'F'


    @classmethod
    def search_api(cls, keyword):
        try:
            tmdb_search = tmdbsimple.Search().tv(query=keyword, language='ko', include_adult=True)
            return tmdb_search
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
        return


    @classmethod
    def search(cls, keyword, year=None):
        try:
            logger.debug('TMDB TV [%s] [%s]', keyword, year)
            ret = {}
            data = cls.search_api(keyword)
            result_list = []
            if data is not None:
                for idx, item in enumerate(data['results']):
                    entity = EntitySearchItemFtv(cls.site_name)
                    entity.code = cls.module_char + cls.site_char + str(item['id'])
                    entity.title = item['name']
                    entity.title = re.sub(r'\(\d{4}\)$', '', entity.title).strip()
                    entity.title_original = item['original_name']
                    entity.image_url = cls.get_image_url(item['poster_path'])
                    if 'first_air_date' not in item:
                        continue
                    entity.premiered = item['first_air_date']
                    try: entity.year = int(entity.premiered.split('-')[0])
                    except Exception: entity.year = 1900
                    try: entity.desc = item['overview']
                    except Exception: pass
                    entity.link = f"https://www.themoviedb.org/tv/{item['id']}"

                    if SiteUtil.compare(keyword, entity.title) or SiteUtil.compare(keyword, entity.title_original):
                        if year is not None:
                            if entity.year - year == 0:
                                entity.score = 100
                            else:
                                entity.score = 80
                        else:
                            entity.score = 95
                    else:
                        entity.score = 80 - (idx*5)
                    #logger.debug(entity.score)
                    result_list.append(entity.as_dict())
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
    def info_api(cls, code):
        try:
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]
            tmdb = tmdbsimple.TV(code)
            ret = {}
            ret['info'] = tmdb.info(language='ko')
            ret['alternative_titles'] = tmdb.alternative_titles(language='ko')
            ret['content_ratings'] = tmdb.content_ratings(language='ko')
            ret['credits'] = tmdb.credits(language='ko')
            ret['image'] = tmdb.images()
            ret['video'] = cls.fetch_videos(tmdb)
            ret['external_ids'] = tmdb.external_ids()
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info(cls, code, use_trailer=False):
        try:
            ret = {}
            entity = EntityFtv(cls.site_name, code)
            tmdb = tmdbsimple.TV(code[2:])
            entity.code_list.append(['tmdb_id', code[2:]])
            cls.info_basic(tmdb, entity)
            cls.info_content_ratings(tmdb, entity)
            cls.info_credits(tmdb, entity)
            if use_trailer:
                cls.info_trailers(tmdb, entity)
            for season in entity.seasons:
                season_no = season.season_no
                season = tmdbsimple.TV_Seasons(code[2:], season_no)
                cls.info_credits(season, entity, crew=False)

            cls.info_external_ids(tmdb, entity)
            entity = entity.as_dict()
            cls._process_image(tmdb, entity['art'])
            entity['actor'] = list(sorted(entity['actor'], key=lambda k: k['order']))
            ret['ret'] = 'success'
            ret['data'] = entity #entity.as_dict() #tmdb_dict
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def info_external_ids(cls, tmdb, entity):
        try:
            info = tmdb.external_ids()
            if 'imdb_id' in info:
                entity.code_list.append(['imdb_id', info['imdb_id']])
            if 'tvdb_id' in info:
                entity.code_list.append(['tvdb_id', info['tvdb_id']])
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info_credits(cls, tmdb, entity, crew=True):
        try:
            info = tmdb.credits(language='ko')

            for tmdb_item in info['cast']:#[:20]:
                actor = EntityActor2(site=cls.site_name)
                actor.tmdb_id = tmdb_item['id']
                is_exist = False
                for tmp in entity.actor:
                    if tmp.tmdb_id == actor.tmdb_id:
                        is_exist = True
                if is_exist:
                    continue

                actor.tmdb_id = tmdb_item.get('id')
                actor.order = tmdb_item.get('order', 0)
                actor.tmdb_credit_id = tmdb_item.get('credit_id') or ''
                actor.name = tmdb_item.get('name') or ''
                actor.name_original = tmdb_item.get('original_name') or actor.name
                #if SiteUtil.is_include_hangul(actor.name_original):
                #    actor.name = actor.name_ko = actor.name_original
                #else:
                #    people_info = tmdbsimple.People(actor.tmdb_id).info()
                #    for tmp in people_info['also_known_as']:
                #        if SiteUtil.is_include_hangul(tmp):
                #            actor.name = actor.name_ko = tmp
                #            break
                actor.role = tmdb_item.get('character') or ''
                if profile_path := tmdb_item.get('profile_path'):
                    actor.image = cls.get_image_url(profile_path, 'profile')
                entity.actor.append(actor)

            if crew == False:
                return

            mappings = {
                # EntityFtv: director, producer, writer
                'Director': ([], entity.director),
                'Executive Producer': ([], entity.producer),
                'Producer': ([], entity.producer),
                'Writer': ([], entity.writer),
                'Novel': ([], entity.writer),
                'Book': ([], entity.writer),
                'Screenplay': ([], entity.writer)
            }
            cls._set_crews(info, mappings)
            _stash_tmdb_extra(entity, 'crews', [
                {'id': c.get('id'), 'name': c.get('name'), 'original_name': c.get('original_name'),
                 'department': c.get('department'), 'job': c.get('job'),
                 'profile_path': c.get('profile_path'), 'credit_id': c.get('credit_id')}
                for c in (info.get('crew') or [])
                if c.get('job') in ('Director', 'Producer', 'Executive Producer', 'Writer', 'Screenplay', 'Novel', 'Book')
            ])
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info_content_ratings(cls, tmdb, entity):
        try:
            info = tmdb.content_ratings(language='ko')
            _stash_tmdb_extra(entity, 'content_ratings', [
                {'country': item.get('iso_3166_1'), 'rating': item.get('rating')}
                for item in (info.get('results') or []) if item.get('rating')
            ])
            order = [u'한국', u'미국', u'영국', u'일본', u'중국']
            ret = ['', '', '', '', '']
            for item in info['results']:
                country = SiteUtil.country_code_translate[item['iso_3166_1']]
                for idx, value in enumerate(order):
                    if country == value:
                        ret[idx] = item['rating']
                        break
            for tmp in ret:
                if tmp != '':
                    entity.mpaa = tmp
                    return
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def info_basic(cls, tmdb, entity):
        try:
            info = tmdb.info(language='ko')
            info_en = tmdb.info(language='en')

            if backdrop_path := info.get('backdrop_path'):
                backdrop_url = cls.get_image_url(backdrop_path, 'backdrop')
                backdrop_thumb_url = cls.get_image_url(backdrop_path, 'backdrop', 'thumb')
                entity.art.append(EntityThumb(aspect='landscape', value=backdrop_url, thumb=backdrop_thumb_url, site=cls.site_name, score=200))
            if poster_path := info.get('poster_path'):
                poster_url = cls.get_image_url(poster_path, 'poster')
                poster_thumb_url = cls.get_image_url(poster_path, 'poster', 'thumb')
                entity.art.append(EntityThumb(aspect='poster', value=poster_url, thumb=poster_thumb_url, site=cls.site_name, score=200))


            if 'created_by' in info:
                for tmp in info['created_by']:
                    entity.producer.append(tmp['name'])

            if 'genres' in info:
                for genre in info['genres']:
                    if genre['name'] in SiteUtil.genre_map:
                        entity.genre.append(SiteUtil.genre_map[genre['name']])
                    else:
                        entity.genre.append(genre['name'])

            if 'first_air_date'  in info:
                entity.premiered = info['first_air_date']
                try: entity.year = int(info['first_air_date'].split('-')[0])
                except Exception: entity.year = 1900
            entity.title = info['name'] if 'name' in info else ''
            entity.originaltitle = info['original_name'] if 'original_name' in info else ''
            if 'overview' in info and info['overview'] != '':
                entity.plot = info['overview'] if 'overview' in info else ''
                entity.is_plot_kor = True
            else:
                entity.plot = info_en['overview']
                entity.is_plot_kor = False

            #if 'production_companies' in info:
            #    for tmp in info['production_companies']:
            #        entity.studio.append(tmp['name'])
            if 'networks' in info and len(info['networks']) > 0:
                entity.studio = info['networks'][0]['name']

            _stash_tmdb_extra(entity, 'type', info.get('type'))
            _stash_tmdb_extra(entity, 'companies', [
                {'id': c.get('id'), 'name': c.get('name'), 'origin_country': c.get('origin_country'),
                 'logo_path': c.get('logo_path')}
                for c in (info.get('production_companies') or []) if c.get('name')
            ])
            _stash_tmdb_extra(entity, 'countries', [
                c for c in ((info.get('origin_country') or info_en.get('origin_country')) or []) if c
            ])

            # 2021-05-21
            #if 'production_countries' in info:
            #    for tmp in info['production_countries']:
            #        entity.country.append(SiteUtil.country_code_translate[tmp['iso_3166_1']])
            if 'origin_country' in info and len(info['origin_country']) > 0:
                for tmp in info['origin_country']:
                    entity.country.append(SiteUtil.country_code_translate[tmp])
            else:
                if 'origin_country' in info_en:
                    for tmp in info_en['origin_country']:
                        entity.country.append(SiteUtil.country_code_translate[tmp])


            if 'seasons' in info:
                for tmp in info['seasons']:
                    if tmp['episode_count'] > 0 and tmp['season_number'] > 0:
                        entity.seasons.append(EntitySeason(
                            cls.site_name,
                            parent_code=cls.module_char + cls.site_char +str(info['id']),
                            #season_code=cls.module_char + cls.site_char +str(tmp['id']),
                            season_code=cls.module_char + cls.site_char + '_' + str(tmp['season_number']),
                            season_no=tmp['season_number'],
                            season_name=tmp['name'],
                            plot=tmp['overview'],
                            poster=cls.get_image_url(tmp['poster_path']),
                            epi_count=tmp['episode_count'],
                            premiered=tmp['air_date']))

            entity.status = info['status'] if 'status' in info else ''

            try: entity.ratings.append(EntityRatings(info['vote_average'], name=cls.site_name, votes=info['vote_count']))
            except Exception: pass
            entity.episode_run_time = info['episode_run_time'][0] if 'episode_run_time' in info and len(info['episode_run_time'])>0 else 0
            return
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info_season_api(cls, code):
        try:
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]
            tmp = code.split('_')
            if len(tmp) != 2:
                return
            tmdb_id = tmp[0]
            season_number = tmp[1]
            tmdb = tmdbsimple.TV_Seasons(tmdb_id, season_number)
            ret = {}
            ret['info'] = tmdb.info(language='ko')
            ret['credits'] = tmdb.credits(language='ko')
            ret['image'] = tmdb.images()
            ret['video'] = cls.fetch_videos(tmdb)
            ret['external_ids'] = tmdb.external_ids()
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info_season(cls, code):
        try:
            if code.startswith(cls.module_char + cls.site_char):
                code = code[2:]
            tmp = code.split('_')
            if len(tmp) != 2:
                return
            tmdb_id = tmp[0]
            season_number = int(tmp[1])
            """
            series_info = tmdbsimple.TV(tmdb_id).info(language='ko')
            series_title = series_info['name']
            series_season_count = 0
            for tmp in series_info['seasons']:
                if tmp['episode_count'] > 0 and tmp['season_number'] > 0:
                    series_season_count += 1
            try: series_year = int(series_info['first_air_date'].split('-')[0])
            except: series_year = 1900
            """
            ret = {}
            entity = EntitySeason(cls.site_name, parent_code=cls.module_char + cls.site_char +str(tmdb_id), season_code=cls.module_char + cls.site_char + code, season_no=season_number)
            tmdb = tmdbsimple.TV_Seasons(tmdb_id, season_number)

            cls.info_season_basic(tmdb, entity)
            #cls.info_content_ratings(tmdb, entity)
            #cls.info_credits(tmdb, entity)
            #cls.info_external_ids(tmdb, entity)
            entity = entity.as_dict()
            cls._process_image(tmdb, entity['art'])
            ret['ret'] = 'success'
            ret['data'] = entity #entity.as_dict() #tmdb_dict
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def info_season_basic(cls, tmdb, entity):
        try:
            info = tmdb.info(language='ko')
            info_us = tmdb.info(language='en')
            entity.season_name = info['name'] if 'name' in info else ''
            if entity.season_name.find(u'시즌') == -1:
                entity.season_name = u'시즌 %s. %s' % (entity.season_no, entity.season_name)

            entity.plot = info['overview'] if 'overview' in info else ''
            entity.premiered = info['first_air_date'] if 'first_air_date'  in info else ''

            if 'episodes' in info:
                for idx, tmp in enumerate(info['episodes']):
                    episode_arts = [cls.get_image_url(tmp['still_path'], 'still')] if tmp.get('still_path') else []
                    episode = EntityEpisode2(
                        cls.site_name, entity.season_no, tmp['episode_number'],
                        title=tmp['name'],
                        plot=tmp['overview'],
                        premiered=tmp['air_date'],
                        art=episode_arts)
                    if episode.title.find(u'에피소드') == -1 and SiteUtil.is_include_hangul(episode.title):
                        episode.is_title_kor = True
                    else:
                        episode.is_title_kor = False
                        episode.title = info_us['episodes'][idx]['name']

                    if episode.plot != '' and SiteUtil.is_include_hangul(episode.plot):
                        episode.is_plot_kor = True
                    else:
                        episode.is_plot_kor = False
                        episode.plot = info_us['episodes'][idx]['overview']

                    if 'guest_stars' in tmp:
                        for t in tmp['guest_stars']:
                            if 'original_name' in t:
                                episode.guest.append(t['original_name'])
                    if 'crew' in tmp:
                         for t in tmp['crew']:
                            if t['job'] == 'Director':
                                episode.director.append(t['original_name'])
                            if t['job'] == 'Executive Producer':
                                episode.producer.append(t['original_name'])
                            if t['job'] == 'Producer':
                                episode.producer.append(t['original_name'])
                            if t['job'] in ['Writer', 'Novel', 'Screenplay']:
                                episode.writer.append(t['original_name'])


                    #entity.episodes.append(episode)
                    entity.episodes[tmp['episode_number']] = episode.as_dict()
            return
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
