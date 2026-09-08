"""Paid acceptance: four languages, sharing, switching, and a rejected fifth language."""
import asyncio
import json
import sys
import urllib.request
import wave

import websockets


async def run():
    base = sys.argv[1]
    with wave.open(sys.argv[2]) as f:
        assert (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (24000, 1, 2)
        pcm = f.readframes(f.getnframes())
    assert pcm, 'Empty audio fixture'
    request = urllib.request.Request(base + '/api/rooms', data=b'{"source":"de","language":"en"}',
                                     headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        room = json.load(response)
    url = base.replace('http:', 'ws:') + '/api/rooms/' + room['id'] + '/ws'
    languages = ['en', 'en', 'fr', 'es', 'it']
    sockets = []
    tasks = []
    events = [[] for _ in languages]
    live = [asyncio.Event() for _ in languages]
    rejected = asyncio.Event()
    switched = asyncio.Event()
    speaker_events = []
    try:
        for i, language in enumerate(languages):
            ws = await websockets.connect(url, proxy=None)
            sockets.append(ws)
            await ws.send(json.dumps({'role':'listener','language':language,'subscription':1}))
            async def receive(index=i, sock=ws):
                async for raw in sock:
                    event = json.loads(raw)
                    events[index].append(event)
                    if event.get('type') == 'subscription_rejected':rejected.set()
                    if event.get('status') == 'live':live[index].set()
                    if event.get('type') == 'snapshot' and event.get('subscription') == 3:switched.set()
                    if event.get('status') == 'ended':return
            tasks.append(asyncio.create_task(receive()))
        speaker = await websockets.connect(url, proxy=None)
        sockets.append(speaker)
        await speaker.send(json.dumps({'role':'speaker','owner':room['owner']}))
        async def read_speaker():
            async for raw in speaker:
                event = json.loads(raw);speaker_events.append(event)
                if event.get('type')=='error':raise AssertionError(event)
                if event.get('status')=='ended':return
        tasks.append(asyncio.create_task(read_speaker()))
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in live)),35)
        await sockets[1].send(json.dumps({'type':'subscribe','language':'pt','subscription':2}))
        await asyncio.wait_for(rejected.wait(),5)
        async def feed():
            for i in range(0,len(pcm),4800):
                await speaker.send(pcm[i:i+4800].ljust(4800,b'\0'))
                await asyncio.sleep(.1)
        await feed()
        await asyncio.sleep(2)
        await sockets[1].send(json.dumps({'type':'subscribe','language':'fr','subscription':3}))
        await asyncio.wait_for(switched.wait(),5)
        await feed()
        await speaker.send('stop')
        await asyncio.wait_for(asyncio.gather(*tasks),30)
        for i, output in enumerate(events):
            assert not any(e['type'] in ('error','notice') for e in output), output[-5:]
            assert any(e['type']=='audio' for e in output), (i,'No audio')
            assert any(e['type']=='translation' and e['text'] for e in output), (i,'No text')
            for event in output:
                if event['type'] in ('audio','translation'):
                    assert event['language'] == ('fr' if i==1 and event['subscription']==3 else languages[i])
            if i==1:
                ack = next(n for n,e in enumerate(output) if e['type']=='snapshot' and e.get('subscription')==3)
                assert all(e.get('language') in (None,'fr') and e.get('subscription',3)==3 for e in output[ack:] if e['type'] in ('audio','translation'))
                assert any(e['type']=='audio' and e['subscription']==3 for e in output[ack:])
        assert any(e['type']=='original' and e['text'] for e in speaker_events)
        assert not any(e['type'] in ('audio','translation') for e in speaker_events), 'Speaker received translated output'
        print(json.dumps({'passed':True,'languages':sorted(set(languages)), 'listeners':5,
                          'fifth_language_rejected':True,'switch':'en -> fr',
                          'audio_chunks':[sum(e['type']=='audio' for e in es) for es in events]}))
    except Exception:
        print('CHANNEL_EVENTS', [[(e.get('type'), e.get('status'), e.get('language'), e.get('message')) for e in es if e.get('type') not in ('audio','translation','original')] for es in events])
        raise
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for ws in sockets:await ws.close()

asyncio.run(run())
