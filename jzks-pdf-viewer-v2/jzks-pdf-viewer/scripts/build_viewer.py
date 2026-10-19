"""Build an offline, source-linked paper reader. No model/network calls."""
from pathlib import Path
import argparse,base64,hashlib,html,json,re,unicodedata,io,shutil
import pymupdf as fitz

COLORS=['#2872a7','#7856a0','#27876d','#b27321','#b75463']
def norm(s):return ''.join(c for c in unicodedata.normalize('NFKC',s).casefold() if c.isalnum())
def locate(page,quote):
    words=page.get_text('words')
    chars=[]; mapping=[]
    for i,w in enumerate(words):
        s=norm(w[4]);chars.extend(s);mapping.extend([i]*len(s))
    stream=''.join(chars);needle=norm(quote)
    if len(needle)<12:return [],'quote_too_short'
    starts=[m.start() for m in re.finditer(re.escape(needle),stream)]
    if len(starts)!=1:return [],'ambiguous' if starts else 'not_found'
    ids=sorted(set(mapping[starts[0]:starts[0]+len(needle)]))
    lines=[]
    for i in ids:
        r=fitz.Rect(words[i][:4])
        if lines and abs(lines[-1].y0-r.y0)<3 and 0<=r.x0-lines[-1].x1<70:
            lines[-1]|=r
        else:lines.append(r)
    return [list(r) for r in lines],'matched'

def markdown(card):
    out=['# '+card['paper']['title'],'',card.get('summary',''),'']
    ann={a['id']:a for a in card['annotations']}
    for s in card['steps']:
        out+=['## '+str(s['id']).zfill(2)+' '+s['title'],'']
        for p in s['paragraphs']:
            tag='作者报告' if p['layer']=='author' else 'AI解读'
            refs='；'.join(f"{x} · PDF第{ann[x]['page']}页" for x in p['refs'])
            out+=['### '+p['title'],'',f'[{tag}] '+p['text'],'','出处：'+refs,'']
    return '\n'.join(out)

