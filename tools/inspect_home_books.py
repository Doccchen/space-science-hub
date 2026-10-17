"""Read only the opening pages of local books for catalog metadata and covers."""
import json
import sys
from pathlib import Path
import pypdfium2 as pdfium
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path('E:/storage/华为家庭存储')
OUT=ROOT/'artifacts/home-books-20261017'

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    OUT.mkdir(parents=True,exist_ok=True)
    inventory=[]
    paths=sorted(p for p in SOURCE.glob('*.pdf') if '第四版' not in p.name and '-笔记' not in p.name)
    for index,path in enumerate(paths,1):
        book_id=f'book-{index:02}'
        folder=OUT/book_id;folder.mkdir(exist_ok=True)
        doc=pdfium.PdfDocument(path)
        record={'id':book_id,'source':str(path),'filename':path.name,'pages':len(doc),'opening_text':[]}
        for page_index in range(min(8,len(doc))):
            page=doc[page_index]
            text=page.get_textpage().get_text_range()
            record['opening_text'].append({'page':page_index+1,'text':text[:14000]})
            if page_index<4:
                scale=1100/max(page.get_width(),page.get_height())
                image=page.render(scale=scale).to_pil().convert('RGB')
                image.save(folder/f'page-{page_index+1}.jpg',quality=85)
        doc.close()
        (folder/'metadata.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        inventory.append(record)
        print(book_id,path.name,'pages',record['pages'],'text chars',sum(len(p['text']) for p in record['opening_text']),flush=True)
    (OUT/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    for start in range(0,len(inventory),10):
        sheet=Image.new('RGB',(1500,1060),'#f3f1ea');draw=ImageDraw.Draw(sheet)
        for i,record in enumerate(inventory[start:start+10]):
            image=Image.open(OUT/record['id']/'page-1.jpg');image.thumbnail((280,480))
            x=(i%5)*300;y=(i//5)*530
            sheet.paste(image,(x+(280-image.width)//2,y))
            draw.text((x+8,y+486),record['id'],fill='#10233f')
        sheet.save(OUT/f'covers-{start//10+1}.jpg',quality=90)

if __name__=='__main__':main()
