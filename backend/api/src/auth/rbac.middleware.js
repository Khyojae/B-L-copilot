const { ForbiddenError } = require('../common/errors');
const { isAllowed, ADMIN_ROLE } = require('./permissions');

function requirePermission(featureKey, { onAdminAccess } = {}) {
  return (req, res, next) => {
    const role = req.user && req.user.role;

    if (!isAllowed(featureKey, role)) {
      next(new ForbiddenError(`Role '${role}' is not permitted to perform '${featureKey}'`));
      return;
    }

    if (role === ADMIN_ROLE && typeof onAdminAccess === 'function') {
      onAdminAccess(req, featureKey);
    }

    next();
  };
}

module.exports = { requirePermission };
