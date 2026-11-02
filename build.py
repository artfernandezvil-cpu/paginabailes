"""Build the standalone page without installing packages."""
import base64
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def js_json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
def inline_script(source):
    return '<script>'+source.replace('</script','<\\/script')+'</script>'
def build():
    seed={'records':json.loads((ROOT/'data/records.json').read_text()),'territories':json.loads((ROOT/'data/territories.json').read_text()),'contents':json.loads((ROOT/'data/content.json').read_text()),'contributions':[],'layers':[],'connected':False,'contentRevision':0}
    assets={key:'data:image/png;base64,'+base64.b64encode((ROOT/'public/assets'/name).read_bytes()).decode() for key,name in [('andacollo','andacollo.png'),('norte','norte.png')]}
    html=(ROOT/'template.html').read_text()
    html=html.replace('/*VENDOR_CSS*/',(ROOT/'public/vendor/map.css').read_text())
    html=html.replace('/*SITE_CSS*/',(ROOT/'public/style.css').read_text())
    html=html.replace('/*SEED*/','const BC_SEED='+js_json(seed)+';const BC_ASSETS='+js_json(assets)+';')
    html=html.replace('<!--VENDOR_JS-->','\n'.join(inline_script((ROOT/'public/vendor'/name).read_text()) for name in ['leaflet.js','maplibre-gl.js','leaflet-maplibre-gl.js','leaflet.markercluster.js']))
    html=html.replace('/*APP_JS*/',(ROOT/'public/app.js').read_text().replace('</script','<\\/script'))
    notices='\n\n'.join(p.name+'\n'+p.read_text() for p in sorted((ROOT/'licenses').glob('*.txt')))
    html=html.replace('</head>','<script type="text/plain" id="software-notices">'+notices.replace('</script','<\\/script')+'</script></head>')
    out=ROOT/'public/index.html'
    out.write_text(html)
    print(f'index.html: {out.stat().st_size:,} bytes; {len(seed["records"])} fichas; {len(assets)} ilustraciones.')
if __name__=='__main__':build()
