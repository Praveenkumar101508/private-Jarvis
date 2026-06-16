# caldav — third-party dependency

- **Project:** python-caldav — a CalDAV client library
- **Upstream:** https://github.com/python-caldav/caldav
- **Version pinned:** 3.2.1 (see `supracloud-jarvis/ira/requirements.txt`)
- **License:** dual-licensed **GPL-3.0-or-later OR Apache-2.0**

## How we use it

IRA uses `caldav` **as an installed dependency** under its **Apache-2.0** option
(the permissive arm of the dual license — no copyleft obligation). We do not
vendor, copy, or modify its source code; it is pulled from PyPI at install time
and imported lazily by `ira/actions/calendar_dav.py`.

It powers the local-first calendar action that talks to the owner's own CalDAV
server (Radicale, Nextcloud, Baïkal, …). No third-party cloud calendar is
involved. Create and delete operations are gated behind IRA's approval guardrail
(owner + explicit confirmation).

This NOTICE is recorded for license hygiene (R3). The full Apache-2.0 text is the
standard one already vendored at `third_party/bumblebee/LICENSE` and available at
https://www.apache.org/licenses/LICENSE-2.0.
