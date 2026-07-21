const test = require('node:test');
const assert = require('node:assert/strict');
const { asyncHandler } = require('../../src/common/asyncHandler');

function callWithNext(handler, req = {}, res = {}) {
  return new Promise((resolve) => {
    handler(req, res, (err) => resolve(err));
  });
}

// A successfully-resolving handler is expected to have sent the response itself
// (res.json/res.send) and must NOT call next() — that's what lets asyncHandler's
// catch(next) be the only path that ever forwards to Express's error middleware.
function nextWasNotCalledWithin(handler, req = {}, res = {}) {
  return new Promise((resolve) => {
    let called = false;
    handler(req, res, () => { called = true; });
    setImmediate(() => resolve(called));
  });
}

test('a handler that resolves normally does NOT call next (it already sent the response)', async () => {
  const handler = asyncHandler(async () => 'ignored return value');
  const nextCalled = await nextWasNotCalledWithin(handler);
  assert.equal(nextCalled, false);
});

test('a handler that throws synchronously inside an async fn is forwarded to next(err)', async () => {
  const boom = new Error('boom');
  const handler = asyncHandler(async () => {
    throw boom;
  });
  const err = await callWithNext(handler);
  assert.equal(err, boom);
});

test('a handler that returns a rejected promise is forwarded to next(err)', async () => {
  const boom = new Error('rejected');
  const handler = asyncHandler(() => Promise.reject(boom));
  const err = await callWithNext(handler);
  assert.equal(err, boom);
});

test('req/res are passed through to the wrapped handler unchanged, without requiring next()', async () => {
  const req = { marker: 'req' };
  const res = { marker: 'res' };
  let seen = null;
  const handler = asyncHandler(async (r, s) => {
    seen = { r, s };
  });
  await new Promise((resolve) => {
    handler(req, res, () => {});
    setImmediate(resolve);
  });
  assert.equal(seen.r, req);
  assert.equal(seen.s, res);
});

test('a non-async handler that throws synchronously is still forwarded to next(err) (Promise.resolve wraps it)', async () => {
  const boom = new Error('sync boom');
  const handler = asyncHandler(() => {
    throw boom;
  });
  const err = await callWithNext(handler);
  assert.equal(err, boom);
});
