const test = require('node:test');
const assert = require('node:assert/strict');
const { z } = require('zod');
const { validate } = require('../../src/common/validate');
const { ValidationError } = require('../../src/common/errors');

function run(schema, source, req) {
  return new Promise((resolve) => {
    const mw = validate(schema, source);
    mw(req, {}, (err) => resolve({ err, req }));
  });
}

test('valid input calls next with no error and replaces req[source] with the parsed data', async () => {
  const schema = z.object({ email: z.string().email(), age: z.coerce.number().optional() });
  const req = { body: { email: 'a@b.com', age: '30' } };
  const { err, req: finalReq } = await run(schema, 'body', req);

  assert.equal(err, undefined);
  assert.equal(finalReq.body.email, 'a@b.com');
  assert.equal(finalReq.body.age, 30); // coerced to number, proving req.body was actually replaced
});

test('invalid input calls next with a ValidationError, not a raw zod error', async () => {
  const schema = z.object({ email: z.string().email() });
  const { err } = await run(schema, 'body', { body: { email: 'not-an-email' } });

  assert.ok(err instanceof ValidationError);
  assert.equal(err.status, 400);
});

test('multiple validation failures are joined into one readable message', async () => {
  const schema = z.object({
    email: z.string().email(),
    password: z.string().min(10),
  });
  const { err } = await run(schema, 'body', { body: { email: 'bad', password: 'short' } });

  assert.ok(err.publicMessage.length > 0);
  assert.ok(err.publicMessage.includes(','), 'expected multiple joined messages');
});

test('defaults to validating req.body when no source is given', async () => {
  const schema = z.object({ x: z.string() });
  const { err } = await run(schema, undefined, { body: { x: 'ok' } });
  assert.equal(err, undefined);
});

test('can validate req.query or req.params instead of req.body', async () => {
  const schema = z.object({ id: z.string() });
  const { err, req } = await run(schema, 'params', { params: { id: '123' } });
  assert.equal(err, undefined);
  assert.equal(req.params.id, '123');
});

test('missing required field is rejected', async () => {
  const schema = z.object({ email: z.string().email() });
  const { err } = await run(schema, 'body', { body: {} });
  assert.ok(err instanceof ValidationError);
});
