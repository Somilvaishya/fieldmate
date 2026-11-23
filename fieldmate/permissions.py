import frappe


def check_app_permission():
	"""Whether FieldMate's tile shows on the /apps screen and in the Desk app switcher.

	Only for somebody Desk will let in. A rep, an Area Manager or a Regional Manager is a Website
	User - they work in the PWA - and a tile that leads to /app would end on a 403.
	"""
	if frappe.session.user == "Administrator":
		return True
	if frappe.get_cached_value("User", frappe.session.user, "user_type") != "System User":
		return False
	return bool(frappe.has_permission("FieldMate Outlet", ptype="read"))
