from . import SiteUtil
from .entity_base import (EntityActor2, EntityEpisode2, EntityFtv,
                          EntityRatings, EntitySearchItemFtv, EntitySeason,
                          EntityThumb)
from .setup import *

try:
    import tvdb_api
except:
    try:
        #os.system("{} install requests_cache==0.5.2".format(app.config['config']['pip']))
        os.system("pip install requests_cache==0.5.2")
        os.system("pip install tvdb-api")
        import tvdb_api
    except Exception as e: 
        logger.error(f"Exception:{str(e)}")
        logger.error(traceback.format_exc())

APIKEY = 'D4DDDAEFAD083E6F'

genre_map = {
    'Action' : '액션',
    'Adventure' : '어드벤처',
    'Drama' : '드라마',
    'Mystery' : '미스터리',
    'Mini-Series' : '미니시리즈',
    'Science-Fiction' : 'SF',
    'Thriller' : '스릴러',
    'Crime' : '범죄',
    'Documentary' : '다큐멘터리',
    'Sci-Fi & Fantasy' : 'SF & 판타지',
    'Animation' : '애니메이션',
    'Comedy' : '코미디',
    'Romance' : '로맨스',
    'Fantasy' : '판타지',
    'Sport' : '스포츠',
    'Soap' : '연속극',
    'Suspense' : '서스펜스',
    'Action & Adventure' : '액션 & 어드벤처',
    'History' : '역사',
    'Science Fiction' : 'SF',
}


class SiteTvdb(object):
    site_base_url = 'https://thetvdb.com'
    site_name = 'tvdb'
    site_char = 'U'


