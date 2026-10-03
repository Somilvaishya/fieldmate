"""Give the field users somebody to report to.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_managers.py
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_managers.py --show
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_managers.py --undo

An order held for credit may be released by the rep's **own** manager, by their distributor, or
by an administrator. On a site where nobody has filled in `reports_to` - which is every site on
day one, and was this one - the first of those three does not exist, so a breach can only be
decided by the depot or by an admin. That is not wrong, but it is not the design either.

This builds the missing half: one area manager per territory that has reps in it, and every rep
in that territory pointed at them. It is deliberately flat. A real hierarchy is somebody's
org chart, not a script's guess; what this gives is a working reporting line to test against and
a shape to edit rather than a blank field.

Safe to run twice: everything is looked up by name first.
"""

import sys

import frappe

from _guard import require_test_site

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
    if not arg.startswith("--"):
        SITE = arg

UNDO = "--undo" in sys.argv
SHOW = "--show" in sys.argv

PASSWORD = "FieldMate@9"
ROLE = "FieldMate Area Manager"


def note(verb: str, what: str, detail: str = "") -> None:
    print(f"  {verb:8} {what}" + (f"   ({detail})" if detail else ""))


def email_for(territory: str) -> str:
    """One manager per territory, named after it so a second run finds the same person."""
    slug = "".join(c.lower() if c.isalnum() else "." for c in territory).strip(".")
    while ".." in slug:
        slug = slug.replace("..", ".")
    return f"manager.{slug}@fieldmate.test"


def territories_with_reps() -> dict:
    """Territory -> the reps in it who have no manager yet."""
    out = {}
    for row in frappe.get_all(
        "FieldMate Field User",
        filters={"status": "Active"},
        fields=["name", "territory", "reports_to", "designation"],
        limit_page_length=0,
    ):
        # A manager is a field user too. Only people who actually walk a beat get one.
        if row.designation and "manager" in row.designation.lower():
            continue
        if not row.territory:
            continue
        out.setdefault(row.territory, []).append(row)
    return out


def ensure_manager(territory: str) -> str:
    email = email_for(territory)

    if not frappe.db.exists("User", email):
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": "Area Manager",
            "last_name": territory,
            "send_welcome_email": 0,
        })
        user.flags.ignore_permissions = True
        user.insert(ignore_permissions=True)
        note("created", f"User {email}")
    else:
        note("kept", f"User {email}")

    user = frappe.get_doc("User", email)
    if ROLE not in {r.role for r in user.roles}:
        user.append("roles", {"role": ROLE})
        user.flags.ignore_permissions = True
        user.save(ignore_permissions=True)
        note("granted", ROLE, email)

    from frappe.utils.password import update_password
    update_password(email, PASSWORD)

    if frappe.db.exists("FieldMate Field User", email):
        note("kept", f"Field User {email}")
        return email

    row = frappe.get_doc({
        "doctype": "FieldMate Field User",
        "user": email,
        "full_name": f"Area Manager {territory}",
        "designation": "Area Manager",
        "territory": territory,
        "status": "Active",
        "company": frappe.db.get_value("Company", {}, "name"),
    })
    row.flags.ignore_permissions = True
    row.insert(ignore_permissions=True)
    note("created", f"Field User {email}", territory)
    return email


def run() -> None:
    found = territories_with_reps()
    if not found:
        print("\n  No field reps with a territory. Nothing to do.\n")
        return

    print("\nGiving every rep a manager")
    print("-" * 72)
    for territory, reps in sorted(found.items()):
        manager = ensure_manager(territory)
        for rep in reps:
            if rep.reports_to == manager:
                note("kept", rep.name, f"reports to {manager}")
                continue
            if rep.reports_to:
                note("left", rep.name, f"already reports to {rep.reports_to}")
                continue
            frappe.db.set_value("FieldMate Field User", rep.name, "reports_to", manager,
                                update_modified=False)
            note("linked", rep.name, f"-> {manager}")
    frappe.db.commit()


def undo() -> None:
    print("\nTaking the managers back out")
    print("-" * 72)
    for territory in sorted(territories_with_reps()):
        email = email_for(territory)
        for rep in frappe.get_all("FieldMate Field User",
                                  filters={"reports_to": email}, pluck="name"):
            frappe.db.set_value("FieldMate Field User", rep, "reports_to", None,
                                update_modified=False)
            note("unlinked", rep)
        if frappe.db.exists("FieldMate Field User", email):
            frappe.delete_doc("FieldMate Field User", email, force=True,
                              ignore_permissions=True, delete_permanently=True)
            note("removed", f"Field User {email}")
        # The login is left. It may be shared, and deleting a User takes its roles with it.
    frappe.db.commit()


def show() -> None:
    print("\nReporting line")
    print("-" * 72)
    rows = frappe.get_all("FieldMate Field User",
                          fields=["name", "designation", "territory", "reports_to"],
                          order_by="territory, designation", limit_page_length=0)
    for r in rows:
        print(f"  {r.name:34} {str(r.designation or ''):16} {str(r.territory or ''):16} "
              f"-> {r.reports_to or '(nobody)'}")
    orphans = [r for r in rows if not r.reports_to
               and "manager" not in str(r.designation or "").lower()]
    print(f"\n  {len(orphans)} rep(s) with nobody to approve their held orders")


def main() -> None:
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")

    try:
        if SHOW:
            show()
        elif UNDO:
            undo()
            show()
        else:
            run()
            show()
            print(f"\n  Sign in as any manager with: {PASSWORD}\n")
    finally:
        frappe.destroy()


if __name__ == "__main__":
    main()
