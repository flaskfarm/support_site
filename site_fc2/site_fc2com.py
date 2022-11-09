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

class SiteFc2Com(object):
    site_name = 'fc2com'
    site_base_url = 'https://adult.contents.fc2.com/article'
    module_char = 'L'
    site_char = 'F'

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        try:
            ret = {}
            keyword = keyword.strip().lower()
            url = f'{cls.site_base_url}/{keyword}/'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)
            
            ret = {'data' : []}

            if tree.xpath('/html/head/title/text()')[0] == 'お探しの商品が見つかりません':
                logger.debug(f'not found: {keyword}')
                logger.debug(f'try search google cache: {keyword}')
                google_cache = cls.search_google_cache(url)

                if google_cache is not None:
                    tree = google_cache
                else:
                    wayback_cache = cls.search_wayback(url, proxy_url=proxy_url)
                    if wayback_cache is not None:
                        tree = wayback_cache
                    else:
                        ret['ret'] = 'failed'
                        ret['data'] = 'not found'
                        return ret

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + keyword
            item.title = item.title_ko = tree.xpath('//*[@id="top"]/div[1]/section[1]/div/section/div[2]/h3/text()')[0].strip()
            item.year = re.search('\d{4}/\d{2}/\d{2}', tree.xpath('//*[@id="top"]/div[1]/section[1]/div/section/div[2]/div[2]/p/text()')[0]).group(0).split('/')[0]

            item.image_url = 'https:'+tree.xpath('//*[@id="top"]/div[1]/section[1]/div/section/div[1]/span/img/@src')[0]
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
            url = f'{cls.site_base_url}/{code[2:]}/'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url)
            if tree.xpath('/html/head/title/text()')[0] == 'お探しの商品が見つかりません':
                if cls.search_google_cache(url):
                    tree = cls.search_google_cache(url)
                else:
                    tree = cls.search_wayback(url, proxy_url=proxy_url)
                
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            entity.thumb = []
            try:
                data_poster = SiteUtil.get_image_url('https:'+tree.xpath('//*[@id="top"]/div[1]/section[1]/div/section/div[1]/span/img/@src')[0], image_mode, proxy_url=proxy_url)
                entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            except:
                logger.debug(f'포스터 없음: {code}')
            try:
                data_landscape = SiteUtil.get_image_url(tree.xpath('//*[@id="top"]/div[1]/section[2]/ul/li[1]/a/@href')[0], image_mode, proxy_url=proxy_url)
                entity.thumb.append(EntityThumb(aspect='landscape', value=data_landscape['image_url']))
            except:
                logger.debug(f'landscape 없음: {code}')


            # tagline, plot
            entity.tagline = entity.plot = SiteUtil.trans(tree.xpath('//*[@id="top"]/div[1]/section[1]/div/section/div[2]/h3/text()')[0].strip(), do_trans=do_trans)

            # date, year
            tmp_date = parse(re.search('\d{4}/\d{2}/\d{2}', tree.xpath('//*[@id="top"]/div[1]/section[1]/div/section/div[2]/div[2]/p/text()')[0]).group(0))
            entity.premiered = str(tmp_date.date())
            entity.year = str(tmp_date.date().year)

            # director
            entity.director = tree.xpath('//*[@id="top"]/div[1]/section[1]/div/section/div[2]/ul/li/a/text()')[0]

            # tag
            entity.tag = []
            entity.tag.append('FC2')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = [x for x in tree.xpath('//*[@id="top"]/div[1]/section[1]/div/section/div[2]/section/div/a/text()')]
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(SiteUtil.get_translated_tag('fc2_tags', item))

            
            # title / FC2-XXXXXXX
            entity.title = entity.originaltitle = entity.sorttitle = f'FC2-{code[2:]}'

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

        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(exception)

        return ret
    
    def search_google_cache(url):
        cache_url = f'https://webcache.googleusercontent.com/search?q=cache:{url}'
        try:
            cache_response = SiteUtil.get_response(cache_url, headers=SiteUtil.default_headers).status_code
            logger.debug(cache_response)
            if cache_response == 404:
                logger.debug(f'not found in google cache')
                return
            elif cache_response == 429:
                logger.debug(f'google cache blocked')
                return
            else:
                logger.debug(f'found in google cache')
                tree = SiteUtil.get_tree(cache_url, headers=SiteUtil.default_headers)
                return tree
            
        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())

    def search_wayback(url, proxy_url):
        wayback_url = f'http://archive.org/wayback/available?url={url}&timestamp=0'
        try:
            wayback_response = SiteUtil.get_response(wayback_url, headers=SiteUtil.default_headers)
            if len(wayback_response.json()['archived_snapshots']) > 0:
                logger.debug(f'found in wayback machine')
                cache_url = wayback_response.json()['archived_snapshots']['closest']['url']
                logger.debug(SiteUtil.get_response(cache_url, headers=SiteUtil.default_headers).text)
                tree = SiteUtil.get_tree(cache_url, headers=SiteUtil.default_headers)
                return tree
            else:
                logger.debug(f'not found in wayback machine')
                return

        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())