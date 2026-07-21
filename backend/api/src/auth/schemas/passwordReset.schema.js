const { z } = require('zod');

const passwordResetRequestSchema = z.object({
  email: z.string().email(),
});

const passwordResetConfirmSchema = z.object({
  token: z.string().min(1),
  newPassword: z.string().min(10).max(128),
});

module.exports = { passwordResetRequestSchema, passwordResetConfirmSchema };