class SiteTvdbTv(SiteTvdb):
    module_char = 'F'
    
    @classmethod 
    def search_api(cls, keyword):
        try:
            tvdb = tvdb_api.Tvdb(apikey=APIKEY)#, language='ko') 
            return tvdb.search(keyword)
        except:
            return

    @classmethod 
    def search(cls, keyword, year=None):
        try:
            logger.debug('TVDB TV [%s] [%s]', keyword, year)
            ret = {}
            data = cls.search_api(keyword)
            result_list = []
            if data is not None:
                for idx, item in enumerate(data[:10]):
                    entity = EntitySearchItemFtv(cls.site_name)
                    entity.code = cls.module_char + cls.site_char + str(item['id'])
                    entity.studio = item['network']
                    entity.image_url = cls.site_base_url + item['image']
                    entity.status = item['status']
                    entity.premiered = item['firstAired']
                    try: entity.year = int(entity.premiered.split('-')[0])
                    except: pass
                    entity.title = item['seriesName']
                    entity.title = re.sub(r'\(\d{4}\)$', '', entity.title).strip()
                    try: entity.desc = item['overview']
                    except: pass
                    if (SiteUtil.is_hangul(keyword) and SiteUtil.is_hangul(entity.title) and SiteUtil.compare(keyword, entity.title)) or (SiteUtil.is_hangul(keyword) == False and SiteUtil.is_hangul(entity.title) == False and SiteUtil.compare(keyword, entity.title)):
                        if year is not None:
                            if entity.year - year == 0:
                                entity.score = 100
                            else:
                                entity.score = 80
                        else:
                            entity.score = 95
                    elif SiteUtil.is_hangul(keyword) and SiteUtil.is_hangul(entity.title) == False: #한글로 검색했는데 한글이 아니면.. 아예 잘못
                        entity.socre = 60
                    elif SiteUtil.is_hangul(keyword) == False and SiteUtil.is_hangul(entity.title): #영어로 검색했는데 한글이면..
                        entity.score = 99
                    else:
                        entity.score = 80 - (idx*5)
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
    def info(cls, code):
        try:
            #logger.debug('TVDB TV [%s]', code)
            #ret = {}
            try:
                tvdb = tvdb_api.Tvdb(apikey=APIKEY, select_first=True, banners=True, actors=True, language='en') 
                series = tvdb[code[2:]]
            except Exception as e: 
                logger.error(f"Exception:{str(e)}")
                logger.error(traceback.format_exc())
                tvdb = tvdb_api.Tvdb(apikey=APIKEY, select_first=True, banners=True, language='en') 
                series = tvdb[code[2:]]
            entity = EntityFtv(cls.site_name, code)
            entity.title = entity.originaltitle = series['seriesName']
            entity.mpaa = series['rating']
            entity.plot = series['overview']
            entity.premiered = series['firstAired']
            try: entity.year = int(series['firstAired'].split('-')[0])
            except: entity.year = ''
            entity.studio = series['network']
            logger.debug(series['fanart'])
            logger.debug(series['poster'])
            logger.debug(series['banner'])
            if series['fanart'] != 'http://thetvdb.com/banners/':
                entity.art.append(EntityThumb(aspect='landscape', value=series['fanart'], site=cls.site_name, score=80))
            if series['poster'] != 'http://thetvdb.com/banners/':
                entity.art.append(EntityThumb(aspect='poster', value=series['poster'], site=cls.site_name, score=80))
            if series['banner'] != 'http://thetvdb.com/banners/':
                entity.art.append(EntityThumb(aspect='banner', value=series['banner'], site=cls.site_name, score=80))
            entity.season_count = int(series['season'])
            for i in range(1, entity.season_count+1):
                entity.seasons[i] = EntitySeason(code, i)
            entity.extra_info['imdbId'] = series['imdbId']
            entity.status = series['status']
            for item in series['genre']:
                entity.genre.append(genre_map[item] if item in genre_map else item)
            try: entity.ratings.append(EntityRatings(float(series['siteRating']), name=cls.site_name))
            except: pass
            try:
                for item in series['_actors']:
                    entity.actor.append(EntityActor2(name=item['name'], role=item['role'], image=item['image']))
            except:
                logger.debug('actor...not load')
            if 'fanart' in series['_banners']:        
                for item in series['_banners']['fanart']['raw'][:10]:
                    entity.art.append(EntityThumb(aspect='landscape', value='http://thetvdb.com/banners/' + item['fileName'], site=cls.site_name, score=70))
            if 'poster' in series['_banners']:
                for item in series['_banners']['poster']['raw']:
                    entity.art.append(EntityThumb(aspect='poster', value='http://thetvdb.com/banners/' + item['fileName'], site=cls.site_name, score=70))
            if 'series' in series['_banners']:
                for item in series['_banners']['series']['raw']:
                    entity.art.append(EntityThumb(aspect='banner', value='http://thetvdb.com/banners/' + item['fileName'], site=cls.site_name, score=70))
            if 'season' in series['_banners']:
                for item in series['_banners']['season']['raw']:
                    if item['subKey'] == '0':
                        continue
                    entity.seasons[int(item['subKey'])].art.append(EntityThumb(aspect='poster', value='http://thetvdb.com/banners/' + item['fileName'], site=cls.site_name, score=70))
            if 'seasonwide' in series['_banners']:
                for item in series['_banners']['seasonwide']['raw']:
                    if item['subKey'] == '0':
                        continue
                    entity.seasons[int(item['subKey'])].art.append(EntityThumb(aspect='banner', value='http://thetvdb.com/banners/' + item['fileName'], site=cls.site_name, score=70))
            for season_no in range(1, entity.season_count+1):
                episode_count = len(series[season_no].keys())
                for epi_no in range(1, episode_count+1):
                    episode_info = series[season_no][epi_no]
                    episode = EntityEpisode2(season_no, epi_no)
                    episode.title = episode_info['episodeName']
                    episode.plot = episode_info['overview']
                    episode.guests = episode_info['guestStars']
                    episode.premiered = episode_info['firstAired']
                    episode.rating = episode_info['siteRating']
                    episode.directors = episode_info['directors']
                    episode.writers = episode_info['writers']
                    episode.art.append(episode_info['filename'])
                    entity.seasons[season_no].episodes[epi_no] = episode
            return entity.as_dict()
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
