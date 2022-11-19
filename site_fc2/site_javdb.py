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


class SiteJavdb(object):
    site_name = 'javdb'
    module_char = 'L'
    site_char = 'J'

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        from metadata import P as MetadataPlugin
        MetadataModelSetting = MetadataPlugin.ModelSetting
        javdb_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cookie': f'locale=en; over18=1; _jdb_session={MetadataModelSetting.get("jav_fc2_javdb_jdbsession")};',
        }
        try:
            ret = {}
            keyword = keyword.strip().lower()
            url = f'{MetadataModelSetting.get("jav_fc2_javdb_url")}/search?q={keyword}'
            if MetadataModelSetting.get('jav_fc2_javdb_jdbsession') == '':
                raise Exception('jdbsession required')
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=javdb_headers)

            ret = {'data' : []}

            search_result = (
                zip(tree.xpath('//*[@id="videos"]/div/div/a/div[2]/text()'),
                    tree.xpath('//*[@id="videos"]/div/div/a/div[4]/text()'),
                    tree.xpath('//*[@id="videos"]/div/div/a/@href'),
                    tree.xpath('//*[@id="videos"]/div/div/a/div[1]/img/@data-src'),
                    tree.xpath('//*[@id="videos"]/div/div[1]/a/div[3]/text()')))

            item = EntityAVSearch(cls.site_name)
            javdb_code = ''
            for result, date, url, thumburl, summary in search_result:
                if result.find('FC2-'+keyword) >= 0:
                    javdb_code = url.split('/')[2]
                    item.code = cls.module_char + cls.site_char + javdb_code
                    item.title = item.title_ko = summary
                    item.image_url = thumburl
                    if manual == True:
                        if image_mode == '3':
                            image_mode = '0'
                        item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
                    try:
                        item.year = parse(date.strip()).date().year
                    except:
                        pass
                    
                    break

            if javdb_code == '':
                logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret


            if do_trans:
                item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
            
            item.ui_code = f'FC2-{keyword}'
            
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
        from metadata import P as MetadataPlugin
        MetadataModelSetting = MetadataPlugin.ModelSetting
        javdb_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cookie': f'locale=en; over18=1; _jdb_session={MetadataModelSetting.get("jav_fc2_javdb_jdbsession")};',
        }
        try:
            ret = {}
            url = f'{MetadataModelSetting.get("jav_fc2_javdb_url")}/v/{code[2:]}'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=javdb_headers)
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            entity.thumb = []
            data_poster = SiteUtil.get_image_url(tree.xpath('//a/img[@class="video-cover"]/@src')[0], image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            try:
                data_landscape = SiteUtil.get_image_url(tree.xpath('//a[@class="tile-item"]/@href')[0], image_mode, proxy_url=proxy_url)
                entity.thumb.append(EntityThumb(aspect='landscape', value=data_landscape['image_url']))
            except:
                logger.debug(f'landscape 없음: {code}')

            # tagline, plot
            entity.tagline = entity.plot = SiteUtil.trans(re.split('FC2-\d*\s', tree.xpath('/html/body/section/div/*[@class="title is-4"]/strong/text()')[0].strip())[1], do_trans=do_trans)

            genrelist = []

            for x in range(1, len(tree.xpath('//nav[@class="panel movie-panel-info"]/div/strong'))+1):
                divname = tree.xpath('//nav[@class="panel movie-panel-info"]/div[%d]/strong/text()' % x)[0]

                if divname == 'ID:':
                    # title / FC2-XXXXXXX
                    entity.title = entity.originaltitle = entity.sorttitle = tree.xpath('//nav[@class="panel movie-panel-info"]/div[%d]/span' % x)[0].text_content()

                elif divname == 'Released Date:':
                    # date, year
                    tmp_date = parse(tree.xpath('//nav[@class="panel movie-panel-info"]/div[%d]/span/text()' % x)[0])
                    entity.premiered = str(tmp_date.date())
                    entity.year = str(tmp_date.date().year)

                elif divname == 'Tags:':
                    genrelist = tree.xpath('//nav[@class="panel movie-panel-info"]/div[%d]/span/a/text()' % x)

                elif divname == 'Seller:':
                    # director
                    entity.director = tree.xpath('//nav[@class="panel movie-panel-info"]/div[%d]/span/a/text()' % x)[0]
            
            # tag
            entity.tag = []
            entity.tag.append('FC2')

            # genre
            entity.genre = []
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(SiteUtil.get_translated_tag('javdb_tags', item))
            # if genrelist != []:
            #     for item in genrelist:
            #         if item in JAVDB_TAGS:
            #             entity.genre.append(JAVDB_TAGS[item])
            #         else: # 장르 번역 부분 추후 수정 필요
            #             entity.genre.append(item)


            # 별점 지원할 경우 추가할 부분 / entity.ratings
            # javdb 지원은 하지만 귀찮으므로 나중에 추가
            
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

    @classmethod
    def test_cookie(cls):
        from metadata import P as MetadataPlugin
        MetadataModelSetting = MetadataPlugin.ModelSetting
        javdb_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cookie': f'locale=en; over18=1; _jdb_session={MetadataModelSetting.get("jav_fc2_javdb_jdbsession")};',
        }
        req = requests.head(f'{MetadataModelSetting.get("jav_fc2_javdb_url")}/fc2', headers=javdb_headers, allow_redirects=True)
        ret = None
        if req.url == f'{MetadataModelSetting.get("jav_fc2_javdb_url")}/fc2':
            ret = True
        else:
            ret = False

        return ret