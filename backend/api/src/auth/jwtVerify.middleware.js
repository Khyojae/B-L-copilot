const { verifyAccessToken } = require('./jwt.service');
const { UnauthorizedError } = require('../common/errors');

// token_version(tv) 비교는 DB 조회가 필요해 별도의 tokenVersion 미들웨어에서 처리한다.
// 여기서는 서명/만료/iss/aud 검증과 req.user 세팅만 담당한다.
function jwtVerify(req, res, next) {
  const authHeader = req.headers.authorization || '';
  const [scheme, token] = authHeader.split(' ');

  if (scheme !== 'Bearer' || !token) {
    next(new UnauthorizedError());
    return;
  }

  try {
    const decoded = verifyAccessToken(token);
    req.user = {
      sub: decoded.sub,
      role: decoded.role,
      orgId: decoded.org_id,
      tokenVersion: decoded.tv,
      jti: decoded.jti,
    };
    next();
  } catch (err) {
    next(new UnauthorizedError());
  }
}

module.exports = { jwtVerify };
