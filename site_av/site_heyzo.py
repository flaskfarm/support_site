import json
import re
import traceback
import unicodedata
from dateutil.parser import parse
from lxml import html
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.heyzo.com'

class SiteHeyzo(SiteAvBase):
    site_name = 'heyzo'
    site_char = 'H'
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    @classmethod
    def search(cls, keyword, do_trans=True, manual=False):
        try:
            ret = {}
            if re.search('(\\d{4})', keyword, re.I) is not None and 'heyzo' in keyword.lower():
                code = re.search('(\\d{4})', keyword, re.I).group()
            else:
                # logger.debug(f'invalid keyword: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'invalid keyword'
                return ret

            url = f'{SITE_BASE_URL}/moviepages/{code}/index.html'
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

            # json이 있는 경우, 없는 경우
            tmp = {}
            try:
                json_data = json.loads(re.sub('(\"\")\w.', '\"', tree.xpath('//*[@id="movie"]/script[@type="application/ld+json"]/text()')[0]), strict=False)
                tmp['title'] = unicodedata.normalize('NFKC', json_data['name'])
                tmp['year'] = parse(json_data['dateCreated']).date().year
                tmp['image_url'] = f'https:{json_data["image"]}'
            except:
                m_tree = cls.get_tree(url.replace('www.', 'm.'))
                tmp['title'] = m_tree.xpath('//div[@id="container"]/h1/text()')[0].strip()
                tmp['year'] = parse(m_tree.xpath('//*[@id="moviedetail"]/div[2]/span/text()')[1].strip()).date().year
                tmp['image_url'] = f'https://m.heyzo.com/contents/3000/{code}/images/player_thumbnail.jpg'


            item.title = item.title_ko = tmp['title']
            item.year = tmp['year']

            item.image_url = tmp['image_url']
            if manual == True:
                try:
                    if cls.config['use_proxy']:
                        item.image_url = cls.make_image_url(item.image_url)
                except Exception as e_img: 
                    logger.error(f"DMM Search: ImgProcErr (manual):{e_img}")

            if do_trans:
                item.title_ko = cls.trans(item.title)
            
            item.ui_code = f'HEYZO-{code}'
            
            if 'heyzo' in keyword.lower():
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

            # json이 있는 경우, 없는 경우
            tmp = {}
            try:
                json_data = json.loads(re.sub('(\"\")\w.', '\"', tree.xpath('//*[@id="movie"]/script[@type="application/ld+json"]/text()')[0]), strict=False)
                tmp['data_poster'] = f'https:{json_data["actor"]["image"]}'
                tmp['data_landscape'] = f'https:{json_data["image"]}'
                tmp['tagline'] = unicodedata.normalize('NFKC', json_data['name'])
                tmp['premiered'] = str(parse(json_data['dateCreated']).date())
                tmp['year'] = parse(json_data['dateCreated']).date().year
                tmp['actorlist'] = tree.xpath('//div[@id="movie"]//table[@class="movieInfo"]//tr[@class="table-actor"]//span/text()')
                tmp['genrelist'] = tree.xpath('//tr[@class="table-tag-keyword-small"]//ul[@class="tag-keyword-list"]//li/a/text()')
                if json_data['description'] != '':
                    tmp['plot'] = unicodedata.normalize('NFKC', json_data['description']).strip()
                else:
                    tmp['plot'] = tmp['tagline']

            except:
                m_tree = cls.get_tree(url.replace('www.', 'm.'))
                tmp['data_poster'] = f'https://m.heyzo.com/contents/3000/{code[2:]}/images/thumbnail.jpg'
                tmp['data_landscape'] = f'https://m.heyzo.com/contents/3000/{code[2:]}/images/player_thumbnail.jpg'
                tmp['tagline'] = m_tree.xpath('//div[@id="container"]/h1/text()')[0].strip()
                tmp['premiered'] = str(parse(m_tree.xpath('//*[@id="moviedetail"]/div[2]/span/text()')[1].strip()).date())
                tmp['year'] = parse(m_tree.xpath('//*[@id="moviedetail"]/div[2]/span/text()')[1].strip()).date().year
                tmp['actorlist'] = m_tree.xpath('//*[@id="moviedetail"]/div[1]/strong/text()')[0].strip().split()
                tmp['genrelist'] = m_tree.xpath('//*[@id="keyword"]/ul//li/a/text()')
                try:
                    tmp['plot'] = m_tree.xpath('//*[@id="memo"]/text()')[0]
                except:
                    tmp['plot'] = tmp['tagline']
            

            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            # 썸네일
            final_image_sources = {
                'poster_source': None,
                'poster_mode': None,
                'landscape_source': None,
                'arts': [],
            }
            entity.thumb = []
            final_image_sources['poster_source'] = tmp['data_poster']
            final_image_sources['landscape_source'] = tmp['data_landscape']

            # tagline
            entity.tagline = cls.trans(tmp['tagline'])

            # date, year
            entity.premiered = tmp['premiered']
            entity.year = tmp['year']

            # actor
            entity.actor = []
            for actor in tmp['actorlist']:
                entity.actor.append(EntityActor(actor))


            # director
            # entity.director = []

            # tag
            entity.tag = []
            entity.tag.append('HEYZO')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = tmp['genrelist']
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(cls.get_translated_tag('uncen_tags', item)) # 미리 번역된 태그를 포함
                    # entity.genre.append(SiteUtil.trans(item.strip(), do_trans=do_trans).strip())
            
            # title
            entity.title = entity.originaltitle = entity.sorttitle = f'HEYZO-{code[2:]}'

            # entity.ratings
            # try: 
            #     entity.ratings.append(EntityRatings(float(tree.xpath('//*[@id="movie"]//span[@itemprop="ratingValue"]/text()')[0], max=5, name=cls.site_name)))
            # except: pass

            # plot
            # 플롯 없는 경우도 있음
            if tmp['plot'] != '':
                entity.plot = cls.trans(tmp['plot'])
            else:
                entity.plot = ''
            
            # 팬아트
            # entity.fanart = []

            # 제작사
            entity.studio = 'HEYZO'

            # 부가영상 or 예고편
            entity.extras = []
            try:
                if cls.config['use_extras']:
                    video = cls.make_video_url(f'https://m.heyzo.com/contents/3000/{code[2:]}/sample.mp4')
                    image = cls.make_image_url(f'https://m.heyzo.com/contents/3000/{code[2:]}/images/player_thumbnail.jpg')
                    entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', video, thumb=image))
            except:
                pass
            cls.finalize_images_for_entity(entity, final_image_sources)
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)

        return ret
