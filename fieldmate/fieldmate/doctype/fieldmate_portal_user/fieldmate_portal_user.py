import frappe
from frappe.model.document import Document
from frappe.utils import cint

PORTAL_ROLE = "FieldMate Distributor"


class FieldMatePortalUser(Document):
	"""A login at a depot, and the only thing that ties one to a distributor.

	Every portal query resolves the session user through this row. Nothing else does that lookup,
	which is deliberate: one place that decides whose documents a session may see is auditable,
	and six places are not.

	The role on the User is granted and revoked from here rather than by hand, because a row
	marked inactive whose User still carries the role is a revocation that did not happen.
	"""

	def validate(self):
		self.refuse_system_users()

	def refuse_system_users(self):
		"""A Desk login must not double as a depot login.

		The portal narrows what a session can see by resolving this row. A System Manager
		carries permissions from elsewhere that no narrowing here can take away, so attaching a
		depot to one would create an account that reads as scoped and is not.
		"""
		roles = set(frappe.get_roles(self.user))
		for role in ("System Manager", "FieldMate Admin"):
			if role in roles:
				frappe.throw(
					frappe._("{0} holds the {1} role. Give the depot its own login rather than "
					         "attaching one to an administrator.").format(self.user, role))

	def on_update(self):
		self.sync_role()

	def after_insert(self):
		self.sync_role()

	def on_trash(self):
		revoke(self.user)

	def sync_role(self):
		grant(self.user) if cint(self.is_active) else revoke(self.user)


def grant(user: str) -> None:
	if not frappe.db.exists("Role", PORTAL_ROLE):
		return
	if frappe.db.exists("Has Role", {"parent": user, "role": PORTAL_ROLE}):
		return
	doc = frappe.get_doc("User", user)
	doc.append("roles", {"role": PORTAL_ROLE})
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


def revoke(user: str) -> None:
	"""Drop the role. One login belongs to one depot - the DocType is named on `user` and the
	field is unique - so there is never a second row still needing it."""
	for name in frappe.get_all("Has Role", filters={"parent": user, "role": PORTAL_ROLE},
	                           pluck="name"):
		frappe.delete_doc("Has Role", name, ignore_permissions=True, force=True)
