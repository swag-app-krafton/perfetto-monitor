// Drive Swag Pay's own modules (by Metro module id) into the errors a bad
// input causes, and print each stack. 517 surfaceRoute, 545 contactsDirectory,
// 542 money.
function probe(label, run) {
  try {
    run();
  } catch (e) {
    print('@@STACK ' + label + '\n' + e.stack + '\n@@END');
  }
}
probe('surface_route', function () { __r(517).parseSurfaceRoute(undefined); });
probe('filter_contacts', function () { __r(545).filterContacts([{name: null}], 'a'); });
probe('build_contact_list', function () { __r(545).buildContactList([null]); });
probe('format_rupees', function () {
  __r(542).formatRupees({valueOf: function () { throw new RangeError('amount is not a number'); }});
});
