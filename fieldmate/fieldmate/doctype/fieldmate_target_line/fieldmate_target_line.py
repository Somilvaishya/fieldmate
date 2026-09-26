from frappe.model.document import Document

# The six, and the one property that decides how each one cascades.
#
# Five of them are quantities: they are split among the children and the leaves add back up to
# the root. The sixth is a rate - lines per productive call - and a rate does not divide. A root
# asking for 4.5 lines a call means every rep is asked for 4.5, not for 4.5 between them, and a
# cascade that split it would hand each of twenty reps a target of 0.225 lines.
#
# Stored on each line as `is_additive` rather than looked up at cascade time, so a plan cascaded
# last year can still be read against the rule that was in force when it ran.
TARGET_TYPES = {
	"Value": True,
	"Volume": True,
	"Outlet Coverage": True,
	"Productive Calls": True,
	"New Outlets": True,
	"Lines Per Call": False,
}

ADDITIVE_TYPES = tuple(t for t, additive in TARGET_TYPES.items() if additive)
RATIO_TYPES = tuple(t for t, additive in TARGET_TYPES.items() if not additive)

# Which of them are money, and so are held in paise while they are being divided (ADR-022).
MONEY_TYPES = ("Value",)

# Which of them can only be whole things. Half a shop is not covered.
WHOLE_TYPES = ("Outlet Coverage", "Productive Calls", "New Outlets")


class FieldMateTargetLine(Document):
	"""One number somebody is asked for, and the scope it applies to.

	A line with no category and no brand is the overall target. A line with one is a target
	beside it, not inside it: a rep can be at 110% overall and at 48% on tea, and the second is
	the only one worth a conversation.
	"""
