"""UI smoke/regression checks with Playwright and a mock local API.
Run from project directory after: pip install playwright; python -m playwright install chromium
This does not modify real bursiyer data.
"""
from pathlib import Path
import base64
import json
import os
import sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from guide import GUIDE,TEMPLATES

html=(ROOT/'web/index.html').read_text(encoding='utf-8')
html=html.replace('<link rel="stylesheet" href="/styles.css"/>','<style>'+(ROOT/'web/styles.css').read_text(encoding='utf-8')+'</style>')
encoded=base64.b64encode((ROOT/'assets/atlas-icon-512.png').read_bytes()).decode()
encoded_brand=base64.b64encode((ROOT/'assets/atlas-brand-hires.png').read_bytes()).decode()
html=html.replace('src="/brand-icon.png?v=236"','src="data:image/png;base64,'+encoded_brand+'"')
html=html.replace('<script src="/app.js" defer></script>','')
js=(ROOT/'web/app.js').read_text(encoding='utf-8')
cache={"guide":[dict(id=i,title=t,page=p,level=l,summary=d,group=g)for i,t,p,l,d,g in GUIDE],"templates":[dict(title=t,kind=k,ref_key=r,page=p,html=h)for t,k,r,p,h in TEMPLATES],"settings":{},**{k:[] for k in ['universities','programs','advisors','tasks','documents','ielts_sessions','events','attachments','notes','resources']}}
mock='''window.__DB='''+json.dumps(cache,ensure_ascii=False)+''';
window.fetch=async(url,opt={})=>{let path=String(url).replace(/^\\/api\\//,'').split('?')[0],method=opt.method||'GET',parts=path.split('/'),table=parts[0],id=+parts[1],data=opt.body?JSON.parse(opt.body):null,r;
if(method==='GET'){r=window.__DB[path]||window.__DB[table]||[];if(id&&Array.isArray(r))r=r.find(x=>x.id===id)}
else if(method==='POST'&&Array.isArray(window.__DB[table])){r={id:window.__DB[table].length+1,...data};window.__DB[table].push(r)}
else if(method==='PUT'){r=window.__DB[table].find(x=>x.id===id);Object.assign(r,data)}
else if(method==='DELETE'){window.__DB[table]=window.__DB[table].filter(x=>x.id!==id);r={ok:true}}
else r={ok:true};
if(table==='settings'&&method==='POST'){window.__DB.settings={...window.__DB.settings,...data};r=window.__DB.settings}
if(table==='overview'){let d=window.__DB,t=d.tasks,done=t.filter(x=>x.status==='done').length;r={total:t.length,done,doing:t.filter(x=>x.status==='doing').length,completion:t.length?Math.round(done/t.length*100):0,university_count:d.universities.length,program_count:d.programs.length,advisor_count:d.advisors.length,submitted:0,accepted:0}}
return {ok:true,json:async()=>r,blob:async()=>new Blob(['test']),status:200}}
'''

