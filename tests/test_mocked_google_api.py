"""Drive API contract test with a deterministic mock (no live Google account)."""
import hashlib, json, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import Store
from drive_sync import CloudController, APP_KEY

class FakeDrive:
    def __init__(self):self.data={};self.seq=0;self.folder_id='folder-id'
    def get_or_create_app_folder(self,parent):return self.folder_id
    def list_docs(self):
        return {key:{'id':key,'md5Checksum':hashlib.md5(data).hexdigest(), 'key':key} for key,data in self.data.items()}
    def put_doc(self,key,data,file_id):
        self.data[key]=data
        return self.list_docs()[key]
    def doc_info(self,file_id):
        return self.list_docs().get(file_id)
    def get_doc(self,file_id):return self.data[file_id]

with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    drive=FakeDrive()
    local=Store(root/'one');c=CloudController(local,root/'res')
    c._drive=lambda folder_id=None: drive
    c._start_worker=lambda:None
    c.credentials=object()
    doc=local.save('documents', {'title':'Doktora belgeleri','html':'<p>Özgeçmiş</p>'})
    assert c.dirty
    c.select_google_folder('root')
    c.sync_once()
    assert APP_KEY in drive.data
    assert not c.dirty and c.synced
    assert drive.list_docs()[APP_KEY]['md5Checksum']==c.last_remote
    assert not c.conflict_blocked
    # Second machine loads from cloud, without creating a new empty archive.
    local2=Store(root/'two');c2=CloudController(local2,root/'res');c2._drive=lambda folder_id=None:drive;c2.credentials=object();c2._start_worker=lambda:None
    c2.select_google_folder('root');c2.sync_once()
    assert local2.all('documents')[0]['html']=='<p>Özgeçmiş</p>'
    # A local edit is saved to remote on a later sync.
    local2.save('documents', {'html':'<p>Yeni metin</p>'},doc['id'])
    c2.sync_once();assert c2.synced
    c.sync_once();assert local.all('documents')[0]['html']=='<p>Yeni metin</p>'
    # Overlapping edits never silently overwrite other computer's data.
    local.save('documents', {'html':'<p>Bilgisayar A</p>'},doc['id'])
    local2.save('documents', {'html':'<p>Bilgisayar B</p>'},doc['id'])
    c2.sync_once();c.sync_once()
    assert c.conflict_blocked
    assert local.all('documents')[0]['html']=='<p>Bilgisayar A</p>'
    assert any(key.startswith('atlas-conflict-') for key in drive.data)
    old=drive.data[APP_KEY];c.sync_once();assert drive.data[APP_KEY]==old
    c.close();c2.close()
    print('PASS: server-verified MD5 mock, second-device restore, incremental sync, simultaneous edits stored as conflict, no silent data loss')
