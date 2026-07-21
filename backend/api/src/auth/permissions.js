const ADMIN_ROLE = 'admin';

const ROLES = ['shipper', 'carrier', 'forwarder', 'bank', 'customs', ADMIN_ROLE];

const PERMISSIONS = {
  EBL_ISSUE: { roles: ['carrier'], ownershipGated: false },
  EBL_VIEW: { roles: ['shipper', 'carrier', 'forwarder', 'bank', 'customs'], ownershipGated: true },
  OWNERSHIP_TRANSFER: { roles: ['shipper', 'forwarder', 'bank'], ownershipGated: false },
  DOCUMENT_UPLOAD: { roles: ['shipper', 'forwarder'], ownershipGated: false },
  AI_VERIFICATION_REQUEST: { roles: ['shipper', 'forwarder', 'bank'], ownershipGated: false },
  LC_VERIFICATION: { roles: ['bank'], ownershipGated: false },
  CUSTOMS_INQUIRY: { roles: ['shipper', 'carrier', 'forwarder', 'customs'], ownershipGated: false },
  DO_ISSUE: { roles: ['carrier'], ownershipGated: false },
};

function isAllowed(featureKey, role) {
  if (role === ADMIN_ROLE) return true;
  const permission = PERMISSIONS[featureKey];
  if (!permission) return false;
  return permission.roles.includes(role);
}

function isOwnershipGated(featureKey) {
  return Boolean(PERMISSIONS[featureKey]?.ownershipGated);
}

module.exports = { ROLES, ADMIN_ROLE, PERMISSIONS, isAllowed, isOwnershipGated };
