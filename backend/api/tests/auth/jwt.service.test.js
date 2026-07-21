process.env.JWT_ACCESS_SECRET = process.env.JWT_ACCESS_SECRET || 'test-access-secret';
process.env.JWT_REFRESH_SECRET = process.env.JWT_REFRESH_SECRET || 'test-refresh-secret';

const test = require('node:test');
const assert = require('node:assert/strict');
const jwt = require('jsonwebtoken');
const {
  signAccessToken,
  signRefreshToken,
  verifyAccessToken,
  verifyRefreshToken,
} = require('../../src/auth/jwt.service');

test('signAccessToken embeds role/org_id/tv and verifies', () => {
  const { token } = signAccessToken({ sub: 42, role: 'carrier', orgId: 'ACME01', tokenVersion: 3 });
  const decoded = verifyAccessToken(token);

  assert.equal(decoded.sub, '42');
  assert.equal(decoded.role, 'carrier');
  assert.equal(decoded.org_id, 'ACME01');
  assert.equal(decoded.tv, 3);
});

test('signRefreshToken verifies and carries subject', () => {
  const { token } = signRefreshToken({ sub: 7 });
  const decoded = verifyRefreshToken(token);
  assert.equal(decoded.sub, '7');
});

test('access token cannot be verified with the refresh secret (and vice versa)', () => {
  const { token: accessToken } = signAccessToken({ sub: 1, role: 'shipper', orgId: 'X', tokenVersion: 0 });
  const { token: refreshToken } = signRefreshToken({ sub: 1 });

  assert.throws(() => verifyRefreshToken(accessToken));
  assert.throws(() => verifyAccessToken(refreshToken));
});

test('tampered / wrong-secret token is rejected', () => {
  const forged = jwt.sign(
    { role: 'admin' },
    'not-the-real-secret',
    { subject: '1', issuer: 'smart-ebl-auth', audience: 'smart-ebl-api', expiresIn: '15m' },
  );
  assert.throws(() => verifyAccessToken(forged));
});

test('expired access token is rejected', () => {
  const expired = jwt.sign(
    { role: 'carrier' },
    process.env.JWT_ACCESS_SECRET,
    { subject: '1', issuer: 'smart-ebl-auth', audience: 'smart-ebl-api', expiresIn: -10 },
  );
  assert.throws(() => verifyAccessToken(expired));
});

test('token with the correct secret but wrong issuer is rejected', () => {
  const wrongIssuer = jwt.sign(
    { role: 'carrier' },
    process.env.JWT_ACCESS_SECRET,
    { subject: '1', issuer: 'someone-elses-auth-server', audience: 'smart-ebl-api', expiresIn: '15m' },
  );
  assert.throws(() => verifyAccessToken(wrongIssuer));
});

test('token with the correct secret but wrong audience is rejected', () => {
  const wrongAudience = jwt.sign(
    { role: 'carrier' },
    process.env.JWT_ACCESS_SECRET,
    { subject: '1', issuer: 'smart-ebl-auth', audience: 'someone-elses-api', expiresIn: '15m' },
  );
  assert.throws(() => verifyAccessToken(wrongAudience));
});

test('garbage / non-JWT string does not verify (and does not crash the process)', () => {
  assert.throws(() => verifyAccessToken('not.a.jwt'));
  assert.throws(() => verifyAccessToken(''));
  assert.throws(() => verifyRefreshToken('###invalid###'));
});

test('token with an alg-substitution attempt (none algorithm) is rejected', () => {
  const header = Buffer.from(JSON.stringify({ alg: 'none', typ: 'JWT' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({
    sub: '1', role: 'admin', iss: 'smart-ebl-auth', aud: 'smart-ebl-api', exp: Math.floor(Date.now() / 1000) + 900,
  })).toString('base64url');
  const noneAlgToken = `${header}.${payload}.`;
  assert.throws(() => verifyAccessToken(noneAlgToken));
});
