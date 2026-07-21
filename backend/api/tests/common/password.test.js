const test = require('node:test');
const assert = require('node:assert/strict');
const { hashPassword, comparePassword } = require('../../src/common/password');

test('hashPassword produces a bcrypt-shaped hash, never the plaintext', async () => {
  const hash = await hashPassword('correct horse battery staple');
  assert.match(hash, /^\$2[aby]?\$\d{2}\$/);
  assert.notEqual(hash, 'correct horse battery staple');
});

test('comparePassword returns true for the correct password and false otherwise', async () => {
  const hash = await hashPassword('correct horse battery staple');
  assert.equal(await comparePassword('correct horse battery staple', hash), true);
  assert.equal(await comparePassword('wrong password', hash), false);
});

test('hashing the same password twice yields different hashes (random salt) but both verify', async () => {
  const hashA = await hashPassword('same-password');
  const hashB = await hashPassword('same-password');

  assert.notEqual(hashA, hashB);
  assert.equal(await comparePassword('same-password', hashA), true);
  assert.equal(await comparePassword('same-password', hashB), true);
});

test('comparePassword is case-sensitive and rejects near-miss passwords', async () => {
  const hash = await hashPassword('Password123');
  assert.equal(await comparePassword('password123', hash), false);
  assert.equal(await comparePassword('Password123 ', hash), false);
});

test('comparePassword against an empty string never matches a real password hash', async () => {
  const hash = await hashPassword('real-password');
  assert.equal(await comparePassword('', hash), false);
});
