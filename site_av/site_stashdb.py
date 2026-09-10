# -*- coding: utf-8 -*-
import re
import urllib.parse
import os
import time
import shutil
import difflib
import json
import requests
import traceback
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

class SiteStashdb(SiteAvBase):
    site_name = 'stashdb'
    site_char = 'S'
    module_char = 'W'
    default_headers = SiteAvBase.base_default_headers.copy()

    site_base_url = 'https://stashdb.org/graphql'

    @classmethod
    def get_performer_by_id(cls, performer_id):
        if not performer_id:
            return None
        clean_id = str(performer_id).replace('PS', '').strip()
        query = """
        query FindPerformer($id: ID!) {
          findPerformer(id: $id) {
            id
            name
            disambiguation
            aliases
            gender
            birth_date
            career_start_year
            height
            band_size
            cup_size
            waist_size
            hip_size
            breast_type
            country
            ethnicity
            hair_color
            eye_color
            images { url width height }
            urls { url }
          }
        }
        """
        res_data = cls._call_graphql_api(query, {"id": clean_id})
        return ((res_data or {}).get('data') or {}).get('findPerformer')

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
            query = """
            query SearchPerformers($term: String!) {
              searchPerformers(term: $term) {
                performers {
                  id
                  name
                  images { url }
                }
              }
            }
            """
            res = cls._call_graphql_api(query, {"term": actor_name})
            performers = ((res or {}).get('data') or {}).get('searchPerformers', {}).get('performers', [])
            if performers:
                p_data = cls.get_performer_by_id(performers[0].get('id')) or performers[0]

        if p_data:
            p_id = str(p_data.get('id') or '')
            images = p_data.get('images') or []
            act_img = images[0].get('url') if images and isinstance(images[0], dict) else ''

            entity_actor['name_ko'] = p_data.get('name_ko') or ''
            entity_actor['name_org'] = actor_name or ''
            entity_actor['actor_idx'] = f"PS{p_id}" if (p_id and not p_id.startswith('PS')) else p_id
            entity_actor['thumb'] = act_img
            entity_actor['site'] = 'stashdb'
            return True
        return False

    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        
        prefix = 'western'
        cls.config.update({
            "stashdb_api_key": db.get(f"{prefix}_{cls.site_name}_api_key") or db.get(f"{prefix}_{cls.site_name}_api_token"),
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
            "western_image_format": db.get(f"{prefix}_image_server_save_format") or "/western/{studio_1}/{studio}",

            "use_smart_crop": db.get_bool("western_use_smart_crop"),
            "stashdb_user_schema": db.get("western_stashdb_user_schema"),
            "poster_force_studios": db.get(f"{prefix}_poster_force_studios"),
            
            "use_fingerprint": db.get_bool("western_stashdb_use_fingerprint"),
            "fingerprint_type": db.get("western_stashdb_fingerprint_type") or "OSHASH",
            "ffmpeg_path": db.get("western_stashdb_ffmpeg_path") or "ffmpeg",

            "use_proxy": False,
            "proxy_url": "",
            "use_trailer_proxy": db.get_bool(f"{prefix}_use_trailer_proxy"),
        })

        force_studios_raw = cls.config.get("poster_force_studios", "")
        force_studios_list = [x.strip().lower() for x in re.split(r'[\n,]', force_studios_raw) if x and x.strip()]
        cls.config["poster_force_studios_set"] = set(force_studios_list)


    @classmethod
    def _call_graphql_api(cls, query, variables=None):
        api_key = cls.config.get("stashdb_api_key")
        if not api_key:
            logger.warning(f"[{cls.site_name}] StashDB API Key가 설정되지 않았습니다.")
            return None

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ApiKey": api_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        
        payload = {"query": query, "variables": variables or {}}

        try:
            post_data = json.dumps(payload).encode('utf-8')
            res = requests.post(cls.site_base_url, headers=headers, data=post_data, timeout=30)
            
            if res is not None and res.status_code == 200:
                try:
                    res_json = res.json()
                    if isinstance(res_json, dict) and res_json.get('errors'):
                        logger.error(f"[{cls.site_name}] GraphQL Errors: {res_json['errors']}")
                    return res_json
                except Exception as e_json:
                    logger.error(f"[{cls.site_name}] JSON parse error: {e_json}. Text: {res.text[:200]}")
                    return None
            else:
                logger.error(f"[{cls.site_name}] API Error: Status {res.status_code if res else 'None'}")
                return None
        except Exception as e:
            logger.error(f"[{cls.site_name}] API Request Exception: {e}")
            return None


    @classmethod
    def _format_scene_title(cls, raw_title, studio_name, studio_code, item_data=None):
        raw_title = str(raw_title or '').strip()
        studio_code = str(studio_code or '').strip()
        studio_name = str(studio_name or '').strip()
        if not raw_title: return raw_title

        item_data = item_data or {}
        date_val = str(item_data.get('date') or '').strip()
        year_val = date_val[:4] if len(date_val) >= 4 and date_val[:4].isdigit() else ''
        director_val = str(item_data.get('director') or '').strip()

        females, males = [], []
        performers = item_data.get('performers') or []
        if isinstance(performers, list):
            for p in performers:
                if not isinstance(p, dict): continue
                p_dict = p.get('performer') or {}
                actor_name = str(p_dict.get('name') or '').strip()
                gender = str(p_dict.get('gender') or '').lower()
                if actor_name:
                    if gender == 'female': females.append(actor_name)
                    else: males.append(actor_name)
        include_male = cls.config.get("include_male", False)
        selected_actors = (females + males) if include_male else (females if females else males)
        actor_val = ", ".join(selected_actors[:3]) if selected_actors else ""

        user_schema_str = cls.config.get("stashdb_user_schema") or "studio:czechvr|{raw_title}|{studio_code} - {raw_title}"
        if not user_schema_str or not user_schema_str.strip():
            return raw_title

        lines = [line.strip() for line in user_schema_str.split('\n') if line.strip()]
        format_kwargs = {
            'raw_title': raw_title, 'studio_code': studio_code, 'studio': studio_name,
            'date': date_val, 'year': year_val, 'actor': actor_val, 'director': director_val
        }

        for line in lines:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 3: continue
            filter_expr, target_field, rule_fmt = parts[0], parts[1], parts[2]

            filter_matched = False
            if ':' in filter_expr:
                f_type, f_val = filter_expr.split(':', 1)
                f_type, f_val = f_type.strip().lower(), f_val.strip().lower().replace(' ', '')
                if f_type == 'studio' and f_val in studio_name.lower().replace(' ', ''): filter_matched = True
                elif f_type == 'code' and f_val in studio_code.lower().replace(' ', ''): filter_matched = True
            elif filter_expr.lower().replace(' ', '') in studio_name.lower().replace(' ', ''):
                filter_matched = True

            if filter_matched:
                try:
                    if studio_code and raw_title.startswith(studio_code): return raw_title
                    return rule_fmt.format(**format_kwargs).strip()
                except Exception as e_fmt:
                    logger.error(f"[{cls.site_name}] 사용자 스키마 룰 예외 '{line}': {e_fmt}")

        return raw_title


    @classmethod
    def _format_studio_name(cls, name):
        if not name: return 'Unknown'
        words = str(name).split()
        return "".join([w[0].upper() + w[1:] for w in words if w])


    @classmethod
    def _make_safe_filename(cls, text):
        if not text: return "Unknown"
        text = re.sub(r'[\[\]\(\)]', '', str(text))
        text = re.sub(r'[^\w\s가-힣-]', '', text)
        return re.sub(r'\s+', '_', text.strip())


    @classmethod
    def _calculate_western_score(cls, keyword, item_data, rank, local_duration=None):
        if not isinstance(item_data, dict): return 0.0

        word_pattern = r'[^a-z0-9\s]'
        kw_clean = re.sub(r'\s+', ' ', re.sub(word_pattern, '', str(keyword or '').lower())).strip()
        raw_title = str(item_data.get('title') or '').lower()
        title_clean = re.sub(r'\s+', ' ', re.sub(word_pattern, '', raw_title)).strip()
        studio_code = str(item_data.get('code') or '').lower()

        kw_norm = kw_clean.replace(' ', '')
        title_norm = title_clean.replace(' ', '')

        # 1. 랭크 기본점 (1위 30점, 2위 18점, 3위 17점, 4위 16점, 5위~ 15점)
        score = 30.0 if rank == 0 else max(15.0, 19.0 - float(rank))

        # 2. 영상 길이(Duration) 정밀 매칭 (최대 +30점 가산)
        duration_matched = False
        item_duration = item_data.get('duration')
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
        studio_node = item_data.get('studio') or {}
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

        # 4. 배우명 일치 검증 (+20점)
        actor_matched = False
        performers = item_data.get('performers') or []
        if isinstance(performers, list):
            for p in performers:
                if not isinstance(p, dict): continue
                p_name = str((p.get('performer') or {}).get('name') or '').lower()
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
        code_nums = set(re.findall(r'\b\d+\b', studio_code))
        all_item_nums = title_nums.union(code_nums)

        if kw_nums:
            num_matched = any(len(num) >= 2 and num in all_item_nums for num in kw_nums)
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

        # 9. 이미지 데이터 부재 (-10점)
        images = item_data.get('images') or []
        if not (images or studio_node.get('images')):
            score -= 10.0

        final_score = min(100.0, max(1.0, score))
        dur_log = f"DurMatch:{duration_matched}" if local_duration else "DurMatch:N/A"
        logger.debug(f"[{cls.site_name}] 채점 상세 -> Title:'{raw_title[:30]}' | Score:{final_score:.1f} (Rank:{rank}, Studio:{studio_matched}, Actor:{actor_matched}, Date:{date_matched}, {dur_log})")
        return final_score


    @classmethod
    def search_by_fingerprint(cls, media_path=None, filename=None):
        use_fp = cls.config.get("use_fingerprint", False)
        video_file = media_path or filename
        if not use_fp or not video_file or not os.path.exists(video_file):
            return []

        # 지문 GraphQL 쿼리 헬퍼
        def query_stash_fingerprints(fps_list):
            if not fps_list: return []
            fp_query = """
            query FindScenesBySceneFingerprints($fingerprints: [[FingerprintQueryInput!]!]!) {
              findScenesBySceneFingerprints(fingerprints: $fingerprints) {
                id
                title
                code
                date
                studio { id name parent { id name } }
                performers { performer { name gender } }
                images { url }
              }
            }
            """
            res = cls._call_graphql_api(fp_query, {"fingerprints": [fps_list]})
            raw_data = ((res or {}).get('data') or {}).get('findScenesBySceneFingerprints') or []
            matched = []
            for group in raw_data:
                if isinstance(group, list):
                    matched.extend([s for s in group if isinstance(s, dict)])
                elif isinstance(group, dict):
                    matched.append(group)
            return matched

        try:
            fp_type = (cls.config.get("fingerprint_type") or "OSHASH").upper()
            ffmpeg_path = cls.config.get("ffmpeg_path") or "ffmpeg"

            # 1단계: OSHash 우선 시도
            if fp_type in ["OSHASH", "BOTH"]:
                oshash = cls.calculate_oshash(video_file)
                if oshash:
                    logger.debug(f"[{cls.site_name}] 1단계 OSHash 조회 시작: {oshash}")
                    matched_scenes = query_stash_fingerprints([{"algorithm": "OSHASH", "hash": oshash}])
                    if matched_scenes:
                        logger.info(f"[{cls.site_name}] StashDB OSHash 초고속 매칭 성공! (pHash 생략)")
                        return matched_scenes

            # 2단계: pHash 지연 평가 (PHASH 모드이거나, BOTH 모드에서 OSHash 매칭에 실패한 경우에만 실행)
            if fp_type in ["PHASH", "BOTH"]:
                if fp_type == "BOTH":
                    logger.debug(f"[{cls.site_name}] OSHash 미매칭 ➔ 2단계 pHash(5x5 스프라이트 지문) 캡처 및 조회 진행...")

                phash = cls.calculate_phash(video_file, ffmpeg_path=ffmpeg_path)
                if phash:
                    logger.debug(f"[{cls.site_name}] 2단계 pHash 조회 시작: {phash}")
                    matched_scenes = query_stash_fingerprints([{"algorithm": "PHASH", "hash": phash}])
                    if matched_scenes:
                        logger.info(f"[{cls.site_name}] StashDB pHash 시각 지문 매칭 성공!")
                        return matched_scenes

        except Exception as e_fp:
            logger.error(f"[{cls.site_name}] search_by_fingerprint 예외: {e_fp}")
            logger.error(traceback.format_exc())

        return []


    @classmethod
    def search(cls, keyword, manual=False, media_path=None, filename=None, **kwargs):
        scenes_list = []
        is_fp_match = False

        # 0순위: 비디오 지문(Fingerprint) 탐색
        target_video = media_path or filename
        if not target_video and os.path.isabs(keyword) and os.path.exists(keyword):
            target_video = keyword

        # 로컬 Meta DB 전용 B-Tree 지문 인덱스 0순위 초고속 확인
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

        if target_video:
            fp_scenes = cls.search_by_fingerprint(media_path=target_video)
            if fp_scenes:
                scenes_list = fp_scenes
                is_fp_match = True

        # 1순위: searchScenes 텍스트 통합 검색 (지문 결과가 없을 때)
        if not is_fp_match:
            query = """
            query SearchScenes($term: String!) {
              searchScenes(term: $term) {
                count
                scenes {
                  id
                  title
                  code
                  details
                  date
                  duration
                  studio { id name parent { id name } images { url } }
                  performers { performer { id name gender disambiguation images { url } } }
                  images { url width height }
                  urls { url type }
                  tags { id name }
                }
              }
            }
            """
            cleaned_kw = re.sub(r'[\[\]\(\)_.,]', ' ', str(keyword or '')).strip()
            cleaned_kw = re.sub(r'\s+', ' ', cleaned_kw)

            res_data = cls._call_graphql_api(query, {"term": cleaned_kw})
            search_node = ((res_data or {}).get('data') or {}).get('searchScenes') or {}
            scenes_list = search_node.get('scenes') if isinstance(search_node, dict) else (search_node if isinstance(search_node, list) else [])

            # 2차 연도 제거 폴백 검색
            if not scenes_list:
                no_year_kw = re.sub(r'\b(19|20)\d{2}[-._]?\d{1,2}[-._]?\d{1,2}\b|\b\d{2}[-._]\d{2}[-._]\d{2}\b|\b(19|20)\d{2}\b', '', cleaned_kw).strip()
                no_year_kw = re.sub(r'\s+', ' ', no_year_kw)
                if no_year_kw and no_year_kw != cleaned_kw:
                    logger.info(f"[{cls.site_name}] 1차 실패 ➔ 2차 연도제거 폴백 검색: '{no_year_kw}'")
                    res_data2 = cls._call_graphql_api(query, {"term": no_year_kw})
                    search_node2 = ((res_data2 or {}).get('data') or {}).get('searchScenes') or {}
                    scenes_list = search_node2.get('scenes') if isinstance(search_node2, dict) else (search_node2 if isinstance(search_node2, list) else [])

        if not scenes_list:
            logger.info(f"[{cls.site_name}] Search END - 결과 없음: {keyword}")
            return {'ret': 'no_match', 'data': []}

        ret = []
        local_dur = cls.get_video_duration(target_video) if target_video and os.path.exists(target_video) else None

        ret = []
        for idx, item_data in enumerate(scenes_list):
            if not isinstance(item_data, dict): continue
            item_id = str(item_data.get('id') or '').strip()
            if not item_id: continue

            item = EntityAVSearch(cls.site_name)
            type_char = 'S'
            item.code = f"{cls.module_char}{cls.site_char}{type_char}_{item_id}"
            item.ui_code = item.code
            item.content_type = 'scene'
            
            studio_dict = item_data.get('studio') or {}
            final_studio = cls._format_studio_name(studio_dict.get('name'))
            
            raw_title = str(item_data.get('title') or '').strip() or item.ui_code
            studio_code = str(item_data.get('code') or '').strip()
            raw_title = cls._format_scene_title(raw_title, final_studio, studio_code, item_data=item_data)

            females, males = [], []
            performers = item_data.get('performers') or []
            if isinstance(performers, list):
                for p_wrap in performers:
                    if not isinstance(p_wrap, dict): continue
                    p_dict = p_wrap.get('performer') or {}
                    actor_name = str(p_dict.get('name') or '').strip()
                    gender = str(p_dict.get('gender') or '').lower()
                    if actor_name:
                        if gender == 'female': females.append(actor_name)
                        else: males.append(actor_name)

            include_male = cls.config.get("include_male", False)
            selected_actors = (females + males) if include_male else (females if females else males)
            actor_str = ", ".join(selected_actors[:3]) if selected_actors else ""
            date_val = str(item_data.get('date') or '').strip()
            year_val = date_val[:4] if len(date_val) >= 4 and date_val[:4].isdigit() else ''

            format_dict = {
                'originaltitle': raw_title, 'plot': '', 'title': raw_title,
                'studio': final_studio, 'year': year_val, 'actor': actor_str, 'tagline': ''
            }
            fmt = cls.config.get("title_format") or "[{studio}] {actor} - {title}"
            try: item.title = fmt.format(**format_dict)
            except Exception: item.title = f"[{final_studio}] {raw_title}"

            item.title_ko = item.title
            item.year = int(date_val[:4]) if date_val else 1900
            item.desc = f"Type: Scene {'[★ 지문 일치]' if is_fp_match else ''} / Date: {date_val} / Studio: {final_studio}"

            img_url = ''
            images = item_data.get('images') or []
            if isinstance(images, list) and len(images) > 0 and isinstance(images[0], dict):
                img_url = str(images[0].get('url') or '')
            item.image_url = img_url or ''

            if manual and item.image_url and item.image_url.startswith('http'):
                try:
                    safe_url = urllib.parse.quote(item.image_url, safe=':/&?%=')
                    item.image_url = cls.make_image_url(safe_url)
                except Exception as e_proxy:
                    logger.error(f"[{cls.site_name}] Proxy conversion error: {e_proxy}")

            if is_fp_match:
                item.score = 100
            else:
                calc_score = cls._calculate_western_score(keyword, item_data, idx, local_duration=local_dur)
                item.score = int(round(calc_score))

            item.score = max(0, min(100, item.score))
            ret.append(item.as_dict())

        ret.sort(key=lambda k: k.get("score", 0), reverse=True)

        # 단일 검색 결과 신뢰 옵션 (100점 바이패스)
        if len(ret) == 1 and cls.config.get("trust_single_result", False):
            ret[0]['score'] = 100
            logger.debug(f"[{cls.site_name}] 단일 검색 결과 감지 -> 100점 부여")

        logger.info(f"[{cls.site_name}] Search Success: {len(ret)} results found.")
        for i, item_log in enumerate(ret[:5]):
            logger.debug(f"  {i+1}. Score:{item_log.get('score'):>3} | Studio:{final_studio} | Title:{item_log.get('title')} | Code:{item_log.get('code')}")

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
            logger.error(f"[{cls.site_name}] 잘못된 코드 형식: {code}")
            return None
            
        type_char = code[2]
        item_id = code[4:]
        content_type = 'scene' if type_char == 'S' else 'movie'

        query = """
        query FindScene($id: ID!) {
          findScene(id: $id) {
            id
            title
            code
            details
            date
            studio { id name parent { id name images { url } } images { url } }
            performers {
              performer {
                id
                name
                disambiguation
                aliases
                gender
                birth_date
                career_start_year
                height
                band_size
                cup_size
                waist_size
                hip_size
                breast_type
                country
                ethnicity
                hair_color
                eye_color
                images { url }
                urls { url }
              }
            }
            images { url width height }
            urls { url type }
            tags { id name }
            fingerprints { algorithm hash }
          }
        }
        """

        res_data = cls._call_graphql_api(query, {"id": item_id})
        item_data = ((res_data or {}).get('data') or {}).get('findScene')
        if not item_data or not isinstance(item_data, dict):
            logger.warning(f"[{cls.site_name}] findScene 결과 없음 (ID: {item_id})")
            return None

        entity = EntityMovie(cls.site_name, code)
        entity.content_type = content_type
        entity.country = ['미국']
        entity.mpaa = '청소년 관람불가'
        entity.thumb = []; entity.fanart = []; entity.extras = []; entity.tag = []; entity.genre = []; entity.actor = []
        entity.director = ""
        entity.original = {}
        if not hasattr(entity, 'extra_info') or entity.extra_info is None:
            entity.extra_info = {}

        site_fps = []
        raw_fps = item_data.get('fingerprints') or []
        for rf in raw_fps:
            if isinstance(rf, dict) and rf.get('hash'):
                site_fps.append({
                    'algorithm': str(rf.get('algorithm') or 'OSHASH').upper(),
                    'hash': str(rf.get('hash')).lower(),
                    'source': 'site'
                })

        user_fps = []
        if media_path and os.path.exists(media_path):
            # info 단계에서는 이미 계산되어 캐싱된 지문만 재활용하고 불필요한 pHash 신규 계산(FFmpeg 캡처) 방지
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
        raw_title = str(item_data.get('title') or entity.ui_code).strip()

        entity.extra_info['info_url'] = f"https://stashdb.org/scenes/{item_id}"

        date_str = str(item_data.get('date') or '').strip()
        if date_str:
            entity.premiered = date_str
            try: entity.year = int(date_str[:4])
            except: pass

        # Studio & Network
        studio_node = item_data.get('studio') or {}
        parent_studio_node = studio_node.get('parent') or {}
        final_studio = cls._format_studio_name(studio_node.get('name'))
        final_network = cls._format_studio_name(parent_studio_node.get('name'))

        entity.studio = final_studio if final_studio != 'Unknown' else final_network
        entity.original['studio'] = entity.studio
        entity.original['network'] = final_network

        studio_code = str(item_data.get('code') or '').strip()
        raw_title = cls._format_scene_title(raw_title, entity.studio, studio_code, item_data=item_data)
        entity.title = entity.originaltitle = entity.sorttitle = raw_title

        cleaned_tagline = cls.A_P(raw_title)
        entity.original['tagline'] = cleaned_tagline
        
        if skip_trans or not cls.config.get('trans_title', True):
            entity.tagline = cleaned_tagline
        else:
            entity.tagline = cls.trans_by_llm(cleaned_tagline)

        # Plot
        plot_text = str(item_data.get('details') or '').strip()
        if plot_text:
            cleaned_plot = cls.A_P(plot_text)
            entity.original['plot'] = cleaned_plot
            entity.plot = cleaned_plot if skip_trans else cls.trans_by_llm(entity.original['plot'])

        females, males = [], []
        performers = item_data.get('performers') or []
        if isinstance(performers, list):
            for p_wrap in performers:
                if not isinstance(p_wrap, dict): continue
                p_dict = p_wrap.get('performer') or {}
                actor_name = str(p_dict.get('name') or '').strip()
                actor_id = str(p_dict.get('id') or '').strip()
                if not actor_name: continue

                gender = str(p_dict.get('gender') or '').lower()
                images_list = p_dict.get('images') or []
                act_img = str(images_list[0].get('url') or '') if (images_list and isinstance(images_list[0], dict)) else ''

                formatted_idx = f"PS{actor_id}" if (actor_id and not actor_id.startswith('PS')) else actor_id

                band_sz = str(p_dict.get('band_size') or '').strip()
                cup_sz = str(p_dict.get('cup_size') or '').strip()
                waist_sz = str(p_dict.get('waist_size') or '').strip()
                hip_sz = str(p_dict.get('hip_size') or '').strip()

                bra_size_str = f"{band_sz}{cup_sz}".strip() if (band_sz or cup_sz) else ""
                body_size_str = ""
                if bra_size_str or waist_sz or hip_sz:
                    b_part = f"B{bra_size_str}" if bra_size_str else "B-"
                    w_part = f"W{waist_sz}" if waist_sz else "W-"
                    h_part = f"H{hip_sz}" if hip_sz else "H-"
                    body_size_str = f"{b_part}-{w_part}-{h_part}"

                all_site_photos = [str(im.get('url')) for im in images_list if isinstance(im, dict) and im.get('url')]

                actor_entry = ActorDict({
                    'name_org': actor_name,
                    'name_ko': '',
                    'name_en': actor_name,
                    'actor_idx': formatted_idx,
                    'thumb': act_img,
                    'role': '출연',
                    'gender': gender,
                    'extra_info': {
                        'gender': gender,
                        'birth': str(p_dict.get('birth_date') or p_dict.get('birthdate') or '').strip(),
                        'height': p_dict.get('height'),
                        'body_size': body_size_str,
                        'bra_size': f"{cup_sz}컵" if (cup_sz and not cup_sz.endswith('컵')) else bra_size_str,
                        'debut': str(p_dict.get('career_start_year') or '').strip(),
                        'country': str(p_dict.get('country') or '').strip(),
                        'info_url': f"https://stashdb.org/performers/{actor_id}" if actor_id else '',
                        'site_img_url': act_img,
                        'site_img_urls': all_site_photos,
                        'aliases': p_dict.get('aliases') or []
                    }
                })

                if gender == 'female':
                    females.append(actor_entry)
                else:
                    males.append(actor_entry)

        entity.actor.extend(females + males)

        # Tags & Genres
        if 'genre' not in entity.original: entity.original['genre'] = []
        for tag in (item_data.get('tags') or []):
            if isinstance(tag, dict) and tag.get('name'):
                tag_str = str(tag['name']).strip()
                entity.original['genre'].append(tag_str)
                trans_genre = cls.get_translated_tag(tag_str)
                if trans_genre not in entity.genre:
                    entity.genre.append(trans_genre)

        # Images
        raw_image_urls = {'poster': None, 'pl': None, 'arts': []}
        use_smart_crop = cls.config.get('use_smart_crop', False)
        force_studios = cls.config.get('poster_force_studios_set', set())
        is_force_poster = (entity.studio.lower() if entity.studio else "") in force_studios

        landscape_cover_url = None
        portrait_poster_url = None

        for img_obj in (item_data.get('images') or []):
            if not isinstance(img_obj, dict): continue
            url = str(img_obj.get('url') or '')
            if not url: continue
            w = img_obj.get('width')
            h = img_obj.get('height')
            if w and h and int(w) > int(h):
                if not landscape_cover_url: landscape_cover_url = url
            else:
                if not portrait_poster_url: portrait_poster_url = url

        if not landscape_cover_url and not portrait_poster_url and item_data.get('images'):
            first_url = str(item_data['images'][0].get('url') or '')
            landscape_cover_url = first_url

        entity.original['thumb'] = {
            'poster': portrait_poster_url or '',
            'landscape': landscape_cover_url or ''
        }

        # 스마트 크롭 실행 (이미지 서버 저장용 임시 포스터 파일 생성)
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
                        cropped.close()
                    img_pl.close()
            except Exception as e_crop:
                logger.error(f"[{cls.site_name}] 스마트 크롭 오류: {e_crop}")

        # 세로 포스터가 없고 크롭이 실패/미적용된 경우 가로 커버를 포스터로 폴백 지정
        if not poster_url and landscape_cover_url:
            poster_url = landscape_cover_url
            logger.debug(f"[{cls.site_name}] 세로 포스터 부재/크롭 실패 -> 가로 커버를 포스터로 폴백 지정")

        raw_image_urls['poster'] = poster_url
        raw_image_urls['pl'] = landscape_cover_url

        # 고유 코드(WSS_ID) 기반으로 이미지 저장
        entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None, extra_opts=opts)

        # Trailers
        urls_list = item_data.get('urls') or []
        if cls.config.get('use_extras', False) and isinstance(urls_list, list):
            trailer_url = None
            for u_obj in urls_list:
                if not isinstance(u_obj, dict): continue
                u_type = str(u_obj.get('type') or '').upper()
                u_url = str(u_obj.get('url') or '')
                if u_type in ['TRAILER', 'PREVIEW'] or '.mp4' in u_url or '.m3u8' in u_url:
                    trailer_url = u_url
                    break
            if trailer_url:
                if not hasattr(entity, 'original') or entity.original is None:
                    entity.original = {}
                entity.original['extras'] = [{
                    'content_url': trailer_url,
                    'content_type': 'trailer'
                }]

                final_url = cls.make_video_url(trailer_url) if cls.config.get('use_trailer_proxy', False) else trailer_url
                if final_url:
                    entity.extras.append(EntityExtra("trailer", entity.tagline or entity.title, "mp4", final_url))

        used_model = getattr(cls, '_last_used_llm_model', None)
        if used_model:
            entity.extra_info['ai_translator'] = f"Ollama ({used_model})"
            cls._last_used_llm_model = None
        else:
            entity.extra_info['ai_translator'] = "Default (FF)"

        return entity
