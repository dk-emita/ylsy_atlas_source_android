from pathlib import Path
from server import create_server
from com.ylsyatlas.mobile import AndroidSecretStore
from java import jclass
JavaString = jclass("java.lang.String")
import threading, webbrowser
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
 app=context.getApplicationContext(); data_dir=Path(str(app.getFilesDir().getAbsolutePath()))/"workspace"
 webbrowser.register("android",None,_Browser()); webbrowser._tryorder=["android"]
 server=create_server(root=data_dir,port=0,start_cloud_worker=True,secret_store=_SecretStore(app))
 threading.Thread(target=server.serve_forever,name="AtlasHttp",daemon=True).start()
 return server.atlas_url
