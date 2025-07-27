import re
import traceback
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityRatings)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.1pondo.tv'

class Site1PondoTv(SiteAvBase):
    site_name = '1pondo'
    site_char = 'D'
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    @classmethod
    def search(cls, keyword, do_trans=True, manual=False):
        try:
            ret = {}
            if re.search('(\\d{6}[_-]\\d+)', keyword, re.I) is not None:
                code = re.search('(\\d{6}[_-]\\d+)', keyword, re.I).group().replace('-', '_')
            else:
                # logger.debug(f'invalid keyword: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'invalid keyword'
                return ret

            url = f'{SITE_BASE_URL}/dyn/phpauto/movie_details/movie_id/{code}.json'
            
            try:
                response = cls.get_response(url)
                json_data = response.json()
            except:
                # logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = response.status_code
                return ret
            
            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.title = item.title_ko = json_data['Title']
            item.year = json_data['Year']

            item.image_url = json_data['MovieThumb']
            if manual == True:
                try:
                    if cls.config['use_proxy']:
                        item.image_url = cls.make_image_url(item.image_url)
                except Exception as e_img: 
                    logger.error(f"DMM Search: ImgProcErr (manual):{e_img}")
            
            if do_trans:
                item.title_ko = cls.trans(item.title)
            
            item.ui_code = f'1pon-{code}'
            
            if '1pon' in keyword.lower():
                item.score = 100
            else:
                item.score = 90

            logger.debug('score :%s %s ', item.score, item.ui_code)
            ret['data'].append(item.as_dict())

            ret['data'] = sorted(ret['data'], key=lambda k: k['score'], reverse=True)  
            ret['ret'] = 'success'

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
            url = f'{SITE_BASE_URL}/dyn/phpauto/movie_details/movie_id/{code[2:]}.json'
            json_data = cls.get_response(url).json()

            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            final_image_sources = {
                'poster_source': json_data['MovieThumb'],
                'poster_mode': None,
                'landscape_source': json_data['ThumbUltra'],
                'arts': [],
            }
            cls.finalize_images_for_entity(entity, final_image_sources)

            # tagline
            entity.tagline = cls.trans(json_data['Title'])

            # date, year
            entity.premiered = json_data['Release']
            entity.year = json_data['Year']
            if entity.year == None:
                entity.year = code[6:7] + code[2:3]

            # actor
            entity.actor = []
            for actor in json_data['ActressesJa']:
                entity.actor.append(EntityActor(actor))
            # director
            # entity.director = []

            # tag
            entity.tag = []
            entity.tag.append('1Pondo')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = json_data['UCNAME']
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(cls.get_translated_tag('uncen_tags', item)) # 미리 번역된 태그를 포함
            
            # title
            entity.title = entity.originaltitle = entity.sorttitle = f'1pon-{code[2:]}'

            # entity.ratings
            entity.ratings = []
            try: entity.ratings.append(EntityRatings(float(json_data['AvgRating']), name=cls.site_name))
            except: pass

            # plot
            entity.plot = cls.trans(json_data['Desc'])
            
            # 팬아트
            # entity.fanart = []

            # 제작사
            entity.studio = '1Pondo'

            # 부가영상 or 예고편
            entity.extras = []
            try:
                if cls.config['use_extras']:
                    url = cls.make_image_url(json_data['MovieThumb'])
                    video = cls.make_video_url(json_data['SampleFiles'][-1]['URL'])
                    entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', video, thumb=url))
            except: pass
            cls.finalize_images_for_entity(entity, final_image_sources)
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)

        return ret