with sync_playwright() as p:
    launch_args=dict(headless=True)
    if os.path.exists('/usr/bin/chromium'):
        launch_args['executable_path']='/usr/bin/chromium'
        launch_args['args']=['--no-sandbox']
    browser=p.chromium.launch(**launch_args)
    page=browser.new_page(viewport={'width':1536,'height':900})
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.set_content(html,wait_until='domcontentloaded')
    page.add_script_tag(content=mock)
    page.add_script_tag(content=js)
    page.wait_for_selector('.metrics-5',timeout=10000)

    assert page.locator('.topbar-brand').inner_text().strip()=='YLSY Bursiyerleri için Başvuru ve Hazırlık Platformu'
    assert page.locator('.topbar-brand img').count()==0
    assert page.locator('.topbar-brand b').count()==0
    assert page.locator('.topbar-brand').bounding_box()['x']<36
    assert page.locator('.brand-title b').inner_text().strip()=='YLSY Atlas'
    assert page.locator('.metric-copy strong').first.inner_text()=='0'

    for route in ['dashboard','roadmap','universities','advisors','applications','documents','ielts','calendar','guide','administration','notes','resources','settings']:
        page.locator(f'[data-nav="{route}"]').first.click()
        assert page.locator('#main').inner_text().strip(),route
    page.locator('[data-nav="roadmap"]').first.click()
    assert page.locator('.road-entry').count()==len(GUIDE)
    page.locator('[data-act="add-task"]').first.click()
    assert page.locator('#form-status option').all_text_contents()==['Seçiniz','Yapılacak','Devam ediyor','Tamamlandı']
    page.locator('.modal [data-act="close-modal"]').first.click()

    page.locator('[data-nav="universities"]').first.click()
    page.locator('[data-act="add-university"]').first.click()
    page.locator('#form-name').fill('UI Test Üniversitesi')
    page.locator('#form-short').fill('Test Üniversitesi')
    page.locator('.modal button[type=submit]').click()
    assert page.locator('.uni-row').count()==1
    page.locator('.uni-row').first.click()
    page.locator('[data-act="add-program"]').first.click()
    page.locator('#form-name').fill('Mechanical Engineering PhD')
    page.locator('.modal button[type=submit]').click()
    assert page.locator('.related-item').count()==1, 'Program must be visible under its parent university'

    page.locator('[data-nav="documents"]').first.click()
    assert page.locator('.template-catalog-row').count()>=16
    page.locator('[data-act="choose-template"]').first.click()
    assert page.locator('.modal [data-act="create-template"]').count()>=16
    page.locator('.modal [data-act="create-template"]').first.click()
    assert page.locator('#doc-editor').count()==1
    assert 'Akademik Özgeçmiş' in page.locator('#doc-editor').inner_text()
    page.locator('#doc-editor').fill('CV-ONLY UNIQUE TEST')
    # Select the separate SoP template; document texts must not merge.
    page.locator('.template-catalog-row [data-act="create-template"]').nth(1).click()
    assert 'Statement of Purpose' in page.locator('#doc-editor').inner_text()
    assert 'CV-ONLY UNIQUE TEST' not in page.locator('#doc-editor').inner_text()

    # 2.3.1: document deletion, missing-PDF call-to-action, sidebar arrows, calendar button
    assert page.locator('.doc-list-row').count()==2
    assert page.locator('.doc-list-row .doc-delete').count()==0
    assert page.locator('.doc-editor-panel [data-delete]').count()==0
    assert page.locator('.doc-library .doc-header-delete').count()==1
    assert page.locator('.doc-library .doc-header-delete').is_enabled()
    selected=page.locator('.doc-list-item.active b').inner_text()
    if os.environ.get('ATLAS_SCREENSHOT'):
        page.screenshot(path=os.environ['ATLAS_SCREENSHOT'],full_page=False)
    page.once('dialog',lambda dialog:dialog.accept())
    page.locator('.doc-library .doc-header-delete').click()
    page.wait_for_timeout(150)
    assert page.locator('.doc-list-row').count()==1
    assert page.locator('.doc-list-item').filter(has_text=selected).count()==0
    assert page.locator('.doc-library .doc-header-delete').is_disabled()
    page.locator('[data-nav="guide"]').first.click()
    assert page.get_by_text('MEB rehberi henüz eklenmedi').count()==1
    assert page.get_by_role('button',name='PDF Seç / Değiştir').count()==1
    page.locator('[data-nav="calendar"]').first.click()
    today=page.locator('.cal-arrows [data-act="calendar-today"]')
    assert today.is_visible() and today.bounding_box()['width']>=76,today.bounding_box()
    xs=[round(elem.bounding_box()['x']) for elem in page.locator('.nav-link .nav-trailing:visible').all()]
    assert xs and max(xs)-min(xs)<2,xs
    page.locator('[data-nav="dashboard"]').first.click()
    for width,height in [(1536,900),(1280,720),(1024,640)]:
        page.set_viewport_size({'width':width,'height':height})
        assert not page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth'),(width,height)
        page.locator('#sidebar-toggle').click()
        page.wait_for_timeout(250)
        overlapping=page.evaluate('''()=>{let a=document.querySelector('.sidebar-bottom-toggle').getBoundingClientRect(),b=document.querySelector('.nav-link').getBoundingClientRect();return a.left<b.right&&b.left<a.right&&a.top<b.bottom&&b.top<a.bottom}''')
        assert not overlapping,(width,height)
        page.locator('#sidebar-toggle').click()
    assert not errors,errors
    browser.close()
    print('PASS UI 2.3.2: PDF prompt, document delete, nav alignment, calendar layout, branding, 46-stage roadmap, all screens, nested program, 16 templates, document isolation, collapsed menu, 1024-1536px, no JS errors')
