# 使い方: python3 embed.py <index.html> <フォントttfのあるフォルダ>
import sys,re,base64,io,os
from fontTools import subset
from fontTools.ttLib import TTFont
p,d=sys.argv[1],sys.argv[2]
html=open(p).read()
body=re.sub(r"@font-face\{[^}]*\}","",html)
ascii_=''.join(chr(c) for c in range(32,127))
jp=''.join(sorted(set(c for c in body if ord(c)>127)))
F=[('Dela Gothic One',400,None,'hESp6XxvMDRA-2eD0lXpDa6QkBAGRQ.ttf',ascii_+jp),
('Archivo',800,'125%','k3k6o8UDI-1M0wlSV9XAw6lQkqWY8Q8EsJaRE-NWIDdgffTTtDRp8A.ttf',ascii_+'×¥★→'),
('Archivo',900,'125%','k3k6o8UDI-1M0wlSV9XAw6lQkqWY8Q8EsJaRE-NWIDdgffTTnTRp8A.ttf',ascii_+'×¥★→'),
('Jost',500,None,'92zPtBhPNqw79Ij1E865zBUv7myRJQVG.ttf',ascii_+'×¥→'),
('Jost',600,None,'92zPtBhPNqw79Ij1E865zBUv7mx9IgVG.ttf',ascii_+'×¥→'),
('Jost',700,None,'92zPtBhPNqw79Ij1E865zBUv7mxEIgVG.ttf',ascii_+'×¥→'),
('Jost',800,None,'92zPtBhPNqw79Ij1E865zBUv7mwjIgVG.ttf',ascii_+'×¥→')]
css=[]
for fam,w,st,f,chars in F:
  opt=subset.Options();opt.flavor='woff2';opt.layout_features=['*']
  ft=TTFont(os.path.join(d,f));s=subset.Subsetter(opt);s.populate(text=chars);s.subset(ft)
  b=io.BytesIO();ft.flavor='woff2';ft.save(b)
  css.append("@font-face{font-family:'%s';font-weight:%d;%sfont-display:swap;src:url(data:font/woff2;base64,%s) format('woff2')}"%(fam,w,('font-stretch:%s;'%st) if st else '',base64.b64encode(b.getvalue()).decode()))
a=html.index("@font-face{");z=html.index("</style>",a)
html=html[:a]+'\n'.join(css)+'\n'+html[z:]
open(p,'w').write(html);print('chars',len(jp),'size',len(html))
