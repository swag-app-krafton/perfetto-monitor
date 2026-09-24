'use strict';
// A stand-in third-party library: validation and a callback-driven helper,
// so stacks run app -> library -> app.
function validate(value) {
  if (value == null) {
    throw new TypeError('fake-lib: value is required');
  }
  return value;
}
function eachItem(items, callback) {
  for (let i = 0; i < items.length; i++) {
    callback(items[i], i);
  }
}
module.exports = {validate, eachItem};
