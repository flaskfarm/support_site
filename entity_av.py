# -*- coding: utf-8 -*-
class EntityAVSearch(object):
    def __init__(self, site):
        self.site = site
        self.ui_code = None
        self.code = None
        self.image_url = None
        self.title = None
        self.title_ko = None
        self.score = 0
        self.desc = ''
        self.year = 1900
        self.content_type = None


    def __repr__(self):
        tmp = 'site : %s\n' % self.site
        tmp += 'code : %s\n' % self.code
        tmp += 'ui_code : %s\n' % self.ui_code
        tmp += 'image_url : %s\n' % self.image_url
        tmp += 'title : %s\n' % self.title
        tmp += 'title_ko : %s\n' % self.title_ko
        tmp += 'content_type : %s\n' % self.content_type
        tmp += 'score : %s\n' % self.score
        tmp += 'desc : %s\n' % self.desc
        tmp += 'year : %s\n' % self.year
        return tmp


    def as_dict(self):
        return {
            'site' : self.site,
            'code' : self.code,
            'ui_code' : self.ui_code,
            'image_url' : self.image_url,
            'title' : self.title,
            'title_ko' : self.title_ko,
            'content_type' : self.content_type,
            'score' : self.score,
            'desc' : self.desc,
            'year' : self.year,
        }
