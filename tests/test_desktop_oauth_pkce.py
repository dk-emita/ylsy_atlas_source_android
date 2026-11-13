"""Real local loopback callback + simulated Google endpoint, no Google credentials/network."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import threading
import types
import urllib.parse
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ylsy_atlas_drive.google_drive import GoogleAuth, OAUTH_SERVICE, SCOPES

class FakeKeyring:
    def __init__(self):self.entries={}
    def get_password(self, service, key):return self.entries.get((service,key))
    def set_password(self, service,key,value):self.entries[(service,key)]=value
    def delete_password(self,service,key):self.entries.pop((service,key),None)

class FakeCredentials:
    def __init__(self,token,refresh_token,token_uri,client_id,client_secret,scopes,expiry):
        self.token=token;self.refresh_token=refresh_token;self.client_id=client_id
        self._client_secret=client_secret;self.scopes=scopes;self.expiry=expiry;self.valid=True;self.expired=False
    @property
    def client_secret(self):return self._client_secret
    def to_json(self):return json.dumps({'client_id':self.client_id,'client_secret':self.client_secret,'refresh_token':self.refresh_token,'token':self.token,'scopes':self.scopes,'token_uri':'https://oauth2.googleapis.com/token'})
    @classmethod
    def from_authorized_user_info(cls,info,scopes):
        return cls(info['token'],info['refresh_token'],info['token_uri'],info['client_id'],info.get('client_secret'),scopes,None)

cred_module=types.ModuleType('google.oauth2.credentials');cred_module.Credentials=FakeCredentials
transport_module=types.ModuleType('google.auth.transport.requests');transport_module.Request=lambda: object()
modules={'google':types.ModuleType('google'),
         'google.oauth2':types.ModuleType('google.oauth2'),
         'google.oauth2.credentials':cred_module,
         'google.auth':types.ModuleType('google.auth'),
         'google.auth.transport':types.ModuleType('google.auth.transport'),
         'google.auth.transport.requests':transport_module}

class FakeResponse:
    ok=True
    def json(self):return {'access_token':'fake-access','refresh_token':'fake-refresh','expires_in':3600}

chosen=[]
expected_client_secret=None
def fake_browser(url, new=0):
    parsed=urllib.parse.urlparse(url)
    query=urllib.parse.parse_qs(parsed.query)
    assert parsed.hostname=='accounts.google.com'
    assert query['scope']==SCOPES
    assert query['code_challenge_method']==['S256']
    assert query['prompt']==['select_account consent']
    assert query['access_type']==['offline']
    chosen.append(query)
    def callback():
        redirect=query['redirect_uri'][0]
        assert urllib.parse.urlparse(redirect).path==''
        response=urllib.request.urlopen(redirect+'?'+urllib.parse.urlencode({'state':query['state'][0],'code':'fake-auth-code'}),timeout=5)
        assert response.status==200
        page=response.read().decode('utf-8')
        assert 'window.close()' in page and 'Google hesabı bağlandı' in page
    threading.Thread(target=callback,daemon=True).start()
    return True

def fake_post(url,data,timeout):
    assert url=='https://oauth2.googleapis.com/token'
    assert data['client_id'].endswith('.apps.googleusercontent.com')
    assert data['code']=='fake-auth-code'
    assert data['grant_type']=='authorization_code'
    assert data['code_verifier']
    challenge=base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).decode().rstrip('=')
    assert challenge==chosen[-1]['code_challenge'][0]
    assert data['redirect_uri'].startswith('http://127.0.0.1:')
    assert data.get('client_secret')==expected_client_secret
    if expected_client_secret is None:assert 'client_secret' not in data
    return FakeResponse()

with patch.dict(sys.modules,modules):
    store=FakeKeyring()
    auth=GoogleAuth(Path(__file__).resolve().parents[1]/'resources/google_oauth_client.json',secret_store=store)
    expected_client_secret=auth.client_secret
    with patch('webbrowser.open',side_effect=fake_browser),patch('requests.post',side_effect=fake_post):
        creds=auth.authorize(interactive=True,force_account_choice=True)
        assert creds.valid and creds.refresh_token=='fake-refresh'
    assert len(chosen)==1
    assert store.get_password(OAUTH_SERVICE,auth.client_id)
    saved=auth.authorize(interactive=False)
    assert saved.refresh_token=='fake-refresh'
    assert saved.client_secret==expected_client_secret
    auth.disconnect()
    assert not store.get_password(OAUTH_SERVICE,auth.client_id)
    auth.client_secret='test-desktop-client-secret'
    expected_client_secret=auth.client_secret
    with patch('webbrowser.open',side_effect=fake_browser),patch('requests.post',side_effect=fake_post):
        creds=auth.authorize(interactive=True,force_account_choice=True)
        assert creds.client_secret==expected_client_secret
    assert len(chosen)==2
print('PASS: Desktop OAuth PKCE, callback, optional client secret, token vault, reconnect, logout')
