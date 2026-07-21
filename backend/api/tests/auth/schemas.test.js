const test = require('node:test');
const assert = require('node:assert/strict');
const { signupSchema } = require('../../src/auth/schemas/signup.schema');
const { loginSchema } = require('../../src/auth/schemas/login.schema');
const {
  passwordResetRequestSchema,
  passwordResetConfirmSchema,
} = require('../../src/auth/schemas/passwordReset.schema');
const {
  phoneOtpRequestSchema,
  phoneOtpVerifySchema,
} = require('../../src/auth/schemas/phoneVerification.schema');

test('signupSchema accepts a valid business-role signup', () => {
  const result = signupSchema.safeParse({
    email: 'a@b.com',
    password: 'longenoughpassword',
    role: 'carrier',
    companyName: 'ACME Shipping',
  });
  assert.equal(result.success, true);
});

test('signupSchema rejects admin as a self-signup role', () => {
  const result = signupSchema.safeParse({
    email: 'a@b.com',
    password: 'longenoughpassword',
    role: 'admin',
    companyName: 'X',
  });
  assert.equal(result.success, false);
});

test('signupSchema rejects a too-short password', () => {
  const result = signupSchema.safeParse({
    email: 'a@b.com',
    password: 'short',
    role: 'carrier',
    companyName: 'X',
  });
  assert.equal(result.success, false);
});

test('signupSchema rejects a malformed phone number', () => {
  const result = signupSchema.safeParse({
    email: 'a@b.com',
    password: 'longenoughpassword',
    role: 'carrier',
    companyName: 'X',
    phoneNumber: '123',
  });
  assert.equal(result.success, false);
});

test('loginSchema rejects a non-email value', () => {
  assert.equal(loginSchema.safeParse({ email: 'not-an-email', password: 'x' }).success, false);
});

test('passwordReset schemas validate request/confirm shapes', () => {
  assert.equal(passwordResetRequestSchema.safeParse({ email: 'a@b.com' }).success, true);
  assert.equal(
    passwordResetConfirmSchema.safeParse({ token: 'abc', newPassword: 'longenoughpassword' }).success,
    true,
  );
  assert.equal(
    passwordResetConfirmSchema.safeParse({ token: 'abc', newPassword: 'short' }).success,
    false,
  );
});

test('phone OTP schemas validate phone number format and 6-digit code', () => {
  assert.equal(phoneOtpRequestSchema.safeParse({ phoneNumber: '01012345678' }).success, true);
  assert.equal(phoneOtpRequestSchema.safeParse({ phoneNumber: 'not-a-phone' }).success, false);
  assert.equal(
    phoneOtpVerifySchema.safeParse({ phoneNumber: '01012345678', code: '123456' }).success,
    true,
  );
  assert.equal(
    phoneOtpVerifySchema.safeParse({ phoneNumber: '01012345678', code: '123' }).success,
    false,
  );
});
