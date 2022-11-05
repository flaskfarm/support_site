from .setup import *


class ModuleSite(PluginModuleBase):
    db_default = {
        f'db_version' : '1',
        f"site_wavve_credential": "",
        f"site_wavve_use_proxy": "False",
        f"site_wavve_proxy_url": "",
    }

    def __init__(self, P):
        super(ModuleSite, self).__init__(P, name='site', first_menu='setting')

    def setting_save_after(self, change_list):
        self.__wavve_init()

    def plugin_load(self):
        self.__wavve_init()
    
    def __wavve_init(self):
        from . import SupportWavve
        SupportWavve.initialize(
            P.ModelSetting.get('site_wavve_credential'),
            P.ModelSetting.get_bool('site_wavve_use_proxy'),
            P.ModelSetting.get('site_wavve_proxy_url'),
        )
