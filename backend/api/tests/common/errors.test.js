const test = require('node:test');
const assert = require('node:assert/strict');
const {
  AppError,
  UnauthorizedError,
  ForbiddenError,
  ValidationError,
  NotFoundError,
} = require('../../src/common/errors');

test('AppError carries the given status and message as both message and publicMessage', () => {
  const err = new AppError(418, "I'm a teapot");
  assert.equal(err.status, 418);
  assert.equal(err.publicMessage, "I'm a teapot");
  assert.equal(err.message, "I'm a teapot");
  assert.ok(err instanceof Error);
});

test('UnauthorizedError defaults to 401 with a generic message', () => {
  const err = new UnauthorizedError();
  assert.equal(err.status, 401);
  assert.equal(err.publicMessage, 'Unauthorized');
});

test('ForbiddenError defaults to 403', () => {
  assert.equal(new ForbiddenError().status, 403);
});

test('ValidationError defaults to 400 and accepts a custom message', () => {
  const err = new ValidationError('email is required');
  assert.equal(err.status, 400);
  assert.equal(err.publicMessage, 'email is required');
});

test('NotFoundError defaults to 404', () => {
  assert.equal(new NotFoundError().status, 404);
});

test('each error subclass is also an instance of AppError and Error', () => {
  for (const ErrorClass of [UnauthorizedError, ForbiddenError, ValidationError, NotFoundError]) {
    const err = new ErrorClass();
    assert.ok(err instanceof AppError);
    assert.ok(err instanceof Error);
  }
});
