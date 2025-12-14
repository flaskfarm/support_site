import json
import re
import os
import traceback
import unicodedata
from dateutil.parser import parse
from lxml import html
from io import BytesIO
from PIL import Image

from ..entity_av import EntityAVSearch
from ..entity_base import (EntityActor, EntityExtra, EntityMovie, EntityRatings, EntityThumb)
from ..setup import P, logger, path_data
from .site_av_base import SiteAvBase

SITE_BASE_URL = 'https://www.heyzo.com'
MOBILE_BASE_URL = 'https://m.heyzo.com'

class SiteHeyzo(SiteAvBase):
    site_name = 'heyzo'
    site_char = 'H'
    module_char = 'E'
    default_headers = SiteAvBase.base_default_headers.copy()

    _info_cache = {}

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

            tmp = {}
            try:
                json_str = tree.xpath('//script[@type="application/ld+json"]/text()')[0]
                json_str_cleaned = re.sub(r'""(.*?)"":"', r'"\1":"', json_str)
                json_data = json.loads(json_str_cleaned, strict=False)
                cls._info_cache[code] = json_data 

                tmp['title'] = unicodedata.normalize('NFKC', json_data['name'])
                tmp['year'] = parse(json_data['dateCreated']).year
                tmp['image_url'] = f"https:{json_data['image']}"
                logger.debug(f"[{cls.site_name}] Search: JSON-LD parsed successfully.")
            except Exception as e:
                logger.debug(f"[{cls.site_name}] Search: JSON-LD parse failed ({e}). Fallback to basic info.")
                tmp['title'] = item.ui_code
                tmp['year'] = 0
                tmp['image_url'] = ""

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
        json_data = None

        if code_part in cls._info_cache:
            json_data = cls._info_cache[code_part]
            del cls._info_cache[code_part]

        if json_data is None:
            url = f'{SITE_BASE_URL}/moviepages/{code_part}/index.html'
            try:
                tree = cls.get_tree(url)
                if tree is not None:
                    json_str = tree.xpath('//script[@type="application/ld+json"]/text()')[0]
                    json_str_cleaned = re.sub(r'""(.*?)"":"', r'"\1":"', json_str)
                    json_data = json.loads(json_str_cleaned, strict=False)
            except Exception:
                pass

        m_url = f'{MOBILE_BASE_URL}/moviepages/{code_part}/index.html'
        mobile_headers = cls.default_headers.copy()
        mobile_headers['User-Agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
        
        m_html = None
        try:
            m_res = cls.get_response(m_url, headers=mobile_headers)
            if m_res and m_res.status_code == 200:
                m_html = m_res.text
        except Exception:
            pass
        
        if m_html is None and json_data is None:
            logger.error(f"[{cls.site_name}] Failed to get both JSON-LD and Mobile Page for {code_part}")
            return None

        def fix_url(url):
            if not url: return None
            if url.startswith('//'): return 'https:' + url
            return url

        if json_data:
            tmp['title'] = unicodedata.normalize('NFKC', json_data['name'])
            tmp['premiered'] = str(parse(json_data['dateCreated']).date())
            tmp['year'] = parse(json_data['dateCreated']).year
            if json_data.get('description'):
                tmp['plot'] = cls.A_P(unicodedata.normalize('NFKC', json_data['description']))
            tmp['json_poster'] = fix_url(json_data.get('actor', {}).get('image'))
            tmp['json_landscape'] = fix_url(json_data.get('image'))
            
            actor_data = json_data.get('actor')
            if isinstance(actor_data, dict):
                tmp['actor'] = [actor_data.get('name')]
            elif isinstance(actor_data, list):
                tmp['actor'] = [a.get('name') for a in actor_data if a.get('name')]
            elif isinstance(actor_data, str):
                tmp['actor'] = [actor_data]
            else:
                tmp['actor'] = []
        else:
            tmp['actor'] = []
            if m_html:
                title_match = re.search(r'<div id="header">.*?<h1>(.*?) - </h1>', m_html, re.DOTALL)
                if not title_match: title_match = re.search(r'<h1>(.*?)</h1>', m_html)
                if title_match: tmp['title'] = title_match.group(1).strip()
                
                date_match = re.search(r'配信日：</span>\s*(\d{4}-\d{2}-\d{2})', m_html)
                if date_match:
                    tmp['premiered'] = date_match.group(1)
                    tmp['year'] = int(tmp['premiered'][:4])
                
                plot_match = re.search(r'<p id="memo">(.*?)</p>', m_html, re.DOTALL)
                if plot_match: tmp['plot'] = cls.A_P(plot_match.group(1))

        if m_html:
            actor_match = re.search(r'<strong class="name">\s*(.*?)\s*</strong>', m_html, re.DOTALL)
            if actor_match:
                actor_str = actor_match.group(1).strip()
                if actor_str: tmp['actor'] = actor_str.split()

            keyword_section = re.search(r'<div id="keyword">.*?<ul>(.*?)</ul>', m_html, re.DOTALL)
            if keyword_section:
                genre_matches = re.findall(r'<a href="/search/.*?">(.*?)</a>', keyword_section.group(1))
                if genre_matches: tmp['genre'] = [g.strip() for g in genre_matches]
            
            gallery_pattern = r'[\"\']((?://m\.heyzo\.com)?/contents/3000/' + code_part + r'/gallery/(?:thumbnail_)?\d+\.jpg)[\"\']'
            found_urls = re.findall(gallery_pattern, m_html)
            
            gallery_srcs = []
            for src in found_urls:
                hq_src = src.replace('thumbnail_', '')
                gallery_srcs.append(hq_src)
            
            gallery_srcs = sorted(list(set(gallery_srcs)))
            tmp['gallery'] = [fix_url(src) for src in gallery_srcs[:5]]
            
            tmp['mobile_poster'] = f'https://m.heyzo.com/contents/3000/{code_part}/images/thumbnail.jpg'
            tmp['mobile_landscape'] = f'https://m.heyzo.com/contents/3000/{code_part}/images/player_thumbnail.jpg'
        else:
            if not tmp.get('actor'): tmp['actor'] = []
            tmp['genre'] = []
            tmp['gallery'] = []


        entity = EntityMovie(cls.site_name, code)
        entity.country = [u'일본']; entity.mpaa = u'청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.ratings = []
        entity.tag = []; entity.genre = []; entity.actor = []
        entity.original = {}

        entity.ui_code = cls._parse_ui_code_uncensored(f'heyzo-{code_part}')
        if not entity.ui_code: entity.ui_code = f'HEYZO-{code_part}'

        entity.title = entity.originaltitle = entity.sorttitle = entity.ui_code.upper()
        entity.label = "HEYZO"

        entity.original['tagline'] = tmp.get('title', '')
        entity.tagline = cls.trans(tmp.get('title', ''))
        entity.premiered = tmp.get('premiered')
        entity.year = tmp.get('year')
        
        # === 이미지 처리 섹션 ===
        poster_url = None
        
        landscape_url = tmp.get('json_landscape') or tmp.get('mobile_landscape')
        gallery_urls = tmp.get('gallery', [])

        use_smart = cls.config.get('use_smart_crop')

        # [1단계] 갤러리 순회 (세로 이미지 탐색)
        for curr_url in gallery_urls[:12]:
            try:
                res = cls.get_response(curr_url, stream=True, timeout=3, headers=mobile_headers)
                if not res or res.status_code != 200: continue
                
                img_bytes = BytesIO(res.content)
                with Image.open(img_bytes) as img:
                    w, h = img.size
                    if h > w:
                        poster_url = curr_url
                        logger.debug(f"[{cls.site_name}] Found portrait poster in gallery: {poster_url}")
                        break
            except Exception:
                continue

        # 포스터 최종 결정 (스마트 크롭 시도)
        if not poster_url and use_smart:
            logger.debug(f"[{cls.site_name}] No portrait poster found. Trying Smart Crop...")

            # [2단계] PL(Landscape) 스마트 크롭
            if landscape_url:
                try:
                    res_pl = cls.get_response(landscape_url, stream=True, timeout=5, headers=mobile_headers)
                    if res_pl and res_pl.status_code == 200:
                        img_pl = Image.open(BytesIO(res_pl.content))
                        
                        cropped = cls._smart_crop_image(img_pl)
                        if cropped:
                            temp_path = cls.save_pil_to_temp(cropped)
                            if temp_path:
                                poster_url = temp_path
                                logger.debug(f"[{cls.site_name}] PL(Landscape) Smart Cropped.")
                        else:
                            logger.debug(f"[{cls.site_name}] PL(Landscape) ignored (Smart Crop failed).")
                except Exception as e_pl:
                    logger.debug(f"[{cls.site_name}] Error checking PL image: {e_pl}")

            # [3단계] 갤러리 스마트 크롭 (PL 실패 시)
            if not poster_url:
                for curr_url in gallery_urls[:12]:
                    try:
                        res = cls.get_response(curr_url, stream=True, timeout=5, headers=mobile_headers)
                        if not res or res.status_code != 200: continue
                        
                        img = Image.open(BytesIO(res.content))
                        cropped = cls._smart_crop_image(img)
                        if cropped:
                            temp_path = cls.save_pil_to_temp(cropped)
                            if temp_path:
                                poster_url = temp_path
                                logger.debug(f"[{cls.site_name}] Gallery Smart Cropped: {curr_url}")
                                break
                    except Exception:
                        continue

        # [4단계] 최후의 수단
        if not poster_url:
            poster_url = tmp.get('json_poster') or tmp.get('mobile_poster') or landscape_url
            logger.debug(f"[{cls.site_name}] Fallback to original poster/PL.")

        image_mode = cls.MetadataSetting.get('jav_censored_image_mode')
        if image_mode == 'image_server':
            try:
                local_path = cls.MetadataSetting.get('jav_censored_image_server_local_path')
                server_url = cls.MetadataSetting.get('jav_censored_image_server_url')
                base_save_format = cls.MetadataSetting.get('jav_uncensored_image_server_save_format')
                base_path_part = base_save_format.format(label=entity.label)
                code_prefix_part = code_part[:2] 
                final_relative_folder_path = os.path.join(base_path_part.strip('/\\'), code_prefix_part)
                entity.image_server_target_folder = os.path.join(local_path, final_relative_folder_path)
                entity.image_server_url_prefix = f"{server_url.rstrip('/')}/{final_relative_folder_path.replace(os.path.sep, '/')}"
            except Exception as e:
                logger.error(f"[{cls.site_name}] Failed to set custom image server path: {e}")

        try:
            raw_image_urls = {
                'poster': poster_url,
                'pl': landscape_url,
                'arts': gallery_urls,
            }
            entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None)
        except Exception as e:
            logger.exception(f"[{cls.site_name}] Error during image processing delegation for {code}: {e}")

        for actor_name in tmp.get('actor', []):
            entity.actor.append(EntityActor(actor_name))

        entity.tag.append('HEYZO')

        genrelist = tmp.get('genre', [])
        if genrelist != []:
            if 'genre' not in entity.original: entity.original['genre'] = []
            for item in genrelist:
                entity.original['genre'].append(item)
                entity.genre.append(cls.get_translated_tag('uncen_tags', item))

        raw_plot = tmp.get('plot', '')
        if raw_plot:
            entity.original['plot'] = raw_plot
            entity.plot = cls.trans(raw_plot)
        else:
            entity.plot = ''

        entity.studio = 'HEYZO'
        entity.original['studio'] = 'HEYZO'

        # 부가영상 or 예고편
        if cls.config.get('use_extras'):
            try:
                video_url = cls.make_video_url(f'https://m.heyzo.com/contents/3000/{code_part}/sample.mp4')
                if video_url:
                    trailer_title = entity.tagline if entity.tagline else entity.title
                    entity.extras.append(EntityExtra('trailer', trailer_title, 'mp4', video_url))
            except Exception as e:
                logger.error(f"[{cls.site_name}] Trailer processing error: {e}")

        return entity
