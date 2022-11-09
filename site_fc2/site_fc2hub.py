# -*- coding: utf-8 -*-
import requests, re, json
import traceback
from dateutil.parser import parse

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

class SiteFc2Hub(object):
    site_name = 'fc2hub'
    site_base_url = 'https://fc2hub.com'
    module_char = 'L'
    site_char = 'H'

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        try:
            ret = {}
            keyword = keyword.strip().lower()
            url = f'{cls.site_base_url}/search?kw={keyword}'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)

            if SiteUtil.get_response(url).status_code == 404 or SiteUtil.get_response(url).status_code == 500:
                logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret
            elif tree.xpath('/html/head/meta[@property="og:url"]/@content')[0] == 'https://fc2hub.com/search':
                logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret

            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)

            item.code = cls.module_char + cls.site_char + tree.xpath('//*[@id="content"]//h1[@class="card-title fc2-id"]/text()')[0].split('-')[2]

            # 세로 포스터 없음
            item.image_url = tree.xpath('//a[@data-fancybox="gallery"]/@href')[0]
            
            item.title = tree.xpath('//*[@id="content"]//h1[@class="card-text fc2-title"]/text()')[0].strip()
            
            # 정확하지 않음, 추후 처리 필요
            item.year = parse(tree.xpath('/html/head/meta[@property="videos:published_time"]/@content')[0]).date().year

            if manual == True:
                if image_mode == '3':
                    image_mode = '0'
                item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
            
            if do_trans:
                item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
            
            item.ui_code = f'FC2-{item.code[2:]}'
            
            # 스코어 계산 부분 필요
            # fc2hub는 정확한 날짜가 없음, 그래서 90
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
            url = f'{cls.site_base_url}/search?kw={code[2:]}'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일, 세로 포스터 없음
            entity.thumb = []
            data_poster = SiteUtil.get_image_url(tree.xpath('//a[@data-fancybox="gallery"]/@href')[0], image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            entity.thumb.append(EntityThumb(aspect='landscape', value=data_poster['image_url']))

            # tagline, plot
            entity.tagline = entity.plot = SiteUtil.trans(tree.xpath('//*[@id="content"]/div/div[2]/div[1]/div[1]/div[2]/h1/text()')[0], do_trans=do_trans)

            # date, year
            tmp_date = parse(tree.xpath('/html/head/meta[@property="videos:published_time"]/@content')[0])
            entity.premiered = str(tmp_date.date())
            entity.year = str(tmp_date.date().year)

            # director
            entity.director = tree.xpath('//*[@id="content"]/div/div[2]/div[2]/div[1]/div[2]/div/div[2]/text()')[0].strip()
            
            # tag
            entity.tag = []
            entity.tag.append('FC2')
            
            # genre
            entity.genre = []
            genrelist = tree.xpath('//*[@id="content"]/div/div[2]/div[1]/div[1]/div[2]/p/a/text()')

            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(SiteUtil.get_translated_tag('fc2_tags', item))

            # title / FC2-XXXXXXX
            entity.title = entity.originaltitle = entity.sorttitle = f'FC2-{code[2:]}'

            # 별점 지원할 경우 추가할 부분 / entity.ratings
            
            # 팬아트
            # 나중에
            entity.fanart = []

            # 부가영상 or 예고편
            # 나중에
            entity.extras = []


            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()

        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(exception)

        return ret