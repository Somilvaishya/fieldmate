#!/usr/bin/env bash
# Restore the manual-test logins. The test suite creates and deletes Users, which can clear
# the auth rows of fixtures that share the site, so run this before a manual pass.
set -e
export PATH="$HOME/.local/bin:$PATH"
SITE="${1:-testerp2.web.gargsystems.com}"
cd "$HOME/frappe/frappe-bench-v15"
cat > /tmp/_fm_reset.py <<'PY'
import frappe
from frappe.utils.password import update_password
for email in ("rep1@fieldmate.test", "mgr1@fieldmate.test"):
    if frappe.db.exists("User", email):
        frappe.db.set_value("User", email, "enabled", 1, update_modified=False)
        update_password(email, "FieldMate@2026")
frappe.db.commit()
PY
bench --site "$SITE" console < /tmp/_fm_reset.py >/dev/null 2>&1
rm -f /tmp/_fm_reset.py
echo "rep1@fieldmate.test and mgr1@fieldmate.test reset to FieldMate@2026 on $SITE"
