function asyncHandler(fn) {
  return (req, res, next) => {
    // fn(...) itself can throw synchronously (fn isn't necessarily an async function),
    // which happens before Promise.resolve ever runs — .catch(next) alone can't see that.
    try {
      Promise.resolve(fn(req, res, next)).catch(next);
    } catch (err) {
      next(err);
    }
  };
}

module.exports = { asyncHandler };
