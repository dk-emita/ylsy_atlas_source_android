"""Google account UI: no desktop-folder option; folder picker opens after verified OAuth.
Browser calls mocked local endpoints; NO real Google account is used.
"""
from pathlib import Path
import sys
import os
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'web/index.html').read_text(encoding='utf-8')
html=html.replace('<link rel="stylesheet" href="/styles.css"/>','<style>'+(ROOT/'web/styles.css').read_text(encoding='utf-8')+'</style>')
for item in ('qrc:///qtwebchannel/qwebchannel.js','/app.js','/cloud.js'):
    html=html.replace(f'<script src="{item}" defer></script>','')
js=(ROOT/'web/cloud.js').read_text(encoding='utf-8')
mock='''
window.__mock={mode:'none',configured:true,connected:false,authorization_ready:false,startup_shown:false,status:'Bağlı değil',error:'',dirty:false,synchronized:false,change_number:0};
window.__requests=[];
window.fetch=async(path,opt={})=>{
  let route=String(path).split('?')[0], method=opt.method||'GET';
  window.__requests.push(route);
  let m=window.__mock,ret={ok:true};
  if(route.endsWith('/connect') && method==='POST'){
    m.status='Google giriş sayfası açılıyor'; m.change_number++;
    setTimeout(()=>{m.authorization_ready=true;m.status='Google hesabı doğrulandı; Drive klasörü seçiniz';m.change_number++},150);
  }
  if(route.endsWith('/folders'))ret=[{id:'parent-folder',name:'Doktora Başvurularım'}];
  if(route.endsWith('/select-folder') && method==='POST'){
    m.connected=true;m.mode='oauth';m.status='Drive klasörü ayarlandı; ilk senkronizasyon başlıyor';m.change_number++;
  }
  if(route.endsWith('/skip') && method==='POST'){m.startup_shown=true;}
  return {ok:true,json:async()=>JSON.parse(JSON.stringify(route.endsWith('/folders')?ret:m)),status:200};
}
'''
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1280,'height':760})
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.set_content(html,wait_until='domcontentloaded')
    page.add_script_tag(content=mock)
    page.add_script_tag(content=js)
    page.get_by_role('heading',name='Çalışmalarını nasıl kaydedelim?').wait_for(timeout=4000)
    assert page.get_by_role('button',name='Google hesabını bağla',exact=True).count()==1
    if os.environ.get('ATLAS_SCREENSHOT'):
        page.locator('.cloud-panel').screenshot(path=os.environ['ATLAS_SCREENSHOT'])
    assert page.get_by_role('button',name='Alternatif: Drive masaüstü klasörü').count()==0
    assert page.locator('[data-cloud="desktop"]').count()==0
    page.get_by_role('button',name='Google hesabını bağla',exact=True).click()
    page.get_by_role('heading',name='Google Drive klasörü seç').wait_for(timeout=8500)
    page.get_by_role('button',name='📁 Doktora Başvurularım').click()
    page.get_by_text('Drive ana klasörü / Doktora Başvurularım').wait_for(timeout=2500)
    page.get_by_role('button',name='Burada “YLSY Atlas” klasörü oluştur').click()
    page.get_by_text('Google Drive klasörü bağlandı. Senkronizasyon başlatıldı.').wait_for(timeout=2500)
    assert page.evaluate('window.__mock.connected')
    assert page.locator('#profile-button').count()==1
    assert not errors,errors
    browser.close()
print('PASS: no Drive Desktop button, OAuth success triggers automatic Drive folder chooser, folder traversal and selection, no JS errors')
