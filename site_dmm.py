
# -*- coding: utf-8 -*-
import json
import re
import traceback

import requests
from framework import SystemModelSetting
from framework.util import Util
from lxml import html
from system import SystemLogicTrans

from .entity_av import EntityAVSearch
from .entity_base import (EntityActor, EntityExtra, EntityMovie, EntityRatings,
                          EntityThumb)
from .plugin import P
from .site_util import SiteUtil

logger = P.logger



class SiteDmm(object):
    site_name = 'dmm'
    site_base_url = 'https://www.dmm.co.jp'
    module_char = 'C'
    site_char = 'D'

    dmm_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/71.0.3578.98 Safari/537.36',
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language' : 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cookie' : 'age_check_done=1',
    }

    @classmethod
    def search(cls, keyword, do_trans=True, proxy_url=None, image_mode='0', manual=False):
        try:
            ret = {}
            keyword = keyword.strip().lower()
            # 2020-06-24
            if keyword[-3:-1] == 'cd':
                keyword = keyword[:-3]
            keyword = keyword.replace('-', ' ')
            keyword_tmps = keyword.split(' ')
            if len(keyword_tmps) == 2:
                if len(keyword_tmps[1]) <= 5:
                    dmm_keyword = '%s%s' % (keyword_tmps[0], keyword_tmps[1].zfill(5))
                elif len(keyword_tmps[1]) > 5:
                    dmm_keyword = '%s%s' % (keyword_tmps[0], keyword_tmps[1])
            else:
                dmm_keyword = keyword
            logger.debug('keyword [%s] -> [%s]', keyword, dmm_keyword)

            url = '%s/digital/videoa/-/list/search/=/?searchstr=%s' % (cls.site_base_url, dmm_keyword)
            #url = '%s/search/=/?searchstr=%s' % (cls.site_base_url, dmm_keyword)
            #https://www.dmm.co.jp/search/=/searchstr=tsms00060/
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=cls.dmm_headers)
            lists = tree.xpath('//*[@id="list"]/li')
            ret = {'data' : []}
            score = 60
            logger.debug('dmm search len lists2 :%s', len(lists))
            if len(lists) > 10:
                lists = lists[:10]
            for node in lists:
                try:
                    item = EntityAVSearch(cls.site_name)
                    tag = node.xpath('.//div/p[@class="tmb"]/a')[0]
                    href = tag.attrib['href'].lower()
                    match = re.compile(r'\/cid=(?P<code>.*?)\/').search(href)
                    if match:
                        item.code = cls.module_char + cls.site_char + match.group('code')
                    already_exist = False
                    for exist_item in ret['data']:
                        if exist_item['code'] == item.code:
                            already_exist = True
                            break
                    if already_exist:
                        continue

                    tag = node.xpath('.//span[1]/img')[0]
                    item.title = item.title_ko = tag.attrib['alt']
                    item.image_url = tag.attrib['src']


                    # tmp = SiteUtil.discord_proxy_get_target(item.image_url)
                    # 2021-03-22 서치에는 discord 고정 url을 사용하지 않는다. 3번
                    # manual == False  때는 아예 이미치 처리를 할 필요가 없다.
                    # 일치항목 찾기 때는 화면에 보여줄 필요가 있는데 3번은 하면 하지 않는다.
                    if manual == True:
                        if image_mode == '3':
                            image_mode = '0'
                        item.image_url = SiteUtil.process_image_mode(image_mode, item.image_url, proxy_url=proxy_url)

                    if do_trans:
                        item.title_ko = SiteUtil.trans(item.title, source='ja', target='ko')

                    match = re.compile(r'^(h_)?\d*(?P<real>[a-zA-Z]+)(?P<no>\d+)([a-zA-Z]+)?$').search(item.code[2:])
                    if match:
                        item.ui_code = '%s%s' % (match.group('real'), match.group('no'))
                    else:
                        item.ui_code = item.code[2:]

                    if len(keyword_tmps) == 2:
                        #2019-11-20 ntr mntr 둘다100
                        if item.ui_code == dmm_keyword:
                            item.score = 100
                        elif item.ui_code.replace('0','') == dmm_keyword.replace('0',''):
                            item.score = 100
                        elif item.ui_code.find(dmm_keyword) != -1: #전체포함 DAID => AID
                            item.score = score
                            score += -5
                        elif item.code.find(keyword_tmps[0]) != -1 and item.code.find(keyword_tmps[1]) != -1:
                            item.score = score
                            score += -5
                        elif item.code.find(keyword_tmps[0]) != -1 or item.code.find(keyword_tmps[1]) != -1:
                            item.score = 60
                        else:
                            item.score = 20
                    else:
                        if item.code == keyword_tmps[0]:
                            item.score = 100
                        elif item.code.find(keyword_tmps[0]) != -1:
                            item.score = score
                            score += -5
                        else:
                            item.score = 20

                    if match:
                        item.ui_code = '%s-%s' % (match.group('real').upper(), str(int(match.group('no'))).zfill(3))
                    else:
                        if item.ui_code.find ('0000') != -1:
                            item.ui_code = item.ui_code.replace('0000', '-00').upper()
                        else:
                            item.ui_code = item.ui_code.replace('00', '-').upper()
                        if item.ui_code.endswith('-'):
                            item.ui_code = '%s00' % (item.ui_code[:-1])

                    logger.debug('score :%s %s ', item.score, item.ui_code)
                    ret['data'].append(item.as_dict())
                except Exception as e:
                    logger.error(f"Exception:{str(e)}")
                    logger.error(traceback.format_exc())
            ret['data'] = sorted(ret['data'], key=lambda k: k['score'], reverse=True)
            ret['ret'] = 'success'
            if len(ret['data']) == 0 and len(keyword_tmps) == 2 and len(keyword_tmps[1]) == 5:
                new_title = '%s%s' % (keyword_tmps[0], keyword_tmps[1].zfill(6))
                return cls.search(new_title, do_trans=do_trans, proxy_url=proxy_url, image_mode=image_mode)
        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret



    @classmethod
    def info(cls, code, do_trans=True, proxy_url=None, image_mode='0', small_image_to_poster_list=[]):
        try:
            ret = {}
            url = '%s/digital/videoa/-/detail/=/cid=%s/' % (cls.site_base_url, code[2:])
            tree = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=cls.dmm_headers)

            entity = EntityMovie(cls.site_name, code)
            entity.country = [u'일본']
            entity.mpaa = u'청소년 관람불가'
            entity.thumb = []
            basetag = '//*[@id="mu"]/div/table//tr/td[1]'
            nodes = tree.xpath('{basetag}/div[1]/div[1]'.format(basetag=basetag))
            if not nodes:
                ret['ret'] = 'fail_tag_not_exist'
                logger.debug('CRITICAL!!!')
                return ret

            # 2021-12-01 : div[2]/img  인 것들이 있음
            # 예) thtp00052
            tmp_nodes = tree.xpath('{basetag}/div[1]/div'.format(basetag=basetag))
            if len(tmp_nodes) == 2:
                nodes = [tmp_nodes[1]]

            #logger.debug('crs-full :%s ', len(a_nodes))
            # 2020-05-31 A태그가 없는 경우가 있음. 확대이미지가 없는 경우  tsds-42464
            #if a_nodes:
            # svoks stvf - 확대이미지가 포스터. 이미지 크기로 자르지 않고 포스터러 결정됨
            # stcead - 확대이지미가 랜드스케이프. 축소 이미지를 포스터로 사용

            small_img_to_poster = False
            for tmp in small_image_to_poster_list:
                if code.find(tmp) != -1:
                    small_img_to_poster = True
                    break

            try:
                a_nodes = nodes[0].xpath('.//a')
                anodes = a_nodes
                #logger.debug(html.tostring(anodes[0]))
                img_tag = anodes[0].xpath('.//img')[0]
                if small_img_to_poster:
                    data = SiteUtil.get_image_url(a_nodes[0].attrib['href'], image_mode, proxy_url=proxy_url, with_poster=False)
                    entity.thumb.append(EntityThumb(aspect='landscape', value=data['image_url']))
                else:
                    data = SiteUtil.get_image_url(a_nodes[0].attrib['href'], image_mode, proxy_url=proxy_url, with_poster=True)
                    entity.thumb.append(EntityThumb(aspect='landscape', value=data['image_url']))
                    entity.thumb.append(EntityThumb(aspect='poster', value=data['poster_image_url']))
            except:
                small_img_to_poster = True

            if small_img_to_poster:
                img_tag = nodes[0].xpath('.//img')[0]
                entity.thumb.append(EntityThumb(aspect='poster', value=SiteUtil.process_image_mode(image_mode, img_tag.attrib['src'], proxy_url=proxy_url)))


            entity.tagline = SiteUtil.trans(img_tag.attrib['alt'], do_trans=do_trans).replace(u'[배달 전용]', '').replace(u'[특가]', '').strip()
            tags = tree.xpath('{basetag}/table//tr'.format(basetag=basetag))
            tmp_premiered = None
            for tag in tags:
                td_tag = tag.xpath('.//td')
                if len(td_tag) != 2:
                    continue
                key = td_tag[0].text_content().strip()
                value = td_tag[1].text_content().strip()
                if value == '----':
                    continue
                if key == u'商品発売日：':
                    entity.premiered = value.replace('/', '-')
                    entity.year = int(value[:4])
                elif key == u'配信開始日：':
                    tmp_premiered = value.replace('/', '-')
                elif key == u'収録時間：':
                    entity.runtime = int(value.replace(u'分', ''))
                elif key == u'出演者：':
                    entity.actor = []
                    a_tags = tag.xpath('.//a')
                    for a_tag in a_tags:
                        tmp = a_tag.text_content().strip()
                        if tmp == u'▼すべて表示する':
                            break
                        entity.actor.append(EntityActor(tmp))
                    #for v in value.split(' '):
                    #    entity.actor.append(EntityActor(v.strip()))
                elif key == u'監督：':
                    entity.director =  value
                elif key == u'シリーズ：':
                    if entity.tag is None:
                        entity.tag = []
                    entity.tag.append(SiteUtil.trans(value, do_trans=do_trans))
                elif key == u'レーベル：':
                    entity.studio = value
                    if do_trans:
                        if value in SiteUtil.av_studio:
                            entity.studio = SiteUtil.av_studio[value]
                        else:
                            entity.studio = SiteUtil.change_html(SiteUtil.trans(value, do_trans=do_trans))
                elif key == u'ジャンル：':
                    a_tags = td_tag[1].xpath('.//a')
                    entity.genre = []
                    for tag in a_tags:
                        tmp = tag.text_content().strip()
                        if tmp.find('％OFF') != -1:
                            continue
                        if tmp in SiteUtil.av_genre:
                            entity.genre.append(SiteUtil.av_genre[tmp])
                        elif tmp in SiteUtil.av_genre_ignore_ja:
                            continue
                        else:
                            genre_tmp = SiteUtil.trans(tmp, do_trans=do_trans).replace(' ', '')
                            if genre_tmp not in SiteUtil.av_genre_ignore_ko:
                                entity.genre.append(genre_tmp)
                elif key == u'品番：':
                    #24id
                    match = re.compile('\d{2}id', re.I).search(value)
                    id_before = None
                    if match:
                        id_before = match.group(0)
                        value = value.lower().replace(id_before, 'zzid')

                    match = re.compile(r'^(h_)?\d*(?P<real>[a-zA-Z]+)(?P<no>\d+)([a-zA-Z]+)?$').match(value)
                    if match:
                        label = match.group('real').upper()
                        if id_before is not None:
                            label = label.replace('ZZID', id_before.upper())

                        value = '%s-%s' % (label, str(int(match.group('no'))).zfill(3))
                        if entity.tag is None:
                            entity.tag = []
                        entity.tag.append(label)
                    entity.title = entity.originaltitle = entity.sorttitle = value
            if entity.premiered is None and tmp_premiered is not None:
                entity.premiered = tmp_premiered
                entity.year = int(tmp_premiered[:4])

            try:
                tag = tree.xpath('{basetag}/table//tr[13]/td[2]/img'.format(basetag=basetag))
                if tag:
                    match = re.compile(r'(?P<rating>[\d|_]+)\.gif').search(tag[0].attrib['src'])
                    if match:
                        tmp = match.group('rating')
                        entity.ratings = [EntityRatings(float(tmp.replace('_', '.')), max=5, name='dmm', image_url=tag[0].attrib['src'])]
            except Exception as e:
                #logger.error(f"Exception:{str(e)}")
                #logger.error(traceback.format_exc())
                logger.error('point exception')

            tmp = tree.xpath('{basetag}/div[4]/text()'.format(basetag=basetag))[0]
            tmp = tmp.split('※')[0].strip()
            entity.plot = SiteUtil.trans(tmp, do_trans=do_trans)

            nodes = tree.xpath('//*[@id="sample-image-block"]/a')
            entity.fanart = []
            for idx, node in enumerate(nodes):
                if idx > 9:
                    break
                tag = node.xpath('.//img')
                tmp = tag[0].attrib['src']
                image_url = tag[0].attrib['src'].replace(entity.code[2:]+'-', entity.code[2:]+'jp-')
                #discord_url = SiteUtil.process_image_mode(image_mode, image_url, proxy_url=proxy_url)
                entity.fanart.append(image_url)

            try:
                if tree.xpath('//div[@class="d-review__points"]/p[1]/strong'):
                    point = float(tree.xpath('//div[@class="d-review__points"]/p[1]/strong')[0].text_content().replace(u'点', '').strip())
                    votes = int(tree.xpath('//div[@class="d-review__points"]/p[2]/strong')[0].text_content().strip())
                    entity.ratings[0].value = point
                    entity.ratings[0].votes = votes
            except Exception as e:
                logger.error(f"Exception:{str(e)}")
                logger.error(traceback.format_exc())

            try:
                tmp = tree.xpath('//*[@id="detail-sample-movie"]/div/a')
                if tmp:
                    tmp = tmp[0].attrib['onclick']
                    url = cls.site_base_url + tmp.split("'")[1]
                    url = SiteUtil.get_tree(url, proxy_url=proxy_url, headers=cls.dmm_headers).xpath('//iframe')[0].attrib['src']
                    text = SiteUtil.get_text(url, proxy_url=proxy_url, headers=cls.dmm_headers)
                    pos = text.find('var params = {')
                    data = json.loads(text[text.find('{', pos):text.find(';', pos)])
                    #logger.debug(json.dumps(data, indent=4))
                    data['bitrates'] = sorted(data['bitrates'], key=lambda k: k['bitrate'], reverse=True)
                    entity.extras = [EntityExtra('trailer', SiteUtil.trans(data['title'], do_trans=do_trans), 'mp4', 'https:%s' % data['bitrates'][0]['src'])]
            except Exception as e:
                logger.error(f"Exception:{str(e)}")
                logger.error(traceback.format_exc())
            ret['ret'] = 'success'
            ret['data'] = entity.as_dict()

        except Exception as e:
            logger.error(f"Exception:{str(e)}")
            logger.error(traceback.format_exc())
            ret['ret'] = 'exception'
            ret['data'] = str(e)
        return ret