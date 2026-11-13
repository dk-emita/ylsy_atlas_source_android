from pathlib import Path
from server import create_server
from com.ylsyatlas.mobile import AndroidSecretStore
from java import jclass
JavaString = jclass("java.lang.String")
import threading, webbrowser
_server = None
_server_thread = None
class _SecretStore:
 def __init__(self, context): self.store = AndroidSecretStore(context)
 def get_password(self, service, account): return self.store.getPassword(JavaString(str(service)), JavaString(str(account)))
 def set_password(self, service, account, value): return self.store.setPassword(JavaString(str(service)), JavaString(str(account)), JavaString(str(value)))
 def delete_password(self, service, account): return self.store.deletePassword(JavaString(str(service)), JavaString(str(account)))
class _Browser:
 def open(self,url,new=0,autoraise=True):
  from com.ylsyatlas.mobile import AndroidBridge
  address=str(url or '').strip()
  if not address.lower().startswith(('https://','http://')): raise RuntimeError('Google giriş bağlantısı oluşturulamadı.')
  AndroidBridge.startOAuthNetworkSession()
  AndroidBridge.openUrl(address); return True
def start_server(context):
 global _server, _server_thread
 if _server is not None and _server_thread is not None and _server_thread.is_alive():
  return _server.atlas_url
 app=context.getApplicationContext(); data_dir=Path(str(app.getFilesDir().getAbsolutePath()))/"workspace"
 webbrowser.register("android",None,_Browser()); webbrowser._tryorder=["android"]
 _server=create_server(root=data_dir,port=0,start_cloud_worker=False,secret_store=_SecretStore(app),
                       oauth_return_uri='ylsyatlas://oauth-complete')
 if _server.atlas_cloud.connected and _server.atlas_cloud.config.get('local_purged'):
  try:
   _server.atlas_cloud.sync_once()
  except Exception as error:
   _server.atlas_cloud.status_text='Çevrimdışı: yedekli kayıtlar bağlantı gelince alınacak'
   _server.atlas_cloud.error=str(error)[:240]
 if _server.atlas_cloud.connected:
  _server.atlas_cloud._start_worker()
 _server_thread=threading.Thread(target=_server.serve_forever,name="AtlasHttp",daemon=True)
 _server_thread.start()
 return _server.atlas_url

def stop_server():
 global _server, _server_thread
 server=_server
 if server is None: return
 try:
  server.shutdown()
  server.server_close()
  server.atlas_cloud.close()
  server.atlas_cloud.purge_verified_local_data()
 finally:
  _server=None
  _server_thread=None
