app_name = "fieldmate"
app_title = "FieldMate"
app_publisher = "somilvaishya"
app_description = "Sales Force Automation for field sales teams - offline-first PWA on Frappe and ERPNext"
app_email = "nexaflowtech007@gmail.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]  # hrms is optional - probed via fieldmate.compat.capabilities()

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "fieldmate",
# 		"logo": "/assets/fieldmate/logo.png",
# 		"title": "FieldMate",
# 		"route": "/fieldmate",
# 		"has_permission": "fieldmate.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/fieldmate/css/fieldmate.css"
# app_include_js = "/assets/fieldmate/js/fieldmate.js"

# include js, css files in header of web template
# web_include_css = "/assets/fieldmate/css/fieldmate.css"
# web_include_js = "/assets/fieldmate/js/fieldmate.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "fieldmate/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "fieldmate/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "fieldmate.utils.jinja_methods",
# 	"filters": "fieldmate.utils.jinja_filters"
# }

# Installation
# ------------

before_install = "fieldmate.setup.install.before_install"
after_install = "fieldmate.setup.install.after_install"

# The idempotency keys have to reach sites that were installed before Phase 6, not only new ones.
# Both are idempotent, so running them on every migrate costs nothing and means an existing site
# is never left with adapters that refuse to post.
after_migrate = [
	"fieldmate.setup.install.create_roles",
	"fieldmate.setup.install.create_idempotency_fields",
]

# Uninstallation
# ------------

# before_uninstall = "fieldmate.uninstall.before_uninstall"
# after_uninstall = "fieldmate.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "fieldmate.utils.before_app_install"
# after_app_install = "fieldmate.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "fieldmate.utils.before_app_uninstall"
# after_app_uninstall = "fieldmate.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "fieldmate.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# A distributor portal session is narrowed to its own depot by the framework as well as by
# `services.portal`, which is the only thing that calls it. Belt and braces on purpose: the
# service layer covers the portal's own screens, and these two cover every other route into the
# same rows - a report, a Desk list, an api.resource call, anything added later that forgets.
# Both return a no-op for every session that is not a portal user, which is nearly all of them.
#
# Phase 7 adds a second, narrower rule on the four DocTypes that carry somebody's own numbers.
# Territory scoping cannot cover these: a target belongs to a person, not to a place, and two
# reps routinely share a territory. A rep sees the rows that name them; every manager keeps the
# full view.
permission_query_conditions = {
	"FieldMate Order": "fieldmate.services.portal.order_query",
	"FieldMate Claim": "fieldmate.services.portal.claim_query",
	"FieldMate Target Plan": "fieldmate.services.field_user.target_plan_query",
	"FieldMate Achievement": "fieldmate.services.field_user.achievement_query",
	"FieldMate Incentive Payout": "fieldmate.services.field_user.incentive_payout_query",
	"FieldMate Expense Claim": "fieldmate.services.field_user.expense_claim_query",
}

has_permission = {
	"FieldMate Order": "fieldmate.services.portal.order_permission",
	"FieldMate Claim": "fieldmate.services.portal.claim_permission",
	"FieldMate Target Plan": "fieldmate.services.field_user.own_row_permission",
	"FieldMate Achievement": "fieldmate.services.field_user.own_row_permission",
	"FieldMate Incentive Payout": "fieldmate.services.field_user.own_row_permission",
	"FieldMate Expense Claim": "fieldmate.services.field_user.own_row_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"fieldmate.tasks.all"
# 	],
# 	"daily": [
# 		"fieldmate.tasks.daily"
# 	],
# 	"hourly": [
# 		"fieldmate.tasks.hourly"
# 	],
# 	"weekly": [
# 		"fieldmate.tasks.weekly"
# 	],
# 	"monthly": [
# 		"fieldmate.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "fieldmate.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "fieldmate.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "fieldmate.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["fieldmate.utils.before_request"]
# after_request = ["fieldmate.utils.after_request"]

# Job Events
# ----------
# before_job = ["fieldmate.utils.before_job"]
# after_job = ["fieldmate.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"fieldmate.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# The PWA is served straight from fieldmate/www/fieldmate/ and routes on the hash,
# so no website_route_rules rewrite is needed.

# ---------------------------------------------------------------------------
# Scheduled work
# ---------------------------------------------------------------------------
scheduler_events = {
	"daily": [
		# Close days a rep forgot to end, so tomorrow starts cleanly. The record is marked
		# Auto Closed rather than Closed: a forgotten day is not a finished one.
		"fieldmate.tasks.close_stale_days",
		# GPS trails track a named employee. Keep them only as long as FieldMate Settings says.
		"fieldmate.tasks.purge_old_trails",
		# Re-measure every live target plan. This is what makes a rep's performance screen a
		# read of one stored row rather than a count over a month of orders on every open
		# (Gate 7 criterion 5).
		"fieldmate.tasks.measure_targets",
	],
}