def build(pdf,cardpath,out):
    pdf=Path(pdf);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    raw=pdf.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    doc=fitz.open(stream=raw,filetype='pdf')
    card=json.loads(Path(cardpath).read_text(encoding='utf-8-sig'))
    assert card['schema']=='jzks-pdf-viewer/v1'
    assert [s['id'] for s in card['steps']]==[1,2,3,4,5]
    ids=[a['id'] for a in card['annotations']];assert len(ids)==len(set(ids))
    byid={a['id']:a for a in card['annotations']}
    for s in card['steps']:
        for p in s['paragraphs']:
            assert p['layer'] in ['author','analysis']
            assert all(x in byid for x in p['refs'])
    pages=[];records=[]
    for n,page in enumerate(doc):
        pix=page.get_pixmap(matrix=fitz.Matrix(1.7,1.7),alpha=False,annots=False)
        image='data:image/jpeg;base64,'+base64.b64encode(pix.tobytes('jpeg',jpg_quality=85)).decode()
        pages.append({'width':page.rect.width,'height':page.rect.height,'image':image})
    for a in card['annotations']:
        a.setdefault('kind',{1:'background',2:'method',3:'result',4:'question',5:'implication'}[a['step']])
        assert a['kind'] in ['background','method','result','question','implication']
        assert 1<=a['page']<=len(doc) and a['step'] in range(1,6)
        assert a['layer'] in ['author','analysis']
        page=doc[a['page']-1];rects,status=locate(page,a['quote'])
        a['rects']=rects;a['anchor_status']=status
        a['normalized_rects']=[[r[0]/page.rect.width,r[1]/page.rect.height,r[2]/page.rect.width,r[3]/page.rect.height] for r in rects]
        records.append({'id':a['id'],'page':a['page'],'status':status,'rectangles':len(rects)})
    card['source']={'sha256':sha,'filename':pdf.name,'pages':len(doc)}
    md=markdown(card)
    (out/'paper-card.md').write_text(md,encoding='utf-8')
    (out/'reading.json').write_text(json.dumps(card,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'annotation-map.json').write_text(json.dumps({'source_sha256':sha,'annotations':card['annotations']},ensure_ascii=False,indent=2),encoding='utf-8')
    evidence=[{'step':s['id'],'title':p['title'],'claim':p['text'],'layer':p['layer'],'references':[{'id':r,'page':byid[r]['page'],'quote':byid[r]['quote'],'status':byid[r]['anchor_status']} for r in p['refs']]} for s in card['steps'] for p in s['paragraphs']]
    (out/'evidence-index.json').write_text(json.dumps({'source_sha256':sha,'claims':evidence},ensure_ascii=False,indent=2),encoding='utf-8')
    # Original page content stays vector; annotations occupy a new right margin.
    annotated=fitz.open()
    for n,original in enumerate(doc):
        w,h=original.rect.width,original.rect.height
        current=annotated.new_page(width=w+290,height=h)
        current.show_pdf_page(fitz.Rect(0,0,w,h),doc,n)
        original_display=current
        current.insert_text((w+15,24),f'Paper notes | PDF {n+1}',fontsize=11,color=(.2,.2,.2))
        y=40
        anns=sorted([a for a in card['annotations'] if a['page']==n+1],key=lambda a:a['normalized_rects'][0][1] if a['normalized_rects'] else 0)
        prepared=[]
        for a in anns:
            col=tuple(int(COLORS[a['step']-1][k:k+2],16)/255 for k in [1,3,5])
            for rect in a['rects']:
                highlight=original_display.add_highlight_annot(fitz.Rect(rect));highlight.set_colors(stroke=col);highlight.set_opacity(.22);highlight.set_info(title=a['id'],content=a['explanation']);highlight.update()
            content=f"{a['id']}  {a['title']}\n"+('作者报告' if a['layer']=='author' else 'AI解读')+'｜'+a['explanation']
            # Wrap using the actual CJK font widths; continue on a notes page if needed.
            lines=[]
            for paragraph in content.splitlines():
                line=''
                for ch in paragraph:
                    # Built-in CJK PDF font uses full-width Latin glyph advances.
                    # A fixed-width bound avoids overflowing the annotation margin.
                    if len(line+ch)*9.5>247:lines.append(line);line=''
                    line+=ch
                if line:lines.append(line)
            prepared.append((a,lines,col))
        heights=[len(lines)*14+15 for a,lines,col in prepared]
        positions=[];cursor=40
        for (a,lines,col),height in zip(prepared,heights):
            desired=(a['normalized_rects'][0][1]*h) if a['normalized_rects'] else 40
            positions.append(max(cursor,desired));cursor=positions[-1]+height+8
        if sum(heights)+max(0,len(heights)-1)*8<=h-60:
            end=h-20
            for i in range(len(positions)-1,-1,-1):
                positions[i]=min(positions[i],end-heights[i]);end=positions[i]-8
        else:positions=[]
        for i,(a,lines,col) in enumerate(prepared):
            height=heights[i]
            y=positions[i] if positions else max(y,min((a['normalized_rects'][0][1]*h) if a['normalized_rects'] else 40,h-height-20))
            if y+height>h-20:
                current=annotated.new_page(width=w+290,height=h)
                current.insert_text((20,24),f'Notes continued | original PDF {n+1}',fontsize=11)
                y=45
            current.draw_rect(fitz.Rect(w+10,y-5,w+280,y+height-5),color=col,fill=(.98,.98,.98),width=.5)
            for line in lines:
                current.insert_text((w+17,y+8),line,fontname='china-s',fontsize=9.5,color=(.15,.15,.15));y+=14
            y+=23
    annotated.subset_fonts()
    annotated.save(out/'annotated-paper.pdf',garbage=4,deflate=True)
    payload={'card':card,'pages':pages,'markdown':md,'pdf':base64.b64encode(raw).decode(),'annotatedPdf':base64.b64encode((out/'annotated-paper.pdf').read_bytes()).decode()}
    assets=Path(__file__).resolve().parents[1]/'assets'
    template=(assets/'viewer.html').read_text(encoding='utf-8')
    template=template.replace('/*__PDFLIB__*/',(assets/'vendor/pdf-lib.min.js').read_text(encoding='utf-8').replace('</script','<\\/script'))
    template=template.replace('/*__EXPORT_CODE__*/',(assets/'export-pdf.js').read_text(encoding='utf-8'))
    data=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    (out/'index.html').write_text(template.replace('/*__PAYLOAD__*/',data),encoding='utf-8')
    result={'pages':len(doc),'annotations':len(records),'matched':sum(x['status']=='matched' for x in records),'unresolved':[x for x in records if x['status']!='matched'],'anchors':records,'source_sha256':sha}
    (out/'build-report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='anchors'},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pdf',required=True);p.add_argument('--card',required=True);p.add_argument('--out',required=True);a=p.parse_args();build(a.pdf,a.card,a.out)
