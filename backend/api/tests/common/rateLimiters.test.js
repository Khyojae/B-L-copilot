const test = require('node:test');
const assert = require('node:assert/strict');
const express = require('express');
const request = require('supertest');
const { loginLimiter, refreshLimiter, passwordResetLimiter } = require('../../src/common/rateLimiters');

function buildApp(limiter) {
  const app = express();
  app.use(limiter);
  app.get('/x', (req, res) => res.json({ ok: true }));
  return app;
}

// Each limiter below is a module-level singleton and is only ever exercised in ONE test in this
// file (deliberately) — reusing the same limiter across multiple tests would carry its request
// count over between tests and make results order-dependent.

test('passwordResetLimiter (limit 5) allows exactly 5 requests then 429s the 6th', async () => {
  const app = buildApp(passwordResetLimiter);
  const agent = request.agent(app);

  for (let i = 0; i < 5; i++) {
    const res = await agent.get('/x');
    assert.equal(res.status, 200, `request ${i + 1} should succeed`);
  }

  const blocked = await agent.get('/x');
  assert.equal(blocked.status, 429);
});

test('loginLimiter (limit 10) allows exactly 10 requests then 429s the 11th', async () => {
  const app = buildApp(loginLimiter);
  const agent = request.agent(app);

  for (let i = 0; i < 10; i++) {
    const res = await agent.get('/x');
    assert.equal(res.status, 200, `request ${i + 1} should succeed`);
  }

  const blocked = await agent.get('/x');
  assert.equal(blocked.status, 429);
});

test('refreshLimiter (limit 30) allows exactly 30 requests then 429s the 31st', async () => {
  const app = buildApp(refreshLimiter);
  const agent = request.agent(app);

  for (let i = 0; i < 30; i++) {
    const res = await agent.get('/x');
    assert.equal(res.status, 200, `request ${i + 1} should succeed`);
  }

  const blocked = await agent.get('/x');
  assert.equal(blocked.status, 429);
});
