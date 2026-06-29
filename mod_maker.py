from .setup import *
from .task_maker import Task
from .site.cli_make_sheet import CliMakeSheet

class ModuleMaker(PluginModuleBase):
    def __init__(self, P):
        super(ModuleMaker, self).__init__(P, name='maker', first_menu='setting', scheduler_desc="epg_data.db 생성")
        self.db_default = {
            f'{self.name}_db_version' : '1',
            f'{self.name}_auto_start' : 'False',
            f'{self.name}_interval' : '120',
            f'{self.name}_force_update' : 'False',
            f'{self.name}_epg_url' : 'https://ff.cothr.duckdns.org/myepg/api/epgall?apikey=a456456456',
        }
    
    def process_command(self, command, arg1, arg2, arg3, req):
        try:
            ret = {'ret':'success'}
            if command == 'sheet':
                # 구글 시트 기능 제거됨
                ret = {'ret':'warning', 'msg':'구글 시트 연동 기능이 제거되었습니다.'}
            elif command == 'git_upload':
                def func():
                    func = Task.start
                    time.sleep(1)
                    if F.config['use_celery']:
                        result = Task.upload.apply_async()
                        ret = result.get()
                    else:
                        ret = Task.upload()
                th = threading.Thread(target=func, args=())
                th.setDaemon(True)
                th.start()
                th.join()
                ret['msg'] = '명령전달'

            return jsonify(ret)
        except Exception as e: 
            P.logger.error(f'Exception:{str(e)}')
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'danger', 'msg':str(e)})

    
    def scheduler_function(self):
        def func():
            func = Task.start
            time.sleep(1)
            if F.config['use_celery']:
                result = Task.start.apply_async()
                ret = result.get()
            else:
                ret = Task.start()
        
        if P.ModelSettingDATA.get('updated_time') == None:
            P.ModelSettingDATA.set('updated_time', '')

        th = threading.Thread(target=func, args=())
        th.setDaemon(True)
        th.start()
        th.join()
    
        
    #########################################################

    