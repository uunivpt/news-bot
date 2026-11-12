"""Shared browser assertions for static, attributed chart downloads."""
import xml.etree.ElementTree as ET
from pathlib import Path


def chart_export(page, section, expected, output):
    button=section.get_by_role('button',name='Download chart (SVG)',exact=True)
    button.wait_for()
    requests=[]
    def record(request):
        if request.url.startswith(('http://','https://')):requests.append(request.url)
    page.on('request',record)
    before=page.evaluate('JSON.stringify(localStorage)')
    section.locator('svg').evaluate("""svg=>{
      const link=document.createElementNS('http://www.w3.org/2000/svg','a');
      link.id='export-unsafe-fixture';link.setAttribute('href','https://example.org/must-not-export');
      link.textContent='must-not-export';svg.append(link);
    }""")
    button.focus()
    with page.expect_download() as event:page.keyboard.press('Enter')
    download=event.value
    assert download.suggested_filename.startswith('politicshub-') and download.suggested_filename.endswith('.svg')
    content=Path(download.path()).read_text()
    section.locator('#export-unsafe-fixture').evaluate('(node)=>node.remove()')
    assert 'must-not-export' not in content
    svg=ET.fromstring(content);ns='{http://www.w3.org/2000/svg}'
    assert svg.tag==ns+'svg'
    allowed={'svg','g','rect','circle','path','polyline','line','text','title','desc'}
    assert all(node.tag.removeprefix(ns) in allowed for node in svg.iter())
    assert all(not key.lower().startswith('on') and key not in {'href','style','class','tabindex'} and 'url(' not in value.lower() for node in svg.iter() for key,value in node.attrib.items())
    text=' '.join(' '.join(svg.itertext()).split())
    assert 'POLITICSHUB.IN' in text
    for value in expected:assert value in text,(value,text)
    assert float(svg.attrib['height'])>400 and svg.attrib['width']=='900'
    assert len(list(svg.iter(ns+'rect')))+len(list(svg.iter(ns+'circle')))+len(list(svg.iter(ns+'path')))>1
    assert button.evaluate('(node)=>node===document.activeElement')
    assert page.evaluate('JSON.stringify(localStorage)')==before
    assert not requests,requests
    page.remove_listener('request',record)
    output.write_text(content)
    # The downloaded file must render by itself with scripts disabled and
    # every non-file request blocked, including page fonts and stylesheets.
    isolated=page.context.browser.new_context(java_script_enabled=False,viewport={'width':900,'height':1000})
    isolated.route('**/*',lambda route:route.continue_() if route.request.url.startswith('file:') else route.abort())
    try:
        view=isolated.new_page();view.goto(output.resolve().as_uri())
        assert view.locator('svg text').evaluate_all('''nodes=>nodes.every(node=>{
          const box=node.getBBox(),root=node.ownerSVGElement.viewBox.baseVal;
          return box.x>=-1&&box.x+box.width<=root.width+1&&box.y>=-1&&box.y+box.height<=root.height+1;
        })'''),'Exported labels clipped outside the image'
        view.locator('svg').screenshot(path=str(output.with_suffix('.png')))
    finally:
        isolated.close()
    return content
