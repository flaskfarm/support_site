import traceback

from lxml import etree as ET
from lxml.builder import E
import lxml.builder as builder
from flask import Response

from support import SupportFile
from .setup import P, logger, app
from support import SupportYaml
try:
    import yaml
except ImportError:
    P.logger.warning("PyYAML is not installed. YAML download feature will not work.")
    yaml = None


class UtilNfo(object):
    @classmethod
    def change_html(cls, text):
        if text is not None:
            return text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"').replace('&#35;', '#').replace('&#39;', "‘")

    @classmethod
    def append_tag(cls, parent, dictionary, key, **kwargs):
        #logger.debug('key:%s, value:%s', key, dictionary[key])
        try:
            if key in dictionary and dictionary[key] is not None and dictionary[key] != '':
                #parent.append(E(key, cls.change_html(str(dictionary[key])), kwargs))
                value = dictionary[key]
                if type(value) == int or type(value) == float:
                    value = str(value)
                parent.append(E(key, cls.change_html(value), kwargs))
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def append_tag_list(cls, parent, dictionary, key):
        #logger.debug('key:%s, value:%s', key, dictionary[key])
        try:
            if key in dictionary and dictionary[key] is not None and len(dictionary[key]) > 1:
                for value in dictionary[key]:
                    parent.append(E(key, cls.change_html(value)))
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def _make_nfo_movie(cls, info):
        try:
            movie = builder.ElementMaker().movie()

            # NFO 필드는 서로 독립적으로 추가해 하나의 누락/오류가 전체 생성을 막지 않도록 합니다.
            for key in ('title', 'originaltitle', 'sorttitle'):
                try:
                    value = info.get(key)
                    if value is not None and value != '':
                        movie.append(E(key, cls.change_html(str(value))))
                except Exception as e:
                    logger.warning(f"NFO 필드 '{key}' 생성 건너뜀: {e}")

            for key, value in (('id', info.get('originaltitle')), ('uniqueid', info.get('code'))):
                try:
                    if value is None or value == '':
                        continue
                    if key == 'uniqueid':
                        movie.append(E.uniqueid(str(value), type=str(info.get('site') or ''), default='true'))
                    else:
                        movie.append(E.id(str(value)))
                except Exception as e:
                    logger.warning(f"NFO 필드 '{key}' 생성 건너뜀: {e}")

            cls.append_tag(movie, info, 'credits')
            cls.append_tag(movie, info, 'mpaa')
            cls.append_tag(movie, info, 'studio')
            cls.append_tag(movie, info, 'plot')
            cls.append_tag(movie, info, 'runtime')
            cls.append_tag(movie, info, 'tagline')
            cls.append_tag(movie, info, 'premiered')
            cls.append_tag(movie, info, 'year')

            cls.append_tag_list(movie, info, 'genre')
            cls.append_tag_list(movie, info, 'country')
            cls.append_tag_list(movie, info, 'tag')


            for item in info.get('thumb') or []:
                try:
                    value = item.get('value') if isinstance(item, dict) else None
                    if value is None:
                        continue
                    attrs = {}
                    if isinstance(item, dict) and item.get('aspect'):
                        attrs['aspect'] = str(item['aspect'])
                    movie.append(E.thumb(str(value), **attrs))
                except Exception as e:
                    logger.warning(f"NFO thumb 필드 생성 건너뜀: {e}")

            for item in info.get('fanart') or []:
                try:
                    if item is not None:
                        movie.append(E.fanart(E.thumb(str(item))))
                except Exception as e:
                    logger.warning(f"NFO fanart 필드 생성 건너뜀: {e}")

            for item in info.get('ratings') or []:
                try:
                    if not isinstance(item, dict):
                        continue
                    attrs = {}
                    if item.get('name') not in (None, ''):
                        attrs['name'] = str(item['name'])
                    if item.get('max') not in (None, ''):
                        attrs['max'] = str(item['max'])
                    if not attrs:
                        continue
                    tag = E.ratings(**attrs)
                    cls.append_tag(tag, item, 'value')
                    cls.append_tag(tag, item, 'votes')
                    movie.append(tag)
                except Exception as e:
                    logger.warning(f"NFO ratings 필드 생성 건너뜀: {e}")

            for item in info.get('extras') or []:
                try:
                    if isinstance(item, dict) and item.get('content_type') == 'trailer' and item.get('content_url'):
                        movie.append(E.trailer(str(item['content_url'])))
                except Exception as e:
                    logger.warning(f"NFO extras 필드 생성 건너뜀: {e}")

            for item in info.get('actor') or []:
                try:
                    if not isinstance(item, dict):
                        continue
                    tag = E.actor()
                    actor_display_name = item.get('name_ko') or item.get('name_org', '')
                    cls.append_tag(tag, {'name': actor_display_name}, 'name')
                    cls.append_tag(tag, item, 'role')
                    cls.append_tag(tag, item, 'order')
                    cls.append_tag(tag, item, 'thumb')
                    movie.append(tag)
                except Exception as e:
                    logger.warning(f"NFO actor 필드 생성 건너뜀: {e}")

            root = movie
            tmp = ET.tostring(root, pretty_print=True, xml_declaration=True, encoding="utf-8")
            if isinstance(tmp, bytes):
                tmp = tmp.decode('utf-8')
            return tmp
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())

    @classmethod
    def make_nfo_movie(cls, info, output='text', filename='movie.nfo', savepath=None):
        text = cls._make_nfo_movie(info)
        if text is None:
            logger.error("NFO 본문 생성 실패로 저장을 중단합니다.")
            return None
        if output == 'text':
            return text
        elif output == 'xml':
            return app.response_class(text, mimetype='application/xml')
        elif output == 'file':
            from io import StringIO
            output_stream = StringIO(u'%s' % text)
            response = Response(
                output_stream.getvalue().encode('utf-8'),
                mimetype='application/xml',
                content_type='application/octet-stream',
            )
            response.headers["Content-Disposition"] = "attachment; filename=%s" % filename
            return response
        elif output == 'save':
            if savepath is not None:
                return SupportFile.write_file(savepath, text)

    @classmethod
    def make_yaml_movie(cls, info, output='string', filename=None):
        """
        메타데이터(info)를 받아 YAML 문자열 또는 파일 응답을 생성합니다.
        """
        try:
            yaml_data = cls._make_yaml_movie(info)
            if yaml_data is None:
                return None

            if output == 'file':
                if filename is None:
                    filename = f"{info.get('originaltitle', 'movie').upper()}.yaml"
                
                if yaml:
                    yaml_string = yaml.dump(yaml_data, allow_unicode=True, sort_keys=False, indent=2)
                else:
                    # yaml 라이브러리가 없는 경우 에러 처리
                    return "PyYAML library not installed."
                
                from flask import Response
                return Response(
                    yaml_string,
                    mimetype='application/x-yaml',
                    headers={'Content-disposition': f'attachment; filename="{filename}"'}
                )
            
            return yaml_data
            
        except Exception as e:
            logger.error(f"Error in make_yaml_movie: {e}")
            logger.error(traceback.format_exc())
            return None

    @classmethod
    def _make_yaml_movie(cls, info):
        """
        _make_nfo_movie와 유사한 구조로, 메타데이터를 YAML용 딕셔너리로 변환합니다.
        """
        try:
            # 헬퍼: lxml 객체를 순수 문자열로 변환
            def clean_str(val):
                if val is None: return ''
                return str(val).strip()

            # 기본 템플릿 생성
            yaml_data = {
                'primary': True,
                'code': clean_str(info.get('code', '')),
                'title': clean_str(info.get('title', '')),
                'original_title': clean_str(info.get('originaltitle', '')),
                'title_sort': clean_str(info.get('sorttitle', '')),
                'originally_available_at': clean_str(info.get('premiered', '')),
                'year': info.get('year'), # int는 그대로
                'studio': clean_str(info.get('studio', '')),
                'content_rating': clean_str(info.get('mpaa', '')),
                'tagline': clean_str(info.get('tagline', '')),
                'summary': clean_str(info.get('plot', '')),
                'genres': [clean_str(x) for x in (info.get('genre') or [])],
                'collections': [clean_str(x) for x in (info.get('tag') or [])],
                'countries': [clean_str(x) for x in (info.get('country') or [])],
                'directors': [],
                'roles': [],
                'posters': [],
                'art': [],
                'extras': []
            }

            # 감독
            if director := info.get('director'):
                yaml_data['directors'].append(director)

            # 평점
            if ratings := info.get('ratings'):
                if isinstance(ratings, list) and ratings:
                    try:
                        val = float(ratings[0]['value'])
                        yaml_data['rating'] = val * 2 if ratings[0]['max'] == 5 else val
                    except: pass
            
            # 썸네일 (포스터, 랜드스케이프)
            if thumbs := info.get('thumb'):
                for item in thumbs:
                    if item.get('aspect') == 'poster':
                        yaml_data['posters'].append({'url': item.get('value')})
                    elif item.get('aspect') == 'landscape':
                        yaml_data['art'].append({'url': item.get('value')})
            
            # 팬아트
            if fanarts := info.get('fanart'):
                for item in fanarts:
                    yaml_data['art'].append({'url': item})
            
            # 부가 영상
            if extras := info.get('extras'):
                for item in extras:
                    if item.get('content_type') == 'trailer':
                        yaml_data['extras'].append({
                            'mode': 'url', 'type': 'trailer', 'title': item.get('title'),
                            'url': item.get('content_url'), 'thumb': ''
                        })
            
            # 배우
            if actors := info.get('actor'):
                for item in actors:
                    name_ko_val = clean_str(item.get('name_ko', ''))
                    name_org_val = clean_str(item.get('name_org') or item.get('originalname', ''))
                    name_en_val = clean_str(item.get('name_en', ''))
                    display_name = name_ko_val or name_org_val or clean_str(item.get('name', ''))

                    role_dict = {
                        'name': display_name,
                        'name_ko': name_ko_val,
                        'name_org': name_org_val,
                        'name_en': name_en_val,
                        'role': name_org_val or clean_str(item.get('role', '출연')),
                        'photo': clean_str(item.get('thumb', ''))
                    }
                    yaml_data['roles'].append(role_dict)

            return yaml_data
        except Exception as e:
            logger.error(f"Error in _make_yaml_movie: {e}")
            logger.error(traceback.format_exc())
            return None
