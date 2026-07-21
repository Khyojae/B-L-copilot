process.env.JWT_ACCESS_SECRET = process.env.JWT_ACCESS_SECRET || 'test-access-secret';
process.env.JWT_REFRESH_SECRET = process.env.JWT_REFRESH_SECRET || 'test-refresh-secret';

const test = require('node:test');
const assert = require('node:assert/strict');
const { signAccessToken } = require('../../src/auth/jwt.service');
const { jwtVerify } = require('../../src/auth/jwtVerify.middleware');
const { requirePermission } = require('../../src/auth/rbac.middleware');
const { requireOwnership } = require('../../src/auth/ownership.middleware');
const { PERMISSIONS } = require('../../src/auth/permissions');

function runChain(middlewares, req) {
  return new Promise((resolve) => {
    let i = 0;
    const next = (err) => {
      if (err) {
        resolve({ error: err });
        return;
      }
      if (i >= middlewares.length) {
        resolve({ ok: true });
        return;
      }
      middlewares[i++](req, {}, next);
    };
    next();
  });
}

function bearerReq(token) {
  return { headers: { authorization: `Bearer ${token}` } };
}

test('every role/feature combination in the matrix is enforced', async () => {
  for (const [featureKey, { roles }] of Object.entries(PERMISSIONS)) {
    for (const role of ['shipper', 'carrier', 'forwarder', 'bank', 'customs']) {
      const { token } = signAccessToken({ sub: 1, role, orgId: 'X', tokenVersion: 0 });
      const result = await runChain([jwtVerify, requirePermission(featureKey)], bearerReq(token));
      const shouldAllow = roles.includes(role);
      assert.equal(Boolean(result.ok), shouldAllow, `${featureKey} / ${role}`);
    }
  }
});

test('admin bypasses every permission check', async () => {
  const { token } = signAccessToken({ sub: 99, role: 'admin', orgId: null, tokenVersion: 0 });
  for (const featureKey of Object.keys(PERMISSIONS)) {
    const result = await runChain([jwtVerify, requirePermission(featureKey)], bearerReq(token));
    assert.ok(result.ok, `admin should be allowed for ${featureKey}`);
  }
});

test('admin access triggers the onAdminAccess hook (for audit logging later)', async () => {
  const { token } = signAccessToken({ sub: 99, role: 'admin', orgId: null, tokenVersion: 0 });
  let hookCalled = null;
  const mw = requirePermission('EBL_ISSUE', { onAdminAccess: (req, key) => { hookCalled = key; } });
  await runChain([jwtVerify, mw], bearerReq(token));
  assert.equal(hookCalled, 'EBL_ISSUE');
});

test('missing/invalid Authorization header is rejected before RBAC runs', async () => {
  let r = await runChain([jwtVerify, requirePermission('EBL_ISSUE')], { headers: {} });
  assert.ok(r.error);

  r = await runChain([jwtVerify, requirePermission('EBL_ISSUE')], { headers: { authorization: 'Basic abc' } });
  assert.ok(r.error);
});

test('ownership middleware allows the resource owner and denies everyone else', async () => {
  const { token: ownerToken } = signAccessToken({ sub: 2, role: 'shipper', orgId: 'X', tokenVersion: 0 });
  const { token: strangerToken } = signAccessToken({ sub: 55, role: 'shipper', orgId: 'X', tokenVersion: 0 });
  const loadOwnerIds = async () => [2, 5];

  const ownerResult = await runChain(
    [jwtVerify, requirePermission('EBL_VIEW'), requireOwnership(loadOwnerIds)],
    bearerReq(ownerToken),
  );
  assert.ok(ownerResult.ok);

  const strangerResult = await runChain(
    [jwtVerify, requirePermission('EBL_VIEW'), requireOwnership(loadOwnerIds)],
    bearerReq(strangerToken),
  );
  assert.ok(strangerResult.error);
});

test('admin bypasses ownership too', async () => {
  const { token } = signAccessToken({ sub: 99, role: 'admin', orgId: null, tokenVersion: 0 });
  const loadOwnerIds = async () => [2, 5];
  const result = await runChain(
    [jwtVerify, requirePermission('EBL_VIEW'), requireOwnership(loadOwnerIds)],
    bearerReq(token),
  );
  assert.ok(result.ok);
});

test('a nonexistent feature key denies every business role (fails closed, not open)', async () => {
  for (const role of ['shipper', 'carrier', 'forwarder', 'bank', 'customs']) {
    const { token } = signAccessToken({ sub: 1, role, orgId: 'X', tokenVersion: 0 });
    const result = await runChain([jwtVerify, requirePermission('TOTALLY_MADE_UP_FEATURE')], bearerReq(token));
    assert.ok(result.error, `role ${role} should be denied for an unknown feature key`);
  }
});

test('admin still bypasses even a nonexistent/typo feature key', async () => {
  const { token } = signAccessToken({ sub: 99, role: 'admin', orgId: null, tokenVersion: 0 });
  const result = await runChain([jwtVerify, requirePermission('TOTALLY_MADE_UP_FEATURE')], bearerReq(token));
  assert.ok(result.ok);
});

test('ownership middleware propagates errors from the injected loader instead of swallowing them', async () => {
  const { token } = signAccessToken({ sub: 2, role: 'shipper', orgId: 'X', tokenVersion: 0 });
  const dbFailure = new Error('connection refused');
  const loadOwnerIds = async () => { throw dbFailure; };

  const result = await runChain(
    [jwtVerify, requirePermission('EBL_VIEW'), requireOwnership(loadOwnerIds)],
    bearerReq(token),
  );

  assert.equal(result.error, dbFailure);
});

test('an expired/tampered access token is rejected before it ever reaches RBAC', async () => {
  const result = await runChain(
    [jwtVerify, requirePermission('EBL_ISSUE')],
    bearerReq('Bearer-worthy-but-fake.token.value'),
  );
  assert.ok(result.error);
});

test('role missing from the token payload entirely is denied, not treated as admin', async () => {
  // req.user with no role set (e.g. a decode edge case) must not accidentally match anything
  const result = await runChain(
    [(req, res, next) => { req.user = { sub: 1 }; next(); }, requirePermission('EBL_ISSUE')],
    {},
  );
  assert.ok(result.error);
});
