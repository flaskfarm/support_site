# -*- coding: utf-8 -*-
import requests, re, json
import traceback
from dateutil.parser import parse
import unicodedata

from lxml import html

from framework import SystemModelSetting
from framework.util import Util
from system import SystemLogicTrans

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityThumb, EntityActor, EntityRatings, EntityExtra
from ..site_util import SiteUtil

#########################################################
from ..plugin import P
logger = P.logger
ModelSetting = P.ModelSetting

class SiteHeyzo(object):
    site_name = 'heyzo'
    site_base_url = 'https://www.heyzo.com'
    module_char = 'E'
    site_char = 'H'

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        try:
            ret = {}
            if re.search('(\\d{4})', keyword, re.I) is not None and 'heyzo' in keyword.lower():
                code = re.search('(\\d{4})', keyword, re.I).group()
            else:
                # logger.debug(f'invalid keyword: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'invalid keyword'
                return ret

            url = f'{cls.site_base_url}/moviepages/{code}/index.html'

            if SiteUtil.get_response(url, proxy_url=proxy_url).status_code == 404:
                # logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret

            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)
            
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
                m_tree = SiteUtil.get_tree(url.replace('www.', 'm.'), proxy_url=proxy_url)
                tmp['title'] = m_tree.xpath('//div[@id="container"]/h1/text()')[0].strip()
                tmp['year'] = parse(m_tree.xpath('//*[@id="moviedetail"]/div[2]/span/text()')[1].strip()).date().year
                tmp['image_url'] = f'https://m.heyzo.com/contents/3000/{code}/images/player_thumbnail.jpg'


            item.title = item.title_ko = tmp['title']
            item.year = tmp['year']

            item.image_url = tmp['image_url']
            if manual == True:
                if image_mode == '3':
                    image_mode = '0'
                item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
            
            if do_trans:
                item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
            
            item.ui_code = f'HEYZO-{code}'
            
            if 'heyzo' in keyword.lower():
                item.score = 100
            else:
                item.score = 90

            logger.debug('score :%s %s ', item.score, item.ui_code)
            ret['data'].append(item.as_dict())

            ret['data'] = sorted(ret['data'], key=lambda k: k['score'], reverse=True)  
            ret['ret'] = 'success'

        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(exception)
        
        return ret


    @classmethod
    def info(cls, code, do_trans=True, proxy_url=None, image_mode='0'):
        try:
            ret = {}
            url = f'{cls.site_base_url}/moviepages/{code[2:]}/index.html'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)

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
                m_tree = SiteUtil.get_tree(url.replace('www.', 'm.'), proxy_url=proxy_url)
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
            entity.thumb = []
            data_poster = SiteUtil.get_image_url(tmp['data_poster'], image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            data_landscape = SiteUtil.get_image_url(tmp['data_landscape'], image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='landscape', value=data_landscape['image_url']))

            # tagline
            entity.tagline = SiteUtil.trans(tmp['tagline'], do_trans=do_trans)

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
                    entity.genre.append(SiteUtil.get_translated_tag('uncen_tags', item)) # 미리 번역된 태그를 포함
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
                entity.plot = SiteUtil.trans(tmp['plot'], do_trans=do_trans)
            else:
                entity.plot = ''
            
            # 팬아트
            # entity.fanart = []

            # 제작사
            entity.studio = 'HEYZO'

            # 부가영상 or 예고편
            entity.extras = []
            try:
                entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', f'https://m.heyzo.com/contents/3000/{code[2:]}/sample.mp4', thumb=f'https://m.heyzo.com/contents/3000/{code[2:]}/images/player_thumbnail.jpg'))
            except:
                pass

            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()

        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(exception)

        return ret
