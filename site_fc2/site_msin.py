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

class SiteMsin(object):
    site_name = 'msin'
    site_base_url = 'https://db.msin.jp'
    module_char = 'L'
    site_char = 'N'

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        try:
            ret = {}
            keyword = keyword.strip().lower()
            url = f'{cls.site_base_url}/search/movie?str={keyword}'

            response = SiteUtil.get_response(url, cookies={'age': 'off'})
            tree = html.fromstring(response.text)
            tree.make_links_absolute(url)
            
            ret = {'data' : []}
            # logger.debug(tree.xpath('//*[@id="content"]/p[1]/text()'))
            if tree.xpath('//*[@id="content"]/p[1]/text()') != []:
                logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'not found'
                return ret

            elif len(response.history) >= 1:
                # logger.debug('302')
                try:
                    item = EntityAVSearch(cls.site_name)
                    item.code = cls.module_char + cls.site_char + response.url.split('=')[-1]
                    item.title = item.title_ko = "".join(tree.xpath('//*[@id="content"]//div[contains(@class, "mv_title")]//span/text()')).strip()
                    item.year = parse(tree.xpath('//*[@id="content"]//div[@class="mv_createDate"]/a/text()')[0]).year if tree.xpath('//*[@id="content"]//div[@class="mv_createDate"]/a/text()') !=[] else None
                    item.image_url = tree.xpath('//*[@id="content"]//div[contains(@class, "movie_image_ditail")]/img/@src')[0] if tree.xpath('//*[@id="content"]//div[contains(@class, "movie_image_ditail")]/img/@src') !=[] else None

                    if manual == True:
                        if image_mode == '3':
                            image_mode = '0'
                        item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
                
                    if do_trans:
                        item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')

                    pn = tree.xpath('//*[@id="content"]//div[@class="mv_fileName"]/text()')[0].split('-')[-1]
                    item.ui_code = f'FC2-{pn}'

                    item.score = 100
                    logger.debug('score :%s %s ', item.score, item.ui_code)

                    ret['data'].append(item.as_dict())

                except Exception as exception: 
                    logger.error('Exception:%s', exception)
                    logger.error(traceback.format_exc()) 

            else:
                # logger.debug('search')
                for entry in tree.xpath('//*[@id="content"]//div[@class="movie_info"]'):
                    item = EntityAVSearch(cls.site_name)
                    item.code = cls.module_char + cls.site_char + entry.xpath('./div[@class="movie_ditail"]/div[contains(@class, "movie_title")]/a/@href')[0].split('=')[-1]
                    item.title = item.title_ko = entry.xpath('./div[@class="movie_ditail"]/div[contains(@class, "movie_title")]/a/text()')[0].strip()
                    item.year = parse(entry.xpath('./div[@class="movie_ditail"]/div[@class="movie_create"]/a//text()')[0]).year if entry.xpath('./div[@class="movie_ditail"]/div[@class="movie_create"]/a//text()') !=[] else None
                    item.image_url = entry.xpath('./div//div[@class="img_wrap"]/a/img/@src')[0] if entry.xpath('./div//div[@class="img_wrap"]/a/img/@src') != [] else None

                    if manual == True:
                        if image_mode == '3':
                            image_mode = '0'
                        item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
            
                    if do_trans:
                        item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
                    
                    pn = entry.xpath('./div[@class="movie_ditail"]/div[@class="movie_pn"]/text()')[0].split('-')[-1]
                    item.ui_code = f'FC2-{pn}'

                    # 스코어 계산 부분 필요
                    if keyword == pn:
                        item.score = 100
                    else:
                        item.score = 85
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
            url = f'{cls.site_base_url}/page/movie?id={code[2:]}'
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, cookies={'age': 'off'})
            tree.make_links_absolute(url)
                
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            entity.thumb = []
            try:
                data_poster = SiteUtil.get_image_url(tree.xpath('//*[@id="content"]//div[contains(@class, "movie_image_ditail")]/img/@src')[0], image_mode, proxy_url=proxy_url)
                entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            except:
                logger.debug(f'포스터 없음: {code}')

            # tagline
            entity.tagline = entity.plot = SiteUtil.trans("".join(tree.xpath('//*[@id="content"]//div[contains(@class, "mv_title")]//span/text()')).strip(), do_trans=do_trans)

            # date, year
            tmp_date = parse(tree.xpath('//*[@id="content"]//div[@class="mv_createDate"]/a/text()')[0]) if tree.xpath('//*[@id="content"]//div[@class="mv_createDate"]/a/text()') !=[] else None
            if tmp_date:
                entity.premiered = str(tmp_date.date())
                entity.year = str(tmp_date.date().year)

            # director
            entity.director = tree.xpath('//*[@id="content"]//div[contains(@class, "mv_writer")]/a/text()')[0].strip() if tree.xpath('//*[@id="content"]//div[contains(@class, "mv_writer")]/a/text()') !=[] else None

            # tag
            entity.tag = []
            entity.tag.append('FC2')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = tree.xpath('//*[@id="content"]//div[contains(@class, "mv_tag")]/input/@value')
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(SiteUtil.get_translated_tag('fc2_tags', item))

            
            # title / FC2-XXXXXXX
            pn = tree.xpath('//*[@id="content"]//div[@class="mv_fileName"]/text()')[0].split('-')[-1]
            entity.title = entity.originaltitle = entity.sorttitle = f'FC2-{pn}'

            # 별점 지원할 경우 추가할 부분 / entity.ratings

            # actor
            entity.actor = []
            for actorurl in tree.xpath('//*[@id="content"]//div[contains(@class, "mv_artist")]/span/a/@href'):
                tmpactor = cls.get_actor_msin(actorurl)
                entity.actor.append(tmpactor)

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

    @classmethod
    def get_actor_msin(cls, url):
        response = SiteUtil.get_response(url, cookies={'age': 'off'})
        tree = html.fromstring(response.text)
        actor = EntityActor('', site='msin')
        actor.originalname = tree.xpath('//div[@class="act_name"]/span[@class="mv_name"]/text()')[0].strip()
        actor.name = SiteUtil.trans(actor.originalname, do_trans=True).strip()
        try:
            actor.thumb = SiteUtil.get_image_url(tree.xpath('//div[@class="act_image"]//img/@src')[0], image_mode='3')['image_url']
        except:
            pass

        return actor