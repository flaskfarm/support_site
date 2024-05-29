setting = {
    'filepath' : __file__,
    'use_db': True,
    'use_default_setting': True,
    'home_module': None,
    'menu': None,
    'setting_menu': {
        'uri': f"support_site",
        'name': 'SUPPORT SITE 설정',
        'list': [
            {'uri': 'setting', 'name': '설정'},
            {'uri': 'manual/files/스캔.md', 'name': '매뉴얼'},
        ]
    },
    'default_route': 'normal',
}


from plugin import *

P = create_plugin_instance(setting)

try:
    from .mod_site import ModuleSite
    P.set_module_list([ModuleSite])
except Exception as e:
    P.logger.error(f'Exception:{str(e)}')
    P.logger.error(traceback.format_exc())

logger = P.logger
