import test from 'node:test';
import assert from 'node:assert/strict';
import {pricedEvidenceStillFresh} from '../lib/fast-cache.ts';

const now=Date.parse('2026-10-07T06:00:00Z');

test('accepts priced evidence that is still inside the 15 minute freshness window',()=>{
 const payload={picks:[{available:true,best_available_book:'book',best_available_price:-110,as_of:'2026-10-07T05:50:00Z',event_time:'2026-10-07T08:00:00Z'}]};
 assert.equal(pricedEvidenceStillFresh(payload,now),true);
});

test('rejects cached priced evidence once its quote is stale',()=>{
 const payload={picks:[{available:true,best_available_book:'book',best_available_price:-110,as_of:'2026-10-07T05:44:59Z',event_time:'2026-10-07T08:00:00Z'}]};
 assert.equal(pricedEvidenceStillFresh(payload,now),false);
});

test('rejects cached selections after the event has started',()=>{
 const payload={cards:[{legs:[{available:true,best_available_book:'book',best_available_price:120,as_of:'2026-10-07T05:58:00Z',event_time:'2026-10-07T05:59:00Z'}]}]};
 assert.equal(pricedEvidenceStillFresh(payload,now),false);
});
