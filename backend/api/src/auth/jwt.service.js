const crypto = require('crypto');
const jwt = require('jsonwebtoken');

const ACCESS_SECRET = process.env.JWT_ACCESS_SECRET;
const REFRESH_SECRET = process.env.JWT_REFRESH_SECRET;
const ACCESS_EXPIRES_IN = process.env.JWT_ACCESS_EXPIRES_IN || '15m';
const REFRESH_EXPIRES_IN = process.env.JWT_REFRESH_EXPIRES_IN || '1d';
const ISSUER = process.env.JWT_ISSUER || 'smart-ebl-auth';
const AUDIENCE = process.env.JWT_AUDIENCE || 'smart-ebl-api';
const CLOCK_TOLERANCE_SECONDS = 10;

function signAccessToken({ sub, role, orgId, tokenVersion }) {
  const jti = crypto.randomUUID();
  const token = jwt.sign(
    { role, org_id: orgId, tv: tokenVersion },
    ACCESS_SECRET,
    {
      subject: String(sub),
      issuer: ISSUER,
      audience: AUDIENCE,
      expiresIn: ACCESS_EXPIRES_IN,
      jwtid: jti,
    },
  );
  return { token, jti };
}

function signRefreshToken({ sub }) {
  const jti = crypto.randomUUID();
  const token = jwt.sign(
    {},
    REFRESH_SECRET,
    {
      subject: String(sub),
      issuer: ISSUER,
      audience: AUDIENCE,
      expiresIn: REFRESH_EXPIRES_IN,
      jwtid: jti,
    },
  );
  return { token, jti };
}

function verifyAccessToken(token) {
  return jwt.verify(token, ACCESS_SECRET, {
    issuer: ISSUER,
    audience: AUDIENCE,
    clockTolerance: CLOCK_TOLERANCE_SECONDS,
  });
}

function verifyRefreshToken(token) {
  return jwt.verify(token, REFRESH_SECRET, {
    issuer: ISSUER,
    audience: AUDIENCE,
    clockTolerance: CLOCK_TOLERANCE_SECONDS,
  });
}

module.exports = { signAccessToken, signRefreshToken, verifyAccessToken, verifyRefreshToken };
