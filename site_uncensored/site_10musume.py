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

class Site10Musume(object):
    site_name = '10musume'
    site_base_url = 'https://www.10musume.com'
    module_char = 'E'
    site_char = 'M'

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        try:
            ret = {}
            if re.search('(\\d{6}[_-]\\d+)', keyword, re.I) is not None:
                code = re.search('(\\d{6}[_-]\\d+)', keyword, re.I).group().replace('-', '_')
            else:
                # logger.debug(f'invalid keyword: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = 'invalid keyword'
                return ret

            proxies = {'http': proxy_url, 'https': proxy_url}
            url = f'{cls.site_base_url}/dyn/phpauto/movie_details/movie_id/{code}.json'
            
            try:
                response = requests.get(url, proxies=proxies)
                json_data = response.json()
            except:
                # logger.debug(f'not found: {keyword}')
                ret['ret'] = 'failed'
                ret['data'] = response.status_code
                return ret
            
            ret = {'data' : []}

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.title = item.title_ko = json_data['Title']
            item.year = json_data['Year']

            # json에 url이 잘못된 경우
            try:
                if '10musume.com' not in json_data['MovieThumb']:
                    moviethumb = json_data['MovieThumb'].replace('/moviepages', 'www.10musume.com/moviepages')
                else:
                    moviethumb = json_data['MovieThumb']
            except:
                moviethumb = ''

            item.image_url = moviethumb
            if manual == True:
                if image_mode == '3':
                    image_mode = '0'
                item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)
            
            if do_trans:
                item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')
            
            item.ui_code = f'10mu-{code}'
            
            if '10mu' in keyword.lower():
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
    def info(cls, code, do_trans=True, proxy_url=None, image_mode='0'):
        try:
            ret = {}
            proxies = {'http': proxy_url, 'https': proxy_url}
            url = f'{cls.site_base_url}/dyn/phpauto/movie_details/movie_id/{code[2:]}.json'
            json_data = requests.get(url, proxies=proxies).json()
            
            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'

            # 썸네일
            # json에 url이 잘못된 경우
            try:
                if '10musume.com' not in json_data['MovieThumb']:
                    moviethumb = json_data['MovieThumb'].replace('/moviepages', 'www.10musume.com/moviepages')
                else:
                    moviethumb = json_data['MovieThumb']

                if '10musume.com' not in json_data['ThumbUltra']:
                    thumbultra = json_data['ThumbUltra'].replace('/moviepages', 'www.10musume.com/moviepages')
                else:
                    thumbultra = json_data['ThumbUltra']
            except:
                moviethumb = thumbultra = ''

            entity.thumb = []
            data_poster = SiteUtil.get_image_url(moviethumb, image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='poster', value=data_poster['image_url']))
            data_landscape = SiteUtil.get_image_url(thumbultra, image_mode, proxy_url=proxy_url)
            entity.thumb.append(EntityThumb(aspect='landscape', value=data_landscape['image_url']))

            # tagline
            entity.tagline = SiteUtil.trans(json_data['Title'], do_trans=do_trans)

            # date, year
            entity.premiered = json_data['Release']
            entity.year = json_data['Year']

            # actor
            entity.actor = []
            for actor in json_data['ActressesJa']:
                entity.actor.append(EntityActor(actor))


            # director
            # entity.director = []

            # tag
            entity.tag = []
            entity.tag.append('10Musume')

            # genre
            entity.genre = []
            genrelist = []
            genrelist = json_data['UCNAME']
            if genrelist != []:
                for item in genrelist:
                    entity.genre.append(SiteUtil.get_translated_tag('uncen_tags', item)) # 미리 번역된 태그를 포함
                    # entity.genre.append(SiteUtil.trans(item.strip(), do_trans=do_trans).strip())
            
            # title
            entity.title = entity.originaltitle = entity.sorttitle = f'10mu-{code[2:]}'

            # entity.ratings
            try: entity.ratings.append(EntityRatings(float(json_data['AvgRating']), name=cls.site_name))
            except: pass

            # plot
            entity.plot = SiteUtil.trans(json_data['Desc'], do_trans=do_trans)
            
            # 팬아트
            # entity.fanart = []

            # 제작사
            entity.studio = '10Musume'

            # 부가영상 or 예고편
            entity.extras = []
            try:
                entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', json_data['SampleFiles'][-1]['URL'], thumb=thumbultra))
            except: pass

            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)

        return ret
