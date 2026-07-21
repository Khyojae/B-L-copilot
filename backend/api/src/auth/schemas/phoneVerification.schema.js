const { z } = require('zod');

const phoneOtpRequestSchema = z.object({
  phoneNumber: z.string().regex(/^01[0-9]{8,9}$/),
});

const phoneOtpVerifySchema = z.object({
  phoneNumber: z.string().regex(/^01[0-9]{8,9}$/),
  code: z.string().length(6),
});

module.exports = { phoneOtpRequestSchema, phoneOtpVerifySchema };
