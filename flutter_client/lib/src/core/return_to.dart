/// Shared guard for `return_to` query params (issue #111): the router
/// redirect and the login/register screens must enforce the same rule —
/// relative paths only, with a single leading slash, since `//host` is
/// scheme-relative in a browser.
library;

/// Returns [ret] when it is a safe relative path to navigate to after
/// login/registration, or null when absent or unsafe.
String? safeReturnTo(String? ret) =>
    (ret != null && ret.startsWith('/') && !ret.startsWith('//')) ? ret : null;
