import os

from support import SupportSC

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
