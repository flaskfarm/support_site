import traceback

from lxml import etree as ET
from lxml.builder import E
import lxml.builder as builder
from flask import Response

from support import SupportFile
from .setup import P, logger, app


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

            movie = E.movie (
                E.title(cls.change_html(info['title'])),
                E.originaltitle(info['originaltitle']),
                E.sorttitle(info['sorttitle']),
                E.id(info['originaltitle']),
                E.uniqueid(info['code'], type=info['site'], default='true'),
            )

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


            if info['thumb'] is not None and len(info['thumb']) > 0:
                for item in info['thumb']:
                    tag = E.thumb(item['value'], aspect=item['aspect'])
                    movie.append(tag)

            if info['fanart'] is not None and len(info['fanart']) > 0:
                for item in info['fanart']:
                    tag = E.fanart(E.thumb(item))
                    movie.append(tag)

            if info['ratings'] is not None and len(info['ratings']) > 0:
                for item in info['ratings']:
                    tag = E.ratings(name=item['name'], max=str(item['max']))
                    cls.append_tag(tag, item, 'value')
                    cls.append_tag(tag, item, 'votes')
                    movie.append(tag)

            if info['extras'] is not None and len(info['extras']) > 0:
                for item in info['extras']:
                    if item['content_type'] == 'trailer':
                        tag = E.trailer(item['content_url'])
                        movie.append(tag)

            if info['actor'] is not None and len(info['actor']) > 0:
                for item in info['actor']:
                    tag = E.actor()
                    cls.append_tag(tag, item, 'name')
                    cls.append_tag(tag, item, 'role')
                    cls.append_tag(tag, item, 'order')
                    cls.append_tag(tag, item, 'thumb')
                    movie.append(tag)

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
