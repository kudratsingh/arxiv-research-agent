"""Decode complete successful-run WebMs and make timestamped contact sheets.

This produces inspection aids, never automatic visual-acceptance claims. Original
WebMs stay intact. Failed/partial runs must be preserved elsewhere before final.
"""
from __future__ import annotations
import hashlib,json,math,re,subprocess,tempfile
from pathlib import Path
from PIL import Image,ImageDraw

root=Path('planning/12-workspace-controller-revamp/evidence/after/p7-polish')
ffmpeg=Path('/Users/kudratsingh/Library/Caches/ms-playwright/ffmpeg-1011/ffmpeg-mac')
out=root/'final/video-inspection';out.mkdir(parents=True,exist_ok=True)
report={'scope':'Full WebM decode plus one-frame-per-second visual aids; visual judgment recorded separately','videos':[]}
for folder in [root/'final/commands',root/'final/geometry',root/'ci/daily-loop']:
    run=json.loads((folder/'report.json').read_text())
    assert run['status']=='pass',f'Refuse to label failed/partial run final: {folder}'
    for video in sorted(folder.glob('*.webm')):
        name=folder.name+'-'+video.stem
        with tempfile.TemporaryDirectory(prefix='controller-p7-video-',dir='/private/tmp') as temporary:
            frames=Path(temporary)
            result=subprocess.run([str(ffmpeg),'-hide_banner','-nostdin','-i',str(video),'-r','1','-fps_mode','cfr',str(frames/'%04d.png')],text=True,capture_output=True)
            (out/(name+'-decode.log')).write_text(result.stderr)
            assert result.returncode==0,result.stderr
            pngs=sorted(frames.glob('*.png'));assert pngs
            duration=re.search(r'Duration: (\d+):(\d+):([\d.]+)',result.stderr)
            seconds=int(duration[1])*3600+int(duration[2])*60+float(duration[3]) if duration else None
            first=Image.open(pngs[0]);width,height=first.size;tile_width=320 if width>height else 180
            tile_height=round(height*tile_width/width);columns=4;rows=math.ceil(len(pngs)/columns)
            sheet=Image.new('RGB',(columns*tile_width,rows*(tile_height+25)),(225,225,225));draw=ImageDraw.Draw(sheet)
            frame_metrics=[]
            for index,png in enumerate(pngs):
                with Image.open(png) as original:
                    image=original.convert('RGB');frame_metrics.append({'sampleSecond':index,'extrema':image.getextrema()})
                    image.thumbnail((tile_width,tile_height));x=index%columns*tile_width;y=index//columns*(tile_height+25)
                    sheet.paste(image,(x,y));draw.text((x+4,y+tile_height+4),f'{index:02d}s',(0,0,0))
                    if index in {0,len(pngs)//2,len(pngs)-1}:original.save(out/(name+f'-{index:02d}s.png'))
            sheet.save(out/(name+'-contact-sheet.png'))
            report['videos'].append({'video':str(video.relative_to(root)),'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'bytes':video.stat().st_size,'durationSeconds':seconds,'width':width,'height':height,'fullDecodeExitCode':0,'sampleFrames':len(pngs),'contactSheet':name+'-contact-sheet.png','frameMetrics':frame_metrics,'visualAssessment':'pending visual review'})
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps([{k:v for k,v in item.items() if k!='frameMetrics'} for item in report['videos']],indent=2))
