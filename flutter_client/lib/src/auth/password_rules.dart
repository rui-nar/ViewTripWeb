/// Pure validation for the change-password forms (no I/O, so it's unit-testable
/// without pulling in the auth stack). Returns an error string, or null if OK.
library;

String? changePasswordError({
  required String current,
  required String next,
  required String confirm,
}) {
  if (current.isEmpty || next.isEmpty) return 'Fill in all fields.';
  if (next != confirm) return 'New passwords do not match.';
  return null;
}
