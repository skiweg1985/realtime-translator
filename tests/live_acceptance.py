"""Bounded real-endpoint smoke test: synthetic PCM -> speaker -> two listeners."""
import asyncio
import json
import os
import ssl
import sys
import time
import urllib.request
import wave
import websockets

async def main():
    base = sys.argv[1]
    ssl_context = ssl.create_default_context(cafile=sys.argv[3])
    with wave.open(sys.argv[2], 'rb') as f:
        assert (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (24000, 1, 2)
        pcm = f.readframes(f.getnframes())
    req = urllib.request.Request(base+'/api/rooms', data=json.dumps({"source": "de", "language": "en", "pin": os.getenv("SPEAKER_PIN", "0000")}).encode(), headers={'Content-Type':'application/json'})
    room = json.load(urllib.request.urlopen(req, context=ssl_context))
    url = base.replace('https:', 'wss:')+'/api/rooms/'+room['id']+'/ws'
    options = {'ssl':ssl_context, 'proxy':None}
    events = [[], []]
    async with websockets.connect(url, **options) as a, websockets.connect(url, **options) as b, websockets.connect(url, **options) as speaker:
        for ws in (a,b):
            await ws.send(json.dumps({'role':'listener'}))
        await speaker.send(json.dumps({'role':'speaker','owner':room['owner']}))
        async with asyncio.timeout(25):
            while True:
                e=json.loads(await speaker.recv())
                if e.get('type')=='error':raise AssertionError(e)
                if e.get('status')=='live':break
        async def read(ws, output):
            async for raw in ws:
                e=json.loads(raw);output.append(e)
                if e.get('status')=='ended':return
        tasks=[asyncio.create_task(read(a,events[0])),asyncio.create_task(read(b,events[1]))]
        for start in range(0,len(pcm),4800):
            await speaker.send(pcm[start:start+4800].ljust(4800,b'\0'))
            await asyncio.sleep(.1)
        await speaker.send('stop')
        await asyncio.wait_for(asyncio.gather(*tasks),25)
    for output in events:
        assert not any(e['type']=='notice' for e in output), [e.get('message') for e in output if e['type']=='notice']
        assert any(e['type']=='audio' for e in output), 'No translated audio'
        assert any(e['type']=='translation' and e['text'] for e in output), 'No translation text'
        assert any(e['type']=='original' and e['text'] for e in output), 'No cloud source caption'
        assert not any(e['type']=='error' for e in output), 'Upstream error'
    atext=[e['text'] for e in events[0] if e['type']=='translation'][-1]
    btext=[e['text'] for e in events[1] if e['type']=='translation'][-1]
    assert atext==btext
    print(json.dumps({'passed':True,'listeners':2,'audio_chunks':[sum(e['type']=='audio' for e in o) for o in events], 'translation':atext,'original':[e['text'] for e in events[0] if e['type']=='original'][-1]},ensure_ascii=False))

asyncio.run(main())
