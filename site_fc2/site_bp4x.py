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

class SiteBp4x(object):
    site_name = 'bp4x'
    site_base_url = 'https://www.jav24.com/watch/adult.contents.fc2.com/article/'
    module_char = 'L'
    site_char = 'B'

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        try:
            ret = {}
            keyword = keyword.strip().lower()
            url = f'{cls.site_base_url}{keyword}/'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)
            if SiteUtil.get_response(url).status_code == 404 or SiteUtil.get_response(url).status_code == 410:
                logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret

            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)

            item.code = cls.module_char + cls.site_char + keyword
            item.title = item.title_ko = tree.xpath('//div[@class="my__product__detail__title notranslate"]/text()')[0]
            item.image_url = tree.xpath('//div[@class="my__product__image lazyload"]/@data-bg')[0]
            item.year = parse(tree.xpath('//div[@class="my__product__spec"]/text()')[1]).date().year

            if manual == True:
                if image_mode == '3':
                    image_mode = '0'
                item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
            
            if do_trans:
                item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
            
            item.ui_code = f'FC2-{keyword}'
            
            # 스코어 계산 부분 필요
            item.score = 100

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
            url = f'{cls.site_base_url}{code[2:]}/'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            # 세로 포스터 없음
            entity.thumb = []
            data_poster = SiteUtil.get_image_url(tree.xpath('//div[@class="my__product__image lazyload"]/@data-bg')[0], image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            entity.thumb.append(EntityThumb(aspect='landscape', value=data_poster['image_url']))

            # tagline, plot
            entity.tagline = entity.plot = SiteUtil.trans(tree.xpath('//div[@class="my__product__detail__title notranslate"]/text()')[0].strip(), do_trans=do_trans)

            # date, year
            tmp_date = parse(tree.xpath('//div[@class="my__product__spec"]/text()')[1])
            entity.premiered = str(tmp_date.date())
            entity.year = str(tmp_date.date().year)

            # director
            entity.director = (tree.xpath('//div[@class="my__product__meta__group__flex"]/a/text()')[0]).replace('#', '')

            # tag
            entity.tag = []
            entity.tag.append('FC2')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = [x.replace('#', '') for x in
                        tree.xpath('//div[@class="my__product__meta__group__flex"]/a/text()') if
                        x not in ['#FC2', '#', '#動画', '#FC2コンテンツマーケット', '#ダウンロード', '#'+entity.director]
                        and not x.startswith('#FC2-PPV-')]
            
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