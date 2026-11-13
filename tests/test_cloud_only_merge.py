"""Offline records must merge with cloud data before local cleanup."""
import hashlib
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cloud_merge import merge_new_records
from drive_sync import CloudController
from storage import Store


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    remote = Store(root / 'remote')
    remote.save('universities', {'name': 'Remote University', 'short': 'RU'})
    remote_blob = remote.backup()
    offline = Store(root / 'offline')
    offline.save('universities', {'name': 'Offline University', 'short': 'OU'})
    offline.save('vocabulary', {'word': 'resilient', 'meaning': 'dayanıklı'})
    offline_blob = offline.backup()
    merged = merge_new_records(remote_blob, offline_blob)
    result = Store(root / 'result')
    result.restore(merged, keep_previous=False, notify=False)
    assert {x['name'] for x in result.all('universities')} == {'Remote University', 'Offline University'}
    assert [x['word'] for x in result.all('vocabulary')] == ['resilient']

    # Simulate a previously purged workspace edited without internet.
    client = Store(root / 'client')
    client.save('vocabulary', {'word': 'practice', 'meaning': 'alıştırma'})
    cloud = CloudController(client, root / 'resources', start_worker=False)
    cloud.mode = 'oauth'
    cloud.connected = True
    cloud.dirty = True
    cloud.config.update(mode='oauth', folder_id='fake-folder', dirty=True, local_purged=True)
    remote_md5 = hashlib.md5(remote_blob).hexdigest()
    class Drive:
        def doc_info(self, file_id): return {'md5Checksum': remote_md5}
    cloud._remote = lambda: ({'id': 'remote-id', 'md5Checksum': remote_md5}, remote_blob, Drive())
    cloud._download = lambda info, raw, drive: raw
    uploaded = []
    cloud._upload = lambda contents, remote_info, drive: (uploaded.append(contents) or hashlib.md5(contents).hexdigest())
    cloud.sync_once()
    assert uploaded and not cloud.dirty and not cloud.config['local_purged']
    combined = Store(root / 'combined')
    combined.restore(uploaded[0], keep_previous=False, notify=False)
    assert combined.one('vocabulary', 1)['word'] == 'practice'
    assert combined.one('universities', 1)['name'] == 'Remote University'
    cloud._remote = lambda: ({'id': 'remote-id', 'md5Checksum': cloud.last_remote}, None, Drive())
    cloud.close()
    assert cloud.purge_verified_local_data()
    assert cloud.config['local_purged']
    assert client.all('vocabulary') == [] and client.all('universities') == []
print('PASS: cloud merge, verified local cleanup')
