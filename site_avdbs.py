
# -*- coding: utf-8 -*-
import os, traceback

import requests
from lxml import html

from framework import SystemModelSetting, py_urllib
from system import SystemLogicTrans

from .plugin import P
from .site_util import SiteUtil

logger = P.logger

# 사이트 차단

class SiteAvdbs(object):
    site_char = 'A'
    @staticmethod
    def get_actor_info(entity_actor, proxy_url=None, retry=True):
        try:
            seq_url = 'https://www.avdbs.com/w2017/api/iux_kwd_srch_log.php?op=srch&kwd=%s' % entity_actor['originalname']
            proxies = None
            if proxy_url is not None:
                proxies = {"http"  : proxy_url, "https" : proxy_url}
            try:
                seq_val = requests.get(seq_url, headers=SiteUtil.default_headers, proxies=proxies, timeout=5).json()['seq']
                logger.debug(seq_val)
                url = 'https://www.avdbs.com/w2017/page/search/search_actor.php?kwd=%s&seq=%s' % (entity_actor['originalname'], seq_val)
                logger.debug(url)
                res = requests.get(url, headers=SiteUtil.default_headers, proxies=proxies, timeout=5)
            except Exception as exception: 
                logger.error('Exception:%s', exception)
                logger.error(traceback.format_exc())
            #logger.debug('avdbs status code : %s', res.status_code)
            #logger.debug(res.text)
            res.encoding = 'utf-8'
            data = '<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\">' + res.text
            tree = html.fromstring(data)
            img_tag = tree.xpath('//img')

            if img_tag:
                nodes = tree.xpath('//div[@class="dscr"]/p')
                tmp = nodes[1].xpath('./a')[0].text_content().strip()
                #tmp = nodes[1].xpath('./a')[0].text_content().strip()
                if tmp.split('(')[1].split(')')[0] or tmp.split('（')[1].split('）')[0] == entity_actor['originalname']:
                    entity_actor['name'] = nodes[0].xpath('./a')[0].text_content().strip()
                    entity_actor['name2'] = nodes[1].xpath('./a')[0].text_content().strip().split('(')[0]
                    entity_actor['site'] = 'avdbs'
                    entity_actor['thumb'] = SiteUtil.process_image_mode('3', img_tag[0].attrib['src'].strip())
                else:
                    logger.debug('Avads miss match')
            else:
                logger.debug('Avads no match')
            return entity_actor
        except ValueError:
            # 2020-06-01
            # 단시간에 많은 요청시시 Error발생
            if retry:
                logger.debug(u'단시간 많은 요청으로 재요청')
                time.sleep(2)
                return SiteAvdbs.get_actor_info(entity_actor, proxy_url=proxy_url, retry=False)
        except Exception as exception: 
            logger.error('Exception:%s', exception)
            logger.error(traceback.format_exc())
        return entity_actor
