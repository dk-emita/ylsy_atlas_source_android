"""Cloud API integration regression: direct Google Drive API (mocked), not Desktop folder.
Tests involve no real Google account and do not touch a user's Drive.
"""
import hashlib, json, tempfile, time, threading, sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import create_server
from drive_sync import APP_KEY

class FakeDrive:
    def __init__(self): self.data={}; self.folder_id='app-folder'
    def folders_in(self,parent): return [{'name':'YLSY Belgeleri','id':'test-parent'}] if parent=='root' else []
    def get_or_create_app_folder(self,parent):return self.folder_id
    def list_docs(self):return {k:{'id':k,'key':k,'md5Checksum':hashlib.md5(v).hexdigest()} for k,v in self.data.items()}
    def put_doc(self,key,contents,file_id):self.data[key]=contents;return self.list_docs()[key]
    def doc_info(self,file_id):return self.list_docs().get(file_id)
    def get_doc(self,file_id):return self.data[file_id]

def api(srv,path,method='GET',payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=Request(f'http://127.0.0.1:{srv.server_port}/api/{path}',data=data,method=method,headers={'X-Atlas-Token':srv.atlas_token,'Content-Type':'application/json'})
    with urlopen(req,timeout=15) as r:return json.loads(r.read())

def eventually(cond, seconds=14):
    till=time.monotonic()+seconds
    while time.monotonic()<till:
        try:
            if cond():return
        except Exception:pass
        time.sleep(.15)
    raise AssertionError('Condition did not become true')

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    cloud=FakeDrive()
    srv1=create_server(root=root/'device1')
    th1=threading.Thread(target=srv1.serve_forever,daemon=True);th1.start()
    srv2=None
    try:
        assert api(srv1,'guide-pdf/status')['available']
        assert len(api(srv1,'guide'))==46
        assert api(srv1,'cloud/status')['configured'] is True
        assert api(srv1,'cloud/status')['startup_shown'] is False
        api(srv1,'cloud/skip','POST')
        assert api(srv1,'cloud/status')['startup_shown'] is True
        with __import__('contextlib').suppress(HTTPError):
            api(srv1,'cloud/desktop-folder','POST',{'path':str(root)})
            raise AssertionError('Removed Drive Desktop endpoint must return 404')
        assert api(srv1,'documents')==[]
        srv1.atlas_cloud.credentials=object()
        srv1.atlas_cloud._drive=lambda folder_id=None:cloud
        assert api(srv1,'cloud/folders?parent=root')==[{'name':'YLSY Belgeleri','id':'test-parent'}]
        item=api(srv1,'documents','POST',{'title':'sync test','html':'<p>Deneme</p>'})
        assert srv1.atlas_cloud.dirty
        config=api(srv1,'cloud/select-folder','POST',{'parent':'root'})
        assert config['mode']=='oauth' and config['connected']
        eventually(lambda:APP_KEY in cloud.data and not api(srv1,'cloud/status')['dirty'])
        assert api(srv1,'cloud/status')['synchronized']
        srv2=create_server(root=root/'device2');threading.Thread(target=srv2.serve_forever,daemon=True).start()
        assert api(srv2,'documents')==[]
        srv2.atlas_cloud.credentials=object()
        srv2.atlas_cloud._drive=lambda folder_id=None:cloud
        api(srv2,'cloud/select-folder','POST',{'parent':'root'})
        eventually(lambda:len(api(srv2,'documents'))==1)
        assert api(srv2,'documents')[0]['title']=='sync test'
        doc2=api(srv2,'documents')[0]
        api(srv2,f'documents/{doc2["id"]}','PUT',{'html':'<p>İkinci bilgisayar</p>'})
        eventually(lambda:api(srv1,'documents')[0]['html']=='<p>İkinci bilgisayar</p>')
        # Simulate offline and re-online without deleting unsynced records.
        srv1.atlas_cloud._drive=lambda folder_id=None: (_ for _ in ()).throw(OSError('Network unavailable'))
        api(srv1,'tasks','POST',{'title':'İnternet yokken not'})
        assert api(srv1,'tasks')[0]['title']=='İnternet yokken not'
        assert api(srv1,'cloud/status')['dirty']
        srv1.atlas_cloud._drive=lambda folder_id=None:cloud
        eventually(lambda:not api(srv1,'cloud/status')['dirty'] or api(srv1,'cloud/status')['conflict_blocked'])
        assert api(srv1,'tasks')[0]['title']=='İnternet yokken not'
        print('PASS: packaged PDF, no Drive Desktop endpoint, cloud status and folder API, Google API mock sync, second-device restore, offline data preservation')
    finally:
        for srv in (srv1,srv2):
            if srv:
                srv.shutdown();srv.server_close();srv.atlas_cloud.close()
