import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hostname, prunePins, effectiveBackend, effectiveRequest } from '../src/background/local-ai.ts';
import { DEFAULT_SETTINGS } from '../src/shared/types.ts';

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
