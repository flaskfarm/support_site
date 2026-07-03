# -*- coding: utf-8 -*-
import re
import urllib.parse
import os
import time
import shutil
import difflib
from io import BytesIO
from PIL import Image

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityExtra, EntityThumb
from ..setup import P, logger, F, path_data
from .site_av_base import SiteAvBase

class SiteTpdb(SiteAvBase):
    site_name = 'tpdb'
    site_char = 'P'
    module_char = 'W'

    site_base_url = 'https://api.theporndb.net'
    
    @classmethod
    def set_config(cls, db):
        # 1. Base 클래스의 공통 설정(이미지 임계값, 캐시, 스마트크롭 Threshold 등)을 먼저 로드합니다.
        # 이 부분이 없으면 스마트크롭 시 NoneType 에러가 발생합니다.
        super().set_config(db)
        
        # 2. Western 모듈의 설정으로 덮어씁니다.
        prefix = 'western'
        cls.config.update({
            "tpdb_api_token": db.get(f"{prefix}_{cls.site_name}_api_token"),
            "trans_option": db.get(f"{prefix}_trans_option"),
            "use_extras": db.get_bool(f"{prefix}_use_extras"),

            "title_format": db.get(f"{prefix}_title_format"),
            "use_movie_title_format": db.get_bool(f"{prefix}_use_movie_title_format"),
            "movie_title_format": db.get(f"{prefix}_movie_title_format"),

            "image_mode": db.get(f"{prefix}_image_mode"),
            "image_server_local_path": db.get(f"{prefix}_image_server_local_path"),
            "image_server_url": db.get(f"{prefix}_image_server_url"),
            "image_server_rewrite": db.get_bool(f"{prefix}_image_server_rewrite"),
            "uncensored_image_format": db.get(f"{prefix}_image_server_save_format"),
            "censored_image_format": db.get(f"{prefix}_image_server_save_format"),   

            # Western 전용 Smart Crop 토글 (모델 경로 등은 super().set_config에서 이미 로드됨)
            "use_smart_crop": db.get_bool("western_use_smart_crop"),
            "poster_force_studios": db.get(f"{prefix}_poster_force_studios"),
            
            "use_proxy": db.get_bool(f"{prefix}_use_proxy"),
            "proxy_url": db.get(f"{prefix}_proxy_url"),
            "use_trailer_proxy": db.get_bool(f"{prefix}_use_trailer_proxy"),
        })

        force_studios_raw = cls.config.get("poster_force_studios", "")
        force_studios_list = [x.strip().lower() for x in re.split(r'[\n,]', force_studios_raw) if x.strip()]
        cls.config["poster_force_studios_set"] = set(force_studios_list)

    @classmethod
    def _call_api(cls, endpoint):
        token = cls.config.get("tpdb_api_token")
        if not token:
            logger.warning(f"[{cls.site_name}] TPDB API Token is not set.")
            return None

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ThePornDBScenes.bundle", 
            "Accept-Encoding": "gzip"
        }
        
        full_url = f"{cls.site_base_url}{endpoint}"
        logger.debug(f"[{cls.site_name}] Requesting API: {full_url}")
        
        try:
            res = cls.get_response(full_url, headers=headers, verify=False, timeout=30)
            
            if res and res.status_code == 200:
                try:
                    return res.json()
                except Exception as e_json:
                    logger.error(f"[{cls.site_name}] JSON parse error: {e_json}. Text: {res.text[:200]}")
                    return None
            else:
                logger.error(f"[{cls.site_name}] API Error: Status {res.status_code if res else 'None'} for URL {full_url}")
                return None
        except Exception as e:
            logger.error(f"[{cls.site_name}] API Request Exception: {e}")
            return None

    @classmethod
    def _format_studio_name(cls, name):
        if not name: return 'Unknown'
        words = name.split()
        
        formatted_words = []
        for word in words:
            if not word: continue
            first_char = word[0].upper() if word[0].islower() else word[0]
            rest_chars = word[1:]
            formatted_words.append(first_char + rest_chars)
            
        return "".join(formatted_words)

    @classmethod
    def _make_safe_filename(cls, text):
        if not text: return "Unknown"
        text = re.sub(r'[\[\]\(\)]', '', text)
        text = re.sub(r'[^\w\s가-힣-]', '', text)
        return re.sub(r'\s+', '_', text.strip())

    @classmethod
    def _merge_covers(cls, back_url, front_url):
        try:
            res_back = cls.get_response(back_url, verify=False, timeout=20)
            res_front = cls.get_response(front_url, verify=False, timeout=20)

            if not res_back or res_back.status_code != 200 or not res_front or res_front.status_code != 200:
                logger.warning(f"[{cls.site_name}] Failed to download covers for merging.")
                return None

            img_back = Image.open(BytesIO(res_back.content)).convert('RGB')
            img_front = Image.open(BytesIO(res_front.content)).convert('RGB')

            target_height = img_front.height
            if img_back.height != target_height:
                ratio = target_height / float(img_back.height)
                new_width = int(img_back.width * ratio)
                img_back = img_back.resize((new_width, target_height), Image.Resampling.LANCZOS)

            total_width = img_back.width + img_front.width
            merged_img = Image.new('RGB', (total_width, target_height))
            
            merged_img.paste(img_back, (0, 0))
            merged_img.paste(img_front, (img_back.width, 0))

            temp_filepath = cls.save_pil_to_temp(merged_img)
            
            img_back.close()
            img_front.close()
            merged_img.close()
            
            logger.debug(f"[{cls.site_name}] Successfully merged front and back covers: {temp_filepath}")
            return temp_filepath

        except Exception as e:
            logger.error(f"[{cls.site_name}] Error merging covers: {e}")
            return None

    @classmethod
    def _calculate_western_score(cls, keyword, item_data, tpdb_rank):
        # 1. 공백 및 모든 특수문자 제거
        word_pattern = r'[^a-z0-9\s]'
        kw_clean = re.sub(r'\s+', ' ', re.sub(word_pattern, '', keyword.lower())).strip()
        raw_title = str(item_data.get('title', '')).lower()
        title_clean = re.sub(r'\s+', ' ', re.sub(word_pattern, '', raw_title)).strip()

        # 2. SequenceMatcher를 위한 공백 없는 순수 텍스트
        kw_norm = kw_clean.replace(' ', '')
        title_norm = title_clean.replace(' ', '')

        similarity = difflib.SequenceMatcher(None, kw_norm, title_norm).ratio() if kw_norm and title_norm else 0.0
        score = similarity * 100.0

        # 3. 시리즈 숫자(Number) 불일치 페널티 (-5점)
        kw_nums = set(re.findall(r'\b\d+\b', kw_clean))
        title_nums = set(re.findall(r'\b\d+\b', title_clean))
        if kw_nums != title_nums:
            score -= 5.0

        # 4. 스튜디오 매칭 보너스 (+5점)
        studio = str(item_data.get('site', {}).get('name', '')).lower()
        if not studio:
            studio = str(item_data.get('studio', {}).get('name', '')).lower()
        if studio:
            studio_norm = re.sub(r'[^a-z0-9]', '', studio)
            if studio_norm and studio_norm in kw_norm:
                score += 5.0

        # 5. 배우 매칭 보너스 (+5점)
        performers = item_data.get('performers', [])
        actor_matched = False
        for p in performers:
            actor_name = str(p.get('parent', p).get('name', '')).lower() if p.get('parent') else str(p.get('name', '')).lower()
            if actor_name:
                actor_norm = re.sub(r'[^a-z0-9]', '', actor_name)
                if actor_norm and actor_norm in kw_norm:
                    actor_matched = True
                    break
        if actor_matched:
            score += 5.0

        # 6. 포함 보너스 (+40점)
        # 검색어 안에 [스튜디오]나 배우 이름이 포함되어 있어서 SequenceMatcher 비율은 낮게 나왔지만,
        # 사실 영화 제목 텍스트 자체가 검색어 안에 완벽하게 들어있는 경우 점수 폭등
        if kw_norm and title_norm and (title_norm in kw_norm):
            score += 40.0

        # 7. 양질의 데이터 검증 페널티 (-10점, -5점)
        has_image = False
        if isinstance(item_data.get('posters'), dict) and (item_data['posters'].get('full') or item_data['posters'].get('large')):
            has_image = True
        elif isinstance(item_data.get('background'), dict) and (item_data['background'].get('full') or item_data['background'].get('large')):
            has_image = True
        elif item_data.get('poster') or item_data.get('image'):
            has_image = True
            
        if not has_image: score -= 10.0
        
        plot_text = str(item_data.get('description', '')).strip()
        if not plot_text: score -= 5.0

        # 8. TPDB 랭크 기본 페널티
        score -= (tpdb_rank * 1.0)

        return score

    @classmethod
    def search(cls, keyword, manual=False):
        encoded_keyword = urllib.parse.quote(keyword)
        
        scenes_data = cls._call_api(f"/scenes?parse={encoded_keyword}&hash=")
        movies_data = cls._call_api(f"/movies?parse={encoded_keyword}&hash=")
        
        scenes_list = scenes_data.get('data', []) if scenes_data else []
        movies_list = movies_data.get('data', []) if movies_data else []
        
        if isinstance(scenes_list, dict): scenes_list = [scenes_list]
        if isinstance(movies_list, dict): movies_list = [movies_list]

        combined_results = []
        for idx, item in enumerate(scenes_list):
            combined_results.append({'type': 'scene', 'data': item, 'tpdb_rank': idx})
        for idx, item in enumerate(movies_list):
            combined_results.append({'type': 'movie', 'data': item, 'tpdb_rank': idx})

        if not combined_results:
            logger.info(f"[{cls.site_name}] Search END - No results found for: {keyword}")
            return {'ret': 'no_match', 'data': []}

        ret = []
        for wrapper in combined_results:
            content_type = wrapper['type']
            item_data = wrapper['data']
            tpdb_rank = wrapper['tpdb_rank']
            
            item = EntityAVSearch(cls.site_name)
            item_id = str(item_data.get('id', ''))
            if not item_id: continue
            
            type_char = 'S' if content_type == 'scene' else 'M'
            item.code = f"{cls.module_char}{cls.site_char}{type_char}_{item_id}"
            item.ui_code = item.code
            item.content_type = content_type
            
            site_node = item_data.get('site', {})
            raw_site = str(site_node.get('name', '')).strip()
            final_studio = cls._format_studio_name(raw_site)
            
            raw_title = item_data.get('title', '')

            females, males = [], []
            for performer in item_data.get('performers', []):
                source_dict = performer.get('parent') if performer.get('parent') else performer
                actor_name = str(source_dict.get('name', '')).strip()
                
                gender = ""
                if source_dict.get('extras') and source_dict['extras'].get('gender'):
                    gender = str(source_dict['extras']['gender']).lower()
                elif source_dict.get('extra') and source_dict['extra'].get('gender'):
                    gender = str(source_dict['extra']['gender']).lower()

                if actor_name:
                    if gender == 'female': females.append(actor_name)
                    else: males.append(actor_name)

            if content_type == 'scene':
                selected_actors = females if females else males
            else:
                selected_actors = females + males
            
            actor_str = ", ".join(selected_actors[:3]) if selected_actors else ""
            
            format_dict = {
                'originaltitle': raw_title,
                'plot': '',
                'title': raw_title,
                'studio': final_studio,
                'year': item_data.get('date', '')[:4] if item_data.get('date') else '',
                'actor': actor_str,
                'tagline': ''
            }

            use_movie_format = cls.config.get("use_movie_title_format", True)
            if content_type == 'movie' and use_movie_format:
                fmt = cls.config.get("movie_title_format") or "[{studio}] {title}"
            else:
                fmt = cls.config.get("title_format") or "[{studio}] {actor} - {title}"

            try:
                item.title = fmt.format(**format_dict)
            except Exception:
                item.title = f"[{final_studio}] {raw_title}"

            item.title_ko = item_data.get('description', '')
            
            if item_data.get('date'):
                item.year = int(item_data['date'][:4])
                item.desc = f"Type: {content_type.capitalize()} / Date: {item_data['date']} / Studio: {final_studio}"
            else:
                item.year = 1900

            img_url = ''
            posters = item_data.get('posters', {})
            backgrounds = item_data.get('background', {})
            
            if content_type == 'scene':
                if isinstance(backgrounds, dict) and (backgrounds.get('full') or backgrounds.get('large')):
                    img_url = backgrounds.get('full') or backgrounds.get('large')
                elif isinstance(posters, dict) and (posters.get('full') or posters.get('large')):
                    img_url = posters.get('full') or posters.get('large')
                elif item_data.get('image'):
                    img_url = str(item_data.get('image'))
            else:
                if isinstance(posters, dict) and (posters.get('full') or posters.get('large')):
                    img_url = posters.get('full') or posters.get('large')
                elif isinstance(backgrounds, dict) and (backgrounds.get('full') or backgrounds.get('large')):
                    img_url = backgrounds.get('full') or backgrounds.get('large')
                elif item_data.get('image'):
                    img_url = str(item_data.get('image'))

            if not img_url and item_data.get('poster'):
                img_url = str(item_data.get('poster'))

            item.image_url = img_url or ''

            if manual and item.image_url and item.image_url.startswith('http'):
                try:
                    safe_url = urllib.parse.quote(item.image_url, safe=':/&?%=')
                    item.image_url = cls.make_image_url(safe_url)
                except Exception as e_proxy:
                    logger.error(f"[{cls.site_name}] Proxy conversion error for {item.image_url}: {e_proxy}")

            item.score = cls._calculate_western_score(keyword, item_data, tpdb_rank)
            ret.append(item.as_dict())

        ret.sort(key=lambda k: k.get("score", 0), reverse=True)

        if ret:
            top_score = ret[0]["score"]
            offset = top_score - 100.0 if top_score > 100.0 else 0.0
            
            for item in ret:
                item["score"] = int(round(item["score"] - offset))
                
            for i in range(1, len(ret)):
                if ret[i]["score"] >= ret[i-1]["score"]:
                    ret[i]["score"] = max(0, ret[i-1]["score"] - 1)
                    
            for item in ret:
                item["score"] = max(0, min(100, item["score"]))

        # 단일 검색 결과 신뢰 옵션 (100점 바이패스)
        if len(ret) == 1 and cls.config.get("trust_single_result", True):
            ret[0]['score'] = 100
            logger.debug(f"[{cls.site_name}] Only one result found. Bypassing score check to 100.")

        logger.info(f"[{cls.site_name}] Search Success: {len(ret)} results found.")
        
        for i, item in enumerate(ret[:5]):
            logger.debug(f"  {i+1}. Score:{item.get('score'):>3} | Type:{item.get('content_type'):<5} | Title:{item.get('title')} | Code:{item.get('code')}")

        return {'ret': 'success', 'data': ret[:15]}

    @classmethod
    def info(cls, code, fp_meta_mode=False):
        try:
            entity = cls.__info(code, fp_meta_mode)
            return {'ret': 'success', 'data': entity.as_dict()} if entity else {'ret': 'error'}
        except Exception as e:
            logger.exception(f"[{cls.site_name}] Info Exception: {e}")
            return {'ret': 'exception', 'data': str(e)}

    @classmethod
    def __info(cls, code, fp_meta_mode=False):
        if len(code) < 5 or code[3] != '_':
            logger.error(f"[{cls.site_name}] Invalid code format: {code}")
            return None
            
        type_char = code[2]
        item_id = code[4:]
        content_type = 'scene' if type_char == 'S' else 'movie'
        
        endpoint = f"/scenes/{item_id}" if content_type == 'scene' else f"/movies/{item_id}"
        data = cls._call_api(endpoint)
        
        if not data or 'data' not in data:
            return None
            
        item_data = data['data']
        entity = EntityMovie(cls.site_name, code)
        entity.content_type = content_type
        
        entity.country = ['미국']
        entity.mpaa = '청소년 관람불가'
        if entity.thumb is None: entity.thumb = []
        if entity.fanart is None: entity.fanart = []
        if entity.extras is None: entity.extras = []
        if entity.tag is None: entity.tag = []
        if entity.genre is None: entity.genre = []
        if entity.actor is None: entity.actor = []
        entity.director = ""
        entity.original = {}

        entity.ui_code = f"{cls.module_char}{cls.site_char}{type_char}_{item_id}"
        entity.title = entity.originaltitle = entity.sorttitle = str(item_data.get('title', entity.ui_code))
        entity.original['tagline'] = entity.originaltitle
        entity.tagline = entity.originaltitle
        
        if item_data.get('date'):
            entity.premiered = str(item_data['date'])
            try: entity.year = int(entity.premiered[:4])
            except: pass

        # Studio & Network 파싱
        site_node = item_data.get('site', {})
        network_node = item_data.get('network', {})

        raw_site = str(site_node.get('name', '')).strip()
        raw_network = str(network_node.get('name', '')).strip()

        final_studio = cls._format_studio_name(raw_site)
        final_network = cls._format_studio_name(raw_network)

        entity.studio = final_studio if final_studio != 'Unknown' else final_network
        entity.original['studio'] = entity.studio
        entity.original['network'] = final_network

        if content_type == 'movie' and item_data.get('directors'):
            directors = item_data['directors']
            if directors and isinstance(directors, list):
                entity.director = str(directors[0].get('name', ''))

        plot_text = item_data.get('description', '')
        if plot_text:
            entity.original['plot'] = cls.A_P(str(plot_text))
            entity.plot = cls.trans_by_llm(entity.original['plot'])

        # 배우 필터링
        females, males = [], []
        for performer in item_data.get('performers', []):
            actor_name, gender, act_img = "", "", ""
            source_dict = performer.get('parent') if performer.get('parent') else performer
            
            if source_dict.get('name'): actor_name = str(source_dict['name'])
            if source_dict.get('face'): act_img = str(source_dict['face'])
            if source_dict.get('extras') and source_dict['extras'].get('gender'):
                gender = str(source_dict['extras']['gender']).lower()
            elif source_dict.get('extra') and source_dict['extra'].get('gender'):
                gender = str(source_dict['extra']['gender']).lower()

            if actor_name:
                act = EntityActor(actor_name)
                act.name = str(actor_name)
                act.originalname = str(actor_name)
                if act_img: act.thumb = act_img
                
                if gender == 'female': females.append(act)
                else: males.append(act)

        if content_type == 'scene':
            selected_actors = females if females else males
        else:
            selected_actors = females + males
        entity.actor.extend(selected_actors)

        if 'genre' not in entity.original: entity.original['genre'] = []
        for tag in item_data.get('tags', []):
            tag_name = tag.get('name')
            if tag_name:
                tag_str = str(tag_name)
                entity.original['genre'].append(tag_str)
                entity.genre.append(tag_str)

        # =========================================================
        # 이미지 소스 추출 및 병합 로직
        # =========================================================
        raw_image_urls = {'poster': None, 'pl': None, 'arts': []}
        use_smart_crop = cls.config.get('use_smart_crop', False)
        force_studios = cls.config.get('poster_force_studios_set', set())
        merged_landscape_path = None

        current_studio_norm = entity.studio.lower() if entity.studio else ""
        is_force_poster = current_studio_norm in force_studios

        if content_type == 'scene':
            front_cover = item_data.get('background', {}).get('full') or item_data.get('background', {}).get('large')
            original_poster = item_data.get('posters', {}).get('full') or item_data.get('posters', {}).get('large')
            
            if is_force_poster and original_poster:
                logger.debug(f"[{cls.site_name}] Studio '{entity.studio}' is in Poster Force list. Bypassing Smart Crop.")
                raw_image_urls['poster'] = original_poster
            elif use_smart_crop and front_cover:
                logger.debug(f"[{cls.site_name}] Scene & Smart Crop is ON. Routing Background to Poster for AI Cropping.")
                raw_image_urls['poster'] = front_cover
            else:
                raw_image_urls['poster'] = original_poster
            
            raw_image_urls['pl'] = front_cover

        elif content_type == 'movie':
            raw_image_urls['poster'] = item_data.get('posters', {}).get('full') or item_data.get('posters', {}).get('large')
            
            front_cover = item_data.get('background', {}).get('full') or item_data.get('background', {}).get('large')
            back_cover = item_data.get('background_back', {}).get('full') or item_data.get('background_back', {}).get('large')

            if front_cover and back_cover:
                merged_landscape_path = cls._merge_covers(back_cover, front_cover)
            
            if merged_landscape_path:
                raw_image_urls['pl'] = None 
            else:
                raw_image_urls['pl'] = front_cover

        # 이미지 서버 폴더 포맷팅 설정
        image_mode = cls.MetadataSetting.get('western_image_mode')
        if image_mode == 'image_server':
            try:
                safe_studio = re.sub(r'[^A-Za-z0-9]', '_', entity.studio) if entity.studio else 'Unknown'
                local_path = cls.MetadataSetting.get('western_image_server_local_path')
                server_url = cls.MetadataSetting.get('western_image_server_url')
                base_save_format = cls.MetadataSetting.get('western_image_server_save_format')
                
                format_map = {'studio': safe_studio, 'label': safe_studio, 'label_1': safe_studio[0]}
                final_relative_folder_path = base_save_format.format_map(format_map).strip('/\\')
                
                entity.image_server_target_folder = os.path.join(local_path, final_relative_folder_path)
                entity.image_server_url_prefix = f"{server_url.rstrip('/')}/{final_relative_folder_path.replace(os.path.sep, '/')}"

                combined_title = f"[{safe_studio}] {entity.originaltitle}"
                safe_filename = cls._make_safe_filename(combined_title)
                safe_filename += f"_{type_char}_{item_id}" 
                entity.ui_code = safe_filename 

            except Exception as e:
                logger.error(f"[{cls.site_name}] Failed to set custom image server path: {e}")

        # Base 클래스의 공통 이미지 처리
        entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None, is_validating=False, is_rescued=False)

        # 병합된 Landscape 이미지 로컬/서버 적용
        if merged_landscape_path:
            logger.debug(f"[{cls.site_name}] Applying merged landscape image...")
            if image_mode == 'image_server' and getattr(entity, 'image_server_target_folder', None):
                target_folder = entity.image_server_target_folder
                url_prefix = entity.image_server_url_prefix
                system_landscape_path = os.path.join(target_folder, f"{entity.ui_code.lower()}_pl.jpg")
                
                try:
                    os.makedirs(target_folder, exist_ok=True)
                    shutil.copy(merged_landscape_path, system_landscape_path)
                    entity.thumb.append(EntityThumb(aspect="landscape", value=f"{url_prefix}/{entity.ui_code.lower()}_pl.jpg"))
                except Exception as e_copy:
                    logger.error(f"[{cls.site_name}] Error copying merged image to server folder: {e_copy}")
            else:
                from urllib.parse import urlencode
                param = urlencode({'site': 'system', 'path': merged_landscape_path})
                url = f"{F.SystemModelSetting.get('ddns')}/metadata/normal/jav_image?{param}"
                entity.thumb.append(EntityThumb(aspect="landscape", value=url))

        # 원래 UI Code 복구
        entity.ui_code = f"{cls.module_char}{cls.site_char}{type_char}_{item_id}"

        # 트레일러 프록시 적용
        if cls.config.get('use_extras', False) and item_data.get('trailer'):
            trailer_url = item_data['trailer']
            try:
                if cls.config.get('use_trailer_proxy', False):
                    final_url = cls.make_video_url(trailer_url)
                    if final_url:
                        logger.debug(f"[{cls.site_name}] Added Proxied Trailer URL: {final_url}")
                        entity.extras.append(EntityExtra("trailer", entity.title, "mp4", final_url))
                else:
                    logger.debug(f"[{cls.site_name}] Added Direct Trailer URL: {trailer_url}")
                    entity.extras.append(EntityExtra("trailer", entity.title, "mp4", trailer_url))
            except Exception as e_trailer:
                logger.error(f"[{cls.site_name}] Error adding trailer: {e_trailer}")

        used_model = getattr(cls, '_last_used_llm_model', None)
        if used_model:
            entity.extra_info['ai_translator'] = f"Ollama ({used_model})"
            cls._last_used_llm_model = None
        else:
            entity.extra_info['ai_translator'] = "Default (FF)"

        return entity
