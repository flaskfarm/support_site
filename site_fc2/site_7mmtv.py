# -*- coding: utf-8 -*-
import json
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

class Site7mmTv(object):
    site_name = '7mmtv'
    module_char = 'L'
    site_char = '7'

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        from metadata import P as MetadataPlugin
        MetadataModelSetting = MetadataPlugin.ModelSetting
        try:
            ret = {}
            keyword = keyword.strip().lower()
            site_base_url = MetadataModelSetting.get('jav_fc2_7mmtv_url')
            url = f'{site_base_url}/ko/searchform_search/all/index.html'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, post_data={'search_keyword': keyword, 'search_type': 'uncensored', 'op': 'search'})

            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)

            if tree.xpath('//div[@class="latest-korean-box-row"]'):
                search_result = (
                    zip(tree.xpath('//div[@class="latest-korean-box-row"]/div[@class="latest-korean-box-text"]/a/h2/text()'),
                        tree.xpath('//div[@class="latest-korean-box-row"]/div[@class="latest-korean-box-text"]/a/@href'),
                        tree.xpath('//div[@class="latest-korean-box-row"]/div[@class="latest-korean-box-img"]/a/figure/video/@poster')
                        or tree.xpath('//div[@class="latest-korean-box-row"]/div[@class="latest-korean-box-img"]/a/img/@src'),
                        tree.xpath('//div[@class="latest-korean-box-row"]/div[@class="latest-korean-box-text"]/div[@class="korean-box-text-date-row"]//span[@class="date-part"]/text()'))
                )
                for search_title, url, thumb, date in search_result:
                    if keyword in search_title and 'fc2' in search_title.lower():
                        item.title = item.title_ko = re.sub('(\[?FC2-?PPV-? ?\\d{6,7}\]?)', '', search_title, flags=re.I).strip()
                        item.code = cls.module_char + cls.site_char + url.split('/')[5]
                        item.image_url = thumb
                        item.year = parse(date).year
                        break

            else:
                logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret

            # 검색에서는 연도 파악 불가
            # item.year = ''

            if manual == True:
                if image_mode == '3':
                    image_mode = '0'
                item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
            
            if do_trans:
                item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
            
            item.ui_code = f'FC2-{keyword}'
            
            # 스코어 계산 부분 필요
            # 장르 없는 경우 대다수, 그래서 90
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
    def info(cls, code, do_trans=True, proxy_url=None, image_mode='0'):
        from metadata import P as MetadataPlugin
        MetadataModelSetting = MetadataPlugin.ModelSetting
        try:
            ret = {}
            site_base_url = MetadataModelSetting.get('jav_fc2_7mmtv_url')
            url = f'{site_base_url}/ko/uncensored_content/{code[2:]}/index.html'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            # 세로 포스터 없음
            entity.thumb = []
            data_poster = SiteUtil.get_image_url(tree.xpath('/html/body/section[1]/div/div/div/div/div[2]/div[2]/img/@src')[0], image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            entity.thumb.append(EntityThumb(aspect='landscape', value=data_poster['image_url']))

            # tagline, plot
            entity.tagline = entity.plot = SiteUtil.trans(re.sub('(\[?FC2-?PPV-? ?\\d{6,7}\]?)', '', tree.xpath('/html/body/section[1]/div/div/div/div/div[2]/div[1]/h2/text()')[0], flags=re.I).strip(), do_trans=do_trans)

            # date, year
            tmp_date = parse(tree.xpath('/html/body/section[1]/div/div/div/div/div[3]/div/span[1]/ul/li[@class="posts-message"]/text()')[1])
            entity.premiered = str(tmp_date.date())
            entity.year = str(tmp_date.date().year)

           # title / FC2-XXXXXXX
            entity.title = entity.originaltitle = entity.sorttitle = 'FC2-' + re.search('\\d{6,7}', tree.xpath('/html/body/section[1]/div/div/div/div/div[3]/div/span[1]/ul/li[@class="posts-message"]/text()')[0]).group()

            # director
            # 대부분 director가 없기 때문에 fc2club에서 검색 시도
            if tree.xpath('/html/body/section[1]/div/div/div/div/div[3]/div/span[2]/ul/li[@class="posts-message"]')[2].text.strip() == 'N/A':
                logger.debug('director N/A')
                
                # 2021-09-24 fc2club 접속 불가
                # try:
                #     fc2clubsearch_url = f'https://fc2club.net/html/{entity.title}.html'
                #     fc2club_tree = SiteUtil.get_treefromcontent(fc2clubsearch_url, proxy_url=proxy_url)
                #     entity.director = fc2club_tree.xpath('/html/body/div[2]/div/div[1]/h5[3]/a[1]/text()')[0].strip()
                # except Exception as exception:
                #     logger.debug('director N/A, fc2club')
                #     # entity.director = ''

            else:
                entity.director = tree.xpath('/html/body/section[1]/div/div/div/div/div[3]/div/span[2]/ul/li[@class="posts-message"]')[2].text.strip()

            # tag
            entity.tag = []
            entity.tag.append('FC2')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = [x for x in tree.xpath('/html/body/section[1]/div/div/div/div/div[3]/span/ul/li[2]/span/a/text()') if 'fc2' and 'FC2' not in x]
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(SiteUtil.get_translated_tag('fc2_tags', item))

            
            # 별점 지원할 경우 추가할 부분 / entity.ratings
            # fc2.com 지원은 하지만 귀찮으므로 나중에 추가
            
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