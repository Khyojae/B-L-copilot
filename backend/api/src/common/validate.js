const { ValidationError } = require('./errors');

function validate(schema, source = 'body') {
  return (req, res, next) => {
    const result = schema.safeParse(req[source]);
    if (!result.success) {
      next(new ValidationError(result.error.issues.map((issue) => issue.message).join(', ')));
      return;
    }
    req[source] = result.data;
    next();
  };
}

module.exports = { validate };
