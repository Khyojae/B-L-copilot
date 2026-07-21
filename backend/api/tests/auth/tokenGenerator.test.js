const test = require('node:test');
const assert = require('node:assert/strict');
const { generateToken, generateNumericCode, expiresInMinutes } = require('../../src/common/tokenGenerator');

test('generateToken returns a raw token and a distinct hash of it', () => {
  const { token, tokenHash } = generateToken();
  assert.equal(token.length, 64);
  assert.equal(tokenHash.length, 64);
  assert.notEqual(token, tokenHash);
});

test('generateNumericCode returns a 6-digit code by default and its hash', () => {
  const { code, codeHash } = generateNumericCode();
  assert.match(code, /^[0-9]{6}$/);
  assert.notEqual(code, codeHash);
});

test('expiresInMinutes returns a future timestamp', () => {
  const before = Date.now();
  const expiry = expiresInMinutes(10);
  assert.ok(expiry.getTime() > before);
});

test('generateToken produces distinct tokens across many calls (no collisions)', () => {
  const tokens = new Set();
  for (let i = 0; i < 500; i++) {
    tokens.add(generateToken().token);
  }
  assert.equal(tokens.size, 500);
});

test('generateNumericCode zero-pads codes shorter than the requested digit count', () => {
  // Every draw already proves padding works (code.length is asserted every iteration) —
  // but to also *demonstrably* exercise a case that needs padding (not just get lucky),
  // use digits=2 (range 0-99) where single-digit draws like "5" -> "05" are common
  // (~10% per draw), so 50 draws make seeing at least one all but certain,
  // instead of the digits=6 case where a value under 100 is a 1-in-10000 draw.
  let sawPaddedValue = false;
  for (let i = 0; i < 50; i++) {
    const { code } = generateNumericCode(2);
    assert.equal(code.length, 2);
    if (Number(code) < 10) sawPaddedValue = true;
  }
  assert.ok(sawPaddedValue, 'expected at least one single-digit value to exercise zero-padding across 50 draws');
});

test('generateNumericCode supports a custom digit count', () => {
  const { code } = generateNumericCode(4);
  assert.equal(code.length, 4);
  assert.match(code, /^[0-9]{4}$/);
});
