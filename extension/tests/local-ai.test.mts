import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hostname, prunePins, effectiveBackend, effectiveRequest, localControlSender, setSiteAuto } from '../src/background/local-ai.ts';
import { DEFAULT_SETTINGS } from '../src/shared/types.ts';
import { usableImageUrl } from '../src/shared/image-url.ts';
import { readTranslationStream } from '../src/shared/progress.ts';
import { progressLabel } from '../src/shared/progress-label.ts';

test('site Auto intent survives paths and other tabs but expires when its final host tab leaves', () => {
  const pins = {id:'browser:test',hosts:[],windows:[],autoHosts:['reader.example']};
  assert.deepEqual(prunePins(pins,[{url:'https://reader.example/next',windowId:2}],true).autoHosts,['reader.example']);
  assert.deepEqual(prunePins(pins,[{url:'https://reader.example.evil/',windowId:2}],true).autoHosts,[]);
  assert.deepEqual(prunePins(pins,[],true).autoHosts,[]);
});

test('Auto pins only local demand, sends no host to controller, and works in cloud mode without a controller', async () => {
  const originalChrome=globalThis.chrome, originalFetch=globalThis.fetch;
  let stored: Record<string, unknown>={};
  const requests: unknown[]=[];
  globalThis.chrome={
    storage:{session:{get:async()=>stored,set:async(value:Record<string,unknown>)=>{stored=structuredClone(value);}}},
    tabs:{get:async()=>({id:7,url:'https://reader.example/chapter',windowId:1}),query:async()=>[{id:7,url:'https://reader.example/chapter',windowId:1}]},
    alarms:{create:async()=>{},clear:async()=>{}},
  } as any;
  globalThis.fetch=async(_url,init)=>{requests.push(JSON.parse(init?.body as string));return Response.json({ok:true});};
  try {
    await setSiteAuto(7,true,DEFAULT_SETTINGS);
    assert.equal((requests[0] as any).keep,true);
    assert.equal(JSON.stringify(requests).includes('reader.example'),false);
    await setSiteAuto(7,false,DEFAULT_SETTINGS);
    assert.equal((requests[1] as any).keep,false);
    globalThis.fetch=async()=>{throw new Error('Controller offline');};
    await setSiteAuto(7,true,{...DEFAULT_SETTINGS,localAiEnabled:false});
    assert.deepEqual((Object.values(stored)[0] as any).autoHosts,['reader.example']);
  } finally {globalThis.chrome=originalChrome;globalThis.fetch=originalFetch;}
});

test('stream decoder handles split JSON events and propagates failures without false completion', async () => {
  const bytes = new TextEncoder().encode(JSON.stringify({type:'progress',completed:4,total:8,stage:'Translating'})+'\n'+JSON.stringify({type:'result',result:{translated_image:'synthetic'}})+'\n');
  const response = new Response(new ReadableStream({start(controller) {
    controller.enqueue(bytes.slice(0,11)); controller.enqueue(bytes.slice(11,73)); controller.enqueue(bytes.slice(73)); controller.close();
  }}));
  const updates: unknown[]=[];
  const result=await readTranslationStream(response,p=>updates.push(p));
  assert.equal(result.translated_image,'synthetic');
  assert.deepEqual(updates,[{completed:4,total:8,stage:'Translating'}]);
  assert.match(progressLabel({completed:4,total:8,stage:'Translating'},12.3),/50%.*4\/8 steps.*12.3s/);
  await assert.rejects(readTranslationStream(new Response('{"type":"error","error":"Synthetic failure"}\n'),()=>{}),/Synthetic failure/);
  await assert.rejects(readTranslationStream(new Response(''),()=>{}),/without a result/);
});

test('scanner accepts a direct image document without accepting empty HTML image links', () => {
  const url = 'https://reader.example/page.jpg';
  assert.equal(usableImageUrl(url, url, 'image/jpeg'), true);
  assert.equal(usableImageUrl(url, url, 'text/html'), false);
  assert.equal(usableImageUrl(url, 'https://reader.example/chapter', 'text/html'), true);
  for (const invalid of [null, undefined, '', 'blob:synthetic', 'data:image/png;base64,synthetic']) {
    assert.equal(usableImageUrl(invalid, url, 'image/jpeg'), false);
  }
});

test('local controls accept only the extension-owned popup document', () => {
  assert.equal(localControlSender({id:'self',url:'chrome-extension://self/popup/index.html'},'self'),true);
  for (const sender of [{id:'self',url:'https://reader.example/'},{id:'other',url:'chrome-extension://self/popup/index.html'},{id:'self'},{id:'self',url:'chrome-extension://self/popup/index.html.evil'}]) {
    assert.equal(localControlSender(sender,'self'),false);
  }
});

test('site match is exact hostname, independent of path', () => {
  assert.equal(hostname('https://reader.example/a/chapter?q=secret'), 'reader.example');
  assert.equal(hostname('https://evilreader.example/'), 'evilreader.example');
  assert.equal(hostname('chrome://extensions'), null);
});
test('site remains pinned with another matching tab in a different window', () => {
  const pins = {id:'browser:test',hosts:['reader.example'],windows:[]};
  const next = prunePins(pins,[{url:'https://reader.example/another',windowId:2}],true);
  assert.deepEqual(next.hosts,['reader.example']);
  assert.deepEqual(prunePins(pins,[{url:'https://reader.example.evil.net/',windowId:1}],true).hosts,[]);
  assert.deepEqual(prunePins(pins,[],true).hosts,[]);
});
test('window pin disappears when window closes; disabling local clears pins', () => {
  const pins = {id:'browser:test',hosts:['reader.example'],windows:[1]};
  assert.deepEqual(prunePins(pins,[{url:'https://reader.example/',windowId:2}],true).windows,[]);
  const off=prunePins(pins,[{url:'https://reader.example/',windowId:1}],false);
  assert.deepEqual(off.hosts,[]); assert.deepEqual(off.windows,[]);
});
test('local routing strips cloud credentials and URL', () => {
  const settings = {...DEFAULT_SETTINGS, backendUrl:'https://remote.example', localAiEnabled:true};
  const original = {provider:'Google',model_name:'cloud',api_key:'secret',base_url:'https://remote.example',input_language:'Auto'};
  const body = effectiveRequest(original as any, settings);
  assert.equal(effectiveBackend(settings),'http://127.0.0.1:7677');
  assert.equal(body.provider,'Local');
  assert.equal(body.model_name,'qwen3-vl-4b');
  assert.equal(body.api_key,undefined);
  assert.equal(body.base_url,undefined);
});
