"""AV genre lookup, user overrides and a process-safe machine translation cache."""

import ast
import json
import logging
import os
import re
import sqlite3
import sys
import time
import unicodedata
from functools import lru_cache


logger = logging.getLogger('support_site')
_ACRONYMS = {
    word.casefold(): word for word in (
        'AV', 'AVN', 'ATM', 'BBC', 'BBW', 'BDSM', 'BWC', 'CD', 'CG', 'DILF',
        'DMM', 'DP', 'DVD', 'FANZA', 'FFM', 'FMF', 'HD', 'HDR', 'JAV', 'LGBT',
        'LGBTQ', 'MILF', 'MGS', 'MMF', 'NTR', 'OL', 'OP', 'POV', 'SD', 'SF',
        'SM', 'SNS', 'SOD', 'SS', 'UHD', 'VIP', 'VR', 'WCP', 'YTP',
    )
}
_PROPER_NAMES = {'tiktok': 'TikTok', 'inkedupsex': 'InkedUpSex'}


def normalize_tag_text(tag):
    """Preserve whole phrases; normalize width, compatibility characters and spaces."""
    if not isinstance(tag, str):
        return ''
    text = unicodedata.normalize('NFKC', tag)
    return re.sub(r'\s+', ' ', text).strip(' #')


def normalize_tag_key(tag):
    return normalize_tag_text(tag).casefold()


def canonical_tag_name(tag):
    """Readable spelling for storage; lookup remains independent of capitalization."""
    text = normalize_tag_text(tag)
    if not text.isascii():
        return text
    if text.casefold() in _PROPER_NAMES:
        return _PROPER_NAMES[text.casefold()]

    def word(match):
        value = match.group()
        if value.casefold() in _ACRONYMS:
            return _ACRONYMS[value.casefold()]
        if re.fullmatch('[BGTFM]{2,}', value.upper()):
            return value.upper()
        if match.start() and text[match.start() - 1].isdigit():
            if value.casefold() == 'fps':
                return value.lower()
            if value.casefold() == 'p':
                resolution = re.search(r'(\d+)$', text[:match.start()])
                if resolution and int(resolution.group()) in (144, 240, 360, 480, 540, 576, 720, 1080, 1440, 2160, 2880, 4320):
                    return 'p'
        return value.capitalize()

    return re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?", word, text)


_standard_state = {'signature': None, 'index': None}


def _standard_tags():
    path = os.path.join(os.path.dirname(__file__), 'constants.py')
    try:
        stat = os.stat(path)
        signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
    except OSError as exc:
        signature = None
        if _standard_state['index'] is not None:
            return _standard_state['index']
        logger.warning('[AV Tags] 표준 사전 파일 확인 실패: %s', exc)
    if signature != _standard_state['signature'] or _standard_state['index'] is None:
        try:
            with open(path, encoding='utf-8-sig') as handle:
                tree = ast.parse(handle.read(), filename=path)
            definition = next(node for node in tree.body if isinstance(node, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == 'AV_GENRE' for t in node.targets))
            data = ast.literal_eval(definition.value)
            if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                     for k, v in data.items()):
                raise ValueError('AV_GENRE must be a dictionary of strings')
            index = {}
            for key_node, value_node in zip(definition.value.keys, definition.value.values):
                key, value = ast.literal_eval(key_node), ast.literal_eval(value_node)
                normalized = normalize_tag_key(key)
                if normalized in index and index[normalized] != value:
                    raise ValueError('conflicting normalized genre: ' + key)
                index[normalized] = value
            # Publish a complete snapshot; never clear a dictionary being read.
            _standard_state['index'] = index
            logger.debug('[AV Tags] 표준 사전 로딩: %s건', len(index))
        except (OSError, ValueError, SyntaxError, StopIteration) as exc:
            logger.warning('[AV Tags] 표준 사전 변경 반영 실패, 마지막 정상 사전 유지: %s', exc)
            if _standard_state['index'] is None:
                from .constants import AV_GENRE
                _standard_state['index'] = {normalize_tag_key(k): v for k, v in AV_GENRE.items()}
        # A failed edit is retried only after the file changes again.
        _standard_state['signature'] = signature
    return _standard_state['index']


def lookup_standard_tag(tag):
    return _standard_tags().get(normalize_tag_key(tag))


