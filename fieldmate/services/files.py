"""Turning a photo the device captured into a file the server owns.

The PWA compresses a photo and hands it over as a base64 data URL. An `Attach Image` field is a
varchar(140) holding a *path*, so writing the image itself into it fails at the database with
"Data too long" — which is exactly how this was found.

Everything here produces **private** files. Visit photos, receipts and start-of-day selfies are
evidence about named people and shops; none of them belong on a public URL.
"""

from __future__ import annotations

import base64
import re

import frappe
from frappe.utils import cint

DATA_URL = re.compile(r"^data:image/(?P<kind>jpeg|jpg|png|webp);base64,(?P<payload>.+)$", re.S)

EXTENSIONS = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}


def is_data_url(value) -> bool:
	return isinstance(value, str) and value.startswith("data:image/")


def save_data_url(data_url: str, filename: str, doctype: str | None = None,
                  name: str | None = None, fieldname: str | None = None,
                  max_kb: int | None = None) -> str:
	"""Save a base64 image as a private File and return its URL.

	`max_kb` is enforced here as well as on the device. The device limit is a budget; this is the
	control, because a payload arriving from a phone is never the only thing that could send one.
	"""
	match = DATA_URL.match(data_url or "")
	if not match:
		frappe.throw(frappe._("That photo is not in a format we can read. Take it again."))

	try:
		content = base64.b64decode(match.group("payload"), validate=True)
	except Exception:
		frappe.throw(frappe._("That photo could not be read. Take it again."))

	size_kb = len(content) / 1024
	if max_kb and size_kb > cint(max_kb):
		frappe.throw(
			frappe._("That photo is {0} KB, over the {1} KB limit. It should have been shrunk "
			         "on the phone first.").format(int(size_kb), cint(max_kb))
		)

	extension = EXTENSIONS.get(match.group("kind"), "jpg")
	doc = frappe.get_doc({
		"doctype": "File",
		"file_name": f"{filename}.{extension}",
		"is_private": 1,
		"content": content,
		"decode": False,
		"attached_to_doctype": doctype,
		"attached_to_name": name,
		"attached_to_field": fieldname,
	})
	doc.insert(ignore_permissions=True)
	return doc.file_url


def attach_photo(value, filename: str, doctype: str, name: str, fieldname: str,
                 max_kb: int | None = None) -> str | None:
	"""Accept either a data URL or an already-uploaded path, and return what to store.

	Taking both means an older app build that uploads separately keeps working against a newer
	server, which is the same reason the API ignores unknown fields rather than rejecting them.
	"""
	if not value:
		return None
	if not is_data_url(value):
		return value
	return save_data_url(value, filename, doctype, name, fieldname, max_kb)
