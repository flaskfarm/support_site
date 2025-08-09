import re
import os
import traceback
from lxml import html
from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb)
from ..setup import P, logger
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.caribbeancom.com'

class SiteCarib(SiteAvBase):
    site_name = 'carib'
    site_char = 'C'    
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    _info_cache = {}

    @classmethod
    def search(cls, keyword, manual=False):
        try:
            ret = {}
            match = re.search(r'(\d{6}-\d{3})', keyword, re.I)
            if not match:
                return {'ret': 'success', 'data': []}

            code = match.group(1)

            url = f'{SITE_BASE_URL}/moviepages/{code}/index.html'
            res = cls.get_response(url)
            if res.status_code != 200:
                return {'ret': 'success', 'data': []}

            html_text = res.text
            if html_text:
                cls._info_cache[code] = html_text

            tree = html.fromstring(html_text)

            item = EntityAVSearch(cls.site_name)
            item.code = cls.module_char + cls.site_char + code
            item.ui_code = f'carib-{code}'

            title_node = tree.xpath('//div[@id="moviepages"]//h1[@itemprop="name"]/text()')
            item.title = title_node[0].strip() if title_node else ""

            if manual:
                item.title_ko = "(현재 인터페이스에서는 번역을 제공하지 않습니다) " + item.title
                if cls.config.get('use_proxy'):
                    item.image_url = cls.make_image_url(f'https://www.caribbeancom.com/moviepages/{code}/images/l_l.jpg')
            else:
                item.title_ko = item.title
                item.image_url = f'https://www.caribbeancom.com/moviepages/{code}/images/l_l.jpg'

            try: 
                item.year = int("20" + code[4:6])
            except (ValueError, IndexError): 
                item.year = 0

            item.score = 100

            ret['data'] = [item.as_dict()]
            ret['ret'] = 'success'

        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def info(cls, code):
        try:
            ret = {}
            entity = cls.__info(code)
            if entity:
                ret['ret'] = 'success'
                ret['data'] = entity.as_dict()
            else:
                ret['ret'] = 'error'
        except Exception as e: 
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret


    @classmethod
    def __info(cls, code):
        code_part = code[2:]
        tree = None

        # 1. 캐시에 데이터가 있는지 먼저 확인
        if code_part in cls._info_cache:
            logger.debug(f"Using cached HTML data for carib code: {code_part}")
            html_text = cls._info_cache[code_part]
            tree = html.fromstring(html_text)
            del cls._info_cache[code_part]
        
        # 2. 캐시에 데이터가 없으면 네트워크를 통해 직접 호출
        if tree is None:
            logger.debug(f"Cache miss for carib code: {code_part}. Calling API.")
            url = f'{SITE_BASE_URL}/moviepages/{code_part}/index.html'
            tree = cls.get_tree(url)

        if tree is None: return None

        entity = EntityMovie(cls.site_name, code)

        entity.country = [u'일본']; entity.mpaa = u'청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        entity.tag = []; entity.genre = []; entity.actor = []

        # ui_code 및 title 설정
        entity.ui_code = f'carib-{code_part}'
        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code

        # 연도(year) 및 출시일(premiered) 파싱
        try:
            # 품번(YYMMDD-XXX)에서 파싱
            entity.year = int("20" + code_part[4:6])
            entity.premiered = f"{entity.year}-{code_part[0:2]}-{code_part[2:4]}"
        except (ValueError, IndexError): 
            entity.year = 0
            entity.premiered = None

        # 이미지 서버 경로 계산
        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
        if image_mode == 'image_server':
            module_type = 'jav_uncensored'
            local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
            server_url = cls.MetadataSetting.get('jav_censored_image_server_url')
            base_save_format = cls.MetadataSetting.get(f'{module_type}_image_server_save_format')

            label = entity.ui_code.split('-')[0].upper()
            year_part = str(entity.year) if entity.year else "0000"

            base_path_part = base_save_format.format(label=label)
            final_relative_folder_path = os.path.join(base_path_part.strip('/\\'), year_part)

            entity.image_server_target_folder = os.path.join(local_path, final_relative_folder_path)
            entity.image_server_url_prefix = f"{server_url.rstrip('/')}/{final_relative_folder_path.replace(os.path.sep, '/')}"

        # 썸네일
        # jacket.jpg가 있는지 확인하여 포스터 결정 (404 체크는 비용이 크므로, 다른 방법을 고려할 수 있음)
        # 여기서는 원본 로직을 유지
        poster_url = f'https://www.caribbeancom.com/moviepages/{code_part}/images/l_l.jpg'
        jacket_url = f'https://www.caribbeancom.com/moviepages/{code_part}/images/jacket.jpg'
        if cls.get_response(jacket_url).status_code != 404:
            poster_url = jacket_url

        final_image_sources = {
            'poster_source': poster_url,
            'poster_mode': None,
            'landscape_source': f'https://www.caribbeancom.com/moviepages/{code_part}/images/l_l.jpg',
            'arts': [], # Caribbeancom은 샘플 이미지를 찾기 어려움
        }
        cls.finalize_images_for_entity(entity, final_image_sources)

        # 나머지 메타데이터 파싱
        title_node = tree.xpath('//div[@id="moviepages"]//h1[@itemprop="name"]/text()')
        entity.tagline = cls.trans(title_node[0].strip()) if title_node else ""

        for actor in tree.xpath('//div[@class="movie-info section"]//li[@class="movie-spec"]//span[@itemprop="name"]/text()'):
            entity.actor.append(EntityActor(actor))

        entity.tag.append('carib')

        genre_nodes = tree.xpath('//li[@class="movie-spec"]//span[@class="spec-content"]/a[@class="spec-item"]/text()')
        for item in genre_nodes:
            entity.genre.append(cls.get_translated_tag('uncen_tags', item))

        plot_node = tree.xpath('//p[@itemprop="description"]/text()')
        entity.plot = cls.trans(plot_node[0]) if plot_node else ""

        entity.studio = 'Caribbeancom'

        # 부가영상 or 예고편
        try:
            if cls.config.get('use_extras'):
                thumb_url = next((t.value for t in entity.thumb if t.aspect == 'landscape'), '') # 랜드스케이프를 썸네일로
                video_url = cls.make_video_url(f'https://smovie.caribbeancom.com/sample/movies/{code_part}/480p.mp4')
                if video_url:
                    entity.extras.append(EntityExtra('trailer', entity.title, 'mp4', video_url, thumb=thumb_url))
        except Exception:
            logger.warning(f"Failed to process extras for {code}")

        return entity
