from support.base.file import SupportFile
from support.base.sub_process import SupportSubprocess

from .setup import *
import sqlite3
import requests
from lxml import etree as ET
from datetime import datetime

class Task(object):

    @staticmethod
    @celery.task
    def start(*args, **kargs):
        with F.app.app_context():
            logger.info("EPG MAKER start..")
            
            # 사용자 지정 EPG XML URL 획득
            epg_url = P.ModelSetting.get('maker_epg_url')
            if not epg_url:
                logger.error("설정된 EPG XML URL이 없습니다.")
                return False
            
            # 커스텀 EPG 수집 시작
            ret = Task.make_epg_from_custom_xml(epg_url)
            
            # 후속 처리 (VACUUM 및 xmltv.xml 생성/업로드)
            if ret:
                try:
                    conn = sqlite3.connect(EPG_DATA_DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute('VACUUM;')
                    conn.commit()
                    conn.close()
                    logger.info("VACUUM done.")
                except Exception as e:
                    logger.error(f'Exception:{str(e)}')
                    logger.error(traceback.format_exc())
                
                P.ModelSettingDATA.set('updated_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                from .task_xml import Task as TaskXml
                TaskXml.make_xml('all', no_update=True)
                # Task.upload()
                
            logger.info("EPG MAKER end..")

    @staticmethod
    def make_epg_from_custom_xml(epg_url):
        try:
            logger.info(f"Custom EPG XML 다운로드 시작: {epg_url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36"
            }
            response = requests.get(epg_url, headers=headers, timeout=30)
            response.raise_for_status()
            logger.info("Custom EPG XML 다운로드 완료 및 파싱 시작")
            
            parser = ET.XMLParser(recover=True, encoding='utf-8')
            root = ET.fromstring(response.content, parser=parser)
            
            # 1. 채널 정보 파싱 및 저장
            db_channels = {ch.name: ch for ch in ModelEpgChannel.get_list()}
            
            for channel_node in root.xpath('//channel'):
                channel_id = channel_node.get('id')
                if not channel_id:
                    continue
                
                display_name_node = channel_node.find('display-name')
                display_name = display_name_node.text if display_name_node is not None else channel_id
                
                icon_node = channel_node.find('icon')
                icon_src = icon_node.get('src') if icon_node is not None else ""
                
                if channel_id in db_channels:
                    ch = db_channels[channel_id]
                else:
                    ch = ModelEpgChannel()
                    ch.name = channel_id
                    ch.aka = f"{channel_id}\n{display_name}"
                    ch.created_time = datetime.now()
                    db_channels[channel_id] = ch
                
                ch.icon = icon_src
                ch.update_time = datetime.now()
                ch.epg_from = 'myepg'
                db.session.add(ch)
            
            db.session.commit()
            logger.info(f"채널 DB 업데이트 완료 (총 {len(db_channels)}개 채널)")
            
            # 2. 프로그램 정보 파싱 및 저장
            for name in db_channels.keys():
                ModelEpgProgram.delete_by_channel_name(name)
            
            program_count = 0
            for prog_node in root.xpath('//programme'):
                channel_id = prog_node.get('channel')
                if channel_id not in db_channels:
                    continue
                
                start_str = prog_node.get('start')
                stop_str = prog_node.get('stop')
                if not start_str or not stop_str:
                    continue
                
                start_time = datetime.strptime(start_str[:14], '%Y%m%d%H%M%S')
                end_time = datetime.strptime(stop_str[:14], '%Y%m%d%H%M%S')
                
                title_node = prog_node.find('title')
                title = title_node.text if title_node is not None else ""
                
                desc_node = prog_node.find('desc')
                desc = desc_node.text if desc_node is not None else None
                
                category_node = prog_node.find('category')
                genre = category_node.text if category_node is not None else None
                
                rate = None
                rating_node = prog_node.find('rating')
                if rating_node is not None:
                    value_node = rating_node.find('value')
                    if value_node is not None:
                        rate = value_node.text
                
                episode_number = None
                episode_node = prog_node.find('episode-num')
                if episode_node is not None:
                    episode_number = episode_node.text
                
                poster = None
                icon_node = prog_node.find('icon')
                if icon_node is not None:
                    poster = icon_node.get('src')
                
                actor = None
                director = None
                credits_node = prog_node.find('credits')
                if credits_node is not None:
                    actors = [a.text for a in credits_node.findall('actor') if a.text]
                    directors = [d.text for d in credits_node.findall('director') if d.text]
                    if actors:
                        actor = '|'.join(actors)
                    if directors:
                        director = '|'.join(directors)
                
                re_flag = False
                if '(재)' in title:
                    re_flag = True
                
                p = ModelEpgProgram()
                p.channel_name = channel_id
                p.start_time = start_time
                p.end_time = end_time
                p.title = title
                p.desc = desc
                p.genre = genre
                p.rate = rate
                p.episode_number = episode_number
                p.poster = poster
                p.actor = actor
                p.director = director
                p.re = re_flag
                p.created_time = datetime.now()
                
                db.session.add(p)
                program_count += 1
            
            db.session.commit()
            logger.info(f"EPG 프로그램 정보 저장 완료 (총 {program_count}개 프로그램)")
            return True
        except Exception as e:
            logger.error(f"Custom EPG XML 처리 중 예외 발생: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def make_channel_list(sheet):
        sheet_data = sheet.get_sheet_data()
        # 없어진 채널을 삭제한다.
        db_data = ModelEpgChannel.get_list()
        for db_item in db_data:
            ret = Task.find_in_sheet(sheet_data, db_item.name)
            if ret == None:
                ModelEpgProgram.delete_by_channel_name(db_item.name)
                ModelEpgChannel.delete_by_id(db_item.id)

        for sheet_item in sheet_data:
            if sheet_item['카테고리'] in ['', '미사용']:
                continue
            db_item = ModelEpgChannel.get_by_name(sheet_item['이름'])    
            if db_item == None:
                db_item = ModelEpgChannel()
            db_item.update(sheet_item)

    
    @staticmethod
    def find_in_sheet(sheet_data, name):
        for item in sheet_data:
            if item['이름'] == name and item['카테고리'] != '미사용':
                return item


    @staticmethod
    @celery.task
    def upload():
        try:
            import platform
            import shutil
            git_home = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.epg.db')
            upload_sh = os.path.join(git_home, 'epg_upload.sh')

            time_file = os.path.join(os.path.dirname(__file__), 'files', 'UPDATED_TIME')
            SupportFile.write_file(time_file, P.ModelSettingDATA.get('updated_time'))
            names = ['epg_data.db', 'xmltv.xml', 'UPDATED_TIME']
            for name in names:
                file1 = os.path.join(os.path.dirname(__file__), 'files', name)
                file2 = os.path.join(git_home, name)
                if os.path.exists(file2):
                    os.remove(file2)
                #shutil.move(file1, file2)
                shutil.copyfile(file1, file2)

            if platform.system() == 'Windows':
                git_bash  = "C:\\Program Files\\Git\\bin\\bash.exe"
                cmd = [git_bash, 'chmod', '777', upload_sh]
                ret = SupportSubprocess.execute_command_return(cmd, timeout=60)
                logger.info(ret)
                cmd = [git_bash, upload_sh, git_home]
                ret = SupportSubprocess.execute_command_return(cmd, timeout=60)
                logger.info(ret)
            else:
                os.system(f"chmod 777 {upload_sh}")
                cmd = [upload_sh, git_home]
                logger.info(f"upload command: {' '.join(cmd)}")
                ret = SupportSubprocess.execute_command_return(cmd, timeout=60)
                logger.info(ret)
        except Exception as e: 
            logger.error(f'Exception:{str(e)}')
            logger.error(traceback.format_exc())

    @staticmethod
    def is_need_epg_make(db_item):
        #return True
        #if db_item.update_time + timedelta(days=1) > datetime.now():
        if db_item.update_time == None or db_item.update_time + timedelta(hours=12) < datetime.now():
            return True
        if P.ModelSetting.get('maker_force_update'):
            return True
        return False

 
if __name__ == '__main__':
    Task.start()
    