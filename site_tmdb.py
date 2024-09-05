from support_site import MetadataServerUtil

from .entity_base import (EntityActor, EntityActor2, EntityEpisode2,
                          EntityExtra2, EntityFtv, EntityMovie2, EntityRatings,
                          EntitySearchItemFtv, EntitySearchItemMovie,
                          EntitySeason, EntityThumb)
from .setup import *
from .site_util import SiteUtil

try:
    import tmdbsimple
except:
    os.system("pip install tmdbsimple")
    import tmdbsimple
tmdbsimple.API_KEY = 'f090bb54758cabf231fb605d3e3e0468'

ARTWORK_ITEM_LIMIT = 10
POSTER_SCORE_RATIO = .3 # How much weight to give ratings vs. vote counts when picking best posters. 0 means use only ratings.
BACKDROP_SCORE_RATIO = .3


class SiteTmdb(object):
    site_name = 'tmdb'
    site_char = 'T'

    @classmethod
    def get_poster_path(cls, path):
        if path is None:
            return ''
        return 'https://image.tmdb.org/t/p/'+ 'original' + path

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
                        poster_url = 'https://image.tmdb.org/t/p/'+ 'original' + poster['file_path']
                        thumb_url = 'https://image.tmdb.org/t/p/' + 'w154' + poster['file_path']
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
                        backdrop_url = 'https://image.tmdb.org/t/p/' + 'original' + backdrop['file_path']
                        thumb_url = 'https://image.tmdb.org/t/p/' + 'w300' + backdrop['file_path']
                        data.append(EntityThumb(aspect='landscape', value=backdrop_url, thumb=thumb_url, site='tmdb', score=backdrop['score']+100).as_dict())
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

















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
                except:
                    kor_name = None
                flag_find = False
                for actor in show['actor']:
                    if actor['name'] == kor_name:
                        flag_find = True
                        actor['thumb'] = 'https://image.tmdb.org/t/p/' + 'original' + tmdb_item['profile_path']
                        break
                if flag_find == False:
                    try:
                        kor_role_name = SiteUtil.trans(tmdb_item['character'], source='en', target='ko')
                    except:
                        kor_role_name = None
                    for actor in show['actor']:
                        if actor['role'] == kor_role_name:
                            flag_find = True
                            actor['thumb'] = 'https://image.tmdb.org/t/p/' + 'original' + tmdb_item['profile_path']
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
            #ret['video'] = tmdb.videos()
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
                entity.image_url = cls.get_poster_path(item['poster_path'])
                try: entity.year = int(item['release_date'].split('-')[0])
                except: entity.year = 1900
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
    def info(cls, code):
        try:
            ret = {}
            entity = EntityMovie2(cls.site_name, code)
            tmdb = tmdbsimple.Movies(code[2:])
            entity.code_list.append(['tmdb_id', code[2:]])
            cls.info_basic(tmdb, entity)
            cls.info_actor(tmdb, entity)
            #cls.info_videos(tmdb, entity)
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
            info = tmdb.videos()
            for tmdb_item in info['results']:
                if tmdb_item['site'] == 'YouTube':
                    extra = EntityExtra2()
                    if tmdb_item['type'] == 'Teaser':
                        tmdb_item['type'] = 'Trailer'
                    elif tmdb_item['type'] == 'Clip':
                        tmdb_item['type'] = 'Short'
                    elif tmdb_item['type'] == 'Behind the Scenes':
                        tmdb_item['type'] = 'BehindTheScenes'

                    if tmdb_item['type'] not in ['Trailer', 'Featurette', 'Short', 'BehindTheScenes']:
                        logger.debug(u'소스 확인 zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz')
                        logger.debug(tmdb_item['type'])
                        continue

                    extra.content_type = tmdb_item['type']
                    extra.mode = 'youtube'
                    extra.content_url = tmdb_item['key']
                    extra.thumb = ''
                    extra.title = tmdb_item['name']
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
            if kor_trans and ((len(entity.country) > 0 and entity.country[0] in ['South Korea', u'한국', u'대한민국']) or (entity.extra_info['original_language'] == 'ko')):
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
                    actor.role = tmdb_item['character']
                    try:
                        try:
                            if SiteUtil.is_include_hangul(name) == False:
                                actor.name = SiteUtil.trans(name, source='en', target='ko').replace(' ', '') if trans else name
                            if SiteUtil.is_include_hangul(tmdb_item['character']) == False:
                                actor.role = SiteUtil.trans(tmdb_item['character'], source='en', target='ko').replace(' ', '') if trans else tmdb_item['character']
                        except:
                            pass
                    except:
                        pass
                    if tmdb_item['profile_path'] is not None:
                        actor.thumb = 'https://image.tmdb.org/t/p/' + 'original' + tmdb_item['profile_path']

                    entity.actor.append(actor)
                for tmdb_item in info['crew'][:20]:
                    target_list = None
                    if tmdb_item['job'] == 'Director': target_list = entity.director
                    elif tmdb_item['job'] == 'Executive Producer': target_list = entity.producers
                    elif tmdb_item['job'] == 'Producer': target_list = entity.producers
                    elif tmdb_item['job'] in ['Writer', 'Novel', 'Screenplay']: target_list = entity.credits
                    if target_list != None:
                        try:
                            _ = tmdb_item['name']
                            if SiteUtil.is_include_hangul(_) == False:
                                _ = SiteUtil.trans(_, source='en', target='ko').replace(' ', '') if trans else tmdb_item['name']
                            target_list.append(_)
                        except:
                            target_list.append(tmdb_item['name'])
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
            except: entity.year = 1900

            entity.runtime = info['runtime']
            entity.tagline = info['tagline']

            entity.extra_info['homepage'] = info['homepage']
            entity.extra_info['imdb_id'] = info['imdb_id']
            entity.extra_info['original_language'] = info['original_language']

            entity.extra_info['spoken_languages'] = info['spoken_languages']
            entity.extra_info['status'] = info['status']

            try: entity.ratings.append(EntityRatings(info['vote_average'], name='tmdb', votes=info['vote_count']))
            except: pass
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
                except:
                    kor_name = None
                #kor_name = MetadataServerUtil.trans_en_to_ko(tmdb_item['name'])
                flag_find = False

                #logger.debug(tmdb_item)
                for actor in show['actor']:
                    if actor['name'] == kor_name:
                        flag_find = True
                        actor['thumb'] = 'https://image.tmdb.org/t/p/' + 'original' + tmdb_item['profile_path']
                        break
                if flag_find == False:
                    kor_role_name = MetadataServerUtil.trans_en_to_ko(tmdb_item['character'])
                    for actor in show['actor']:
                        if actor['role'] == kor_role_name:
                            flag_find = True
                            actor['thumb'] = 'https://image.tmdb.org/t/p/' + 'original' + tmdb_item['profile_path']
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
            datas = []
            for item in info['countries']:
                if item['certification'] == '':
                    continue
                value = f"{item['iso_3166_1'].lower()}/{item['certification']}"
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
                    entity.image_url = cls.get_poster_path(item['poster_path'])
                    if 'first_air_date' not in item:
                        continue
                    entity.premiered = item['first_air_date']
                    try: entity.year = int(entity.premiered.split('-')[0])
                    except: entity.year = 1900
                    try: entity.desc = item['overview']
                    except: pass
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
            ret['video'] = tmdb.videos()
            ret['external_ids'] = tmdb.external_ids()
            return ret
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info(cls, code):
        try:
            ret = {}
            entity = EntityFtv(cls.site_name, code)
            tmdb = tmdbsimple.TV(code[2:])
            entity.code_list.append(['tmdb_id', code[2:]])
            cls.info_basic(tmdb, entity)
            cls.info_content_ratings(tmdb, entity)
            cls.info_credits(tmdb, entity)

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

                actor.order = tmdb_item['order']
                actor.name_original = tmdb_item['name']
                actor.name = tmdb_item['name']
                #if SiteUtil.is_include_hangul(actor.name_original):
                #    actor.name = actor.name_ko = actor.name_original
                #else:
                #    people_info = tmdbsimple.People(actor.tmdb_id).info()
                #    for tmp in people_info['also_known_as']:
                #        if SiteUtil.is_include_hangul(tmp):
                #            actor.name = actor.name_ko = tmp
                #            break
                actor.role = tmdb_item['character']
                if 'profile_path' in tmdb_item and tmdb_item['profile_path'] is not None:
                    actor.image = cls.get_poster_path(tmdb_item['profile_path'])
                entity.actor.append(actor)

            if crew == False:
                return

            for tmdb_item in info['crew'][:20]:
                if tmdb_item['job'] == 'Director':
                    entity.director.append(tmdb_item['name'])
                if tmdb_item['job'] == 'Executive Producer':
                    entity.producer.append(tmdb_item['name'])
                if tmdb_item['job'] == 'Producer':
                    entity.producer.append(tmdb_item['name'])
                if tmdb_item['job'] in ['Writer', 'Novel', 'Screenplay']:
                    entity.writer.append(tmdb_item['name'])
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())


    @classmethod
    def info_content_ratings(cls, tmdb, entity):
        try:
            info = tmdb.content_ratings(language='ko')
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

            if 'backdrop_path' in info:
                entity.art.append(EntityThumb(aspect='landscape', value=cls.get_poster_path(info['backdrop_path']), site=cls.site_name, score=200))
            if 'poster_path' in info:
                entity.art.append(EntityThumb(aspect='poster', value=cls.get_poster_path(info['poster_path']), site=cls.site_name, score=200))


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
                except: entity.year = 1900
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
                            poster=cls.get_poster_path(tmp['poster_path']),
                            epi_count=tmp['episode_count'],
                            premiered=tmp['air_date']))

            entity.status = info['status'] if 'status' in info else ''

            try: entity.ratings.append(EntityRatings(info['vote_average'], name=cls.site_name, votes=info['vote_count']))
            except: pass
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
            ret['video'] = tmdb.videos()
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
                    episode = EntityEpisode2(
                        cls.site_name, entity.season_no, tmp['episode_number'],
                        title=tmp['name'],
                        plot=tmp['overview'],
                        premiered=tmp['air_date'],
                        art=[cls.get_poster_path(tmp['still_path'])] if 'still_path' in tmp and tmp['still_path'] is not None else [])
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
