"""Offline edit survives process restart, then uploads; remote edits merge only if clean."""
from pathlib import Path
import sys, tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import Store
from drive_sync import CloudController, APP_KEY
import hashlib

class FakeDrive:
    def __init__(self): self.data={};self.folder_id='app-folder'
    def get_or_create_app_folder(self, parent): return self.folder_id
    def list_docs(self): return {k:{'id':k, 'key':k, 'md5Checksum':hashlib.md5(v).hexdigest()} for k,v in self.data.items()}
    def put_doc(self,key,contents,file_id): self.data[key]=contents;return self.list_docs()[key]
    def doc_info(self,id): return self.list_docs()[id]
    def get_doc(self,id): return self.data[id]

with tempfile.TemporaryDirectory() as d:
    root=Path(d); resources=root/'res';resources.mkdir()
    drive=FakeDrive()
    s1=Store(root/'machine-A')
    c1=CloudController(s1,resources); c1._drive=lambda folder_id=None:drive;c1._start_worker=lambda:None;c1.credentials=object()
    c1.select_google_folder()
    s1.save('notes',{'title':'online','body':'first version'})
    c1.sync_once();assert not c1.dirty and APP_KEY in drive.data
    # Offline change that has not been uploaded, then app closes.
    s1.save('notes',{'title':'offline','body':'no internet'})
    assert c1.dirty and c1.config.get('dirty') is True
    c1.close()
    c1b=CloudController(s1,resources); c1b._drive=lambda folder_id=None:drive;c1b._start_worker=lambda:None
    assert c1b.connected and c1b.dirty
    c1b.sync_once() # initial catch-up, leaves pending marker intact
    c1b.sync_once() # actual upload
    assert not c1b.dirty and c1b.config.get('dirty') is False
    assert len(s1.all('notes'))==2
    c1b.close()
    # A clean second machine can restore new cloud snapshot and download later revisions.
    s2=Store(root/'machine-B');c2=CloudController(s2,resources);c2._drive=lambda folder_id=None:drive;c2.credentials=object();c2._start_worker=lambda:None
    c2.select_google_folder();c2.sync_once()
    assert len(s2.all('notes'))==2
    s2.save('notes',{'title':'second-device'})
    c2.sync_once()
    c2.close()
    c1c=CloudController(s1,resources);c1c._drive=lambda folder_id=None:drive;c1c._start_worker=lambda:None
    assert c1c.connected and not c1c.dirty
    c1c.sync_once()
    assert len(s1.all('notes'))==3
    assert not c1c.conflict_blocked
    c1c.close()
print('PASS: persisted unsynced flag across restart, later upload, newer remote clean-restore without data loss')
