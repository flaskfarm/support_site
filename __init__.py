import os
import sys
import subprocess
from typing import Sequence


def check_packages(packages: Sequence[tuple[str, str]]) -> None:
    for pkg, pi in packages:
        try:
            __import__(pkg)
        except Exception:
            subprocess.check_call((sys.executable, "-m", "pip", "install", pi))


# support_site 에 필요한 파이썬 패키지 설치
check_packages((
    ("xmltodict", "xmltodict"),
    ("lxml", "lxml"),
    ("imagehash", "imagehash"),
    ("cloudscraper", "cloudscraper"),
    ("tmdbsimple", "tmdbsimple"),
    ("tvdb_api", "tvdb_api"),
    ("requests_cache", "requests-cache"),
    ("discord", "discord.py"),
    ("dateutil", "dateutils"),
))

from support import SupportSC

from .site_util import SiteUtil
from .util_nfo import UtilNfo

try:
    if os.path.exists(os.path.join(os.path.dirname(__file__), 'wavve.py')):
        from .wavve import SupportWavve
    else:
        SupportWavve = SupportSC.load_module_f(__file__, 'wavve').SupportWavve
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
from .site_watcha import SiteWatcha, SiteWatchaKTv, SiteWatchaMovie, SiteWatchaTv
from .site_wavve import SiteWavveMovie, SiteWavveTv
from .tool_imgur import ToolImgur
from .tool_naver_cafe import ToolNaverCafe


from .site_av.site_avdbs import SiteAvdbs
from .site_av.site_dmm import SiteDmm
#from .site_av.site_hentaku import SiteHentaku
from .site_av.site_jav321 import SiteJav321
from .site_av.site_javbus import SiteJavbus
from .site_av.site_mgstage import SiteMgstage
from .site_av.site_javdb import SiteJavdb
from .site_util_av import SiteUtilAv
from .tool_discord import DiscordUtil

from .site_av.site_1pondotv import Site1PondoTv
from .site_av.site_10musume import Site10Musume
from .site_av.site_carib import SiteCarib
from .site_av.site_heyzo import SiteHeyzo
from .site_av.site_fc2ppvdb import SiteFc2ppvdb

"""
from .site_fc2.site_7mmtv import Site7mmTv
from .site_fc2.site_bp4x import SiteBp4x
from .site_fc2.site_fc2cm import SiteFc2Cm
from .site_fc2.site_fc2com import SiteFc2Com
from .site_fc2.site_fc2hub import SiteFc2Hub
from .site_fc2.site_msin import SiteMsin
"""
