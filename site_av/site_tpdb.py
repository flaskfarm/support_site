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

class ActorDict(dict):
    def __getattr__(self, key):
        return self.get(key)

    def __setattr__(self, key, value):
        self[key] = value

    def as_dict(self):
        return self

class SiteTpdb(SiteAvBase):
    site_name = 'tpdb'
    site_char = 'P'
    module_char = 'W'
    default_headers = SiteAvBase.base_default_headers.copy()

    site_base_url = 'https://api.theporndb.net'

    @classmethod
    def get_performer_by_id(cls, performer_id):
        if not performer_id:
            return None
        clean_id = str(performer_id).replace('PP', '').replace('PT', '').strip()
        data = cls._call_api(f"/performers/{clean_id}")
        if data and isinstance(data, dict) and 'data' in data:
            return data['data']
        return None

    @classmethod
    def get_actor_info(cls, entity_actor):
        actor_name = entity_actor.get('name_org') or ''
        actor_idx = entity_actor.get('actor_idx') or ''
        if not actor_name and not actor_idx:
            return False

        p_data = None
        if actor_idx:
            p_data = cls.get_performer_by_id(actor_idx)
        
        if not p_data and actor_name:
            encoded_name = urllib.parse.quote(actor_name)
            res = cls._call_api(f"/performers?q={encoded_name}")
            if res and isinstance(res, dict) and res.get('data'):
                performers = res['data'] if isinstance(res['data'], list) else [res['data']]
                if performers:
                    p_data = cls.get_performer_by_id(performers[0].get('id')) or performers[0]

        if p_data:
            p_id = str(p_data.get('id') or '')
            entity_actor['name_ko'] = p_data.get('name_ko') or ''
            entity_actor['name_org'] = actor_name or ''
            entity_actor['actor_idx'] = f"PP{p_id}" if (p_id and not p_id.startswith('PP')) else p_id
            entity_actor['thumb'] = p_data.get('image') or p_data.get('face') or ''
            entity_actor['site'] = 'tpdb'
            return True
        return False

    @classmethod
    def set_config(cls, db):
        # 1. Base 클래스의 공통 설정(이미지 임계값, 캐시, 스마트크롭 Threshold 등)을 먼저 로드
        super().set_config(db)
        
        # 2. Western 모듈의 설정으로 덮어씀
        prefix = 'western'
        cls.config.update({
            "tpdb_api_token": db.get(f"{prefix}_{cls.site_name}_api_token"),
            "trans_option": db.get(f"{prefix}_trans_option"),
            "trans_title": db.get_bool(f"{prefix}_trans_title") if db.get(f"{prefix}_trans_title") is not None else True,
            "include_male": db.get_bool(f"{prefix}_include_male"),
            "use_extras": db.get_bool(f"{prefix}_use_extras"),
            "title_format": db.get(f"{prefix}_title_format"),
            "use_movie_title_format": db.get_bool(f"{prefix}_use_movie_title_format"),
            "movie_title_format": db.get(f"{prefix}_movie_title_format"),

            "image_mode": db.get(f"{prefix}_image_mode"),
            "image_server_local_path": db.get(f"{prefix}_image_server_local_path"),
            "image_server_url": db.get(f"{prefix}_image_server_url"),
            "image_server_rewrite": db.get_bool(f"{prefix}_image_server_rewrite"),
            "western_image_format": db.get(f"{prefix}_image_server_save_format") or "/western/{studio}",   

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
    def _calculate_western_score(cls, keyword, item_data, rank, local_duration=None):
        if not isinstance(item_data, dict): return 0.0

        word_pattern = r'[^a-z0-9\s]'
        kw_clean = re.sub(r'\s+', ' ', re.sub(word_pattern, '', str(keyword or '').lower())).strip()
        raw_title = str(item_data.get('title') or '').lower()
        title_clean = re.sub(r'\s+', ' ', re.sub(word_pattern, '', raw_title)).strip()

        kw_norm = kw_clean.replace(' ', '')
        title_norm = title_clean.replace(' ', '')

        # 1. 랭크 기본점 (1위 30점, 2위 18점, 3위 17점, 4위 16점, 5위~ 15점)
        score = 30.0 if rank == 0 else max(15.0, 19.0 - float(rank))

        # 2. 영상 길이(Duration) 정밀 매칭 (최대 +30점 가산)
        duration_matched = False
        item_duration = item_data.get('duration') or item_data.get('seconds')
        if not item_duration and item_data.get('length'):
            parts = str(item_data['length']).split(':')
            if len(parts) == 2: item_duration = int(parts[0])*60 + int(parts[1])
            elif len(parts) == 3: item_duration = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])

        if local_duration and item_duration:
            try:
                item_sec = float(item_duration)
                diff_sec = abs(float(local_duration) - item_sec)
                if diff_sec <= 0.2:
                    score += 30.0
                    duration_matched = True
                elif diff_sec <= 1.0:
                    score += 25.0
                    duration_matched = True
                elif diff_sec <= 10.0:
                    score += max(2.0, 22.0 - (diff_sec * 2.0))
                    duration_matched = True
            except Exception:
                pass

        # 3. 스튜디오 매칭 (+25점, VR +2점)
        studio_node = item_data.get('site') or item_data.get('studio') or {}
        studio_name = str(studio_node.get('name') or '').lower()
        studio_matched = False
        if studio_name:
            studio_norm = re.sub(r'[^a-z0-9]', '', studio_name)
            if studio_norm:
                if studio_norm in kw_norm:
                    studio_matched = True
                    score += 25.0
                    if 'vr' in kw_norm and 'vr' in studio_norm: score += 2.0
                elif kw_norm.startswith(studio_norm[:6]):
                    studio_matched = True
                    score += 20.0

        # 4. 배우 매칭 (+20점)
        actor_matched = False
        performers = item_data.get('performers') or []
        if isinstance(performers, list):
            for p in performers:
                source_dict = p.get('parent') if p.get('parent') else p
                p_name = str(source_dict.get('name') or '').lower()
                p_norm = re.sub(r'[^a-z0-9]', '', p_name)
                if p_norm and p_norm in kw_norm:
                    actor_matched = True
                    score += 20.0
                    break

        # 5. 날짜 일치 검증 (+20점)
        item_date = str(item_data.get('date') or '').replace('-', ' ')
        date_matched = False
        date_match = re.search(r'\b(20\d{2}|\d{2})[ ._-](\d{2})[ ._-](\d{2})\b', kw_clean)
        kw_date_nums = set()
        if date_match:
            y, m, d = date_match.group(1), date_match.group(2), date_match.group(3)
            kw_date_nums = {y, m, d, y[-2:]}
            if m in item_date and d in item_date:
                date_matched = True
                score += 20.0

        # 품번/에피소드 숫자 (날짜 구성 숫자는 제외)
        kw_nums = set(re.findall(r'\b\d+\b', kw_clean)) - kw_date_nums
        title_nums = set(re.findall(r'\b\d+\b', title_clean))
        if kw_nums:
            num_matched = any(len(num) >= 2 and num in title_nums for num in kw_nums)
            if num_matched: score += 20.0
            elif not date_matched: score -= 15.0

        # 6. 제목 텍스트 일치도 (완전 포함 +25점 / 단어 비례 최대 +20점)
        if kw_norm and title_norm:
            if len(title_norm) >= 3 and (title_norm in kw_norm or kw_norm in title_norm):
                score += 25.0
            else:
                kw_words = set(re.findall(r'\b[a-z0-9]{3,}\b', kw_clean))
                title_words = set(re.findall(r'\b[a-z0-9]{3,}\b', title_clean))
                if kw_words and title_words:
                    intersect = kw_words.intersection(title_words)
                    score += (len(intersect) / len(title_words)) * 20.0

        # 7. 스튜디오 + 배우 + 날짜 3중 완전 일치 시 100점 확정
        if studio_matched and actor_matched and date_matched:
            score = 100.0

        # 8. 스튜디오 + 배우 + 영상길이 일치 시 100점 확정 (제목 없는 파일명 구출)
        if studio_matched and actor_matched and duration_matched:
            score = 100.0

        # 9. 이미지 부재 감점 (-10점)
        has_image = False
        posters = item_data.get('posters') or {}
        backgrounds = item_data.get('background') or {}
        if isinstance(posters, dict) and (posters.get('full') or posters.get('large')): has_image = True
        elif isinstance(backgrounds, dict) and (backgrounds.get('full') or backgrounds.get('large')): has_image = True
        elif item_data.get('poster') or item_data.get('image'): has_image = True
        if not has_image: score -= 10.0

        final_score = min(100.0, max(1.0, score))
        dur_log = f"DurMatch:{duration_matched}" if local_duration else "DurMatch:N/A"
        logger.debug(f"[{cls.site_name}] 채점 상세 -> Title:'{raw_title[:30]}' | Score:{final_score:.1f} (Rank:{rank}, Studio:{studio_matched}, Actor:{actor_matched}, Date:{date_matched}, {dur_log})")
        return final_score


    @classmethod
    def search(cls, keyword, manual=False, media_path=None, filename=None, **kwargs):
        target_video = media_path or filename
        if not target_video and os.path.isabs(keyword) and os.path.exists(keyword):
            target_video = keyword

        # 로컬 Meta DB 전용 B-Tree 지문 인덱스 0순위 확인
        if target_video and os.path.exists(target_video) and not manual:
            local_oshash = cls.calculate_oshash(target_video)
            if local_oshash:
                from ..setup import F
                meta_plugin = F.PluginManager.get_plugin_instance('metadata')
                if meta_plugin:
                    meta_db_mod = meta_plugin.get_module('meta_db')
                    if meta_db_mod:
                        local_db_items = meta_db_mod.search_by_fingerprint('WESTERN', 'OSHASH', local_oshash, preferred_site=cls.site_name)
                        if local_db_items:
                            hit_results = []
                            for idx, local_db_item in enumerate(local_db_items):
                                jd = local_db_item.get('json_data', {})
                                site_key = local_db_item.get('site') or cls.site_name
                                hit_item = EntityAVSearch(site_key)
                                hit_item.code = local_db_item.get('code')
                                hit_item.ui_code = jd.get('ui_code') or local_db_item.get('originaltitle') or hit_item.code
                                
                                title_prefix = "📁 [DB 지문일치]" if local_db_item.get('has_item') else "🌐 [지문일치-원격수집]"
                                hit_item.title = f"{title_prefix} {local_db_item.get('title')}"
                                hit_item.title_ko = hit_item.title
                                hit_item.year = int(jd.get('year') or 1900)
                                hit_item.image_url = local_db_item.get('poster_url') or ''
                                hit_item.desc = f"[지문 히트 #{idx+1}] {local_oshash} | 스튜디오: {jd.get('studio') or '정보없음'}"
                                hit_item.score = max(90, 100 - idx)

                                hit_dict = hit_item.as_dict()
                                hit_dict['site_key'] = site_key
                                hit_dict['is_db_cached'] = local_db_item.get('has_item', True)
                                hit_dict['is_priority_label_site'] = True
                                hit_results.append(hit_dict)

                            logger.info(f"[{cls.site_name}] 로컬 DB 지문 B-Tree 색인 히트 ({len(hit_results)}건 중 최우선 채택: {hit_results[0]['code']})")
                            return {'ret': 'success', 'data': hit_results}

        oshash = None
        if target_video and os.path.exists(target_video):
            oshash = cls.calculate_oshash(target_video)

        local_dur = cls.get_video_duration(target_video) if target_video and os.path.exists(target_video) else None
        encoded_keyword = urllib.parse.quote(keyword)
        
        hash_param = f"&hash={oshash}" if oshash else "&hash="
        scenes_data = cls._call_api(f"/scenes?parse={encoded_keyword}{hash_param}")
        movies_data = cls._call_api(f"/movies?parse={encoded_keyword}{hash_param}")
        
        scenes_list = scenes_data.get('data', []) if scenes_data else []
        movies_list = movies_data.get('data', []) if movies_data else []
        
        if isinstance(scenes_list, dict): scenes_list = [scenes_list]
        if isinstance(movies_list, dict): movies_list = [movies_list]

        # 텍스트+해시 결과가 없을 때 OSHash 단독 검색 시도
        if not scenes_list and not movies_list and oshash:
            logger.debug(f"[{cls.site_name}] 1차 검색 실패 ➔ OSHash 단독 역검색 시도: {oshash}")
            hash_scenes_data = cls._call_api(f"/scenes?hash={oshash}")
            if hash_scenes_data and hash_scenes_data.get('data'):
                h_data = hash_scenes_data['data']
                scenes_list = h_data if isinstance(h_data, list) else [h_data]

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

            include_male = cls.config.get("include_male", False)
            if content_type == 'scene':
                selected_actors = (females + males) if include_male else (females if females else males)
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

            calc_score = cls._calculate_western_score(keyword, item_data, tpdb_rank, local_duration=local_dur)
            item.score = max(0, min(100, int(round(calc_score))))
            ret.append(item.as_dict())

        ret.sort(key=lambda k: k.get("score", 0), reverse=True)

        # 단일 검색 결과 신뢰 옵션 (기본값: False)
        if len(ret) == 1 and cls.config.get("trust_single_result", False):
            ret[0]['score'] = 100
            logger.debug(f"[{cls.site_name}] 단일 검색 결과 신뢰 옵션 활성화 -> 100점 부여")

        logger.info(f"[{cls.site_name}] Search Success: {len(ret)} results found.")

        for i, item in enumerate(ret[:5]):
            logger.debug(f"  {i+1}. Score:{item.get('score'):>3} | Type:{item.get('content_type'):<5} | Title:{item.get('title')} | Code:{item.get('code')}")

        return {'ret': 'success', 'data': ret[:15]}

    @classmethod
    def info(cls, code, extra_opts=None, **kwargs):
        opts = dict(extra_opts or {})
        opts.update(kwargs)

        try:
            entity_obj = cls.__info(code, extra_opts=opts)
            if entity_obj:
                entity_result_val_final = entity_obj.as_dict()
                if hasattr(entity_obj, 'original') and entity_obj.original:
                    entity_result_val_final['original'] = entity_obj.original
                if hasattr(entity_obj, 'extra_info') and entity_obj.extra_info:
                    entity_result_val_final['extra_info'] = entity_obj.extra_info
                return {'ret': 'success', 'data': entity_result_val_final}
            return {'ret': 'error', 'data': f"Failed to get {cls.site_name} info for {code}"}
        except Exception as e:
            logger.exception(f"[{cls.site_name}] Info Exception: {e}")
            return {'ret': 'exception', 'data': str(e)}


    @classmethod
    def __info(cls, code, extra_opts=None, **kwargs):
        opts = dict(extra_opts or {})
        opts.update(kwargs)

        skip_trans = opts.get('skip_trans', False)
        media_path = opts.get('media_path', None)
        is_validating = opts.get('is_validating', False)
        is_rescued = opts.get('is_rescued', False)

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
        if not hasattr(entity, 'extra_info') or entity.extra_info is None:
            entity.extra_info = {}

        # TPDB 사이트 공식 해시 및 로컬 소장 파일 지문 수집
        site_fps = []
        raw_hashes = item_data.get('hashes') or item_data.get('hash') or []
        if isinstance(raw_hashes, str):
            raw_hashes = [{'algorithm': 'OSHASH', 'hash': raw_hashes}]
        elif isinstance(raw_hashes, list):
            formatted_hashes = []
            for h_item in raw_hashes:
                if isinstance(h_item, dict) and h_item.get('hash'):
                    formatted_hashes.append({
                        'algorithm': str(h_item.get('type') or h_item.get('algorithm') or 'OSHASH').upper(),
                        'hash': str(h_item['hash']).lower(),
                        'source': 'site'
                    })
                elif isinstance(h_item, str) and h_item.strip():
                    formatted_hashes.append({'algorithm': 'OSHASH', 'hash': h_item.strip().lower(), 'source': 'site'})
            raw_hashes = formatted_hashes

        site_fps.extend([h for h in raw_hashes if isinstance(h, dict)])

        user_fps = []
        if media_path and os.path.exists(media_path):
            # info 단계에서는 캐시된 지문을 재활용하고 무거운 pHash 신규 계산 방지
            local_fps = cls.get_video_fingerprints(
                media_path,
                fp_type=cls.config.get("fingerprint_type") or "OSHASH",
                ffmpeg_path=cls.config.get("ffmpeg_path") or "ffmpeg",
                force_phash=False
            )
            for l_fp in local_fps:
                h_val = l_fp.get('hash', '').lower()
                algo_val = l_fp.get('algorithm', 'OSHASH').upper()
                user_fps.append({
                    'algorithm': algo_val,
                    'hash': h_val,
                    'source': 'user'
                })

        entity.original['fingerprints'] = site_fps
        all_fps = list(site_fps)
        for uf in user_fps:
            if not any(f.get('hash') == uf['hash'] and f.get('algorithm') == uf['algorithm'] for f in all_fps):
                all_fps.append(uf)

        if all_fps:
            entity.extra_info['fingerprints'] = all_fps

        entity.ui_code = f"{cls.module_char}{cls.site_char}{type_char}_{item_id}"
        raw_title = str(item_data.get('title', entity.ui_code)).strip()
        entity.title = entity.originaltitle = entity.sorttitle = raw_title
        
        entity.extra_info['info_url'] = f"https://theporndb.net/{'scenes' if content_type == 'scene' else 'movies'}/{item_id}"

        cleaned_tagline = cls.A_P(raw_title)
        entity.original['tagline'] = cleaned_tagline
        
        if skip_trans or not cls.config.get('trans_title', True):
            entity.tagline = cleaned_tagline
        else:
            entity.tagline = cls.trans_by_llm(cleaned_tagline)
        
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
            cleaned_plot = cls.A_P(str(plot_text))
            entity.original['plot'] = cleaned_plot
            if skip_trans:
                entity.plot = cleaned_plot
            else:
                entity.plot = cls.trans_by_llm(entity.original['plot'])

        females, males = [], []
        for performer in item_data.get('performers', []):
            source_dict = performer.get('parent') if performer.get('parent') else performer
            actor_name = str(source_dict.get('name') or '').strip()
            actor_id = str(source_dict.get('id') or '').strip()
            if not actor_name: continue

            p_detail = cls.get_performer_by_id(actor_id) if actor_id else None
            p_target = p_detail if p_detail else source_dict

            act_extras = p_target.get('extras') or p_target.get('extra') or {}
            gender = str(act_extras.get('gender') or '').lower()

            all_tpdb_photos = []
            for pst in (p_target.get('posters') or []):
                if isinstance(pst, dict) and pst.get('url'):
                    all_tpdb_photos.append(pst['url'])

            primary_img = p_target.get('image') or p_target.get('face') or source_dict.get('face') or ''
            if primary_img and primary_img not in all_tpdb_photos:
                all_tpdb_photos.insert(0, primary_img)

            formatted_idx = f"PP{actor_id}" if (actor_id and not (actor_id.startswith('PP') or actor_id.startswith('PT'))) else (f"PP{actor_id[2:]}" if actor_id.startswith('PT') else actor_id)

            actor_entry = ActorDict({
                'name_org': actor_name,
                'name_ko': '',
                'name_en': actor_name,
                'actor_idx': formatted_idx,
                'thumb': primary_img,
                'role': '출연',
                'gender': gender,
                'extra_info': {
                    'gender': gender,
                    'birth': str(act_extras.get('birthday') or '').strip(),
                    'height': act_extras.get('height'),
                    'body_size': str(act_extras.get('measurements') or '').strip(),
                    'bra_size': str(act_extras.get('cupsize') or '').strip(),
                    'debut': str(act_extras.get('career_start_year') or '').strip(),
                    'country': str(act_extras.get('birthplace_code') or act_extras.get('nationality') or '').strip(),
                    'info_url': f"https://theporndb.net/performers/{actor_id}" if actor_id else '',
                    'site_img_url': primary_img,
                    'site_img_urls': all_tpdb_photos,
                    'aliases': p_target.get('aliases') or []
                }
            })

            if gender == 'female':
                females.append(actor_entry)
            else:
                males.append(actor_entry)

        entity.actor.extend(females + males)

        # Tags & Genres
        if 'genre' not in entity.original: entity.original['genre'] = []
        for tag in item_data.get('tags', []):
            tag_name = tag.get('name')
            if tag_name:
                tag_str = str(tag_name).strip()
                entity.original['genre'].append(tag_str)
                trans_genre = cls.get_translated_tag(tag_str)
                if trans_genre not in entity.genre:
                    entity.genre.append(trans_genre)

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
            landscape_cover_url = item_data.get('background', {}).get('full') or item_data.get('background', {}).get('large')
            portrait_poster_url = item_data.get('posters', {}).get('full') or item_data.get('posters', {}).get('large')

            entity.original['thumb'] = {
                'poster': portrait_poster_url or '',
                'landscape': landscape_cover_url or ''
            }

            poster_url = None
            if is_force_poster and portrait_poster_url:
                poster_url = portrait_poster_url
            elif portrait_poster_url:
                poster_url = portrait_poster_url
            elif use_smart_crop and landscape_cover_url:
                try:
                    res_pl = cls.get_response(landscape_cover_url, timeout=10)
                    if res_pl and res_pl.status_code == 200:
                        img_pl = Image.open(BytesIO(res_pl.content))
                        cropped = cls._smart_crop_image(img_pl)
                        if cropped:
                            temp_path = cls.save_pil_to_temp(cropped)
                            if temp_path:
                                poster_url = temp_path
                                logger.debug(f"[{cls.site_name}] 스마트 크롭 성공 -> 임시 세로 포스터 생성: {temp_path}")
                            cropped.close()
                        img_pl.close()
                except Exception as e_crop:
                    logger.error(f"[{cls.site_name}] 스마트 크롭 시도 중 오류: {e_crop}")

            # 세로 포스터가 없고 크롭이 실패/미적용된 경우 가로 커버를 포스터로 폴백 지정
            if not poster_url and landscape_cover_url:
                poster_url = landscape_cover_url
                logger.debug(f"[{cls.site_name}] 세로 포스터 부재/크롭 실패 -> 가로 커버를 포스터로 폴백 지정")

            raw_image_urls['poster'] = poster_url
            raw_image_urls['pl'] = landscape_cover_url

        elif content_type == 'movie':
            raw_image_urls['poster'] = item_data.get('posters', {}).get('full') or item_data.get('posters', {}).get('large')
            
            front_cover = item_data.get('background', {}).get('full') or item_data.get('background', {}).get('large')
            back_cover = item_data.get('background_back', {}).get('full') or item_data.get('background_back', {}).get('large')

            entity.original['thumb'] = {
                'poster': raw_image_urls['poster'] or '',
                'landscape': front_cover or ''
            }

            if front_cover and back_cover:
                merged_landscape_path = cls._merge_covers(back_cover, front_cover)
            
            if merged_landscape_path:
                raw_image_urls['pl'] = None 
            else:
                raw_image_urls['pl'] = front_cover

        # 고유 코드(WPS_ID / WPM_ID) 기반으로 이미지 저장
        entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None, extra_opts=opts)

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
                if not hasattr(entity, 'original') or entity.original is None:
                    entity.original = {}
                entity.original['extras'] = [{
                    'content_url': trailer_url,
                    'content_type': 'trailer'
                }]

                if cls.config.get('use_trailer_proxy', False):
                    final_url = cls.make_video_url(trailer_url)
                    if final_url:
                        logger.debug(f"[{cls.site_name}] Added Proxied Trailer URL: {final_url}")
                        entity.extras.append(EntityExtra("trailer", entity.tagline or entity.title, "mp4", final_url))
                else:
                    logger.debug(f"[{cls.site_name}] Added Direct Trailer URL: {trailer_url}")
                    entity.extras.append(EntityExtra("trailer", entity.tagline or entity.title, "mp4", trailer_url))
            except Exception as e_trailer:
                logger.error(f"[{cls.site_name}] Error adding trailer: {e_trailer}")

        used_model = getattr(cls, '_last_used_llm_model', None)
        if used_model:
            entity.extra_info['ai_translator'] = f"Ollama ({used_model})"
            cls._last_used_llm_model = None
        else:
            entity.extra_info['ai_translator'] = "Default (FF)"

        return entity
