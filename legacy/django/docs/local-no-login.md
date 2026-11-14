# Temporary local access without login

`DJANGO_LOCAL_NO_LOGIN=true` in the private `.env` enables the requested temporary
single-computer mode. Start normally using `start-local.cmd`; no administrator
creation or login prompt is required. Existing accounts and authentication code
are preserved. Account-management/password/logout links are hidden in this mode.

Only actual loopback peers (`127.0.0.1`, `::1`) are allowed, regardless of Host or
forwarded headers. Continue binding the server to `127.0.0.1`. CSRF protection and
database integrity constraints remain enabled. This grants all local users of the
browser full access to male/female records; personal role separation is suspended.

A reserved internal operator with an unusable password supplies the existing audit
and foreign-key actor references. It is not a browser login session or a password
account. Actions are attributed to that operator rather than individual staff.
Existing accounts are never repurposed or elevated when the reserved name conflicts.

To return to normal authentication, set `DJANGO_LOCAL_NO_LOGIN=false` and restart
the server. The launcher will request a real administrator if none exists, excluding
the internal operator. Its historical audit references remain preserved.
