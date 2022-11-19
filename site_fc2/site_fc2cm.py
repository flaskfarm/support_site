# -*- coding: utf-8 -*-
import json
import random
import re
import traceback

import requests
from dateutil.parser import parse
from framework import SystemModelSetting
from framework.util import Util
from lxml import html
from system import SystemLogicTrans

from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie,
                           EntityRatings, EntityThumb)
#########################################################
from ..plugin import P
from ..site_util import SiteUtil

logger = P.logger
ModelSetting = P.ModelSetting

class SiteFc2Cm(object):
    site_name = 'fc2cm'
    site_base_url = 'https://fc2cm.com'
    module_char = 'L'
    site_char = 'M'

    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36',
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
        'accept-language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7,zh-CN;q=0.6,zh;q=0.5',
        'sec-ch-ua': '"Chromium";v="104", " Not A;Brand";v="99", "Google Chrome";v="104'
    }

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        try:
            ret = {}
            keyword = keyword.strip().lower()
            url = f'{cls.site_base_url}/?p={keyword}&nc=0'
            cm_headers = cls.headers
            cm_headers['X-Forwarded-For'] = '.'.join(map(lambda x: str(random.randrange(1,256)), range(4)))
            # logger.debug(cm_headers)
            status_code = SiteUtil.get_response(url, headers=cm_headers).status_code
            if status_code == 404:
                logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret
            elif status_code == 403:
                logger.debug('fc2cm 403 error')
                ret['ret'] = 'failed'
                ret['data'] = 'fc2cm 403'
                return ret

            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=cm_headers)
            if tree.xpath('/html/head/title/text()')[0] == '404':
                logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret
            elif tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/h1/text()') != []:
                if tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/h1/text()')[0] == ' Hello! my name is 404 ':
                    logger.debug(f'not found: {keyword}')
                    ret['ret'] = 'failed'
                    ret['data'] = 'not found'
                    return ret

            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)

            for tr in tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/table/tr'):
                if tr.xpath('.//td//text()')[0] == '商品ID':
                    result_codename = tr.xpath('.//td//text()')[2]
                    item.code = cls.module_char + cls.site_char + result_codename

                if tr.xpath('.//td//text()')[0] == '販売日':
                    item.year = parse(tr.xpath('.//td//text()')[2]).date().year

            item.image_url = 'https:'+tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[0] if tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[0].startswith('//') else tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[0]
            item.title = re.sub('(FC2 PPV \\d{6,7})|(FC2-PPV-\\d{6,7})', '', tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/h1/a/text()')[0]).strip()
            # logger.debug(manual)
            if manual == True:
                if image_mode == '3':
                    image_mode = '0'
                item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
            
            if do_trans:
                item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
            
            item.ui_code = f'FC2-{result_codename}'
            
            # 스코어 계산 부분 필요
            item.score = 100

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
    def info(cls, code, do_trans=True, proxy_url=None, image_mode='0'):
        try:
            ret = {}
            url = f'{cls.site_base_url}/?p={code[2:]}&nc=0'
            cm_headers = cls.headers
            cm_headers['X-Forwarded-For'] = '.'.join(map(lambda x: str(random.randrange(1,256)), range(4)))
            # logger.debug(cm_headers)
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=cm_headers)
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            entity.thumb = []
            data_poster = SiteUtil.get_image_url('https:'+tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[0] if tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[0].startswith('//') else tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[0], image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            data_landscape = SiteUtil.get_image_url('https:'+tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[1] if tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[1].startswith('//') else tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/a/img/@data-src')[1], image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='landscape', value=data_landscape['image_url']))

            # tagline, plot
            entity.tagline = entity.plot = SiteUtil.trans(re.sub('(FC2 PPV \\d{6,7})|(FC2-PPV-\\d{6,7})', '', tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/h1/a/text()')[0]).strip(), do_trans=do_trans)

            for tr in tree.xpath('//*[@id="contentInner"]/main/article/aside/div/div/table/tr'):
                # date, year
                if tr.xpath('.//td//text()')[0] == '販売日':
                    tmp_date = parse(tr.xpath('.//td//text()')[2])
                    entity.premiered = str(tmp_date.date())
                    entity.year = str(tmp_date.date().year)
                
                # director
                if tr.xpath('.//td//text()')[0] == '販売者':
                    entity.director = tr.xpath('.//td//h2//text()')[0].strip()
                
                # genre
                if tr.xpath('.//td//text()')[0] == 'タグ':
                    entity.genre = []
                    genrelist = tr.xpath('.//td//h5//text()')
                    if genrelist != []:
                        for item in genrelist:
                            entity.genre.append(SiteUtil.get_translated_tag('fc2_tags', item))


            # tag
            entity.tag = []
            entity.tag.append('FC2')
            
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

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)

        return ret