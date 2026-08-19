# -*- coding: utf-8 -*-
import re
import urllib.parse
import os
import time
import shutil
import difflib
import json
import requests
from io import BytesIO
from PIL import Image

from ..entity_av import EntityAVSearch
from ..entity_base import EntityMovie, EntityActor, EntityExtra, EntityThumb
from ..setup import P, logger, F, path_data
from .site_av_base import SiteAvBase


class SiteStashdb(SiteAvBase):
    site_name = 'stashdb'
    site_char = 'S'
    module_char = 'W'
    default_headers = SiteAvBase.base_default_headers.copy()

    site_base_url = 'https://stashdb.org/graphql'
    
    @classmethod
    def set_config(cls, db):
        super().set_config(db)
        
        prefix = 'western'
        cls.config.update({
            "stashdb_api_key": db.get(f"{prefix}_{cls.site_name}_api_key") or db.get(f"{prefix}_{cls.site_name}_api_token"),
            "trans_option": db.get(f"{prefix}_trans_option"),
            "trans_title": db.get_bool(f"{prefix}_trans_title") if db.get(f"{prefix}_trans_title") is not None else True,
            "use_extras": db.get_bool(f"{prefix}_use_extras"),

            "title_format": db.get(f"{prefix}_title_format"),
            "use_movie_title_format": db.get_bool(f"{prefix}_use_movie_title_format"),
            "movie_title_format": db.get(f"{prefix}_movie_title_format"),

            "image_mode": db.get(f"{prefix}_image_mode"),
            "image_server_local_path": db.get(f"{prefix}_image_server_local_path"),
            "image_server_url": db.get(f"{prefix}_image_server_url"),
            "image_server_rewrite": db.get_bool(f"{prefix}_image_server_rewrite"),
            "western_image_format": db.get(f"{prefix}_image_server_save_format") or "/western/{studio}",

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
        selected_actors = females if females else males
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
    def _calculate_western_score(cls, keyword, item_data, rank):
        if not isinstance(item_data, dict): return 0.0

        word_pattern = r'[^a-z0-9\s]'
        kw_clean = re.sub(r'\s+', ' ', re.sub(word_pattern, '', str(keyword or '').lower())).strip()
        raw_title = str(item_data.get('title') or '').lower()
        title_clean = re.sub(r'\s+', ' ', re.sub(word_pattern, '', raw_title)).strip()
        studio_code = str(item_data.get('code') or '').lower()

        kw_norm = kw_clean.replace(' ', '')
        title_norm = title_clean.replace(' ', '')

        score = max(10.0, 40.0 - (rank * 8.0))

        # 스튜디오 매칭 (+25점, VR 일치 +2점)
        studio_node = item_data.get('studio') or {}
        studio_name = str(studio_node.get('name') or '').lower()
        if studio_name:
            studio_norm = re.sub(r'[^a-z0-9]', '', studio_name)
            if studio_norm:
                if studio_norm in kw_norm:
                    score += 25.0
                    if 'vr' in kw_norm and 'vr' in studio_norm: score += 2.0
                elif kw_norm.startswith(studio_norm[:6]): score += 20.0

        # 배우명 일치 검증 (+20점)
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

        # 날짜 일치 검증 및 번호 페널티 분리
        item_date = str(item_data.get('date') or '').replace('-', ' ')
        date_matched = False
        
        # 검색어 내 날짜 패턴 (예: 26 08 03 또는 2026 08 03) 추출
        date_match = re.search(r'\b(20\d{2}|\d{2})[ ._-](\d{2})[ ._-](\d{2})\b', kw_clean)
        kw_date_nums = set()
        if date_match:
            y, m, d = date_match.group(1), date_match.group(2), date_match.group(3)
            kw_date_nums = {y, m, d, y[-2:]}
            # StashDB 출시일(date)과 일치 시 보너스 (+20점)
            if m in item_date and d in item_date:
                date_matched = True
                score += 20.0

        # 품번/에피소드 숫자 (날짜 구성 숫자는 제외하여 오감점 방지)
        kw_nums = set(re.findall(r'\b\d+\b', kw_clean)) - kw_date_nums
        title_nums = set(re.findall(r'\b\d+\b', title_clean))
        code_nums = set(re.findall(r'\b\d+\b', studio_code))
        all_item_nums = title_nums.union(code_nums)

        if kw_nums:
            num_matched = any(len(num) >= 2 and num in all_item_nums for num in kw_nums)
            if num_matched: score += 20.0
            elif not date_matched: score -= 15.0 # 날짜도 안 맞고 번호도 다를 때만 감점

        # 제목 텍스트 일치도 (완전 포함 +25점 / 단어 비례 최대 +20점)
        if kw_norm and title_norm:
            if len(title_norm) >= 3 and (title_norm in kw_norm or kw_norm in title_norm):
                score += 25.0
            else:
                kw_words = set(re.findall(r'\b[a-z0-9]{3,}\b', kw_clean))
                title_words = set(re.findall(r'\b[a-z0-9]{3,}\b', title_clean))
                if kw_words and title_words:
                    intersect = kw_words.intersection(title_words)
                    score += (len(intersect) / len(title_words)) * 20.0

        # 6. 스튜디오 + 배우 + 날짜 3중 완전 일치 시 순위 무관 100점 확정
        studio_matched = bool(studio_norm and studio_norm in kw_norm)
        if studio_matched and actor_matched and date_matched:
            score = 100.0

        # 이미지 데이터 부재 (-10점)
        images = item_data.get('images') or []
        if not (images or studio_node.get('images')):
            score -= 10.0

        final_score = min(100.0, max(1.0, score))
        logger.debug(f"[{cls.site_name}] 채점 상세 -> Title:'{raw_title[:30]}' | Score:{final_score:.1f} (Rank:{rank}, Studio:{studio_matched}, Actor:{actor_matched}, Date:{date_matched})")
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

            # 1단계: OSHash 우선 시도 (OSHASH 또는 BOTH 모드일 때 0.008초 고속 검사)
            if fp_type in ["OSHASH", "BOTH"]:
                oshash = cls.calculate_oshash(video_file)
                if oshash:
                    logger.debug(f"[{cls.site_name}] 1단계 OSHash 조회 시작: {oshash}")
                    matched_scenes = query_stash_fingerprints([{"algorithm": "OSHASH", "hash": oshash}])
                    if matched_scenes:
                        logger.info(f"[{cls.site_name}] ★★★ StashDB OSHash 초고속 매칭 성공! (0.01초 완료, pHash 생략) ★★★")
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
                        logger.info(f"[{cls.site_name}] ★★★ StashDB pHash 시각 지문 매칭 성공! ★★★")
                        return matched_scenes

        except Exception as e_fp:
            logger.error(f"[{cls.site_name}] search_by_fingerprint 예외: {e_fp}")
            logger.error(traceback.format_exc())

        return []


    @classmethod
    def search(cls, keyword, manual=False, media_path=None, filename=None, **kwargs):
        scenes_list = []
        is_fp_match = False

        # 0순위: 비디오 지문(Fingerprint) Fast-Path 탐색 (미디어 경로 존재 시)
        target_video = media_path or filename
        if not target_video and os.path.isabs(keyword) and os.path.exists(keyword):
            target_video = keyword

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

            selected_actors = females if females else males
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
                calc_score = cls._calculate_western_score(keyword, item_data, idx)
                item.score = int(round(calc_score)) # Plex 인식을 위해 정수형 변환

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
    def info(cls, code, fp_meta_mode=False, skip_trans=False, media_path=None):
        try:
            entity = cls.__info(code, fp_meta_mode=fp_meta_mode, skip_trans=skip_trans, media_path=media_path)
            return {'ret': 'success', 'data': entity.as_dict()} if entity else {'ret': 'error'}
        except Exception as e:
            logger.exception(f"[{cls.site_name}] Info Exception: {e}")
            return {'ret': 'exception', 'data': str(e)}


    @classmethod
    def __info(cls, code, fp_meta_mode=False, skip_trans=False, media_path=None):
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
            performers { performer { id name gender disambiguation images { url } } }
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

        # StashDB에 등록된 모든 공식 핑거프린트를 extra_info에 자동 저장
        fps = item_data.get('fingerprints') or []
        if isinstance(fps, list):
            entity.extra_info['fingerprints'] = fps
            for fp in fps:
                if isinstance(fp, dict):
                    algo = str(fp.get('algorithm') or '').lower()
                    h_val = str(fp.get('hash') or '').strip()
                    if algo and h_val and algo not in entity.extra_info:
                        entity.extra_info[algo] = h_val

        entity.ui_code = f"{cls.module_char}{cls.site_char}{type_char}_{item_id}"
        raw_title = str(item_data.get('title') or entity.ui_code).strip()

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

        # Actors
        females, males = [], []
        performers = item_data.get('performers') or []
        if isinstance(performers, list):
            for p_wrap in performers:
                if not isinstance(p_wrap, dict): continue
                source_dict = p_wrap.get('performer') or {}
                actor_name = str(source_dict.get('name') or '').strip()
                gender = str(source_dict.get('gender') or '').lower()
                act_img = ""
                images_list = source_dict.get('images') or []
                if isinstance(images_list, list) and len(images_list) > 0 and isinstance(images_list[0], dict):
                    act_img = str(images_list[0].get('url') or '')

                if actor_name:
                    act = EntityActor(actor_name)
                    act.name = str(actor_name)
                    act.originalname = str(actor_name)
                    if act_img: act.thumb = act_img
                    if gender == 'female': females.append(act)
                    else: males.append(act)

        selected_actors = females if females else males
        entity.actor.extend(selected_actors)

        # Tags & Genres (JAV 표준 tags.json 및 번역 엔진 적용)
        if 'genre' not in entity.original: entity.original['genre'] = []
        for tag in (item_data.get('tags') or []):
            if isinstance(tag, dict) and tag.get('name'):
                tag_str = str(tag['name']).strip()
                entity.original['genre'].append(tag_str)
                trans_genre = cls.get_translated_tag('uncen_tags', tag_str)
                if trans_genre not in entity.genre:
                    entity.genre.append(trans_genre)

        # Images
        raw_image_urls = {'poster': None, 'pl': None, 'arts': []}
        use_smart_crop = cls.config.get('use_smart_crop', False)
        force_studios = cls.config.get('poster_force_studios_set', set())
        is_force_poster = (entity.studio.lower() if entity.studio else "") in force_studios

        front_cover, original_poster = None, None
        for img_obj in (item_data.get('images') or []):
            if not isinstance(img_obj, dict): continue
            url = str(img_obj.get('url') or '')
            if not url: continue
            w = img_obj.get('width')
            h = img_obj.get('height')
            if w and h and int(w) > int(h):
                if not front_cover: front_cover = url
            else:
                if not original_poster: original_poster = url

        if not front_cover and not original_poster and item_data.get('images'):
            first_url = str(item_data['images'][0].get('url') or '')
            front_cover = first_url
            original_poster = first_url

        if is_force_poster and original_poster:
            raw_image_urls['poster'] = original_poster
        elif use_smart_crop and front_cover:
            raw_image_urls['poster'] = front_cover
        else:
            raw_image_urls['poster'] = original_poster or front_cover

        raw_image_urls['pl'] = front_cover or original_poster

        # Image Server Path
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
                safe_filename = cls._make_safe_filename(combined_title) + f"_{type_char}_{item_id}"
                entity.ui_code = safe_filename
            except Exception as e:
                logger.error(f"[{cls.site_name}] Image Server Path 생성 실패: {e}")

        entity = cls.process_image_data(entity, raw_image_urls, ps_url_from_cache=None, is_validating=False, is_rescued=False)
        entity.ui_code = f"{cls.module_char}{cls.site_char}{type_char}_{item_id}"

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
                final_url = cls.make_video_url(trailer_url) if cls.config.get('use_trailer_proxy', False) else trailer_url
                if final_url:
                    entity.extras.append(EntityExtra("trailer", entity.title, "mp4", final_url))

        used_model = getattr(cls, '_last_used_llm_model', None)
        if used_model:
            entity.extra_info['ai_translator'] = f"Ollama ({used_model})"
            cls._last_used_llm_model = None
        else:
            entity.extra_info['ai_translator'] = "Default (FF)"

        return entity
