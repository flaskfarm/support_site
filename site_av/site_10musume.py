import re
import traceback
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie,
                           EntityRatings, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.10musume.com'

class Site10Musume(SiteAvBase):
    site_name = '10musume'
    site_char = 'M'    
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

            # json에 url이 잘못된 경우
            try:
                if '10musume.com' not in json_data['MovieThumb']:
                    moviethumb = json_data['MovieThumb'].replace('/moviepages', 'www.10musume.com/moviepages')
                else:
                    moviethumb = json_data['MovieThumb']
            except:
                moviethumb = ''

            item.image_url = moviethumb
            if manual == True:
                try:
                    if cls.config['use_proxy']:
                        item.image_url = cls.make_image_url(item.image_url)
                except Exception as e_img: 
                    logger.error(f"DMM Search: ImgProcErr (manual):{e_img}")
            
            if do_trans:
                item.title_ko = cls.trans(item.title)
            
            item.ui_code = f'10mu-{code}'
            
            if '10mu' in keyword.lower():
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
            # json에 url이 잘못된 경우
            
            try:
                if '10musume.com' not in json_data['MovieThumb']:
                    moviethumb = json_data['MovieThumb'].replace('/moviepages', 'www.10musume.com/moviepages')
                else:
                    moviethumb = json_data['MovieThumb']

                if '10musume.com' not in json_data['ThumbUltra']:
                    thumbultra = json_data['ThumbUltra'].replace('/moviepages', 'www.10musume.com/moviepages')
                else:
                    thumbultra = json_data['ThumbUltra']
            except:
                moviethumb = thumbultra = ''

            entity.thumb = []
            final_image_sources = {
                'poster_source': None,
                'poster_mode': None,
                'landscape_source': None,
                'arts': [],
            }

            final_image_sources['poster_source'] = moviethumb
            final_image_sources['landscape_source'] = thumbultra

            # tagline
            entity.tagline = cls.trans(json_data['Title'])

            # date, year
            entity.premiered = json_data['Release']
            entity.year = json_data['Year']

            # actor
            entity.actor = []
            for actor in json_data['ActressesJa']:
                entity.actor.append(EntityActor(actor))

            # director
            # entity.director = []

            # tag
            entity.tag = []
            entity.tag.append('10Musume')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = json_data['UCNAME']
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(cls.get_translated_tag('uncen_tags', item)) # 미리 번역된 태그를 포함
                    # entity.genre.append(SiteUtil.trans(item.strip(), do_trans=do_trans).strip())
            
            # title
            entity.title = entity.originaltitle = entity.sorttitle = f'10mu-{code[2:]}'

            # entity.ratings
            try: entity.ratings.append(EntityRatings(float(json_data['AvgRating']), name=cls.site_name))
            except: pass

            # plot
            entity.plot = cls.trans(json_data['Desc'])
            
            # 팬아트
            # entity.fanart = []

            # 제작사
            entity.studio = '10Musume'

            # 부가영상 or 예고편
            entity.extras = []
            if cls.config['use_extras']:
                try:
                    entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', cls.make_video_url(json_data['SampleFiles'][-1]['URL']), thumb=cls.make_image_url(thumbultra)))
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
