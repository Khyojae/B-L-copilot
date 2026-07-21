const { ForbiddenError } = require('../common/errors');
const { ADMIN_ROLE } = require('./permissions');

// loadOwnerIds(req) -> Promise<Array<string|number>> 형태의 함수를 주입받는 제네릭 팩토리.
// 실제 리소스 조회(DB)는 호출하는 쪽(document/ebl 모듈)에서 구현해서 넘긴다.
function requireOwnership(loadOwnerIds) {
  return async (req, res, next) => {
    if (req.user && req.user.role === ADMIN_ROLE) {
      next();
      return;
    }

    try {
      const ownerIds = await loadOwnerIds(req);
      const userId = String(req.user.sub);
      if (!ownerIds.map(String).includes(userId)) {
        next(new ForbiddenError('Not the owner of this resource'));
        return;
      }
      next();
    } catch (err) {
      next(err);
    }
  };
}

module.exports = { requireOwnership };
