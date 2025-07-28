import re
import traceback
from lxml import html
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://caribbeancom.com'

class SiteCarib(SiteAvBase):
    site_name = 'carib'
    site_char = 'C'    
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    @classmethod
    def search(cls, keyword, do_trans=True, manual=False):
        try:
            ret = {}
            if re.search('(\\d{6}-\\d{3})', keyword, re.I) is not None:
                code = re.search('(\\d{6}-\\d{3})', keyword, re.I).group()
            else:
                ret['ret'] = 'failed'
                ret['data'] = 'invalid keyword'
                return ret

            url = f'{SITE_BASE_URL}/moviepages/{code}/index.html'
            logger.debug(f"Searching URL: {url}")
            res = cls.get_response(url)
            if res.status_code == 404:
                # logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret

            tree = html.fromstring(res.text)
            
            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.title = item.title_ko = tree.xpath('//div[@id="moviepages"]//h1[@itemprop="name"]/text()')[0].strip()
            item.year = "20" + code[4:6]

            item.image_url = f'https://www.caribbeancom.com/moviepages/{code}/images/l_l.jpg'
            if manual == True:
                try:
                    if cls.config['use_proxy']:
                        item.image_url = cls.make_image_url(item.image_url)
                except Exception as e_img: 
                    logger.error(f"DMM Search: ImgProcErr (manual):{e_img}")
            if do_trans:
                item.title_ko = cls.trans(item.title)
            
            item.ui_code = f'carib-{code}'

            if 'carib' in keyword.lower():
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
            url = f'{SITE_BASE_URL}/moviepages/{code[2:]}/index.html'
            tree = cls.get_tree(url)
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'
            
            # 썸네일
            final_image_sources = {
                'poster_source': None,
                'poster_mode': None,
                'landscape_source': None,
                'arts': [],
            }

            entity.thumb = []
            if cls.get_response(f'https://www.caribbeancom.com/moviepages/{code[2:]}/images/jacket.jpg').status_code == 404:
                final_image_sources['poster_source'] =f'https://www.caribbeancom.com/moviepages/{code[2:]}/images/l_l.jpg'
            else:
                final_image_sources['poster_source'] =f'https://www.caribbeancom.com/moviepages/{code[2:]}/images/jacket.jpg'
            
            final_image_sources['landscape_source'] = f'https://www.caribbeancom.com/moviepages/{code[2:]}/images/l_l.jpg'

            # tagline
            entity.tagline = cls.trans(tree.xpath('//div[@id="moviepages"]//h1[@itemprop="name"]/text()')[0].strip())

            # date, year
            
            entity.year = "20" + code[6:8]
            entity.premiered = f"{entity.year}-{code[2:4]}-{code[4:6]}"

            # actor
            entity.actor = []
            for actor in tree.xpath('//div[@class="movie-info section"]//li[@class="movie-spec"]//span[@itemprop="name"]/text()'):
                entity.actor.append(EntityActor(actor))

            # director
            # entity.director = []

            # tag
            entity.tag = []
            entity.tag.append('carib')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = tree.xpath('//li[@class="movie-spec"]//span[@class="spec-content"]/a[@class="spec-item"]/text()')
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(cls.get_translated_tag('uncen_tags', item)) # 미리 번역된 태그를 포함
                    # entity.genre.append(SiteUtil.trans(item.strip(), do_trans=do_trans).strip())
            
            # title
            entity.title = entity.originaltitle = entity.sorttitle = f'carib-{code[2:]}'

            # entity.ratings
            # try: entity.ratings.append()
            # except: pass

            # plot
            entity.plot = cls.trans(tree.xpath('//p[@itemprop="description"]/text()')[0])

            # 팬아트
            # entity.fanart = []

            # 제작사
            entity.studio = 'Caribbeancom'

            # 부가영상 or 예고편
            entity.extras = []
            if cls.config['use_extras']:
                url = cls.make_video_url(f'https://smovie.caribbeancom.com/sample/movies/{code[2:]}/480p.mp4')
                img = cls.make_image_url(f'https://www.caribbeancom.com/moviepages/{code[2:]}/images/l_l.jpg')
                entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', url, thumb=img))
            cls.finalize_images_for_entity(entity, final_image_sources)
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)

        return ret
