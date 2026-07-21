const { z } = require('zod');

// admin은 자가 회원가입 대상이 아니라 운영자가 별도로 만들어주는 계정이라 role enum에서 제외.
const signupSchema = z.object({
  email: z.string().email(),
  password: z.string().min(10).max(128),
  role: z.enum(['shipper', 'carrier', 'forwarder', 'bank', 'customs']),
  companyName: z.string().min(1).max(255),
  companyCode: z.string().max(100).optional(),
  phoneNumber: z.string().regex(/^01[0-9]{8,9}$/).optional(),
});

module.exports = { signupSchema };
