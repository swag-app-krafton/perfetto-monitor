// Drive Swag Pay's own modules (by Metro module id) into the errors a bad
// input causes, and print each stack. 520 surfaceRoute, 548 contactsDirectory,
// 545 money (Android ids).
function probe(label, run) {
  try {
    run();
  } catch (e) {
    print('@@STACK ' + label + '\n' + e.stack + '\n@@END');
  }
}
probe('surface_route', function () { __r(520).parseSurfaceRoute(undefined); });
probe('filter_contacts', function () { __r(548).filterContacts([{name: null}], 'a'); });
probe('build_contact_list', function () { __r(548).buildContactList([null]); });
probe('format_rupees', function () {
  __r(545).formatRupees({valueOf: function () { throw new RangeError('amount is not a number'); }});
});
