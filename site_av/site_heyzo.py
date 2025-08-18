import json
import re
import os
import traceback
import unicodedata
from dateutil.parser import parse
from lxml import html
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.heyzo.com'

class SiteHeyzo(SiteAvBase):
    site_name = 'heyzo'
    site_char = 'H'
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    _info_cache = {} # search에서 얻은 파싱 데이터를 info에서 재사용하기 위한 캐시

    @classmethod
    def search(cls, keyword, manual=False):
        try:
            ret = {}
            parsed_code = cls._parse_ui_code_uncensored(keyword)
            match = re.search(r'heyzo-(\d{4})', parsed_code, re.I)
            if not match:
                return {'ret': 'success', 'data': []}
            code = match.group(1)

            url = f'{SITE_BASE_URL}/moviepages/{code}/index.html'
            res = cls.get_response(url)
            if res.status_code != 200:
                return {'ret': 'success', 'data': []}

            tree = html.fromstring(res.text)

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.ui_code = f'HEYZO-{code}'
            item.score = 100

            # json이 있는 경우, 없는 경우
            tmp = {}
            try:
                json_str = tree.xpath('//script[@type="application/ld+json"]/text()')[0]
                json_str_cleaned = re.sub(r'""(.*?)"":"', r'"\1":"', json_str)
                json_data = json.loads(json_str_cleaned)
                cls._info_cache[code] = {'type': 'json', 'data': json_data, 'tree': tree}

                tmp['title'] = unicodedata.normalize('NFKC', json_data['name'])
                tmp['year'] = parse(json_data['dateCreated']).year
                tmp['image_url'] = f"https:{json_data['image']}"
            except Exception:
                m_tree = cls.get_tree(url.replace('www.', 'm.'))
                if m_tree is not None:
                    cls._info_cache[code] = {'type': 'mobile', 'data': m_tree}
                    tmp['title'] = m_tree.xpath('//div[@id="container"]/h1/text()')[0].strip()
                    tmp['year'] = parse(m_tree.xpath('//*[@id="moviedetail"]/div[2]/span/text()')[1].strip()).year
                    tmp['image_url'] = f'https://m.heyzo.com/contents/3000/{code}/images/player_thumbnail.jpg'
                else:
                    tmp['title'] = item.ui_code; tmp['year'] = 0; tmp['image_url'] = ""

            item.title = tmp.get('title') or item.ui_code 
            item.year = tmp.get('year', 0)
            item.image_url = tmp.get('image_url', "")

            if manual:
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                if cls.config.get('use_proxy') and item.image_url:
                    item.image_url = cls.make_image_url(item.image_url)
            else:
                item.title_ko = item.title

            ret['data'] = [item.as_dict()]
            ret['ret'] = 'success'

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)

        return ret


    @classmethod
    def info(cls, code, fp_meta_mode=False):
        ret = {}
        entity_result_val_final = None
        try:
            entity_result_val_final = cls.__info(code, fp_meta_mode=fp_meta_mode).as_dict()
            if entity_result_val_final:
                ret['ret'] = 'success'
                ret['data'] = entity_result_val_final
            else:
                ret['ret'] = 'error'
                ret["data"] = f"Failed to get heyzo info for {code}"
        except Exception as e:
            ret['ret'] = 'exception'
            ret['data'] = str(e)
            logger.exception(f"heyzo info error: {e}")
        return ret


    @classmethod
    def __info(cls, code, fp_meta_mode=False):
        code_part = code[2:]
        tmp = {}
        tree = None; m_tree = None; json_data = None

        # 1. 캐시 확인
        if code_part in cls._info_cache:
            logger.debug(f"Using cached data for HEYZO-{code_part}")
            cached_data = cls._info_cache[code_part]
            del cls._info_cache[code_part]

            if cached_data['type'] == 'json':
                json_data = cached_data['data']
                tree = cached_data['tree']
            elif cached_data['type'] == 'mobile':
                m_tree = cached_data['data']

        # 2. 캐시 없는 경우, 네트워크 호출
        if json_data is None and m_tree is None:
            logger.debug(f"Cache miss for HEYZO-{code_part}. Calling API.")
            url = f'{SITE_BASE_URL}/moviepages/{code_part}/index.html'
            tree = cls.get_tree(url)
            if tree is None: return None

        # json이 있는 경우, 없는 경우
        try:
            # json_data가 아직 None이면 (캐시 miss), 새로 파싱
            if json_data is None and tree is not None:
                json_str = tree.xpath('//script[@type="application/ld+json"]/text()')[0]
                json_str_cleaned = re.sub(r'""(.*?)"":"', r'"\1":"', json_str)
                json_data = json.loads(json_str_cleaned)

            tmp['poster'] = f"https:{json_data['actor']['image']}" if 'actor' in json_data and 'image' in json_data['actor'] else None
            tmp['landscape'] = f"https:{json_data['image']}"
            tmp['tagline'] = unicodedata.normalize('NFKC', json_data['name'])
            tmp['premiered'] = str(parse(json_data['dateCreated']).date())
            tmp['year'] = parse(json_data['dateCreated']).year
            tmp['actor'] = [name.strip() for name in tree.xpath('//div[@id="movie"]//table[@class="movieInfo"]//tr[@class="table-actor"]//span/text()')]
            tmp['genre'] = tree.xpath('//tr[@class="table-tag-keyword-small"]//ul[@class="tag-keyword-list"]//li/a/text()')
            if json_data.get('description', '') != '':
                tmp['plot'] = unicodedata.normalize('NFKC', json_data['description']).strip()
            else:
                tmp['plot'] = tmp['tagline']

        except Exception:
            # m_tree가 아직 None이면 (캐시 miss), 새로 파싱
            if m_tree is None and tree is not None:
                url = f'{SITE_BASE_URL}/moviepages/{code_part}/index.html'
                m_tree = cls.get_tree(url.replace('www.', 'm.'))

            if m_tree is None: return None # 모바일 페이지도 실패 시 종료

            tmp['poster'] = f'https://m.heyzo.com/contents/3000/{code_part}/images/thumbnail.jpg'
            tmp['landscape'] = f'https://m.heyzo.com/contents/3000/{code_part}/images/player_thumbnail.jpg'
            tmp['tagline'] = m_tree.xpath('//div[@id="container"]/h1/text()')[0].strip()
            date_str = m_tree.xpath('//*[@id="moviedetail"]/div[2]/span/text()')[1].strip()
            tmp['premiered'] = str(parse(date_str).date())
            tmp['year'] = parse(date_str).year
            tmp['actor'] = m_tree.xpath('//*[@id="moviedetail"]/div[1]/strong/text()')[0].strip().split()
            tmp['genre'] = m_tree.xpath('//*[@id="keyword"]/ul//li/a/text()')
            try:
                tmp['plot'] = m_tree.xpath('//*[@id="memo"]/text()')[0]
            except:
                tmp['plot'] = tmp['tagline']

        entity = EntityMovie(cls.site_name, code)
        entity.country = [u'일본']; entity.mpaa = u'청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        entity.tag = []; entity.genre = []; entity.actor = []

        # --- 파싱된 데이터를 entity 객체에 할당 ---
        entity.ui_code = cls._parse_ui_code_uncensored(f'heyzo-{code_part}')
        if not entity.ui_code: entity.ui_code = f'HEYZO-{code_part}'

        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()
        entity.label = "HEYZO"

        entity.tagline = cls.trans(tmp.get('tagline', ''))
        entity.premiered = tmp.get('premiered')
        entity.year = tmp.get('year')

        poster_url = tmp.get('poster')
        landscape_url = tmp.get('landscape')

        if not fp_meta_mode:
            # [일반 모드]
            image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
            if image_mode == 'image_server':
                try:
                    local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
                    server_url = cls.MetadataSetting.get('jav_censored_image_server_url')
                    base_save_format = cls.MetadataSetting.get('jav_uncensored_image_server_save_format')
                    base_path_part = base_save_format.format(label=entity.label)
                    code_prefix_part = code_part[:2] # 품번 앞 2자리 (예: 2681 -> 26)
                    final_relative_folder_path = os.path.join(base_path_part.strip('/\\'), code_prefix_part)
                    entity.image_server_target_folder = os.path.join(local_path, final_relative_folder_path)
                    entity.image_server_url_prefix = f"{server_url.rstrip('/')}/{final_relative_folder_path.replace(os.path.sep, '/')}"
                except Exception as e:
                    logger.error(f"[{cls.site_name}] Failed to set custom image server path: {e}")

            try:
                raw_image_urls = {
                    'poster': poster_url,
                    'pl': landscape_url,
                }
                entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
            except Exception as e:
                logger.exception(f"[{cls.site_name}] Error during image processing delegation for {code}: {e}")
        else:
            # [파일처리 모드]
            logger.debug(f"[{cls.site_name}] FP Meta Mode: Skipping full image processing for {code}.")
            if poster_url:
                entity.thumb.append(EntityThumb(aspect="poster", value=poster_url))
            if landscape_url:
                entity.thumb.append(EntityThumb(aspect="landscape", value=landscape_url))

        for actor_name in tmp.get('actor', []):
            entity.actor.append(EntityActor(actor_name))

        entity.tag.append('HEYZO')

        genrelist = tmp.get('genre', [])
        if genrelist != []:
            for item in genrelist:
                entity.genre.append(cls.get_translated_tag('uncen_tags', item))

        if tmp.get('plot', '') != '':
            entity.plot = cls.trans(tmp['plot'])
        else:
            entity.plot = ''

        entity.studio = 'HEYZO'

        # 부가영상 or 예고편
        if not fp_meta_mode and cls.config.get('use_extras'):
            try:
                video_url = cls.make_video_url(f'https://m.heyzo.com/contents/3000/{code_part}/sample.mp4')
                if video_url:
                    trailer_title = entity.tagline if entity.tagline else entity.title
                    entity.extras.append(EntityExtra('trailer', trailer_title, 'mp4', video_url))
            except Exception as e:
                logger.error(f"[{cls.site_name}] Trailer processing error: {e}")

        return entity
