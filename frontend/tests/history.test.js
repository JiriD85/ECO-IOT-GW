import { test } from 'node:test'
import assert from 'node:assert/strict'
import { recordHistory, historyKey, WINDOW, restoreHistory } from '../src/services/telemetryHistory.js'
const now = 1800000000000
const device = (t, value=0, link='connected') => ({ name: 'PF1', address: 1, displayLink: link, stale_after: 25, readings: [{ tag: 'Vdot_m3h', value, last_seen: new Date(t).toISOString() }] })
test('history keeps zero, deduplicates timestamps and does not record disconnected samples', () => {
 const d = device(now), key = historyKey(d,'Vdot_m3h')
 const h = recordHistory({},[d],now)
 assert.deepEqual(h[key],[[now,0]])
 assert.deepEqual(recordHistory(h,[d],now),h)
 assert.deepEqual(recordHistory(h,[device(now+10000,5,'disconnected')],now+10000)[key],h[key])
})
test('history is bounded, expires old samples and rejects stale/nonfinite values', () => {
 let h={}
 for(let i=0;i<400;i++) h=recordHistory(h,[device(now+i*5000,i)],now+i*5000)
 assert.equal(Object.values(h)[0].length,360)
 assert.deepEqual(Object.values(recordHistory(h,[device(now,NaN)],now+WINDOW*3))[0],[])
 assert.deepEqual(Object.values(recordHistory({},[device(now-30000,4)],now))[0],[])
})
test('invalid or unavailable tab storage does not prevent rendering', () => {
 globalThis.sessionStorage={getItem:()=>'{bad'}
 assert.deepEqual(restoreHistory(),{})
 globalThis.sessionStorage={getItem:()=>{throw Error('blocked')}}
 assert.deepEqual(restoreHistory(),{})
})

test('one-minute samples expand to a rolling thirty-minute history', () => {
 let h={}
 for(let i=0;i<=40;i++) h=recordHistory(h,[device(now+i*60000,i)],now+i*60000)
 const points=Object.values(h)[0]
 assert.equal(points.length,31)
 assert.equal(points.at(-1)[0]-points[0][0],30*60000)
})