@lru_cache(maxsize=8)
def _read_user_tags(path, signature):
    # signature invalidates cached data after a user's edit or atomic replacement.
    try:
        with open(path, encoding='utf-8-sig') as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError('expected a JSON object')
        tags = {}
        for name, value in data.items():
            if not isinstance(name, str) or not isinstance(value, str):
                continue
            key = normalize_tag_key(name)
            if key:
                # Prefer the canonical spelling if legacy aliases disagree.
                if key not in tags or name == canonical_tag_name(name):
                    tags[key] = value
        return tags
    except (OSError, ValueError) as exc:
        logger.warning('[AV Tags] 사용자 사전 읽기 실패: %s', exc)
        return {}


def lookup_user_tag(path_data, tag):
    path = os.path.join(path_data, 'db', 'av_tags.json')
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.debug('[AV Tags] 사용자 사전 확인 실패: %s', exc)
        return None
    signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
    return _read_user_tags(path, signature).get(normalize_tag_key(tag))


def translation_is_usable(original, translated):
    """Reject objectively broken output; semantic accuracy still needs human review."""
    if not isinstance(translated, str) or not translated.strip():
        return False
    if normalize_tag_key(original) == normalize_tag_key(translated):
        return False
    if not re.search(r'[가-힣]', translated):
        return False
    if re.search(r'[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\ufffd<>\x00-\x1f]', translated):
        return False
    if '://' in translated or len(translated) > max(80, len(original) * 4):
        return False
    return True


def _cache_path(path_data):
    return os.path.join(path_data, 'db', 'av_tags_cache.db')


def lookup_cached_tag(path_data, tag):
    path = _cache_path(path_data)
    if not os.path.isfile(path):
        return None
    connection = None
    try:
        # Never wait on a SQLite lock inside a gevent worker. The cache is optional.
        connection = sqlite3.connect(path, timeout=0, isolation_level=None)
        row = connection.execute('SELECT translated FROM av_tag_cache WHERE tag_key = ?',
                                 (normalize_tag_key(tag),)).fetchone()
        if row and translation_is_usable(tag, row[0]):
            return row[0]
    except (OSError, sqlite3.Error) as exc:
        logger.debug('[AV Tags] 번역 캐시 조회 생략: %s', exc)
    finally:
        if connection is not None:
            connection.close()
    return None


def store_cached_tag(path_data, tag, translated, source_lang):
    """Insert one provisional translation atomically, without rewriting user JSON."""
    if not translation_is_usable(tag, translated):
        return None
    for attempt in range(6):
        try:
            return _store_cached_tag_once(path_data, tag, translated, source_lang)
        except sqlite3.OperationalError as exc:
            if ('locked' in str(exc).lower() or 'busy' in str(exc).lower()) and attempt < 5:
                _retry_sleep(0.01 * (2 ** attempt))
                continue
            logger.debug('[AV Tags] 번역 캐시 저장 생략: %s', exc)
            return None
        except (OSError, sqlite3.Error) as exc:
            logger.debug('[AV Tags] 번역 캐시 저장 생략: %s', exc)
            return None


def _retry_sleep(delay):
    monkey = sys.modules.get('gevent.monkey')
    if monkey is not None and monkey.is_module_patched('socket'):
        from gevent import sleep
        sleep(delay)
    else:
        time.sleep(delay)


def _store_cached_tag_once(path_data, tag, translated, source_lang):
    connection = None
    try:
        path = _cache_path(path_data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        connection = sqlite3.connect(path, timeout=0, isolation_level=None)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.execute('''CREATE TABLE IF NOT EXISTS av_tag_cache (
            tag_key TEXT PRIMARY KEY,
            name_org TEXT NOT NULL,
            translated TEXT NOT NULL,
            source_lang TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'machine',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')
        connection.execute('''INSERT INTO av_tag_cache
            (tag_key, name_org, translated, source_lang) VALUES (?, ?, ?, ?)
            ON CONFLICT(tag_key) DO NOTHING''',
            (normalize_tag_key(tag), canonical_tag_name(tag), translated, source_lang))
        row = connection.execute('SELECT translated FROM av_tag_cache WHERE tag_key = ?',
                                 (normalize_tag_key(tag),)).fetchone()
        return row[0] if row else None
    finally:
        if connection is not None:
            connection.close()
