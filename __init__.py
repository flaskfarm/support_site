import os

try:
    import xmltodict
except:
    os.system("pip install xmltodict")

try:
    import lxml
except:
    os.system("pip install lxml")

from support import SupportSC

from .site_util import SiteUtil

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'wavve.py')):
        from .wavve import SupportWavve
    else:
        SupportWavve = SupportSC.load_module_f(__file__, 'wavve').SupportWavve
except:
    pass

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'kakaotv.py')):
        from .kakaotv import SupportKakaotv
    else:
        SupportKakaotv = SupportSC.load_module_f(__file__, 'kakaotv').SupportKakaotv
except:
    pass

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'seezn.py')):
        from .seezn import SupportSeezn
    else:
        SupportSeezn = SupportSC.load_module_f(__file__, 'seezn').SupportSeezn
except:
    pass

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'tving.py')):
        from .tving import SupportTving
    else:
        SupportTving = SupportSC.load_module_f(__file__, 'tving').SupportTving
except:
    pass


try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'cppl.py')):
        from .cppl import SupportCppl
    else:
        SupportCppl = SupportSC.load_module_f(__file__, 'cppl').SupportCppl
except:
    pass


try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'dl_watcha.py')):
        from .dl_watcha import DL_Watcha
    else:
        DL_Watcha = SupportSC.load_module_f(__file__, 'dl_watcha').DL_Watcha
except:
    pass


from .server_util import MetadataServerUtil
from .site_daum import SiteDaum
from .site_daum_movie import SiteDaumMovie
from .site_daum_tv import SiteDaumTv
from .site_lastfm import SiteLastfm
from .site_melon import SiteMelon
from .site_naver import SiteNaver, SiteNaverMovie
from .site_naver_book import SiteNaverBook
from .site_tmdb import SiteTmdbFtv, SiteTmdbMovie, SiteTmdbTv
from .site_tvdb import SiteTvdbTv
from .site_tving import SiteTvingMovie, SiteTvingTv
from .site_vibe import SiteVibe
from .site_watcha import SiteWatchaMovie, SiteWatchaTv
from .site_wavve import SiteWavveMovie, SiteWavveTv
from .tool_imgur import ToolImgur

"""
from .site_fc2.site_7mmtv import Site7mmTv
from .site_fc2.site_bp4x import SiteBp4x
from .site_fc2.site_fc2cm import SiteFc2Cm
from .site_fc2.site_fc2com import SiteFc2Com
from .site_fc2.site_fc2hub import SiteFc2Hub
from .site_fc2.site_msin import SiteMsin
from .site_dmm import SiteDmm
from .site_jav321 import SiteJav321
from .site_javbus import SiteJavbus
from .site_mgstage import SiteMgstageAma, SiteMgstageDvd
from .site_uncensored.site_1pondotv import Site1PondoTv
from .site_uncensored.site_10musume import Site10Musume
from .site_uncensored.site_carib import SiteCarib
from .site_uncensored.site_heyzo import SiteHeyzo
"""
